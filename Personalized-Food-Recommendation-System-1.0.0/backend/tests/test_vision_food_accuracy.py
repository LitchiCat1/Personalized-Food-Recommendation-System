"""Regression cases found using food_picture; all tests are offline."""

import json
import io
import math
import os
from pathlib import Path
import unittest
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

from services.disease_rule_service import load_allergen_taxonomy, load_disease_rules
from services.nutrition_database_service import load_usda_foods
from services.nutrition_label_service import build_custom_food_search_result
from services.vision_food_service import build_vision_food_response, normalize_vision_result, normalize_weight, call_gemini_food_recognition
from services.vision_nutrition_service import find_vision_food_matches
from scripts.convert_usda_fndds import convert_foods
from scripts import convert_tfda


BASE = Path(__file__).resolve().parents[1]


class Storage:
    def get_user(self, _user_id):
        return None

    def get_custom_foods(self, _user_id):
        return []


class VisionFoodAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = json.loads((BASE / "nutrition_db_tw.json").read_text(encoding="utf-8"))
        cls.database.update(load_usda_foods(BASE))
        cls.rules = load_disease_rules(str(BASE))
        cls.taxonomy = load_allergen_taxonomy(str(BASE))

    def match(self, name, **fields):
        return find_vision_food_matches(Storage(), self.database, {"name_zh": name, **fields}, None, build_custom_food_search_result)

    def response(self, items):
        return build_vision_food_response({"items": items}, Storage(), self.database, self.rules, self.taxonomy, [], [], None, build_custom_food_search_result)

    def test_chicken_leg_cannot_become_mushroom(self):
        matches = self.match("滷雞腿", alternatives=["雞腿", "雞腿菇"])
        self.assertTrue(matches)
        self.assertEqual(matches[0]["source"], "USDA FNDDS")
        self.assertNotIn("菇", matches[0]["name_zh"])

    def test_cabbage_uses_tfda_official_alias_not_dumplings(self):
        matches = self.match("炒高麗菜")
        self.assertEqual(matches[0]["source"], "TFDA")
        self.assertEqual(matches[0]["category"], "蔬菜類")
        self.assertTrue(matches[0]["match_notes"])
        self.assertNotIn("水餃", matches[0]["name_zh"])

    def test_tfda_precedes_usda_even_if_usda_name_is_exact(self):
        subset = {key: self.database[key] for key in ("甘藍平均值", "usda_fndds:2709891")}
        matches = find_vision_food_matches(Storage(), subset, {"name_zh": "炒高麗菜"}, None, build_custom_food_search_result)
        self.assertTrue(any(food["source"] == "USDA FNDDS" for food in matches))
        self.assertEqual(matches[0]["source"], "TFDA")

    def test_rice_sausage_cannot_become_pig_intestine(self):
        self.assertEqual(self.match("糯米腸", alternatives=["豬大腸", "大腸"]), [])

    def test_dumplings_use_cooked_whole_food_not_skins(self):
        matches = self.match("水餃")
        self.assertEqual(matches[0]["name_zh"], "熟水餃(高麗菜水餃)")
        self.assertEqual(matches[0]["calories"], 199)
        self.assertTrue(matches[0]["match_notes"])

    def test_braised_pork_uses_cooked_reference_instead_of_rice(self):
        matches = self.match("滷肉", alternatives=["白飯", "豬肉"])
        self.assertEqual(matches[0]["key"], "usda_fndds:2705901")
        self.assertTrue(matches[0]["match_notes"])

    def test_complete_dish_cannot_be_replaced_by_single_ingredient(self):
        self.assertEqual(self.match("滷肉飯", alternatives=["白飯"]), [])

    def test_profile_missing_core_nutrient_cannot_be_auto_used(self):
        database = {"測試食物": {"name_zh": "測試食物", "calories": 100, "protein": None,
                               "carbs": 10, "fat": 5, "sodium": 20, "source": "TFDA"}}
        matches = find_vision_food_matches(Storage(), database, {"name_zh": "測試食物"}, None, build_custom_food_search_result)
        self.assertEqual(matches, [])

    def test_prepared_cup_noodles_cannot_use_dry_noodle_weight(self):
        matches = self.match("泡麵", food_state="prepared")
        self.assertEqual(matches[0]["key"], "usda_fndds:2709152")
        self.assertEqual(matches[0]["calories"], 66)
        response = self.response([{"name_zh": "泡麵", "confidence": 0.95, "estimated_weight_g": 350}])
        self.assertEqual(response["summary"]["total_calories"], 231)

    def test_cooked_oil_noodles_prefer_tfda_wet_profile(self):
        matches = self.match("油麵")
        self.assertEqual(matches[0]["name_zh"], "衛生油麵")
        self.assertEqual(matches[0]["calories"], 163)

    def test_cooked_white_noodles_use_usda_when_tfda_only_has_unprepared(self):
        for name in ("陽春麵條(熟)", "熟白麵條", "白麵條"):
            matches = self.match(name)
            self.assertEqual(matches[0]["key"], "usda_fndds:2708352")
            self.assertEqual(matches[0]["calories"], 137)

    def test_fresh_cucumber_does_not_become_pickled_cucumber(self):
        for name in ("小黃瓜", "小黃瓜片"):
            matches = self.match(name)
            self.assertTrue(matches)
            self.assertFalse(any("醃" in food["name_zh"] for food in matches))

    def test_common_edamame_and_tofu_names_find_tfda_foods(self):
        for name in ("豆干", "毛豆"):
            matches = self.match(name)
            self.assertTrue(matches)
            self.assertEqual(matches[0]["source"], "TFDA")
            self.assertTrue(matches[0]["match_notes"])

    def test_soup_does_not_use_concentrated_stock(self):
        matches = self.match("高湯")
        self.assertEqual(matches[0]["source"], "TFDA")
        self.assertLess(matches[0]["sodium"], 100)
        self.assertNotIn("濃縮", matches[0]["description"])

    def test_unmatched_food_is_visible_and_totals_are_partial(self):
        response = self.response([
            {"name_zh": "白飯", "confidence": 0.95, "estimated_weight_g": 100},
            {"name_zh": "地瓜球", "confidence": 0.95, "estimated_weight_g": 100},
        ])
        self.assertEqual(response["summary"]["recognized_items"], 2)
        self.assertFalse(response["summary"]["nutrition_complete"])
        self.assertTrue(response["summary"]["requires_user_confirmation"])
        self.assertEqual(response["rejected_detections"][0]["nutrition_status"], "unmatched")
        self.assertTrue(any("不完整" in warning for warning in response["detections"][0]["warnings"]))

    def test_visible_name_remains_recognized_name(self):
        response = self.response([{"name_zh": "滷肉", "confidence": 0.96, "estimated_weight_g": 80}])
        detection = response["detections"][0]
        self.assertEqual(detection["name_zh"], "滷肉")
        self.assertNotEqual(detection["matched_food"]["name_zh"], "滷肉")
        self.assertTrue(detection["needs_confirmation"])
        self.assertIn("fdc.nal.usda.gov", detection["nutrition_source_url"])

    def test_missing_or_nonfinite_weight_requires_confirmation(self):
        for value in (None, math.nan, math.inf):
            self.assertIsNone(normalize_weight(value))
            response = self.response([{"name_zh": "白飯", "confidence": 0.99, "estimated_weight_g": value}])
            self.assertTrue(response["detections"][0]["needs_confirmation"])
            self.assertTrue(any("100 g" in note for note in response["detections"][0]["warnings"]))

    def test_missing_optional_nutrients_are_not_claimed_as_measured_zero(self):
        response = self.response([{"name_zh": "滷肉", "confidence": 0.96, "estimated_weight_g": 80}])
        detection = response["detections"][0]
        self.assertIn("trans_fat", detection["missing_nutrition_fields"])
        self.assertTrue(any("缺值不代表實測為 0" in note for note in detection["warnings"]))
        self.assertFalse(response["summary"]["optional_nutrients_complete"])
        self.assertEqual(response["nutrition_database_priority"], ["TFDA", "USDA FNDDS"])

    def test_array_json_and_string_alternative_are_normalized(self):
        parsed = normalize_vision_result([{"name_zh": "白飯", "alternatives": "白米飯"}, None, "bad"])
        self.assertEqual(len(parsed["items"]), 1)
        self.assertEqual(parsed["items"][0]["alternatives"], ["白米飯"])
        with self.assertRaises(ValueError):
            normalize_vision_result({"items": {"name_zh": "白飯"}})

    def test_truncated_relay_output_is_not_silently_accepted(self):
        with patch("services.vision_food_service.get_relay_config", return_value=True), patch(
            "services.vision_food_service.relay_chat", return_value=('{"items":[]}', "length")
        ):
            with self.assertRaises(ValueError):
                call_gemini_food_recognition("local-image", "image/jpeg", "local-test-key")

    def test_custom_per_serving_profile_is_converted_to_per_100g(self):
        class CustomStorage(Storage):
            def get_custom_foods(self, _user_id):
                return [{"food_id": "custom-1", "name_zh": "測試餐", "serving_size_g": 200,
                         "nutrition_per_serving": {"calories": 400, "protein": 10, "fat": 10, "carbs": 60, "sodium": 600}}]
        matches = find_vision_food_matches(CustomStorage(), {}, {"name_zh": "測試餐"}, "user-1", build_custom_food_search_result)
        self.assertEqual(matches[0]["calories"], 200)
        self.assertEqual(matches[0]["sodium"], 300)

    def test_official_source_metadata_is_available(self):
        self.assertGreaterEqual(len(self.database), 7600)
        self.assertIn("高麗菜", self.database["甘藍平均值"]["aliases"])
        self.assertIn("乾麵條", self.database["油麵條"]["description"])
        for filename in ("nutrition_db_tw.source.json", "nutrition_db_usda.source.json"):
            source = json.loads((BASE / filename).read_text(encoding="utf-8"))
            self.assertEqual(len(source["input_sha256"]), 64)


class USDAImporterTests(unittest.TestCase):
    def test_missing_nutrition_is_excluded_and_units_are_verified(self):
        self.assertEqual(convert_foods([{"fdcId": 1, "foodNutrients": []}]), {})
        with self.assertRaises(ValueError):
            convert_foods([{"fdcId": 1, "foodNutrients": [{"nutrient": {"id": 1093, "unitName": "g"}, "amount": 1}]}])


class TFDAImporterTests(unittest.TestCase):
    def test_missing_official_values_remain_null_instead_of_invented_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, output = Path(directory) / "raw.json", Path(directory) / "foods.json"
            raw.write_text(json.dumps([{"整合編號": "test-1", "樣品名稱": "測試品", "分析項": "熱量", "每100克含量": "100"}]), encoding="utf-8")
            with patch("sys.argv", ["convert_tfda", "--raw", str(raw), "--output", str(output)]), redirect_stdout(io.StringIO()):
                convert_tfda.main()
            food = json.loads(output.read_text(encoding="utf-8"))["測試品"]
            self.assertEqual(food["calories"], 100)
            for field in ("protein", "fat", "carbs", "sodium", "fiber", "trans_fat"):
                self.assertIsNone(food[field])


if __name__ == "__main__":
    unittest.main()
