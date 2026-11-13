from datetime import datetime, timezone
import unittest

from services.nutrition_profile_service import NUTRIENTS, UNITS, NutritionProfileError, build_nutrition_profile
from services.nutrition_progress_service import build_daily_nutrition_progress


NOW = datetime(2026, 11, 13, 1, tzinfo=timezone.utc)
USER = {"height": 170, "weight": 65, "age": 30, "gender": "male", "daily_calorie_target": 2000}


def record(**overrides):
    values = {"calories": 100, "protein": 5, "carbs": 10, "fat": 2, "sugar": 0,
              "saturated_fat": 0, "trans_fat": 0, "sodium": 100, "fiber": 1}
    values.update(overrides)
    nutrition = build_nutrition_profile({
        field: None if values[field] is None else {"value": values[field], "unit": UNITS[field], "comparison": "exact"}
        for field in NUTRIENTS
    }, basis="per_100g")
    return {"nutrition_contract_version": 2, "nutrition_context": {"contract_version": 2},
            "foods": [{"item_id": "food", "name": "food", "nutrition_profile": nutrition,
                       "weight_g": 100, "portion_source": "user_weighed"}],
            "total_calories": 5000, "total_sodium": 5000}


class FullStorage:
    def __init__(self, records):
        self.records = records
        self.requests = []

    def get_all_records(self, user_id, date_str=None):
        self.requests.append((user_id, date_str))
        return self.records

    def get_records(self, *args, **kwargs):
        raise AssertionError("Daily coverage must use complete storage scope")


class NutritionProgressV2Tests(unittest.TestCase):
    def progress(self, records, **kwargs):
        return build_daily_nutrition_progress(FullStorage(records), "user", USER, NOW, **kwargs)

    def test_profile_known_sums_override_stale_numeric_record_totals(self):
        result = self.progress([record()])
        self.assertEqual(result["nutrition_contract_version"], 2)
        self.assertEqual(result["consumed"]["calories"], 100)
        self.assertEqual(result["consumed"]["sodium"], 100)
        self.assertEqual(result["coverage"]["nutrients"]["sodium"]["status"], "complete")

    def test_missing_sodium_has_no_remaining_allowance(self):
        result = self.progress([record(sodium=None)])
        self.assertIsNone(result["remaining"]["sodium"])
        self.assertIsNone(result["under_by"]["sodium"])
        self.assertEqual(result["status"]["sodium"], "unknown")
        self.assertEqual(result["consumed"]["sodium"], 0)

    def test_known_overage_survives_partial_coverage(self):
        result = self.progress([record(sodium=2500), record(sodium=None)])
        self.assertEqual(result["consumed"]["sodium"], 2500)
        self.assertEqual(result["over_by"]["sodium"], 500)
        self.assertEqual(result["status"]["sodium"], "over")
        self.assertIsNone(result["remaining"]["sodium"])

    def test_missing_calories_and_fiber_do_not_create_deficiency_claims(self):
        result = self.progress([record(calories=None, fiber=None)])
        shortfalls = {entry["nutrient"] for entry in result["shortfalls"]}
        self.assertNotIn("calories", shortfalls)
        self.assertNotIn("fiber", shortfalls)
        self.assertIn("protein", shortfalls)
        self.assertIsNone(result["remaining"]["calories"])

    def test_mixed_legacy_zero_stays_legacy_unknown(self):
        result = self.progress([record(), {"total_calories": 0, "total_sodium": 0, "foods": []}])
        self.assertEqual(result["consumed"]["sodium"], 100)
        self.assertEqual(result["coverage"]["nutrients"]["sodium"]["status"], "legacy_unknown")
        self.assertIsNone(result["remaining"]["sodium"])
        self.assertEqual(result["shortfalls"], [])

    def test_legacy_only_can_request_v2_unknown_semantics(self):
        result = self.progress([{"total_sodium": 0}], nutrition_contract_version=2)
        self.assertEqual(result["coverage"]["nutrients"]["sodium"]["status"], "legacy_unknown")
        self.assertIsNone(result["remaining"]["sodium"])

    def test_empty_v2_day_has_no_deficiency_or_remaining_claim(self):
        result = self.progress([], nutrition_contract_version=2)
        self.assertEqual(result["shortfalls"], [])
        self.assertEqual(result["status"]["calories"], "unknown")
        self.assertIsNone(result["remaining"]["calories"])

    def test_complete_storage_scope_includes_more_than_five_hundred_records(self):
        storage = FullStorage([record(sodium=1) for _index in range(501)])
        result = build_daily_nutrition_progress(storage, "user", USER, NOW)
        self.assertTrue(result["scope_complete"])
        self.assertEqual(result["consumed"]["sodium"], 501)
        self.assertEqual(result["coverage"]["nutrients"]["sodium"]["eligible_items"], 501)
        self.assertEqual(storage.requests, [("user", "2026-11-13")])

    def test_capped_legacy_adapter_never_claims_complete_day(self):
        class CappedStorage:
            def get_records(self, user_id, date, limit=500):
                return [record(sodium=1) for _index in range(limit)]

        result = build_daily_nutrition_progress(CappedStorage(), "user", USER, NOW)
        self.assertFalse(result["scope_complete"])
        self.assertEqual(result["consumed"]["sodium"], 500)
        self.assertEqual(result["coverage"]["nutrients"]["sodium"]["eligible_items"], 501)
        self.assertIsNone(result["remaining"]["sodium"])

    def test_percentage_overflow_is_a_typed_error(self):
        source = record(trans_fat=1)
        source["foods"][0]["weight_g"] = 1.8e307
        with self.assertRaises(NutritionProfileError) as caught:
            self.progress([source])
        self.assertEqual(caught.exception.code, "numeric_range")


if __name__ == "__main__":
    unittest.main()
