import copy
import os
import unittest

from services.disease_rule_service import load_allergen_taxonomy, load_disease_rules
from services.medical_risk_service import evaluate_meal_medical_risk, evaluate_medical_risk
from services.nutrition_profile_service import (
    NUTRIENTS, UNITS, NutritionProfileError, aggregate_nutrition_coverage, build_nutrition_profile,
)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = {"height": 170, "weight": 65, "age": 30, "gender": "male", "activity_multiplier": 1.375}


def profile(**overrides):
    values = {"calories": 100, "protein": 5, "carbs": 10, "fat": 2, "trans_fat": 0, "sodium": 100}
    values.update(overrides)
    return build_nutrition_profile({
        field: (None if values.get(field) is None else values[field] if isinstance(values[field], dict) else
                {"value": values[field], "unit": UNITS[field], "comparison": "exact"})
        for field in NUTRIENTS
    }, basis="per_100g")


def item(identifier="one", nutrition=None, weight=100, **extra):
    return {"item_id": identifier, "profile": nutrition, "weight_g": weight, **extra}


class NutritionRiskV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_disease_rules(BASE_DIR)
        cls.taxonomy = load_allergen_taxonomy(BASE_DIR)

    def evaluate(self, nutrition, *, weight=100, conditions=("hypertension",), allergens=(), **metadata):
        return evaluate_medical_risk(
            {"nutrition_profile": nutrition, "weight_g": weight, **metadata},
            list(conditions), list(allergens), self.rules, self.taxonomy, user_profile=USER,
            nutrition_contract_version=2,
        )

    def meal(self, entries, metadata=None, conditions=("hypertension",), allergens=()):
        return evaluate_meal_medical_risk(
            metadata or [{"nutrients": {"name_zh": "meal"}} for _entry in entries],
            list(conditions), list(allergens), self.rules, self.taxonomy, user_profile=USER,
            nutrition_contract_version=2, nutrition_coverage=aggregate_nutrition_coverage(entries),
        )

    def test_legacy_missing_values_keep_existing_contract(self):
        result = evaluate_medical_risk({}, ["hypertension"], [], self.rules, self.taxonomy)
        self.assertTrue(result["is_safe"])
        self.assertNotIn("assessment_status", result)

    def test_missing_sodium_is_unknown_rather_than_safe(self):
        result = self.evaluate(profile(sodium=None))
        self.assertIsNone(result["is_safe"])
        self.assertEqual(result["assessment_status"], "unknown")
        self.assertEqual(result["missing_critical_nutrition_fields"], ["sodium"])

    def test_irrelevant_missing_fiber_does_not_hide_available_sodium(self):
        result = self.evaluate(profile())
        self.assertTrue(result["is_safe"])
        self.assertIn("fiber", result["missing_nutrition_fields"])
        self.assertEqual(result["missing_critical_nutrition_fields"], [])
        self.assertEqual(result["assessment_scope"], "reference_nutrition_only")

    def test_unknown_weight_never_assumes_one_hundred_grams(self):
        result = self.evaluate(profile(sodium=1000), weight=None)
        self.assertIsNone(result["is_safe"])
        self.assertEqual(result["assessment_status"], "unknown")
        self.assertEqual(result["block_reasons"], [])

    def test_known_excess_remains_with_other_missing_critical_field(self):
        result = self.evaluate(profile(sodium=900, trans_fat=None))
        self.assertFalse(result["is_safe"])
        self.assertEqual(result["assessment_status"], "known_excess")
        self.assertIn("trans_fat", result["missing_critical_nutrition_fields"])
        self.assertTrue(result["block_reasons"])

    def test_less_than_is_not_treated_as_exact_zero(self):
        result = self.evaluate(profile(sodium={"value": "0.1", "unit": "mg", "comparison": "less_than"}))
        self.assertIsNone(result["is_safe"])
        self.assertIn("sodium", result["missing_critical_nutrition_fields"])

    def test_intake_flat_numbers_cannot_override_profile(self):
        result = self.evaluate(profile(sodium=100), weight=200, sodium=5000, calories=5000)
        self.assertTrue(result["is_safe"])
        self.assertEqual(result["block_reasons"], [])

    def test_high_portion_recomputes_original_profile_once(self):
        result = self.evaluate(profile(sodium=400), weight=200)
        sodium = [risk for risk in result["risks"] if risk.get("nutrient") == "sodium"]
        self.assertTrue(sodium)
        self.assertEqual(sodium[0]["value"], 800)

    def test_invalid_weight_fails_with_contract_error(self):
        with self.assertRaises(NutritionProfileError):
            self.evaluate(profile(), weight=True)

    def test_no_allergen_detection_does_not_establish_allergen_safety(self):
        result = self.evaluate(profile(), allergens=("peanut",), name_zh="rice")
        self.assertIsNone(result["is_safe"])
        self.assertIn("allergens", result["unresolved_risk_fields"])

    def test_known_allergen_blocks_even_with_missing_sodium(self):
        result = self.evaluate(profile(sodium=None), allergens=("peanut",), allergens_text="", name_zh="花生飯")
        self.assertFalse(result["is_safe"])
        self.assertEqual(result["assessment_status"], "known_risk")

    def test_default_medium_gi_does_not_establish_measured_gi(self):
        result = self.evaluate(profile(sugar=0), conditions=("diabetes",), gi="medium")
        self.assertIsNone(result["is_safe"])
        self.assertIn("gi", result["unresolved_risk_fields"])

    def test_whole_meal_known_sum_exceeds_even_when_another_item_is_unknown(self):
        result = self.meal([item(nutrition=profile(sodium=900)), item("two", profile(sodium=None))])
        self.assertEqual(result["assessment_status"], "known_excess")
        self.assertIn("sodium", result["missing_critical_nutrition_fields"])
        self.assertTrue(any(risk.get("nutrient") == "sodium" and risk["value"] == 900 for risk in result["risks"]))

    def test_whole_meal_configured_threshold_catches_combined_excess(self):
        rules = copy.deepcopy(self.rules)
        rules["hypertension"]["threshold_resolutions"] = {
            "sodium": {"use": "configured", "decided_by": "test", "decided_on": "2026-11-13"},
        }
        coverage = aggregate_nutrition_coverage([item(nutrition=profile(sodium=400)), item("two", profile(sodium=400))])
        result = evaluate_meal_medical_risk(
            [], ["hypertension"], [], rules, self.taxonomy, user_profile=USER,
            nutrition_contract_version=2, nutrition_coverage=coverage,
        )
        self.assertEqual(result["assessment_status"], "known_excess")
        self.assertTrue(any(risk.get("nutrient") == "sodium" for risk in result["risks"]))

    def test_whole_meal_metadata_retains_allergen_hit(self):
        result = self.meal([item(nutrition=profile())], metadata=[{"nutrients": {"name_zh": "花生飯"}}], allergens=("peanut",))
        self.assertFalse(result["is_safe"])
        self.assertTrue(any(risk["type"] == "allergen" for risk in result["risks"]))

    def test_empty_v2_meal_is_unknown_for_disease_nutrients(self):
        result = self.meal([])
        self.assertIsNone(result["is_safe"])
        self.assertEqual(result["assessment_status"], "unknown")

    def test_no_nutrition_stays_unknown_without_configured_conditions(self):
        result = self.evaluate(None, conditions=())
        self.assertIsNone(result["is_safe"])
        self.assertEqual(result["assessment_status"], "unknown")

    def test_all_excluded_stays_unknown_without_configured_conditions(self):
        result = self.meal([item(nutrition=profile(), included=False, exclusion_reason="not_consumed")], conditions=())
        self.assertIsNone(result["is_safe"])
        self.assertEqual(result["assessment_status"], "unknown")

    def test_malformed_coverage_fails_instead_of_becoming_safe(self):
        coverage = aggregate_nutrition_coverage([item(nutrition=profile())])
        coverage["nutrients"]["sodium"]["known_sum"] = True
        with self.assertRaises(NutritionProfileError):
            evaluate_meal_medical_risk([], ["hypertension"], [], self.rules, self.taxonomy,
                                       nutrition_contract_version=2, nutrition_coverage=coverage)


if __name__ == "__main__":
    unittest.main()
