import os
import unittest
from unittest.mock import patch

from services.disease_rule_service import build_allergen_taxonomy_response, build_disease_rules_response, build_medical_metadata_response, load_allergen_taxonomy, load_disease_rules, normalize_allergen_ids, normalize_condition_ids
from services.food_analysis_service import build_detection_reliability, build_portion_range
from services.food_service import search_foods
from services.healthy_food_service import build_healthy_food_recommendations, load_restaurant_catalog
from services.history_service import build_history_response
from services.open_food_facts_service import build_open_food_facts_product
from services.profile_service import build_bmr_response, build_user_profile
from services.recommend_service import build_feedback_profile, build_preference_profile, compute_feedback_adjustment, compute_preference_score
from services.restaurant_ai_service import validate_restaurant_summary_input
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

    def get_recommendation_feedback(self, user_id: str, limit: int = 100):
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
            "apple pie": {"name_zh": "apple pie", "category": "processed", "calories": 68},
            "apple": {"name_zh": "apple", "category": "fruit", "calories": 51},
        }

        results = search_foods(FakeStorage(), tfda_db, "apple", 2, "demo_user", lambda food: food)
        self.assertEqual(results[0]["name_zh"], "apple")
        self.assertEqual(results[0]["category"], "fruit")

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

    def test_preference_score(self):
        profile = build_preference_profile([
            {"foods": [{"name": "chicken", "calories": 220, "protein": 32, "sodium": 300, "source": "manual"}]}
        ])
        score, reasons = compute_preference_score(
            {"name_zh": "chicken salad", "label": "chicken", "calories": 240, "protein": 30, "sodium": 260, "source": "manual"},
            profile,
        )
        self.assertGreater(score, 0)
        self.assertGreater(len(reasons), 0)

    def test_feedback_adjustment_rewards_and_penalizes(self):
        profile = build_feedback_profile([
            {"item_label": "salad", "action": "accepted"},
            {"item_label": "salad", "action": "accepted"},
            {"item_label": "burger", "action": "disliked"},
            {"item_label": "soup", "action": "skipped"},
        ])

        salad_score, salad_reasons = compute_feedback_adjustment({"label": "salad"}, profile)
        burger_score, burger_reasons = compute_feedback_adjustment({"label": "burger"}, profile)
        soup_score, soup_reasons = compute_feedback_adjustment({"label": "soup"}, profile)

        self.assertGreater(salad_score, 0)
        self.assertLess(burger_score, 0)
        self.assertLess(soup_score, 0)
        self.assertEqual(profile["total"], 4)

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


if __name__ == "__main__":
    unittest.main()
