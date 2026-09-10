import json
import os
import unittest

import services.healthy_food_service as healthy_food_service_module
from datetime import datetime, timezone
from unittest.mock import patch

from services.disease_rule_service import build_allergen_taxonomy_response, build_disease_rules_response, build_medical_metadata_response, load_allergen_taxonomy, load_disease_rules, normalize_allergen_ids, normalize_condition_ids
from services.food_analysis_service import build_detection_reliability, build_portion_range
from services.food_service import search_foods
from services.healthy_food_service import build_google_places_food_recommendations, build_healthy_food_recommendations, load_restaurant_catalog
from services.history_service import build_history_response
from services.open_food_facts_service import build_open_food_facts_product
from services.app_time_service import app_today
from services.nutrition_progress_service import (
    build_daily_nutrition_progress,
    build_nutrition_goal_types,
    calculate_daily_targets_with_basis,
    calculate_pdf_daily_targets,
)
from services.profile_service import build_bmr_response, build_user_profile
from services.restaurant_ai_service import build_restaurant_summary_prompt, normalize_restaurant_summary, validate_restaurant_summary_input
from services.vision_food_service import build_vision_food_response
from repositories.storage import StorageRepository


class FakeStorage:
    def get_user(self, user_id: str):
        return {
            "user_id": user_id,
            "health_conditions": ["hypertension"],
            "allergens": ["egg"],
            "daily_calorie_target": 2100,
        }

    def get_history(self, user_id: str, days: int):
        return [
            {"date": "2026-04-28", "record_count": 2, "calories": 1000, "protein": 50, "carbs": 120, "fat": 30, "sodium": 900},
            {"date": "2026-04-29", "record_count": 1, "calories": 800, "protein": 40, "carbs": 100, "fat": 20, "sodium": 700},
        ]

    def get_custom_foods(self, user_id: str | None = None):
        return []

    def get_records(self, user_id: str, date: str | None = None, limit: int = 500):
        return []

class ServiceSmokeTests(unittest.TestCase):
    def test_bmr_response(self):
        result = build_bmr_response({"gender": "male", "weight": 72, "height": 175, "age": 28, "activity_multiplier": 1.55})
        self.assertEqual(result["formula"], "Mifflin-St Jeor")
        self.assertGreater(result["bmr"], 0)
        self.assertGreater(result["tdee"], result["bmr"])

    def test_history_summary(self):
        result = build_history_response(FakeStorage(), "demo_user", 7)
        self.assertEqual(result["summary"]["recorded_days"], 2)
        self.assertEqual(result["summary"]["total_records"], 3)
        self.assertEqual(result["summary"]["avg_calories"], 900)

    def test_pdf_daily_targets_cover_diabetes_and_ckd_rules(self):
        diabetes = calculate_pdf_daily_targets({
            "height": 170,
            "weight": 80,
            "health_conditions": ["糖尿病"],
        })
        ideal_weight = 22 * (1.7 ** 2)
        # 沒帶 activity_multiplier 時預設中等活動（1.55）＝ 35 kcal/kg，
        # BMI 27.7 屬過重，糖尿病再往下調一級 -> 30。
        energy = ideal_weight * 30
        self.assertAlmostEqual(diabetes["calories"], energy)
        self.assertAlmostEqual(diabetes["protein"], ideal_weight)
        self.assertAlmostEqual(diabetes["carbs"], energy * 0.475 / 4)
        self.assertAlmostEqual(diabetes["sugar"], min(energy * 0.05 / 4, 25))
        self.assertEqual(diabetes["trans_fat"], 0)

        kidney = calculate_pdf_daily_targets({
            "height": 170,
            "weight": 65,
            "health_conditions": ["ckd"],
        })
        self.assertAlmostEqual(kidney["protein"], ideal_weight * 0.6)
        self.assertEqual(kidney["fiber"], 17.5)
        self.assertEqual(kidney["sodium"], 1500)

    def test_energy_target_follows_activity_level(self):
        """先前不分活動量一律 25/30 kcal/kg，等於把每個人都當輕度活動。"""
        base = {"height": 170, "weight": 60, "age": 22, "gender": "male", "health_conditions": ["高血壓"]}
        ideal_weight = 22 * (1.7 ** 2)

        sedentary = calculate_pdf_daily_targets({**base, "activity_multiplier": 1.2})
        moderate = calculate_pdf_daily_targets({**base, "activity_multiplier": 1.55})
        very_active = calculate_pdf_daily_targets({**base, "activity_multiplier": 1.9})

        self.assertAlmostEqual(sedentary["calories"], ideal_weight * 25)
        self.assertAlmostEqual(moderate["calories"], ideal_weight * 35)
        self.assertAlmostEqual(very_active["calories"], ideal_weight * 40)
        self.assertLess(sedentary["calories"], moderate["calories"])

    def test_disease_target_never_drops_below_bmr(self):
        """疾病目標是 App 幫使用者決定的，不能開出低於基礎代謝的熱量。"""
        result = calculate_daily_targets_with_basis({
            "height": 170,
            "weight": 80,
            "age": 25,
            "gender": "male",
            "activity_multiplier": 1.2,
            "health_conditions": ["糖尿病"],
        })
        bmr = round(10 * 80 + 6.25 * 170 - 5 * 25 + 5)  # compute_bmr 會四捨五入
        # 久坐(25) 過重再降一級(20) -> 63.58 * 20 = 1271.6，低於 BMR 1742.5
        self.assertAlmostEqual(result["targets"]["calories"], bmr)
        self.assertTrue(result["basis"]["floored_at_bmr"])
        self.assertEqual(result["basis"]["source"], "disease")

    def test_target_basis_reports_user_value_when_no_condition(self):
        result = calculate_daily_targets_with_basis({
            "height": 170,
            "weight": 70,
            "age": 22,
            "gender": "male",
            "daily_calorie_target": 2570,
            "health_conditions": [],
        })
        self.assertEqual(result["targets"]["calories"], 2570)
        self.assertEqual(result["basis"]["source"], "user")
        self.assertFalse(result["basis"]["floored_at_bmr"])

    def test_disease_rules_load(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        self.assertIn("hypertension", rules)
        self.assertIn("max_sodium_per_meal", rules["hypertension"])
        self.assertIn("rule_version", rules["hypertension"])

    def test_allergen_taxonomy_load(self):
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        self.assertGreater(len(taxonomy["groups"]), 0)
        self.assertTrue(any(group["id"] == "egg" for group in taxonomy["groups"]))

    def test_medical_metadata_response(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        response = build_medical_metadata_response(rules, taxonomy)
        self.assertIn("disease_rules", response)
        self.assertIn("allergen_taxonomy", response)

    def test_normalization_helpers(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        self.assertEqual(normalize_condition_ids(["高血壓", "hypertension"], rules), ["hypertension"])
        self.assertEqual(normalize_allergen_ids(["蛋", "egg"], taxonomy), ["egg"])

    def test_disease_rules_governance_response(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        response = build_disease_rules_response(rules)
        self.assertEqual(response["count"], len(rules))
        self.assertIn("medical_disclaimer", response)
        hypertension = next(item for item in response["conditions"] if item["condition"] == "hypertension")
        self.assertEqual(hypertension["limits"]["max_sodium_per_meal"], 600)
        self.assertGreater(len(hypertension["references"]), 0)

    def test_allergen_taxonomy_response(self):
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        response = build_allergen_taxonomy_response(taxonomy)
        self.assertEqual(response["count"], len(taxonomy["groups"]))
        self.assertIn("medical_disclaimer", response)

    def test_healthy_food_response_groups_restaurants_for_map(self):
        catalog = [
            {
                "restaurant_id": "map_1",
                "name": "Taiwan Bento",
                "lat": 25.0338,
                "lng": 121.5645,
                "address": "Taipei",
                "open_hours": ["00:00-23:59"],
                "tags": ["bento", "healthy"],
                "items": [
                    {"item_id": "meal_1", "name": "Grilled chicken rice", "price": 120, "calories": 500, "protein": 35, "carbs": 48, "fat": 12, "sodium": 450, "gi": "low"},
                    {"item_id": "meal_2", "name": "Fried chicken set", "price": 220, "calories": 850, "protein": 30, "carbs": 88, "fat": 34, "sodium": 980, "gi": "medium"},
                ],
            }
        ]

        result = build_healthy_food_recommendations(
            FakeStorage(),
            {"hypertension": load_disease_rules(os.path.dirname(os.path.dirname(__file__)))["hypertension"]},
            catalog,
            "demo_user",
            {"budget": 150, "lat": 25.0338, "lng": 121.5645, "radius_km": 1, "category": "bento"},
            {"groups": load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))["groups"]},
        )

        self.assertEqual(result["radius_km"], 1)
        self.assertEqual(len(result["restaurants"]), 1)
        self.assertEqual(result["restaurants"][0]["recommended_items"][0]["item_name"], "Grilled chicken rice")

    def test_food_search_prefers_whole_fruit_over_processed_matches(self):
        tfda_db = {
            "apple pie": {
                "name_zh": "油炸 apple pie",
                "category": "processed",
                "calories": 68,
                "sugar": 8.5,
                "saturated_fat": 2.1,
                "trans_fat": 0.2,
            },
            "apple": {"name_zh": "apple", "category": "fruit", "calories": 51},
        }

        results = search_foods(FakeStorage(), tfda_db, "apple", 2, "demo_user", lambda food: food)
        self.assertEqual(results[0]["name_zh"], "apple")
        self.assertEqual(results[0]["category"], "fruit")
        fried_result = next(result for result in results if result["category"] == "processed")
        self.assertEqual(fried_result["sugar"], 8.5)
        self.assertEqual(fried_result["saturated_fat"], 2.1)
        self.assertEqual(fried_result["trans_fat"], 0.2)
        self.assertTrue(fried_result["is_fried"])

    def test_detection_reliability_and_portion_range(self):
        high = build_detection_reliability("apple", 0.91, False, {"source": "TFDA"})
        low = build_detection_reliability("bowl", 0.58, True, {"source": "TFDA"})

        self.assertEqual(high["level"], "high")
        self.assertEqual(low["level"], "low")
        self.assertIn("Vision", low["reasons"][0])

        high_range = build_portion_range(100, high["level"])
        low_range = build_portion_range(100, low["level"])
        self.assertEqual(high_range["uncertainty_percent"], 25)
        self.assertEqual(low_range["uncertainty_percent"], 60)
        self.assertLess(high_range["min_g"], high_range["max_g"])

    def test_open_food_facts_product_mapping(self):
        product = {
            "product_name": "Milk Biscuit",
            "brands": "Demo",
            "code": "123456",
            "ingredients_text": "milk, wheat, sugar",
            "allergens_tags": ["en:milk", "en:gluten"],
            "nutriments": {"energy-kcal_100g": 420, "proteins_100g": 7, "carbohydrates_100g": 62, "fat_100g": 14, "sodium_100g": 320},
        }
        mapped = build_open_food_facts_product(product)
        self.assertEqual(mapped["source"], "Open Food Facts")
        self.assertIn("en:milk", mapped["allergens"])

    def test_custom_food_lookup_requires_user_scope(self):
        repo = StorageRepository(None, False, {}, [], [])
        saved = repo.upsert_custom_food(
            {
                "food_id": "custom_1",
                "user_id": "user-a",
                "name_zh": "Test Food",
                "nutrition_per_100g": {"calories": 100},
            }
        )

        self.assertEqual(saved["owner_key"], "user-a:custom_1")
        self.assertIsNone(repo.get_custom_food("custom_1"))
        self.assertEqual(repo.get_custom_food("custom_1", "user-a")["name_zh"], "Test Food")

    def test_vision_food_response_uses_allergen_taxonomy(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        parsed = {
            "meal_guess": "egg bowl",
            "items": [
                {
                    "name_zh": "egg bowl",
                    "confidence": 0.96,
                    "estimated_weight_g": 100,
                }
            ],
        }
        tfda_db = {
            "egg_bowl": {
                "name_zh": "egg bowl",
                "calories": 120,
                "protein": 6,
                "fat": 5,
                "carbs": 10,
                "sodium": 220,
                "fiber": 1,
                "gi": "medium",
                "allergens": ["egg"],
                "source": "TFDA",
            }
        }

        result = build_vision_food_response(parsed, FakeStorage(), tfda_db, rules, taxonomy, [], ["egg"], "demo_user", lambda food: food)

        self.assertEqual(result["summary"]["total_items"], 1)
        self.assertTrue(result["detections"][0]["warnings"])

    def test_profile_build_normalizes_medical_tags(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        taxonomy = load_allergen_taxonomy(os.path.dirname(os.path.dirname(__file__)))
        user = build_user_profile(
            {
                "user_id": "user-a",
                "name": "User A",
                "health_conditions": ["高血壓"],
                "allergens": ["蛋"],
                "activity_multiplier": 1.55,
            },
            rules,
            taxonomy,
        )
        self.assertEqual(user["health_conditions"], ["hypertension"])
        self.assertEqual(user["allergens"], ["egg"])

    def test_validate_restaurant_summary_input_smoke(self):
        with self.assertRaises(ValueError):
            validate_restaurant_summary_input(None, 120, "bento", ["hypertension"])

        with self.assertRaises(ValueError):
            validate_restaurant_summary_input({"budget": 120}, 120, "bento", ["hypertension"])

        restaurant, budget, category, health_conditions = validate_restaurant_summary_input(
            {"name": "Taiwan Bento"}, "not-a-number", "bento", ["hypertension", "", None]
        )
        self.assertEqual(restaurant["name"], "Taiwan Bento")
        self.assertEqual(budget, 0)
        self.assertEqual(category, "bento")
        self.assertEqual(health_conditions, ["hypertension"])

    def test_daily_nutrition_progress_preserves_over_target_amounts(self):
        class OverTargetStorage:
            def get_records(self, user_id: str, date: str | None = None, limit: int = 500):
                return [
                    {
                        "total_calories": 2200,
                        "total_protein": 90,
                        "total_carbs": 210,
                        "total_fat": 72,
                        "total_sodium": 2300,
                        "total_fiber": 10,
                    }
                ]

        progress = build_daily_nutrition_progress(
            OverTargetStorage(),
            "user-a",
            {"daily_calorie_target": 2000, "height": 250, "weight": 140},
            datetime(2026, 7, 18, tzinfo=timezone.utc),
        )

        self.assertEqual(progress["date"], "2026-07-18")
        self.assertEqual(progress["remaining"]["sodium"], 0)
        self.assertEqual(progress["over_by"]["sodium"], 300)
        self.assertEqual(progress["status"]["sodium"], "over")
        self.assertEqual(progress["status"]["protein"], "within_target")
        self.assertGreater(progress["progress_percent"]["calories"], 100)

    def test_google_places_recommendations_apply_conditions_and_allergens(self):
        """Places 路徑之前完全沒套疾病與過敏原規則，等於沒有依「不能吃的食物」推薦。"""
        def places(name):
            return {
                "restaurant_id": f"g_{name}",
                "name": name,
                "tags": ["Google Places"],
                "lat": 25.0338,
                "lng": 121.5645,
                "recommended_items": [
                    {
                        "restaurant_id": f"g_{name}",
                        "restaurant_name": name,
                        "item_id": f"g_{name}_visit",
                        "item_name": "到店後選擇符合預算的餐點",
                        "price": 120,
                        "match_score": 70,
                        "calories": 0,
                        "protein": 0,
                        "carbs": 0,
                        "fat": 0,
                        "sodium": 0,
                        "reasons": [],
                    }
                ],
            }

        class PlacesStorage:
            def __init__(self, conditions, allergens):
                self.conditions = conditions
                self.allergens = allergens

            def get_user(self, user_id):
                return {
                    "user_id": user_id,
                    "height": 170,
                    "weight": 65,
                    "health_conditions": self.conditions,
                    "allergens": self.allergens,
                }

            def get_restaurant_menu(self, name="", place_id=""):
                # 這個案例測的是「沒有建檔菜單時靠店名比對」的路徑
                return None

            def get_records(self, user_id, date=None, limit=500):
                return []

        venues = ["頂呱呱炸雞", "阿宏生猛海鮮熱炒", "清粥小菜"]
        with patch.object(
            healthy_food_service_module,
            "fetch_google_places_restaurants",
            lambda *args, **kwargs: [places(name) for name in venues],
        ):
            blocked = build_google_places_food_recommendations(
                PlacesStorage(["hyperlipidemia"], ["shellfish"]), "user-a", {"budget": 150}
            )
            unrestricted = build_google_places_food_recommendations(
                PlacesStorage([], []), "user-a", {"budget": 150}
            )

        recommended_names = [item["restaurant_name"] for item in blocked["recommended"]]
        self.assertNotIn("頂呱呱炸雞", recommended_names)  # 高血脂：油炸店擋掉
        self.assertEqual([item["restaurant_name"] for item in blocked["filtered_out"]], ["頂呱呱炸雞"])

        # 海鮮店不擋掉（同店仍有可吃的品項），但要出現過敏警告
        seafood = next(item for item in blocked["recommended"] if item["restaurant_name"] == "阿宏生猛海鮮熱炒")
        self.assertTrue(
            any("過敏" in reason for reason in seafood["medical_risk"]["caution_reasons"]),
            seafood["medical_risk"]["caution_reasons"],
        )

        # 沒有設定任何條件時不應該擋掉任何店家
        self.assertEqual(len(unrestricted["recommended"]), 3)
        self.assertEqual(unrestricted["filtered_out"], [])

    @staticmethod
    def _seed_dishes(count, sodium=400, fiber=9):
        return [
            {
                "name": f"dish-{index}",
                "calories": 600,
                "protein": 25,
                "carbs": 70,
                "sugar": 5,
                "fat": 15,
                "saturated_fat": 4,
                "trans_fat": 0,
                "fiber": fiber,
                "sodium": sodium,
            }
            for index in range(count)
        ]

    def test_kidney_disease_treats_protein_as_upper_limit(self):
        """CKD 的蛋白質目標是 W x 0.6 的嚴格限量，超過要判成 over 而不是達標。"""
        class HighProteinStorage:
            def get_records(self, user_id: str, date: str | None = None, limit: int = 500):
                return [{"total_protein": 114, "total_calories": 1500}]

        ckd_user = {"height": 170, "weight": 65, "health_conditions": ["ckd"]}
        healthy_user = {"height": 170, "weight": 65, "health_conditions": []}

        self.assertEqual(build_nutrition_goal_types(ckd_user)["protein"], "upper_limit")
        self.assertEqual(build_nutrition_goal_types(healthy_user)["protein"], "minimum_target")

        progress = build_daily_nutrition_progress(HighProteinStorage(), "user-a", ckd_user)
        self.assertEqual(progress["goal_type"]["protein"], "upper_limit")
        self.assertEqual(progress["status"]["protein"], "over")
        self.assertGreater(progress["over_by"]["protein"], 0)

        healthy_progress = build_daily_nutrition_progress(HighProteinStorage(), "user-a", healthy_user)
        self.assertEqual(healthy_progress["status"]["protein"], "target_met")

    def test_app_today_uses_local_date_not_utc(self):
        """紀錄 timestamp 用本地時間，UTC 的日界會讓本地凌晨抓到昨天的資料。"""
        self.assertEqual(app_today(datetime(2026, 7, 18, 17, 0, tzinfo=timezone.utc)), "2026-07-19")
        self.assertEqual(app_today(datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)), "2026-07-18")

    def test_daily_progress_uses_local_date_for_record_lookup(self):
        class DateCapturingStorage:
            requested_date = None

            def get_records(self, user_id: str, date: str | None = None, limit: int = 500):
                DateCapturingStorage.requested_date = date
                return []

        build_daily_nutrition_progress(
            DateCapturingStorage(),
            "user-a",
            {"height": 170, "weight": 65},
            datetime(2026, 7, 18, 17, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(DateCapturingStorage.requested_date, "2026-07-19")

    def test_tfda_trans_fat_is_stored_in_grams(self):
        """TFDA 原始資料的反式脂肪單位是 mg，轉檔時必須換成 g。"""
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nutrition_db_tw.json")
        with open(db_path, "r", encoding="utf-8") as f:
            tfda_db = json.load(f)

        values = [
            food["trans_fat"]
            for food in tfda_db.values()
            if isinstance(food.get("trans_fat"), (int, float))
        ]
        self.assertTrue(values)
        # 每 100 g 的反式脂肪不可能超過總脂肪 100 g；mg 未換算時最大值會是 2122
        self.assertLess(max(values), 100)

    def test_restaurant_prompt_includes_disease_rules_and_over_target_progress(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        progress = {
            "targets": {"sodium": 2000, "protein": 130},
            "consumed": {"sodium": 2300, "protein": 70},
            "remaining": {"sodium": 0, "protein": 60},
            "over_by": {"sodium": 300, "protein": 0},
            "progress_percent": {"sodium": 115, "protein": 53.8},
            "status": {"sodium": "over", "protein": "within_target"},
        }

        prompt = build_restaurant_summary_prompt(
            {"name": "Taiwan Bento", "tags": ["bento"]},
            150,
            "bento",
            ["hypertension"],
            progress,
            rules,
        )

        self.assertIn("hypertension", prompt)
        self.assertIn("高血壓 / 鈉控制", prompt)
        self.assertIn('"sodium": "over"', prompt)
        self.assertIn('"sodium": 300', prompt)
        self.assertIn("不得為了補足其他營養素", prompt)
        self.assertIn("recommended_foods", prompt)

    def test_normalize_restaurant_summary_returns_personalized_foods(self):
        summary = normalize_restaurant_summary(
            {
                "restaurant_type": "便當店",
                "likely_foods": ["排骨便當"],
                "recommended_foods": [
                    {"name": "烤雞蔬菜便當", "reason": "若店內有供應，少醬可降低已超標鈉的增加。"}
                ],
                "price_range_twd": {"min": 100, "max": 140},
                "health_tips": ["醬汁另外放"],
                "confidence": "medium",
            },
            150,
        )

        self.assertEqual(summary["recommended_foods"][0]["name"], "烤雞蔬菜便當")
        self.assertEqual(summary["budget_fit"], "適合")


if __name__ == "__main__":
    unittest.main()


class NutritionZeroFallbackTests(unittest.TestCase):
    """模型留白的欄位不能當成 0 用——那是上限類目標的假達標。"""

    def test_zero_saturated_fat_is_estimated_from_the_fat_it_must_be_part_of(self):
        from services.robust_restaurant_scraper_service import validate_and_balance_nutrition

        item = validate_and_balance_nutrition(
            {"name": "炸雞腿便當", "calories": 800, "protein": 35, "carbs": 80, "fat": 35,
             "saturated_fat": 0, "sugar": 0, "fiber": 0, "sodium": 900}
        )
        self.assertGreater(item["saturated_fat"], 0)
        self.assertLessEqual(item["saturated_fat"], item["fat"])
        self.assertGreater(item["sugar"], 0)
        self.assertLessEqual(item["sugar"], item["carbs"])

    def test_a_reported_value_is_left_alone(self):
        from services.robust_restaurant_scraper_service import validate_and_balance_nutrition

        item = validate_and_balance_nutrition(
            {"name": "雞腿便當", "calories": 800, "protein": 35, "carbs": 80, "fat": 35,
             "saturated_fat": 6.5, "sugar": 3.0, "fiber": 4.0, "sodium": 900}
        )
        self.assertEqual(item["saturated_fat"], 6.5)
        self.assertEqual(item["sugar"], 3.0)

    def test_sweet_drinks_get_a_much_higher_sugar_estimate_than_a_rice_box(self):
        from services.robust_restaurant_scraper_service import validate_and_balance_nutrition

        drink = validate_and_balance_nutrition(
            {"name": "珍珠奶茶", "calories": 400, "protein": 4, "carbs": 70, "fat": 10, "sugar": 0}
        )
        rice_box = validate_and_balance_nutrition(
            {"name": "雞腿便當", "calories": 800, "protein": 35, "carbs": 80, "fat": 35, "sugar": 0}
        )
        self.assertGreater(drink["sugar"], rice_box["sugar"])


class GeminiKeyRotationTests(unittest.TestCase):
    """一把金鑰額度用完或沒權限，不能把後面的金鑰一起拖下水。"""

    def setUp(self):
        os.environ["GEMINI_API_KEYS"] = "key-a,key-b,key-c"
        os.environ["GEMINI_MODELS"] = "m-lite,m-flash,m-pro"

    @staticmethod
    def _reply(status, items=None):
        class R:
            status_code = status

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": json.dumps({"items": items or []})}]}}]}

        return R()

    def test_a_rate_limited_key_is_abandoned_instead_of_retried_on_every_model(self):
        from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini

        calls = []

        def fake_post(url, **kwargs):
            key = url.split("key=")[1]
            calls.append((key, url.split("/models/")[1].split(":")[0]))
            if key == "key-a":
                return self._reply(429)
            return self._reply(200, [{"name": "餐點", "calories": 500, "protein": 20,
                                      "carbs": 60, "fat": 15, "sodium": 500}])

        with patch("services.robust_restaurant_scraper_service.requests.post", fake_post):
            result = enrich_restaurant_with_gemini("測試店", "台北")

        self.assertTrue(result["items"])
        # key-a 只該被試一次就換掉，而不是三個模型全試一遍
        self.assertEqual([key for key, _ in calls].count("key-a"), 1)

    def test_one_keys_missing_permission_does_not_block_a_later_key(self):
        """404 是金鑰沒權限，不是模型不存在——先前記成全域，後面的金鑰全被跳過。"""
        from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini

        tried = []

        def fake_post(url, **kwargs):
            key = url.split("key=")[1]
            model = url.split("/models/")[1].split(":")[0]
            tried.append((key, model))
            if key in {"key-a", "key-b"}:
                return self._reply(404)
            return self._reply(200, [{"name": "餐點", "calories": 500, "protein": 20,
                                      "carbs": 60, "fat": 15, "sodium": 500}])

        with patch("services.robust_restaurant_scraper_service.requests.post", fake_post):
            result = enrich_restaurant_with_gemini("測試店", "台北")

        self.assertTrue(result["items"])
        self.assertIn("key-c", [key for key, _ in tried])


class GeminiModelDefaultsTests(unittest.TestCase):
    def test_the_first_choice_model_is_a_non_expiring_alias(self):
        """固定版號的模型會被 Google 停用（2.5-flash 已經對新金鑰回 404）。
        首選要用 -latest 別名，模型改朝換代時服務才不會整個停擺。"""
        from services.nutrition_label_service import DEFAULT_GEMINI_MODELS

        self.assertTrue(DEFAULT_GEMINI_MODELS[0].endswith("-latest"), DEFAULT_GEMINI_MODELS)
        self.assertTrue(any(m.endswith("-latest") for m in DEFAULT_GEMINI_MODELS[:2]))

    def test_the_retired_models_are_gone_from_the_defaults(self):
        from services.nutrition_label_service import DEFAULT_GEMINI_MODELS

        for retired in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
            self.assertNotIn(retired, DEFAULT_GEMINI_MODELS)


class GeminiJsonShapeTests(unittest.TestCase):
    """新模型常常直接回陣列，不再包一層 {"items": [...]}。"""

    def test_a_bare_array_is_read_as_the_item_list(self):
        from services.nutrition_label_service import extract_json_items

        self.assertEqual(
            extract_json_items('[{"name": "雞腿飯"}, {"name": "排骨飯"}]'),
            [{"name": "雞腿飯"}, {"name": "排骨飯"}],
        )

    def test_the_wrapped_shape_still_works(self):
        from services.nutrition_label_service import extract_json_items

        self.assertEqual(extract_json_items('{"items": [{"name": "雞腿飯"}]}'), [{"name": "雞腿飯"}])

    def test_a_differently_named_wrapper_still_yields_the_list(self):
        from services.nutrition_label_service import extract_json_items

        self.assertEqual(extract_json_items('{"dishes": [{"name": "雞腿飯"}]}'), [{"name": "雞腿飯"}])

    def test_a_fenced_array_is_unwrapped(self):
        from services.nutrition_label_service import extract_json_items

        self.assertEqual(extract_json_items('```json\n[{"name": "雞腿飯"}]\n```'), [{"name": "雞腿飯"}])

    def test_nothing_usable_returns_an_empty_list_not_a_crash(self):
        from services.nutrition_label_service import extract_json_items

        self.assertEqual(extract_json_items('{"error": "no menu"}'), [])


class OpenNowRecommendationTests(unittest.TestCase):
    """推薦是「現在要去吃」，所以現在沒開的店不該出現。"""

    def _venue(self, name, is_open):
        return {
            "restaurant_id": f"google_{name}", "name": name, "lat": 25.03, "lng": 121.56,
            "address": "台北", "distance_km": 0.4, "tags": ["Google Places"],
            "price_level": 1, "is_open": is_open, "rating": 4.2, "user_ratings_total": 30,
            "match_score": 60, "data_source": "google_places", "nutrition_available": False,
            "recommended_items": [{
                "restaurant_id": f"google_{name}", "restaurant_name": name,
                "restaurant_lat": 25.03, "restaurant_lng": 121.56, "address": "台北",
                "distance_km": 0.4, "tags": ["Google Places"],
                "item_id": f"{name}_visit", "item_name": "到店後選擇符合預算的餐點",
                "price": 100, "calories": 0, "protein": 0, "carbs": 0, "fat": 0,
                "sodium": 0, "gi": None, "match_score": 60,
                "nutrition_available": False, "reasons": [],
            }],
        }

    def _build(self, venues):
        storage = StorageRepository(None, False, {}, [], [])
        storage.upsert_user({"user_id": "u1", "name": "U", "height": 170, "weight": 65, "age": 30})
        with patch.object(healthy_food_service_module, "fetch_google_places_restaurants",
                          return_value=venues):
            return build_google_places_food_recommendations(storage, "u1", {"budget": 150})

    def test_a_venue_that_is_closed_right_now_is_not_recommended(self):
        result = self._build([self._venue("開著的店", True), self._venue("打烊的店", False)])
        names = [r["name"] for r in result["restaurants"]]
        self.assertIn("開著的店", names)
        self.assertNotIn("打烊的店", names)

    def test_the_user_is_told_how_many_were_dropped_for_being_closed(self):
        """清單無故變短會像壞掉，要說明少了幾家。"""
        result = self._build([self._venue("開著的店", True), self._venue("打烊的店", False)])
        self.assertEqual(result["closed_now"], 1)
        self.assertIn("1", result["opening_note"])

    def test_unknown_opening_hours_are_still_recommended(self):
        """不知道營業時間不等於沒開，全丟掉會讓清單常常空的。"""
        result = self._build([self._venue("時間未知的店", None)])
        self.assertEqual([r["name"] for r in result["restaurants"]], ["時間未知的店"])
        self.assertIsNone(result["opening_note"])


class IndexedMenuRecommendationTests(unittest.TestCase):
    """已建檔的店要逐道菜比對疾病禁忌，不是掛一個「到店後再選」的佔位品項。"""

    def _storage(self, conditions=(), allergens=(), menu=None):
        storage = StorageRepository(None, False, {}, [], [])
        storage.upsert_user({
            "user_id": "u1", "name": "U", "height": 170, "weight": 65, "age": 30,
            "health_conditions": list(conditions), "allergens": list(allergens),
        })
        if menu:
            storage.save_restaurant_menu("阿美飯館", menu, venue={"google_place_id": "p1"})
        return storage

    @staticmethod
    def _venue():
        return {
            "restaurant_id": "google_p1", "name": "阿美飯館", "lat": 25.03, "lng": 121.56,
            "address": "台北", "distance_km": 0.3, "tags": ["Google Places"],
            "google_place_id": "p1", "price_level": 1, "is_open": True,
            "rating": 4.3, "user_ratings_total": 50, "match_score": 70,
            "data_source": "google_places", "nutrition_available": False,
            "recommended_items": [{
                "restaurant_id": "google_p1", "restaurant_name": "阿美飯館",
                "distance_km": 0.3, "tags": ["Google Places"],
                "item_id": "google_p1_visit", "item_name": "到店後選擇符合預算的餐點",
                "price": 100, "calories": 0, "protein": 0, "carbs": 0, "fat": 0,
                "sodium": 0, "gi": None, "match_score": 70,
                "nutrition_available": False, "reasons": [],
            }],
        }

    def _build(self, storage, budget=150):
        with patch.object(healthy_food_service_module, "fetch_google_places_restaurants",
                          return_value=[self._venue()]):
            return build_google_places_food_recommendations(storage, "u1", {"budget": budget})

    MENU = [
        {"name": "清蒸鱈魚定食", "price": 130, "calories": 450, "protein": 30, "carbs": 45,
         "fat": 12, "sugar": 3, "saturated_fat": 3, "trans_fat": 0, "fiber": 5, "sodium": 500},
        {"name": "重鹹滷肉飯", "price": 90, "calories": 700, "protein": 20, "carbs": 90,
         "fat": 25, "sugar": 5, "saturated_fat": 9, "trans_fat": 0, "fiber": 2, "sodium": 1800},
        {"name": "頂級和牛套餐", "price": 900, "calories": 500, "protein": 35, "carbs": 20,
         "fat": 30, "sugar": 2, "saturated_fat": 10, "trans_fat": 0, "fiber": 3, "sodium": 400},
    ]

    def test_real_dishes_replace_the_go_and_choose_placeholder(self):
        result = self._build(self._storage(menu=self.MENU))
        names = [item["item_name"] for item in result["recommended"]]
        self.assertNotIn("到店後選擇符合預算的餐點", names)
        self.assertIn("清蒸鱈魚定食", names)
        self.assertTrue(result["nutrition_available"])
        self.assertEqual(result["venues_with_menu"], 1)

    def test_a_dish_breaking_a_disease_limit_is_filtered_out_with_the_reason(self):
        result = self._build(self._storage(conditions=["hypertension"], menu=self.MENU))
        names = [item["item_name"] for item in result["recommended"]]
        self.assertIn("清蒸鱈魚定食", names)
        self.assertNotIn("重鹹滷肉飯", names)
        blocked = {entry["item_name"]: entry["reasons"] for entry in result["filtered_out"]}
        self.assertIn("重鹹滷肉飯", blocked)
        self.assertTrue(any("鈉" in reason for reason in blocked["重鹹滷肉飯"]))

    def test_dishes_over_budget_are_filtered_out(self):
        result = self._build(self._storage(menu=self.MENU))
        blocked = {entry["item_name"]: entry["reasons"] for entry in result["filtered_out"]}
        self.assertIn("頂級和牛套餐", blocked)
        self.assertTrue(any("預算" in reason for reason in blocked["頂級和牛套餐"]))

    def test_a_venue_without_an_indexed_menu_keeps_the_old_behaviour(self):
        result = self._build(self._storage())
        self.assertEqual(result["venues_with_menu"], 0)
        self.assertFalse(result["nutrition_available"])
        self.assertIn("還沒建檔", result["nutrition_note"])


class RemainingCalorieRecommendationTests(unittest.TestCase):
    """吃下去會超過今日剩餘熱量的餐點不該推薦。"""

    MENU = [
        {"name": "小份沙拉", "price": 90, "calories": 200, "protein": 8, "carbs": 20,
         "fat": 8, "sugar": 3, "saturated_fat": 2, "trans_fat": 0, "fiber": 6, "sodium": 300},
        {"name": "大份炒飯", "price": 120, "calories": 900, "protein": 22, "carbs": 120,
         "fat": 28, "sugar": 4, "saturated_fat": 7, "trans_fat": 0, "fiber": 3, "sodium": 600},
    ]

    def _storage(self, eaten_calories=0):
        storage = StorageRepository(None, False, {}, [], [])
        storage.upsert_user({"user_id": "u1", "name": "U", "height": 170, "weight": 65, "age": 30})
        storage.save_restaurant_menu("阿美飯館", self.MENU, venue={"google_place_id": "p1"})
        if eaten_calories:
            storage.insert_record({
                "user_id": "u1", "client_record_id": "eaten",
                "timestamp": f"{app_today()}T09:00:00+08:00", "meal_type": "早餐",
                "foods": [], "total_calories": eaten_calories, "total_protein": 0,
                "total_carbs": 0, "total_fat": 0, "total_sodium": 0, "total_fiber": 0,
                "total_sugar": 0, "total_saturated_fat": 0, "total_trans_fat": 0,
                "source": "manual",
            })
        return storage

    def _build(self, storage):
        venue = {
            "restaurant_id": "google_p1", "name": "阿美飯館", "lat": 25.03, "lng": 121.56,
            "address": "台北", "distance_km": 0.3, "tags": ["Google Places"],
            "google_place_id": "p1", "price_level": 1, "is_open": True, "rating": 4.3,
            "user_ratings_total": 50, "match_score": 70, "data_source": "google_places",
            "nutrition_available": False, "recommended_items": [],
        }
        with patch.object(healthy_food_service_module, "fetch_google_places_restaurants",
                          return_value=[venue]):
            return build_google_places_food_recommendations(storage, "u1", {"budget": 150})

    def test_a_dish_bigger_than_the_remaining_allowance_is_not_recommended(self):
        # 已吃 1200 kcal，目標約 1950，剩下約 750 → 900 kcal 的炒飯要被擋
        result = self._build(self._storage(eaten_calories=1200))
        names = [item["item_name"] for item in result["recommended"]]
        self.assertIn("小份沙拉", names)
        self.assertNotIn("大份炒飯", names)

    def test_the_block_reason_names_the_remaining_allowance(self):
        result = self._build(self._storage(eaten_calories=1200))
        blocked = {entry["item_name"]: entry["reasons"] for entry in result["filtered_out"]}
        self.assertTrue(any("剩餘熱量" in reason for reason in blocked["大份炒飯"]))
        self.assertIsNotNone(result["calorie_note"])

    def test_nothing_is_recommended_once_the_allowance_is_gone(self):
        """額度用完時空清單要有解釋，不然看起來像壞掉。"""
        result = self._build(self._storage(eaten_calories=5000))
        self.assertEqual(result["recommended"], [])
        self.assertIn("用完", result["calorie_note"])

    def test_an_empty_stomach_still_sees_everything(self):
        result = self._build(self._storage())
        names = [item["item_name"] for item in result["recommended"]]
        self.assertIn("小份沙拉", names)
        self.assertIn("大份炒飯", names)
        self.assertIsNone(result["calorie_note"])


class MenuCacheStalenessTests(unittest.TestCase):
    """店家會改菜單、漲價、換營業時間，快取不能永久有效。"""

    def setUp(self):
        self.storage = StorageRepository(None, False, {}, [], [])

    def test_a_freshly_saved_menu_is_not_stale(self):
        self.storage.save_restaurant_menu(
            "阿美飯館", [{"name": "雞腿飯", "calories": 700}], venue={"google_place_id": "p1"}
        )
        doc = self.storage.get_restaurant_menu("阿美飯館", "p1")
        self.assertFalse(self.storage.restaurant_menu_is_stale(doc))

    def test_an_old_menu_is_stale(self):
        from datetime import datetime, timedelta, timezone

        doc = {"cached_at": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()}
        self.assertTrue(self.storage.restaurant_menu_is_stale(doc))

    def test_a_menu_with_no_timestamp_counts_as_stale(self):
        """建檔功能加上時間戳之前存的資料，重建一次就會補上。"""
        self.assertTrue(self.storage.restaurant_menu_is_stale({"items": [{"name": "x"}]}))

    def test_the_age_threshold_is_configurable_per_call(self):
        from datetime import datetime, timedelta, timezone

        doc = {"cached_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()}
        self.assertFalse(self.storage.restaurant_menu_is_stale(doc, max_age_days=30))
        self.assertTrue(self.storage.restaurant_menu_is_stale(doc, max_age_days=1))


class FailureClassificationTests(unittest.TestCase):
    """我們自己的程式錯誤不能偽裝成「模型失敗」。"""

    def test_a_programming_error_is_labelled_as_a_bug(self):
        from services.robust_restaurant_scraper_service import _describe_failure

        message = _describe_failure(AttributeError("'list' object has no attribute 'get'"), "Gemini")
        self.assertIn("[BUG]", message)
        self.assertIn("AttributeError", message)

    def test_a_network_error_is_not_labelled_as_a_bug(self):
        import requests

        from services.robust_restaurant_scraper_service import _describe_failure

        message = _describe_failure(requests.ConnectionError("boom"), "Gemini")
        self.assertNotIn("[BUG]", message)
        self.assertIn("ConnectionError", message)


class ActivityLevelTests(unittest.TestCase):
    """運動係數先前寫死 1.55，臥床的人和運動員拿到同一個 TDEE。"""

    def test_each_level_maps_to_its_own_multiplier(self):
        from services.profile_service import ACTIVITY_LEVELS, resolve_activity_multiplier

        multipliers = {
            resolve_activity_multiplier({"activity_level": level["id"]})
            for level in ACTIVITY_LEVELS
        }
        self.assertEqual(len(multipliers), len(ACTIVITY_LEVELS))
        self.assertEqual(min(multipliers), 1.2)
        self.assertEqual(max(multipliers), 1.9)

    def test_a_chinese_label_resolves_too(self):
        from services.profile_service import resolve_activity_multiplier

        self.assertEqual(resolve_activity_multiplier({"activity_level": "久坐（幾乎不運動）"}), 1.2)

    def test_an_out_of_range_multiplier_is_clamped(self):
        """這個數字最後會決定推薦哪些餐點，不能讓客戶端隨便送。"""
        from services.profile_service import resolve_activity_multiplier

        self.assertEqual(resolve_activity_multiplier({"activity_multiplier": 99}), 1.9)
        self.assertEqual(resolve_activity_multiplier({"activity_multiplier": 0}), 1.2)
        self.assertEqual(resolve_activity_multiplier({"activity_multiplier": "abc"}), 1.55)

    def test_tdee_actually_changes_with_the_level(self):
        from services.profile_service import build_user_profile

        base = {"user_id": "u", "gender": "female", "height": 157, "weight": 50, "age": 22}
        sedentary = build_user_profile({**base, "activity_level": "sedentary"})
        very_active = build_user_profile({**base, "activity_level": "very_active"})
        self.assertEqual(sedentary["bmr"], very_active["bmr"])
        self.assertLess(sedentary["tdee"], very_active["tdee"])
        self.assertEqual(sedentary["tdee"], round(sedentary["bmr"] * 1.2))

    def test_the_default_diet_type_is_one_the_app_offers(self):
        """後端預設值必須是前端選單裡有的選項。

        先前後端給「均衡飲食」，但「我的」頁只接受「葷食」或「素食」，
        於是新帳號一建好，儲存鈕就是灰的，而且不說為什麼。
        清單在 frontend/constants/diet.ts。
        """
        import re
        from pathlib import Path
        from services.profile_service import build_user_profile

        source = (Path(__file__).resolve().parents[2] / "frontend" / "constants" / "diet.ts").read_text(encoding="utf-8")
        offered = set(re.findall(r"'([^']+)'", source.split("DIET_TYPES = [", 1)[1].split("]", 1)[0]))
        self.assertTrue(offered, "沒有從 diet.ts 讀到任何選項")

        profile = build_user_profile({"user_id": "u", "height": 170, "weight": 65, "age": 30})
        self.assertIn(profile["diet_type"], offered)

    def test_onboarding_may_omit_the_calorie_target(self):
        """初次設定不再問「每日目標熱量」，改由 BMR × 活動係數 算出來。

        表單少一個欄位是因為這個預設值成立；如果哪天不成立了，
        新帳號會拿到寫死的 2100 kcal，這條測試要先爆掉。
        """
        from services.profile_service import build_user_profile

        profile = build_user_profile({
            "user_id": "u", "gender": "female", "height": 157, "weight": 50,
            "age": 22, "activity_level": "moderate",
        })
        self.assertEqual(profile["daily_calorie_target"], profile["tdee"])
        self.assertNotEqual(profile["daily_calorie_target"], 2100)

    def test_the_reported_level_matches_the_multiplier_actually_used(self):
        """先前 activity_level 是照抄輸入的，可能跟生效的係數對不上。"""
        from services.profile_service import build_user_profile

        profile = build_user_profile({
            "user_id": "u", "height": 170, "weight": 65, "age": 30,
            "activity_level": "極高活動（勞力工作或每日訓練）", "activity_multiplier": 1.2,
        })
        self.assertEqual(profile["activity_multiplier"], 1.9)
        self.assertIn("極高活動", profile["activity_level"])

    def test_sex_changes_the_bmr(self):
        """編輯表單先前沒有性別欄，一律以男性計算，兩者相差 166 kcal。"""
        from services.profile_service import build_user_profile

        base = {"user_id": "u", "height": 157, "weight": 50, "age": 22}
        male = build_user_profile({**base, "gender": "male"})
        female = build_user_profile({**base, "gender": "female"})
        self.assertEqual(male["bmr"] - female["bmr"], 166)




class RecommendationHonestyTests(unittest.TestCase):
    """推薦不能謊稱安全，也不能把示範資料排在真實店家前面。"""

    def test_ai_guessed_dishes_carry_no_invented_nutrition(self):
        """prompt 明寫「不可輸出精準營養數字」，程式卻用菜名關鍵字補一組。"""
        from services.restaurant_ai_service import normalize_restaurant_summary

        result = normalize_restaurant_summary({
            "restaurant_type": "早餐店",
            "likely_foods": ["蛋餅"],
            "recommended_foods": [{"name": "排骨飯", "reason": "蛋白質足夠"}],
            "price_range_twd": {"min": 60, "max": 120},
            "budget_fit": "適合",
            "health_tips": [],
            "confidence": "low",
        }, budget=150)

        dish = result["recommended_foods"][0]
        self.assertEqual(dish["name"], "排骨飯")
        for nutrient in ("calories", "protein", "carbs", "fat", "sodium"):
            self.assertNotIn(nutrient, dish, f"{nutrient} 是編造的，不該回傳")
        self.assertFalse(dish["nutrition_available"])

    def test_a_dish_the_model_never_named_is_dropped(self):
        from services.restaurant_ai_service import normalize_restaurant_summary

        result = normalize_restaurant_summary({
            "recommended_foods": [{"name": "  ", "reason": "x"}, {"name": "滷肉飯", "reason": "y"}],
            "price_range_twd": {"min": 0, "max": 0},
        }, budget=150)
        self.assertEqual([d["name"] for d in result["recommended_foods"]], ["滷肉飯"])

    def test_a_cautioned_dish_does_not_claim_to_be_compliant(self):
        """糖尿病使用者看到油炸餐點，理由欄先前寫「營養與安全條件相符」。"""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        catalog = load_restaurant_catalog(base)
        rules = load_disease_rules(base)
        taxonomy = load_allergen_taxonomy(base)

        storage = StorageRepository(None, False, {}, [], [])
        storage.upsert_user({
            "user_id": "u1", "name": "U", "height": 170, "weight": 65, "age": 30,
            "health_conditions": ["diabetes"],
        })
        result = build_healthy_food_recommendations(
            storage, rules, catalog, "u1", {"budget": 500, "radius_km": 10}, taxonomy
        )
        for item in result["recommended"]:
            cautions = item.get("medical_risk", {}).get("caution_reasons") or []
            if cautions:
                self.assertNotIn("營養與安全條件相符", item["reasons"],
                                 f"{item['item_name']} 有提醒卻聲稱相符")
