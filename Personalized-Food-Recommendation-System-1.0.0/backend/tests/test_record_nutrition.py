import copy
import json
import unittest

from services.nutrition_profile_service import NUTRIENTS, UNITS, NutritionProfileError, build_nutrition_profile
from services.record_nutrition_service import aggregate_record_coverage, enrich_record_nutrition, normalize_v2_record


def manual(**changes):
    values = dict.fromkeys(NUTRIENTS)
    values.update(calories=100, protein=5, carbs=10, fat=3, sugar=0)
    values.update(changes)
    return {"item_id": "a", "name": "Food", "weight_g": 30, "portion_source": "user_adjusted",
            "user_entered_nutrients": values}


def record(foods=None, **changes):
    return {"nutrition_contract_version": 2, "foods": foods if foods is not None else [manual()], **changes}


class RecordNutritionTests(unittest.TestCase):
    def test_manual_precision_and_original_snapshot_survive_json_edit(self):
        food = manual(calories={"value": "123.456789", "unit": "kcal", "comparison": "exact"})
        saved = normalize_v2_record(record([food]))
        draft = json.loads(json.dumps(saved))
        draft["base_revision"] = 0
        draft["foods"][0]["weight_g"] = 123.45
        changed = normalize_v2_record(draft, existing=saved)
        self.assertAlmostEqual(changed["foods"][0]["calories"], 123.456789 * 1.2345)
        self.assertEqual(changed["foods"][0]["nutrition_profile"], saved["foods"][0]["nutrition_profile"])
        self.assertIsNone(changed["foods"][0]["sodium"])
        self.assertEqual(changed["foods"][0]["sugar"], 0)

    def test_unknown_weight_and_unmatched_stay_in_denominator(self):
        a = manual()
        a["weight_g"] = None
        saved = normalize_v2_record(record([a, {"item_id": "b", "name": "Unknown"}]))
        row = saved["nutrition_context"]["coverage"]["nutrients"]["calories"]
        self.assertEqual((row["known_sum"], row["eligible_items"], row["unresolved_items"]), (0, 2, 2))
        self.assertIsNone(saved["foods"][0]["calories"])

    def test_manual_edits_keep_original_reference(self):
        saved = normalize_v2_record(record())
        draft = record([manual(calories=200)], base_revision=0)
        changed = normalize_v2_record(draft, existing=saved)
        self.assertEqual(changed["foods"][0]["source"], "user_modified")
        self.assertEqual(changed["foods"][0]["original_nutrition_profile"], saved["foods"][0]["nutrition_profile"])

    def test_public_profile_upload_does_not_gain_source_authority(self):
        profile = normalize_v2_record(record())["foods"][0]["nutrition_profile"]
        with self.assertRaisesRegex(NutritionProfileError, "authority"):
            normalize_v2_record(record([{"item_id": "a", "name": "Food", "nutrition_profile": profile}]))

    def test_exclusion_requires_not_consumed_and_preserves_item(self):
        food = manual()
        food["included"] = False
        with self.assertRaises(NutritionProfileError):
            normalize_v2_record(record([food]))
        food["exclusion_reason"] = "not_consumed"
        saved = normalize_v2_record(record([food]))
        self.assertEqual(len(saved["foods"]), 1)
        self.assertEqual(saved["nutrition_context"]["coverage"]["nutrients"]["calories"]["status"], "unknown")

    def test_recognition_item_cannot_disappear(self):
        with self.assertRaises(NutritionProfileError):
            normalize_v2_record(record(nutrition_context={"recognition_context": {"items": [{"item_id": "missing"}]}}))

    def test_client_cannot_assert_visual_completeness_or_coverage(self):
        saved = normalize_v2_record(record(nutrition_context={"visual_completeness": "complete", "coverage": {}}))
        self.assertEqual(saved["nutrition_context"]["visual_completeness"], "not_verified")
        self.assertEqual(saved["nutrition_context"]["recognition_context_authority"], "client_supplied")

    def test_invalid_numbers_and_item_ids_rejected(self):
        for value in (True, -1, "100", float("inf")):
            with self.subTest(value=value), self.assertRaises(NutritionProfileError):
                food = manual()
                food["weight_g"] = value
                normalize_v2_record(record([food]))
        with self.assertRaises(NutritionProfileError):
            normalize_v2_record(record([manual(), manual()]))

    def test_unknown_snapshot_does_not_mutate_stored_input(self):
        saved = normalize_v2_record(record())
        before = copy.deepcopy(saved)
        enriched = enrich_record_nutrition(saved)
        enriched["foods"][0]["nutrition_profile"]["source_details"]["food_name"] = "Changed"
        self.assertEqual(saved, before)

    def test_local_reference_resolves_on_server(self):
        profile = normalize_v2_record(record())["foods"][0]["nutrition_profile"]
        source = {"name": "Food", "nutrition_profile": profile, "source": "TFDA", "is_fried": False}
        saved = normalize_v2_record(record([{"item_id": "a", "name": "Food", "food_key": "local", "weight_g": 100}]),
                                    resolve_food=lambda key: source)
        self.assertEqual(saved["foods"][0]["source"], "TFDA")
        self.assertEqual(saved["total_calories"], 100)
        with self.assertRaises(NutritionProfileError):
            normalize_v2_record(record([{"item_id": "a", "name": "Different", "food_key": "local"}]),
                                resolve_food=lambda key: source)

    def test_daily_mixed_legacy_preserves_zero_and_unknown(self):
        current = normalize_v2_record(record())
        coverage = aggregate_record_coverage([current, {"foods": [{"name": "Legacy"}], "total_calories": 0}])
        row = coverage["nutrients"]["calories"]
        self.assertEqual(row["known_sum"], 30)
        self.assertEqual((row["status"], row["legacy_items"], row["eligible_items"]), ("legacy_unknown", 1, 2))
        self.assertIsNone(row["total_upper_bound"])

    def test_bound_is_not_point_or_whole_day_bound_with_unknown(self):
        first = normalize_v2_record(record([manual(sodium={"value": "0.1", "unit": "mg", "comparison": "less_than"})]))
        row = aggregate_record_coverage([first])["nutrients"]["sodium"]
        self.assertEqual(row["known_items"], 0)
        self.assertAlmostEqual(row["total_upper_bound"], .03)
        second = normalize_v2_record(record([{"item_id": "a", "name": "Unknown"}]))
        self.assertIsNone(aggregate_record_coverage([first, second])["nutrients"]["sodium"]["total_upper_bound"])

    def test_empty_aggregation_is_unknown(self):
        row = aggregate_record_coverage([])["nutrients"]["calories"]
        self.assertEqual((row["eligible_items"], row["status"]), (0, "unknown"))

    def test_aggregate_nonfinite_total_bound_has_typed_error(self):
        records = []
        for comparison in ("exact", "less_than"):
            food = manual(calories={"value": "900", "unit": "kcal", "comparison": comparison})
            food["weight_g"] = 1.8e307
            records.append(normalize_v2_record(record([food])))
        with self.assertRaises(NutritionProfileError):
            aggregate_record_coverage(records)
        with self.assertRaises(NutritionProfileError):
            aggregate_record_coverage([{"total_calories": 10 ** 10000}])

    def test_manual_nutrient_edit_keeps_known_allergens_and_identity(self):
        saved = normalize_v2_record(record())
        saved["foods"][0].update(allergens=["egg"], is_fried=True, gi="high")
        changed = normalize_v2_record(record([manual(sodium=1)], base_revision=0), existing=saved)
        self.assertEqual(changed["foods"][0]["allergens"], ["egg"])
        self.assertTrue(changed["foods"][0]["is_fried"])
        self.assertEqual(changed["foods"][0]["original_food_identity"]["name"], "Food")
        renamed = manual()
        renamed["name"] = "Another food"
        with self.assertRaises(NutritionProfileError):
            normalize_v2_record(record([renamed], base_revision=0), existing=saved)


if __name__ == "__main__":
    unittest.main()
