import unittest

from services.disease_rule_service import load_disease_rules
from services.history_service import build_history_response
from services.predict_service import assess_detection
from services.profile_service import build_bmr_response
from services.recommend_service import build_preference_profile, compute_preference_score
from yolo_tfda_mapping import YOLO_MANUAL_SEARCH_HINTS


class FakeStorage:
    def get_history(self, user_id: str, days: int):
        return [
            {"date": "2026-04-28", "record_count": 2, "calories": 1000, "protein": 50, "carbs": 120, "fat": 30, "sodium": 900},
            {"date": "2026-04-29", "record_count": 1, "calories": 800, "protein": 40, "carbs": 100, "fat": 20, "sodium": 700},
        ]


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
        rules = load_disease_rules("backend")
        self.assertIn("高血壓", rules)
        self.assertIn("max_sodium_per_meal", rules["高血壓"])

    def test_generic_detection_returns_search_hints(self):
        result = assess_detection("cup", 0.9, {"calories": 10}, {}, {}, YOLO_MANUAL_SEARCH_HINTS)
        self.assertFalse(result["accepted"])
        self.assertIn("咖啡", result["search_hints"])

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


if __name__ == "__main__":
    unittest.main()
