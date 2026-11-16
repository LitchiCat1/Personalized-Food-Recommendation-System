from copy import deepcopy
import unittest

from services.food_identity_service import requires_food_identity_confirmation
from services.food_query_normalization_service import (
    FoodQueryNormalizationError,
    build_fdc_search_query_plan,
)
from services.fdc_candidate_search_service import _eligible_for_search
from services.nutrition_enrichment_route_service import _web_enrichment_eligible
from services.web_nutrition_service import _identity_ready


GENERIC_NAMES = (
    "菜葉", "葉菜", "綠色葉菜", "炒菜葉", "清炒葉菜", "蒜蓉炒青菜",
    "川燙蔬菜", "菜葉（清炒）", "清炒 綠色葉菜", "炒菜叶", "黃色瓜類",
    "leafy greens", "Stir-fried leafy vegetables", "GREEN LEAFY VEGETABLES (cooked)",
    "ｌｅａｆｙ　ｇｒｅｅｎｓ", "疑似青江菜", "青江菜（不確定）",
    "炒菜葉（種類不明）", "不明葉菜", "未知蔬菜", "unknown leafy vegetables",
    "unidentified greens", "possibly bok choy", "青江菜（無法辨認）",
    "熟食", "熟食材", "炒熟食材", "熟食物", "尚未紀錄", "需補充資料",
    "葉菜（左上格）", "葉菜（右下）", "綠色葉菜（左上格）",
    "「炒菜葉」", "‘stir-fried leafy vegetables’",
)
SPECIFIC_NAMES = (
    "大陸妹", "青江菜", "小白菜", "福山萵苣", "蘿蔓萵苣", "油菜", "菠菜",
    "生菜", "高麗菜", "空心菜", "清炒青江菜", "蒜炒大陸妹", "菠菜葉",
    "bok choy", "pak choi", "romaine lettuce", "mustard greens", "turnip greens",
    "糯米腸", "吉林糯米腸", "紅蘿蔔炒蛋", "綜合蔬菜湯",
    "青江菜（左上格）", "大陸妹（右下）",
)


class FoodIdentityTests(unittest.TestCase):
    def test_known_generic_and_preparation_wrapped_names_require_confirmation(self):
        for name in GENERIC_NAMES:
            with self.subTest(name=name):
                self.assertTrue(requires_food_identity_confirmation(name))

    def test_specific_names_and_legitimate_aliases_are_not_substring_blocked(self):
        for name in SPECIFIC_NAMES:
            with self.subTest(name=name):
                self.assertFalse(requires_food_identity_confirmation(name))

    def test_invalid_or_hidden_control_names_fail_closed(self):
        for name in (None, True, 3, {}, [], "", "   ", "()", "炒", "a" * 301,
                     "菜\u200b葉", "青江菜\n", "\ud800"):
            with self.subTest(name=repr(name)):
                self.assertTrue(requires_food_identity_confirmation(name))

    def test_all_fallback_gates_block_high_and_low_confidence_generic_items(self):
        for name in GENERIC_NAMES:
            for confidence in (0.4, 0.95):
                item = {"name_zh": name, "confidence": confidence, "validation_issues": [],
                        "food_state": "prepared", "preparation_method": "stir_fried",
                        "components_scope": "food_only", "brand": "Fixture brand", "variant": "Fixture"}
                original = deepcopy(item)
                for gate in (_eligible_for_search, _web_enrichment_eligible, _identity_ready):
                    with self.subTest(name=name, confidence=confidence, gate=gate.__name__):
                        self.assertFalse(gate(item))
                        self.assertEqual(item, original)

    def test_location_qualifier_does_not_authorize_fdc_query(self):
        item = {
            "item_id": "scan:2", "item_revision": 0, "scan_revision": 0,
            "name_zh": "葉菜（左上格）", "food_state": "prepared",
            "preparation_method": "stir_fried", "components_scope": "food_only",
        }
        with self.assertRaises(FoodQueryNormalizationError) as raised:
            build_fdc_search_query_plan(item, scan_revision=0)
        self.assertEqual(raised.exception.code, "confirmation_required")

    def test_specific_names_still_need_existing_confidence_and_validation_checks(self):
        for name in SPECIFIC_NAMES:
            for gate in (_eligible_for_search, _web_enrichment_eligible, _identity_ready):
                with self.subTest(name=name, gate=gate.__name__):
                    item = {"name_zh": name, "confidence": 0.95, "validation_issues": []}
                    self.assertTrue(gate(item))
                    self.assertFalse(gate(dict(item, confidence=0.4)))
                    self.assertFalse(gate(dict(item, validation_issues=["ambiguous_name"])))


if __name__ == "__main__":
    unittest.main()
