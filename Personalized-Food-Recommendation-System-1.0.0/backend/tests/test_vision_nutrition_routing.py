"""Offline acceptance cases for the local layers, independent of network AI."""

import json
import math
from pathlib import Path
import unittest

from services.nutrition_database_service import load_usda_foods
from services.nutrition_label_service import build_custom_food_search_result
from services.vision_nutrition_service import find_vision_food_matches, food_identity


BASE = Path(__file__).resolve().parents[1]


class Storage:
    def __init__(self, foods=()):
        self.foods = list(foods)

    def get_custom_foods(self, _user_id):
        return self.foods


def profile(name="測試食物", **fields):
    return dict(dict(name_zh=name, source="TFDA", unit="per 100g", calories=100,
                     protein=5, fat=2, carbs=15, sodium=20), **fields)


class VisionNutritionRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tfda = json.loads((BASE / "nutrition_db_tw.json").read_text(encoding="utf-8"))
        cls.usda = load_usda_foods(BASE)
        cls.database = dict(cls.tfda, **cls.usda)

    def match(self, name, database=None, storage=None, user_id=None, **fields):
        return find_vision_food_matches(storage or Storage(), self.database if database is None else database,
                                        dict(name_zh=name, **fields), user_id, build_custom_food_search_result)

    def test_known_filling_and_brand_are_preserved(self):
        self.assertEqual(food_identity("水餃（韭菜）"), "水餃(韭菜)")
        self.assertEqual(self.match("水餃(韭菜)", food_state="prepared"), [])
        self.assertEqual(self.match("吉林糯米腸", database={"plain": profile("糯米腸")}), [])
        correct = profile("水餃(韭菜)", food_state="prepared")
        self.assertEqual(self.match("水餃(韭菜)", database={"correct": correct})[0]["key"], "correct")

    def test_conflicting_states_and_soup_scope_do_not_match(self):
        for name, fields in (
            ("白飯", {"food_state": "raw"}),
            ("泡麵", {"food_state": "dry", "components_scope": "whole_dish_with_broth"}),
            ("泡麵", {"food_state": "prepared", "components_scope": "noodles_only"}),
            ("泡麵", {"food_state": "prepared"}),
        ):
            with self.subTest(name=name, fields=fields):
                self.assertEqual(self.match(name, **fields), [])
        self.assertEqual(self.match("泡麵(含湯)", food_state="prepared")[0]["key"], "usda_fndds:2709152")
        self.assertEqual(self.match("泡麵", food_state="dry", database=self.usda), [])

    def test_compatible_tfda_wins_and_custom_priority_is_preserved(self):
        database = {"usda": profile(source="USDA FNDDS"), "tfda": profile()}
        self.assertEqual(self.match("測試食物", database=database)[0]["key"], "tfda")
        custom = {"food_id": "custom", "name_zh": "測試食物", "nutrition_per_100g": {
            "calories": 123, "protein": 5, "fat": 2, "carbs": 15, "sodium": 20}}
        self.assertEqual(self.match("測試食物", database=database, storage=Storage([custom]), user_id="one")[0]["key"], "custom")
        self.assertNotIn("custom", [row["key"] for row in self.match("測試食物", database=database, storage=Storage([custom]))])

    def test_many_raw_candidates_cannot_hide_cooked_usda(self):
        database = {f"raw-{index}": dict(self.tfda["甘藍平均值"]) for index in range(10)}
        database["usda_fndds:2709891"] = self.usda["usda_fndds:2709891"]
        matches = self.match("炒高麗菜", database=database, food_state="prepared")
        self.assertEqual([row["key"] for row in matches], ["usda_fndds:2709891"])
        self.assertEqual(self.match("炒高麗菜", database={"raw": self.tfda["甘藍平均值"]}, food_state="prepared"), [])
        self.assertTrue(self.match("高麗菜", database=self.tfda, food_state="raw"))

    def test_reviewed_bilingual_mapping_only(self):
        self.assertEqual(self.match("全脂牛奶", database=self.usda, name_en="Milk, whole")[0]["key"], "usda_fndds:2705385")
        self.assertEqual(self.match("不明液體", database=self.usda, name_en="Milk, whole"), [])
        self.assertEqual(self.match("全脂牛奶", database={"usda_fndds:2705385": profile(name_en="Other milk")}), [])

    def test_invalid_core_and_optional_numbers_and_units_are_rejected(self):
        for field in ("calories", "protein", "fat", "carbs", "sodium", "sugar"):
            for value in (True, False, -1, math.nan, math.inf, "100", 10 ** 400):
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.match("測試食物", database={"bad": profile(**{field: value})}), [])
        for unit, size in (("per serving", True), ("per serving", -100), ("per serving", 0),
                           ("per serving", "200"), ("per serving", math.inf), ("per 100ml", 100)):
            with self.subTest(unit=unit, size=size):
                self.assertEqual(self.match("測試食物", database={"bad": profile(unit=unit, serving_size_g=size)}), [])

    def test_serving_conversion_once_preserves_nullable_optional_fields(self):
        matches = self.match("測試食物", database={"serving": profile(unit="per serving", serving_size_g=200,
                                                                    calories=400, sugar=None)})
        self.assertEqual(matches[0]["calories"], 200)
        self.assertIsNone(matches[0]["sugar"])
        self.assertEqual(matches[0]["unit"], "per 100g")

    def test_explicit_method_and_components_conflicts_are_rejected(self):
        food = profile(preparation_method="boiled", components_scope="noodles_only")
        self.assertEqual(self.match("測試食物", database={"one": food}, preparation_method="fried"), [])
        self.assertEqual(self.match("測試食物", database={"one": food}, components_scope="whole_dish_with_broth"), [])

    def test_boiled_cabbage_cannot_use_stir_fried_reference(self):
        self.assertEqual(self.match("清燙高麗菜", food_state="prepared", preparation_method="boiled"), [])
        self.assertEqual(self.match("炒水餃", food_state="prepared", preparation_method="stir_fried"), [])
        self.assertEqual(self.match("清燙高麗菜", food_state="prepared", preparation_method="stir_fried"), [])

    def test_uncertain_raw_state_is_consistent_but_clear_cooked_name_is_usable(self):
        self.assertEqual(self.match("高麗菜"), [])
        self.assertEqual(self.match("高麗菜", food_state="unknown"), [])
        self.assertEqual(self.match("白飯", food_state="unknown")[0]["key"], "白飯")
        self.assertTrue(self.match("荷包蛋", food_state="prepared", preparation_method="pan_fried"))

    def test_reviewed_tfda_cooked_rice_method_matches_only_steamed(self):
        for method in (None, "unknown", "steamed"):
            with self.subTest(method=method):
                matches = self.match("白飯", food_state="prepared", preparation_method=method)
                self.assertEqual([match["key"] for match in matches], ["白飯"])

        for method in ("boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised"):
            with self.subTest(method=method):
                self.assertEqual(self.match("白飯", food_state="prepared", preparation_method=method), [])

        # Similar-looking synthetic or renamed profiles cannot inherit the
        # reviewed TFDA mapping without the exact source record key and metadata.
        record = dict(self.tfda["白飯"])
        self.assertEqual(self.match("白飯", database={"renamed": record}, food_state="prepared",
                                    preparation_method="steamed"), [])
        altered = dict(record, code="OTHER")
        self.assertEqual(self.match("白飯", database={"白飯": altered}, food_state="prepared",
                                    preparation_method="steamed"), [])

    def test_lookup_reasons_distinguish_missing_mapping_from_invalid_profiles(self):
        for name, database, expected in (
            ("地瓜球", {}, "no_local_mapping"),
            ("炒高麗菜", {"raw": self.tfda["甘藍平均值"]}, "incompatible"),
            ("測試食物", {"bad": profile(calories=None)}, "incomplete_profile"),
            ("測試食物", {"good": profile()}, "matched"),
        ):
            diagnostics = {}
            find_vision_food_matches(Storage(), database, {"name_zh": name}, None,
                                     build_custom_food_search_result, diagnostics=diagnostics)
            self.assertEqual(diagnostics["status"], expected)
            self.assertEqual(diagnostics["candidate_count"], len(database))


if __name__ == "__main__":
    unittest.main()
