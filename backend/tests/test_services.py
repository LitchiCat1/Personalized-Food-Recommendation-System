import os
import unittest

from services.disease_rule_service import build_disease_rules_response, load_disease_rules
from services.food_analysis_service import build_detection_reliability, build_portion_range
from services.food_service import search_foods
from services.healthy_food_service import load_restaurant_catalog
from services.history_service import build_history_response
from services.profile_service import build_bmr_response
from services.recommend_service import (
    build_feedback_profile,
    build_preference_profile,
    compute_feedback_adjustment,
    compute_preference_score,
)
from services.vision_food_service import build_vision_food_response


class FakeStorage:
    def get_history(self, user_id: str, days: int):
        return [
            {"date": "2026-04-28", "record_count": 2, "calories": 1000, "protein": 50, "carbs": 120, "fat": 30, "sodium": 900},
            {"date": "2026-04-29", "record_count": 1, "calories": 800, "protein": 40, "carbs": 100, "fat": 20, "sodium": 700},
        ]

    def get_custom_foods(self, user_id: str | None = None):
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
        self.assertIn("高血壓", rules)
        self.assertIn("max_sodium_per_meal", rules["高血壓"])
        self.assertIn("rule_version", rules["高血壓"])
        self.assertIn("medical_disclaimer", rules["高血壓"])

    def test_disease_rules_governance_response(self):
        rules = load_disease_rules(os.path.dirname(os.path.dirname(__file__)))
        response = build_disease_rules_response(rules)

        self.assertEqual(response["count"], len(rules))
        self.assertIn("medical_disclaimer", response)
        self.assertIn("needs_clinical_review", response["review_status_counts"])
        hypertension = next(item for item in response["conditions"] if item["condition"] == "高血壓")
        self.assertEqual(hypertension["limits"]["max_sodium_per_meal"], 600)
        self.assertGreater(len(hypertension["references"]), 0)

    def test_restaurant_catalog_load(self):
        catalog = load_restaurant_catalog(os.path.dirname(os.path.dirname(__file__)))
        self.assertGreater(len(catalog), 0)
        self.assertIn("items", catalog[0])
        self.assertGreater(len(catalog[0]["items"]), 0)

    def test_food_search_prefers_whole_fruit_over_processed_matches(self):
        tfda_db = {
            "脫脂保久濃稠發酵乳(草莓&蘋果)": {
                "name_zh": "脫脂保久濃稠發酵乳(草莓&蘋果)",
                "category": "乳品類",
                "calories": 68,
            },
            "蘋果平均值(混色)": {
                "name_zh": "蘋果平均值(混色)",
                "name_en": "Apple",
                "category": "水果類",
                "calories": 51,
            },
        }

        results = search_foods(FakeStorage(), tfda_db, "蘋果", 2, "demo_user", lambda food: food)

        self.assertEqual(results[0]["name_zh"], "蘋果平均值(混色)")
        self.assertEqual(results[0]["category"], "水果類")

    def test_detection_reliability_and_portion_range(self):
        high = build_detection_reliability("apple", 0.91, False, {"source": "TFDA"})
        low = build_detection_reliability("bowl", 0.58, True, {"source": "TFDA"})

        self.assertEqual(high["level"], "high")
        self.assertEqual(low["level"], "low")
        self.assertIn("Gemini", low["reasons"][2])

        high_range = build_portion_range(100, high["level"])
        low_range = build_portion_range(100, low["level"])
        self.assertEqual(high_range["uncertainty_percent"], 25)
        self.assertEqual(low_range["uncertainty_percent"], 60)
        self.assertLess(high_range["min_g"], high_range["max_g"])

    def test_vision_food_response_matches_tfda_and_scales_nutrition(self):
        parsed = {
            "meal_guess": "便當",
            "items": [
                {
                    "name_zh": "白飯",
                    "confidence": 0.86,
                    "estimated_weight_g": 180,
                    "portion_description": "約一碗",
                    "visual_evidence": "照片右下方白色米飯",
                    "alternatives": ["白米飯"],
                }
            ],
            "uncertainty_notes": ["份量為照片估算"],
        }
        tfda_db = {
            "白飯": {
                "name_zh": "白飯",
                "calories": 183,
                "protein": 3,
                "fat": 0.3,
                "carbs": 40,
                "sodium": 2,
                "fiber": 0.4,
            }
        }

        response = build_vision_food_response(
            parsed,
            FakeStorage(),
            tfda_db,
            {},
            [],
            [],
            "demo_user",
            lambda food: food,
        )

        self.assertEqual(response["engine"], "gemini-vision-db-lookup")
        self.assertEqual(response["nutrition_grounding"], "database_only")
        self.assertEqual(len(response["detections"]), 1)
        detection = response["detections"][0]
        self.assertEqual(detection["name_zh"], "白飯")
        self.assertEqual(detection["nutrition"]["calories"], 329)
        self.assertEqual(detection["portion_estimation_method"], "gemini_vision_portion_estimate_v1")
        self.assertIn("reliability", detection)

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
        self.assertIn("採納", salad_reasons[0])
        self.assertIn("不喜歡", burger_reasons[0])
        self.assertEqual(profile["total"], 4)


if __name__ == "__main__":
    unittest.main()
