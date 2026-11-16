import unittest

from services.food_query_normalization_service import (
    FoodQueryNormalizationError,
    build_fdc_search_query_plan,
    validate_fdc_search_query_plan,
)


ITEM = {
    "item_id": "rice-sausage-1",
    "item_revision": 0,
    "name_zh": "糯米腸", "food_state": "prepared",
    "preparation_method": "steamed", "components_scope": "food_only",
    "brand": "吉林", "variant": None,
}


class FoodQueryNormalizationTests(unittest.TestCase):
    def test_original_name_and_only_allowlisted_aliases_are_preserved(self):
        result = build_fdc_search_query_plan(ITEM, scan_revision=7)
        self.assertEqual(result["schema_version"], "FdcSearchQueryPlanV1")
        self.assertEqual(result["item_id"], "rice-sausage-1")
        self.assertEqual(result["scan_revision"], 7)
        self.assertEqual(len(result["identity_digest"]), 64)
        self.assertEqual(result["queries"], [
            "糯米腸", "glutinous rice sausage", "Taiwanese glutinous rice sausage"])
        self.assertEqual(result["query_source"], [
            "original_name", "server_allowlisted_alias", "server_allowlisted_alias"])
        self.assertNotIn("吉林", result["queries"])

    def test_broad_or_model_supplied_alias_is_rejected(self):
        for alias in ("rice sausage", "sticky rice sausage", "吉林糯米腸"):
            with self.subTest(alias=alias):
                with self.assertRaises(FoodQueryNormalizationError) as error:
                    build_fdc_search_query_plan(ITEM, scan_revision=7, english_aliases=(alias,))
                self.assertEqual(error.exception.code, "invalid_request")

    def test_generic_name_cannot_bypass_search_eligibility_by_building_a_plan(self):
        for name in ("炒菜葉", "菜葉", "清炒葉菜", "Stir-fried leafy vegetables"):
            with self.subTest(name=name):
                with self.assertRaises(FoodQueryNormalizationError) as error:
                    build_fdc_search_query_plan({**ITEM, "name_zh": name}, scan_revision=7)
                self.assertEqual(error.exception.code, "confirmation_required")

    def test_specific_vegetables_preserve_original_name_and_identity(self):
        for name in ("大陸妹", "青江菜", "小白菜", "清炒青江菜"):
            with self.subTest(name=name):
                item = {**ITEM, "name_zh": name}
                plan = build_fdc_search_query_plan(item, scan_revision=7)
                self.assertEqual(plan["queries"], [name])
                self.assertEqual(plan["original_name_zh"], name)
                self.assertEqual(validate_fdc_search_query_plan(plan, item=item, scan_revision=7), plan)

    def test_unknown_identity_disables_alias_expansion(self):
        item = {**ITEM, "preparation_method": "unknown"}
        result = build_fdc_search_query_plan(item, scan_revision=7)
        self.assertEqual(result["queries"], ["糯米腸"])
        self.assertFalse(result["identity_expansion_allowed"])

    def test_aliases_are_bounded_and_identity_values_are_validated(self):
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan(ITEM, scan_revision=7, english_aliases=("glutinous rice sausage", "Taiwanese glutinous rice sausage", "glutinous rice sausage"))
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan({**ITEM, "name_zh": ""}, scan_revision=7)
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan({**ITEM, "food_state": "cooked"}, scan_revision=7)

    def test_alias_duplicates_and_missing_server_binding_are_rejected(self):
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan(ITEM, scan_revision=7,
                                        english_aliases=("glutinous rice sausage", "glutinous rice sausage"))
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan({**ITEM, "item_id": ""}, scan_revision=7)
        with self.assertRaises(FoodQueryNormalizationError):
            build_fdc_search_query_plan(ITEM)

    def test_query_plan_is_bound_to_item_revision_and_identity(self):
        plan = build_fdc_search_query_plan(ITEM, scan_revision=7)
        self.assertEqual(validate_fdc_search_query_plan(plan, item=ITEM, scan_revision=7), plan)
        for changed_item, revision in (({**ITEM, "name_zh": "糯米腸(品牌)"}, 7),
                                       ({**ITEM, "item_revision": 1}, 7),
                                       (ITEM, 8), ({**ITEM, "brand": "其他"}, 7)):
            with self.subTest(changed_item=changed_item, revision=revision):
                with self.assertRaises(FoodQueryNormalizationError) as error:
                    validate_fdc_search_query_plan(plan, item=changed_item, scan_revision=revision)
                self.assertEqual(error.exception.code, "plan_mismatch")


if __name__ == "__main__":
    unittest.main()
