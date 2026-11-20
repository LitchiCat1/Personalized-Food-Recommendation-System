"""Offline regressions for custom-food units and label numeric validation."""

import math
import unittest

from services.food_service import build_custom_food_doc
from services.nutrition_label_service import (
    build_custom_food_search_result,
    extract_number,
    normalize_nutrition_payload,
    normalize_ocr_result,
    scale_nutrition_per_100g,
)
from services.vision_nutrition_service import find_vision_food_matches


SERVING = {"calories": 400, "protein": 10, "fat": 10, "carbs": 60, "sodium": 600}
HUNDRED = {key: value / 2 for key, value in SERVING.items()}


class CustomNutritionBasisTests(unittest.TestCase):
    def build(self, **fields):
        return build_custom_food_doc(
            {"name_zh": "Test meal", "user_id": "owner", **fields},
            normalize_nutrition_payload,
            scale_nutrition_per_100g,
            extract_number,
        )

    def match(self, doc):
        class Storage:
            def get_custom_foods(self, _user_id):
                return [doc]

        return find_vision_food_matches(
            Storage(), {}, {"name_zh": "Test meal"}, "owner", build_custom_food_search_result
        )

    def legacy(self, **fields):
        return {"food_id": "legacy", "name_zh": "Test meal", **fields}

    def test_serving_is_converted_once_and_original_table_is_retained(self):
        doc = self.build(serving_size_g=200, unit="per serving", nutrition_per_serving=SERVING)
        self.assertEqual(doc["nutrition_per_serving"]["calories"], 400)
        self.assertEqual(doc["nutrition_per_100g"]["calories"], 200)
        self.assertEqual(doc["unit"], "per 100g")
        self.assertEqual(doc["nutrition_basis"], "per_100g")
        self.assertEqual(doc["original_unit"], "per serving")
        self.assertEqual(self.match(doc)[0]["calories"], 200)

    def test_legacy_stale_serving_unit_uses_actual_hundred_gram_table(self):
        doc = self.legacy(
            serving_size_g=200, unit="per serving", nutrition_per_serving=SERVING,
            nutrition_per_100g=HUNDRED,
        )
        result = build_custom_food_search_result(doc)
        self.assertEqual(result["unit"], "per 100g")
        self.assertEqual(result["nutrition_basis_status"], "valid")
        self.assertEqual(self.match(doc)[0]["calories"], 200)
        self.assertEqual(doc["unit"], "per serving")

    def test_legacy_serving_only_table_is_still_supported(self):
        doc = self.legacy(serving_size_g=200, nutrition_per_serving=SERVING)
        self.assertEqual(build_custom_food_search_result(doc)["unit"], "per serving")
        self.assertEqual(self.match(doc)[0]["sodium"], 300)

    def test_all_null_hundred_table_does_not_hide_serving_table(self):
        doc = self.legacy(
            serving_size_g=200, nutrition_per_serving=SERVING,
            nutrition_per_100g={key: None for key in HUNDRED},
        )
        self.assertEqual(self.match(doc)[0]["calories"], 200)

    def test_missing_weight_preserves_original_serving_but_cannot_auto_match(self):
        doc = self.build(nutrition_per_serving=SERVING)
        self.assertEqual(doc["unit"], "per serving")
        self.assertIsNone(doc["nutrition_per_100g"])
        self.assertEqual(doc["nutrition_per_serving"]["calories"], 400)
        self.assertEqual(self.match(doc), [])

    def test_hundred_table_does_not_require_serving_weight(self):
        doc = self.build(nutrition_per_100g=HUNDRED)
        self.assertEqual(self.match(doc)[0]["calories"], 200)

    def test_invalid_nutrients_are_rejected_in_all_supported_fields(self):
        for field in normalize_nutrition_payload({}):
            for value in (True, False, -1, math.nan, math.inf, -math.inf, "12", 10 ** 1000):
                with self.subTest(field=field, value=str(value)[:15]):
                    with self.assertRaises(ValueError):
                        self.build(nutrition_per_100g={**HUNDRED, field: value})

    def test_invalid_portion_metadata_is_rejected(self):
        for field in ("serving_size_g", "servings_per_container"):
            for value in (True, False, 0, -1, math.nan, math.inf, "200", 10 ** 1000):
                with self.subTest(field=field, value=str(value)[:15]):
                    with self.assertRaises(ValueError):
                        self.build(**{"nutrition_per_100g": HUNDRED, field: value})

    def test_structured_nutrition_must_be_an_object(self):
        for field in ("nutrition_per_100g", "nutrition_per_serving"):
            for value in ([], "bad", 2, False):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.build(**{"nutrition_per_100g": HUNDRED, field: value})

    def test_conflicting_tables_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build(serving_size_g=200, nutrition_per_serving=SERVING,
                       nutrition_per_100g={**HUNDRED, "calories": 250})

    def test_two_tables_without_weight_cannot_be_verified(self):
        with self.assertRaises(ValueError):
            self.build(nutrition_per_serving=SERVING, nutrition_per_100g=HUNDRED)

    def test_legacy_conflict_is_excluded_without_rewriting_document(self):
        doc = self.legacy(serving_size_g=200, nutrition_per_serving=SERVING,
                          nutrition_per_100g={**HUNDRED, "calories": 250})
        result = build_custom_food_search_result(doc)
        self.assertEqual(result["nutrition_basis_status"], "conflicting")
        self.assertIsNone(result["calories"])
        self.assertEqual(self.match(doc), [])
        self.assertEqual(doc["nutrition_per_100g"]["calories"], 250)

    def test_independent_table_rounding_is_tolerated(self):
        doc = self.build(
            serving_size_g=133,
            nutrition_per_serving={"calories": 399, "protein": 2.2, "fat": 3.1, "carbs": 5.2, "sodium": 10},
            nutrition_per_100g={"calories": 300, "protein": 1.7, "fat": 2.3, "carbs": 3.9, "sodium": 8},
        )
        self.assertEqual(build_custom_food_search_result(doc)["nutrition_basis_status"], "valid")

    def test_volume_and_unknown_bases_are_not_treated_as_grams(self):
        for unit in ("per 100ml", "per bottle", "unknown"):
            with self.subTest(unit=unit):
                with self.assertRaises(ValueError):
                    self.build(unit=unit, serving_size_g=200, nutrition_per_serving=SERVING)
                doc = self.legacy(unit=unit, serving_size_g=200, nutrition_per_100g=HUNDRED)
                self.assertEqual(build_custom_food_search_result(doc)["nutrition_basis_status"], "invalid")
                self.assertEqual(self.match(doc), [])

    def test_missing_optional_fields_remain_null_and_measured_zero_remains_zero(self):
        doc = self.build(nutrition_per_100g={**HUNDRED, "sodium": 0})
        result = build_custom_food_search_result(doc)
        self.assertIsNone(result["sugar"])
        self.assertIsNone(result["fiber"])
        self.assertEqual(result["sodium"], 0)

    def test_invalid_legacy_values_are_excluded_without_raising(self):
        for value in (True, -1, math.nan, math.inf, "200"):
            with self.subTest(value=value):
                doc = self.legacy(nutrition_per_100g={**HUNDRED, "calories": value})
                self.assertEqual(build_custom_food_search_result(doc)["nutrition_basis_status"], "invalid")
                self.assertEqual(self.match(doc), [])

    def test_label_text_parsing_preserves_valid_ocr_flow(self):
        result = normalize_ocr_result({"serving_size_g": "200 g", "nutrition_per_serving": {"calories": "400 kcal"}})
        self.assertEqual(result["nutrition_per_100g"]["calories"], 200)
        self.assertEqual(result["nutrition_per_100g_source"], "calculated")

    def test_ocr_preserves_printed_values_and_flags_mismatches(self):
        base = {"serving_size_g": 40, "nutrition_per_serving": {"calories": 180, "sugar": 0}}
        for calories, conflict in ((450, False), (500, True)):
            result = normalize_ocr_result({**base, "nutrition_per_100g": {"calories": calories, "sugar": 0, "fiber": "<0.1 g"}})
            self.assertEqual(result["nutrition_per_100g"]["calories"], calories)
            self.assertIsNone(result["nutrition_per_100g"]["fiber"])
            self.assertEqual(result["nutrition_per_100g"]["sugar"], 0)
            self.assertEqual(result["nutrition_per_100g_source"], "label")
            self.assertEqual(result["nutrition_basis_conflict"], conflict)

    def test_ocr_does_not_convert_serving_volume_to_grams(self):
        for weight in ("100mL", "40mg", "0.04 kg", "250cc", "40-60 g", "40g / 320g", "200毫公克", "40"):
            with self.subTest(weight=weight):
                result = normalize_ocr_result({"serving_size_g": weight, "nutrition_per_serving": {"calories": 100}})
                self.assertIsNone(result["serving_size_g"])
                self.assertIsNone(result["nutrition_per_100g"])

    def test_ocr_accepts_only_a_single_serving_count(self):
        for raw in ("8-10份", "約8份", "8份 / 10份", "8盒"):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_ocr_result({"servings_per_container": raw})["servings_per_container"])
        self.assertEqual(normalize_ocr_result({"servings_per_container": "8 份"})["servings_per_container"], 8)

    def test_ocr_missing_serving_grams_preserves_independent_printed_basis(self):
        result = normalize_ocr_result({"package_net_weight_g": 320,
                                       "nutrition_per_serving": {"calories": 186.48},
                                       "nutrition_per_100g": {"calories": 466.2}})
        self.assertTrue(result["nutrition_basis_unverifiable"])
        self.assertFalse(result["nutrition_basis_conflict"])
        self.assertEqual(result["nutrition_per_100g"]["calories"], 466.2)
        self.assertEqual(result["nutrition_per_100g_source"], "label")

    def test_ocr_retains_precision_and_rejects_wrong_units_and_qualified_values(self):
        result = normalize_ocr_result({"serving_size_g": 40, "nutrition_per_serving": {
            "calories": "186.48 kcal", "trans_fat": "0.04 公克", "sodium": "0.15 g",
            "protein": "未檢出 (<0.1 g)", "sugar": 0}})
        serving, hundred = result["nutrition_per_serving"], result["nutrition_per_100g"]
        self.assertEqual(serving["calories"], 186.48)
        self.assertAlmostEqual(hundred["calories"], 466.2)
        self.assertEqual(serving["trans_fat"], 0.04)
        self.assertEqual(hundred["trans_fat"], 0.1)
        self.assertIsNone(serving["sodium"])
        self.assertIsNone(serving["protein"])
        self.assertEqual(serving["sugar"], 0)

    def test_ocr_package_net_weight_is_independent_of_serving_weight(self):
        for raw in (320, "320 g", "320公克", "320克"):
            with self.subTest(raw=raw):
                result = normalize_ocr_result({"package_net_weight_g": raw, "serving_size_g": 40,
                                               "servings_per_container": 8})
                self.assertEqual(result["package_net_weight_g"], 320)
                self.assertEqual(result["serving_size_g"], 40)
        package_only = normalize_ocr_result({"package_net_weight_g": 320, "nutrition_per_serving": SERVING})
        self.assertIsNone(package_only["serving_size_g"])
        self.assertIsNone(package_only["nutrition_per_100g"])

    def test_ocr_package_net_weight_does_not_infer_or_reinterpret_invalid_inputs(self):
        for raw in (None, True, 0, -1, math.nan, math.inf, "320", "320mL", "0.32 kg", "<320 g", "320 g / 40 g"):
            with self.subTest(raw=raw):
                result = normalize_ocr_result({"package_net_weight_g": raw, "serving_size_g": 40,
                                               "servings_per_container": 8})
                self.assertIsNone(result["package_net_weight_g"])

    def test_ocr_boolean_and_invalid_numbers_cannot_become_nutrition(self):
        for value in (True, -1, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_ocr_result({"nutrition_per_serving": {"calories": value}})
                with self.assertRaises(ValueError):
                    normalize_ocr_result({"serving_size_g": value, "nutrition_per_serving": SERVING})

    def test_scaler_rejects_invalid_weight_instead_of_zero_or_type_error(self):
        for value in (True, 0, -1, math.nan, math.inf, "200"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    scale_nutrition_per_100g(SERVING, value)


if __name__ == "__main__":
    unittest.main()
