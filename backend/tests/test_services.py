import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.disease_rule_service import build_allergen_taxonomy_response, build_disease_rules_response, build_medical_metadata_response, load_allergen_taxonomy, load_disease_rules, normalize_allergen_ids, normalize_condition_ids
from services.food_analysis_service import build_detection_reliability, build_portion_range
from services.food_service import search_foods
from services.healthy_food_service import build_healthy_food_recommendations, load_restaurant_catalog
from services.history_service import build_history_response
from services.open_food_facts_service import build_open_food_facts_product
from services.nutrition_progress_service import build_daily_nutrition_progress, calculate_pdf_daily_targets
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
        energy = ideal_weight * 25
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
        self.assertEqual(kidney["calcium"], 800)

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
                "calcium": 12,
                "iron": 0.7,
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
        self.assertEqual(fried_result["calcium"], 12)
        self.assertEqual(fried_result["iron"], 0.7)
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
