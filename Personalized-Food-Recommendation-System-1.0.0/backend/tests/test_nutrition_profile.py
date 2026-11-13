import copy
import json
import math
import unittest

from services.nutrition_profile_service import (
    NUTRIENTS, UNITS, NutritionProfileError, aggregate_nutrition_coverage,
    build_nutrition_profile, calculate_portion, profile_from_local_food,
    validate_profile_consistency,
)


def measurements(**overrides):
    source = {field: None for field in NUTRIENTS}
    for field, value in overrides.items():
        source[field] = value if isinstance(value, dict) or value is None else {
            "value": value, "unit": UNITS[field], "comparison": "exact",
        }
    return source


def profile(**values):
    return build_nutrition_profile(measurements(**values), basis="per_100g")


def included(identifier, nutrition=None, weight=100, **extra):
    return {"item_id": identifier, "profile": nutrition, "weight_g": weight,
            "portion_source": "vision_estimate", **extra}


class NutritionProfileTests(unittest.TestCase):
    def assertError(self, code, function, *args, **kwargs):
        with self.assertRaises(NutritionProfileError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_serving_normalization_and_intake_have_only_one_scale(self):
        value = build_nutrition_profile(
            measurements(calories=400, protein=20, carbs=40, fat=10, sodium=600),
            basis="per_serving", basis_weight_g=200,
        )
        self.assertEqual(value["per_100g"]["calories"], 200)
        intake = calculate_portion(value, 150, portion_source="user_weighed")
        self.assertEqual(intake["values"]["calories"], 300)
        self.assertEqual(intake["values"]["sodium"], 450)
        self.assertEqual(intake["portion_source"], "user_weighed")

    def test_intake_uses_original_unrounded_values(self):
        value = build_nutrition_profile(measurements(calories=1), basis="per_serving", basis_weight_g=3)
        self.assertEqual(calculate_portion(value, 3)["values"]["calories"], 1)
        serialized = json.loads(json.dumps(value, allow_nan=False))
        self.assertEqual(calculate_portion(serialized, 3)["values"]["calories"], 1)

    def test_precise_original_basis_survives_json_and_recalculation(self):
        value = build_nutrition_profile(measurements(calories="1.0000000000000000000001"),
                                        basis="per_serving", basis_weight_g="3.000000000000000000001")
        self.assertEqual(value["source_basis"]["weight_g"], "3.000000000000000000001")
        self.assertAlmostEqual(calculate_portion(json.loads(json.dumps(value)), 3)["values"]["calories"], 1)

    def test_exact_zero_unknown_and_label_rounding_are_distinct(self):
        value = profile(sodium={"value": 0, "unit": "mg", "comparison": "exact", "label_rounding": True})
        self.assertEqual(value["per_100g"]["sodium"], 0)
        self.assertIsNone(value["per_100g"]["fiber"])
        self.assertTrue(value["source_nutrients"]["sodium"]["label_rounding"])
        self.assertNotIn("sodium", value["missing_nutrition_fields"])
        self.assertIn("fiber", value["missing_nutrition_fields"])

    def test_negative_numeric_zero_is_canonicalized_and_round_trips(self):
        value = profile(calories=-0.0)
        self.assertEqual(value["source_nutrients"]["calories"]["value"], "0")
        self.assertEqual(calculate_portion(value, 100)["values"]["calories"], 0)

    def test_maximum_metadata_round_trips_with_same_profile_size_budget(self):
        value = build_nutrition_profile(measurements(calories=1), basis="per_100g",
                                        source_details={"text": "x" * 65000})
        self.assertEqual(calculate_portion(value, 100)["values"]["calories"], 1)

    def test_less_than_preserves_exclusive_bound_and_null_point(self):
        value = profile(sugar={"value": "0.1", "unit": "g", "comparison": "less_than"})
        self.assertIsNone(value["per_100g"]["sugar"])
        self.assertEqual(value["upper_bounds_per_100g"]["sugar"], 0.1)
        portion = calculate_portion(value, 150)
        self.assertEqual(portion["upper_bounds"]["sugar"], 0.15)
        self.assertIsNone(portion["values"]["sugar"])
        self.assertEqual(portion["bound_comparison"], "less_than")

    def test_core_bound_never_qualifies_as_required_point(self):
        value = profile(calories={"value": 100, "unit": "kcal", "comparison": "less_than"},
                        protein=1, carbs=1, fat=1)
        self.assertFalse(value["has_required_point_values"])
        self.assertTrue(profile(calories=100, protein=1, carbs=1, fat=1)["has_required_point_values"])

    def test_missing_weight_and_missing_profile_never_invent_intake(self):
        value = profile(calories=200, sodium=10)
        for nutrition, weight in ((value, None), (None, 100), (None, None)):
            with self.subTest(nutrition=nutrition, weight=weight):
                result = calculate_portion(nutrition, weight)
                self.assertTrue(all(number is None for number in result["values"].values()))
                self.assertTrue(all(number is None for number in result["upper_bounds"].values()))

    def test_standard_unit_conversions(self):
        value = profile(calories={"value": "418.4", "unit": "kJ", "comparison": "exact"},
                        sodium={"value": "0.5", "unit": "g", "comparison": "exact"},
                        protein={"value": 500, "unit": "mg", "comparison": "exact"},
                        fiber={"value": 100000, "unit": "ug", "comparison": "exact"})
        self.assertEqual(value["per_100g"]["calories"], 100)
        self.assertEqual(value["per_100g"]["sodium"], 500)
        self.assertEqual(value["per_100g"]["protein"], 0.5)
        self.assertEqual(value["per_100g"]["fiber"], 0.1)

    def test_unknown_units_and_semantic_substitutes_fail(self):
        for field, unit in (("calories", "cal"), ("calories", "g"), ("sodium", "%DV"),
                            ("protein", "IU"), ("sugar", "added_sugar"), ("carbs", "net_carbs"),
                            ("sodium", "salt"), ("sodium", None)):
            with self.subTest(field=field, unit=unit):
                self.assertError("invalid_unit", profile, **{field: {"value": 1, "unit": unit, "comparison": "exact"}})
        self.assertError("invalid_measurement", build_nutrition_profile,
                         {**measurements(), "added_sugar": None}, basis="per_100g")

    def test_volume_does_not_imply_equal_mass(self):
        self.assertError("invalid_basis", build_nutrition_profile, measurements(calories=100),
                         basis="per_100ml", basis_volume_ml=100)
        value = build_nutrition_profile(measurements(calories=100), basis="per_100ml",
                                        basis_volume_ml=100, basis_weight_g=125)
        self.assertEqual(value["per_100g"]["calories"], 80)

    def test_invalid_or_ambiguous_bases_fail(self):
        cases = [("per_serving", None, None), ("per_100g", 50, None), ("per_bowl", 200, None),
                 ("per_100ml", 100, 50), ("per_100g", 100, 100), ("per_serving", True, None),
                 ("per_serving", -1, None), ("per_serving", 0, None)]
        for basis, weight, volume in cases:
            with self.subTest(basis=basis, weight=weight, volume=volume):
                self.assertError("invalid_basis", build_nutrition_profile, measurements(calories=1),
                                 basis=basis, basis_weight_g=weight, basis_volume_ml=volume)

    def test_invalid_numeric_inputs_fail_without_coercion(self):
        for number in (True, False, -1, math.inf, math.nan, 10 ** 10000, "nan", "1,000", "<0.1", "1g", "1e99999999", "1e-99999999"):
            with self.subTest(kind=type(number).__name__):
                with self.assertRaises(NutritionProfileError):
                    profile(protein=number)
        for weight in (True, 0, -1, "100", math.nan, math.inf, 10 ** 10000):
            with self.subTest(kind=type(weight).__name__):
                with self.assertRaises(NutritionProfileError):
                    calculate_portion(profile(calories=1), weight)

    def test_nonpositive_bound_is_impossible(self):
        for number in (0, -1):
            with self.assertRaises(NutritionProfileError):
                profile(sodium={"value": number, "unit": "mg", "comparison": "less_than"})

    def test_conversion_overflow_or_underflow_fails(self):
        with self.assertRaises(NutritionProfileError):
            build_nutrition_profile(measurements(sodium=1), basis="per_serving", basis_weight_g=5e-324)
        with self.assertRaises(NutritionProfileError):
            calculate_portion(profile(sodium={"value": "5e-324", "unit": "mg", "comparison": "exact"}), 0.01)
        with self.assertRaises(NutritionProfileError):
            calculate_portion(profile(sodium=100000), 1e308)

    def test_mass_and_subset_conflicts_do_not_hide_behind_missing_fields(self):
        for values in ({"protein": 120}, {"protein": 100, "carbs": 20},
                       {"protein": 50, "carbs": 50, "fat": 10}, {"fat": 5, "saturated_fat": 10},
                       {"carbs": 1, "sugar": 5}, {"calories": 1200}):
            with self.subTest(values=values):
                self.assertError("source_conflict", profile, **values)
        self.assertError("source_conflict", profile, carbs={"value": 1, "unit": "g", "comparison": "less_than"}, sugar=10)

    def test_rounded_source_differences_are_tolerated_but_not_filled(self):
        value = profile(calories=200, protein=2.2, carbs=3.9, fat=2.3)
        self.assertIn("energy_macro_discrepancy", value["validation_warnings"])
        missing = profile(protein=1, carbs=1, fat=1)
        self.assertIsNone(missing["per_100g"]["calories"])
        self.assertTrue(validate_profile_consistency(profile(calories=300, protein=1.7), [
            build_nutrition_profile(measurements(calories=399, protein=2.2), basis="per_serving", basis_weight_g=133)]))

    def test_dual_energy_and_basis_conflicts_fail(self):
        self.assertError("source_conflict", validate_profile_consistency, profile(calories=301.2), [
            profile(calories={"value": 1506.2, "unit": "kJ", "comparison": "exact"})])
        self.assertError("source_conflict", validate_profile_consistency, profile(sodium=1000), [
            profile(sodium={"value": 1, "unit": "mg", "comparison": "less_than"})])
        self.assertError("source_conflict", validate_profile_consistency, profile(sodium=None), [
            profile(sodium=100), profile(sodium=300)])

    def test_sparse_corroboration_detects_cross_nutrient_conflict_without_merging(self):
        self.assertError("source_conflict", validate_profile_consistency, profile(carbs=1), [profile(sugar=10)])
        selected = profile(carbs=20)
        self.assertTrue(validate_profile_consistency(selected, [profile(sugar=10)]))
        self.assertIsNone(selected["per_100g"]["sugar"])

    def test_canonical_tampering_and_bool_equal_to_one_are_rejected(self):
        original = profile(calories=1)
        for section, field, value in (("per_100g", "calories", 99), ("per_100g", "calories", True),
                                      ("units", "sodium", "g")):
            changed = copy.deepcopy(original)
            changed[section][field] = value
            self.assertError("invalid_profile", calculate_portion, changed, 100)
        changed = copy.deepcopy(original)
        changed["has_required_point_values"] = 0
        self.assertError("invalid_profile", calculate_portion, changed, 100)

    def test_local_adapter_preserves_null_and_rejects_numeric_strings(self):
        source = {"unit": "per 100g", "calories": 200, "sodium": 0}
        value = profile_from_local_food(source)
        self.assertIsNone(value["per_100g"]["sugar"])
        self.assertEqual(value["per_100g"]["sodium"], 0)
        for changed in ({**source, "calories": "200"}, {**source, "nutrition_basis_status": "conflicting"},
                        {**source, "unit": "per 100ml"}, {**source, "unit": []}, {**source, "unit": {}}):
            with self.assertRaises(NutritionProfileError):
                profile_from_local_food(changed)

    def test_invalid_measurement_shapes_and_metadata_fail(self):
        for value in ([], True, 5, {"value": 1, "unit": "g"},
                      {"value": 1, "unit": "g", "comparison": "exact", "label_rounding": 1}):
            with self.assertRaises(NutritionProfileError):
                build_nutrition_profile({**measurements(), "protein": value}, basis="per_100g")
        for metadata in ([], {"bad": math.nan}):
            self.assertError("invalid_metadata", build_nutrition_profile, measurements(),
                             basis="per_100g", source_details=metadata)


class NutritionCoverageTests(unittest.TestCase):
    def row(self, items, field="sodium"):
        return aggregate_nutrition_coverage(items)["nutrients"][field]

    def test_unresolved_item_stays_in_denominator_and_known_sum(self):
        result = self.row([included("a", profile(sodium=100)), included("b")])
        self.assertEqual(result["known_sum"], 100)
        self.assertEqual(result["known_items"], 1)
        self.assertEqual(result["eligible_items"], 2)
        self.assertEqual(result["unresolved_items"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["total_upper_bound"])

    def test_zero_is_complete_only_for_that_nutrient(self):
        result = aggregate_nutrition_coverage([included("a", profile(sodium=0))])["nutrients"]
        self.assertEqual(result["sodium"]["status"], "complete")
        self.assertEqual(result["sodium"]["known_items"], 1)
        self.assertEqual(result["fiber"]["status"], "unknown")

    def test_bounds_total_disappears_when_any_item_is_unbounded_unknown(self):
        items = [included("a", profile(sodium=100)),
                 included("b", profile(sodium={"value": 10, "unit": "mg", "comparison": "less_than"}))]
        result = self.row(items)
        self.assertEqual(result["known_sum"], 100)
        self.assertEqual(result["total_upper_bound"], 110)
        self.assertEqual(result["upper_bound_comparison"], "less_than")
        self.assertEqual(result["bounded_items"], 1)
        self.assertEqual(result["unresolved_items"], 1)
        unknown = self.row([*items, included("c")])
        self.assertEqual(unknown["known_bounds_sum"], 10)
        self.assertIsNone(unknown["total_upper_bound"])
        self.assertIsNone(unknown["upper_bound_comparison"])

    def test_unknown_weight_keeps_profile_out_of_known_intake(self):
        result = self.row([included("a", profile(sodium=100), weight=None)])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["known_items"], 0)
        self.assertEqual(result["eligible_items"], 1)

    def test_same_name_items_are_separate_and_count_never_multiplies_total_weight(self):
        result = self.row([included("a", profile(sodium=100), name="rice", count=3),
                           included("b", profile(sodium=100), name="rice", count=2)])
        self.assertEqual(result["known_sum"], 200)
        self.assertEqual(result["eligible_items"], 2)
        self.assertEqual(result["status"], "complete")

    def test_only_explicit_not_consumed_can_leave_denominator(self):
        result = aggregate_nutrition_coverage([
            included("a", profile(sodium=100)),
            included("b", included=False, exclusion_reason="not_consumed"),
        ])
        self.assertEqual(result["nutrients"]["sodium"]["eligible_items"], 1)
        self.assertEqual(result["excluded_item_ids"], ["b"])
        with self.assertRaises(NutritionProfileError):
            self.row([included("a", included=False)])

    def test_empty_meal_is_unknown(self):
        row = self.row([])
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["eligible_items"], 0)

    def test_duplicate_or_invalid_ids_and_inclusion_flags_fail(self):
        cases = [[included("a"), included("a")], [included("")], [included("a", included=0)],
                 [included("a", portion_source="high_confidence")]]
        for items in cases:
            with self.assertRaises(NutritionProfileError):
                aggregate_nutrition_coverage(items)

    def test_coverage_recalculates_from_original_cells_and_bounds(self):
        value = build_nutrition_profile(measurements(sodium="0.1"), basis="per_serving", basis_weight_g=3)
        items = [included(str(index), value, weight=1) for index in range(3)]
        self.assertEqual(self.row(items)["known_sum"], 0.1)

    def test_finite_individual_values_can_overflow_aggregate(self):
        value = profile(sodium=100)
        items = [included(str(index), value, weight=1e308) for index in range(2)]
        with self.assertRaises(NutritionProfileError) as caught:
            aggregate_nutrition_coverage(items)
        self.assertEqual(caught.exception.code, "numeric_range")


if __name__ == "__main__":
    unittest.main()
