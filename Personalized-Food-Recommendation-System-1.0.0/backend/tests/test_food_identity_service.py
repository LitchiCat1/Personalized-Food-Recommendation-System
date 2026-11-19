from copy import deepcopy
import unittest

from services.food_identity_service import (requires_food_identity_confirmation,
                                            vision_identity_needs_confirmation, web_identity_ready)
from services.food_query_normalization_service import (
    FoodQueryNormalizationError,
    build_fdc_search_query_plan,
)
from services.fdc_candidate_search_service import _eligible_for_search
from services.nutrition_enrichment_route_service import _web_enrichment_eligible
from services.web_nutrition_service import _identity_ready
from services.vision_food_service import build_vision_food_response


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
                    item = {"name_zh": name, "confidence": 0.95, "validation_issues": [],
                            "identity_confirmation_required": False, "food_state": "prepared",
                            "preparation_method": "stir_fried", "components_scope": "food_only"}
                    self.assertTrue(gate(item))
                    self.assertFalse(gate(dict(item, confidence=0.4)))
                    self.assertFalse(gate(dict(item, validation_issues=["ambiguous_name"])))

    def test_web_identity_requires_server_status_but_not_portion_confidence(self):
        item = {"name_zh": "青江菜", "confidence": 0.95, "validation_issues": [],
                "identity_confirmation_required": False, "food_state": "prepared",
                "preparation_method": "stir_fried", "components_scope": "food_only",
                "weight_confidence": 0.1}
        self.assertFalse(vision_identity_needs_confirmation(item))
        self.assertTrue(web_identity_ready(item))
        self.assertFalse(web_identity_ready({key: value for key, value in item.items()
                                             if key != "identity_confirmation_required"}))
        self.assertFalse(web_identity_ready(dict(item, confidence=0.74)))
        self.assertFalse(web_identity_ready(dict(item, food_state="unknown")))

    def test_generic_name_cannot_be_cleared_by_a_client_status(self):
        item = {"name_zh": "炒菜葉", "confidence": 0.99, "validation_issues": [],
                "identity_confirmation_required": False, "food_state": "prepared",
                "preparation_method": "stir_fried", "components_scope": "food_only"}
        self.assertTrue(vision_identity_needs_confirmation(item))
        self.assertFalse(web_identity_ready(item))

    def test_server_owned_user_confirmation_can_replace_vision_confidence_only(self):
        item = {
            "name_zh": "青江菜", "confidence": 0.42, "validation_issues": [],
            "identity_confirmation_required": False, "identity_confirmation_source": "user",
            "identity_confirmation_id": "server-confirmation-1", "food_state": "prepared",
            "preparation_method": "stir_fried", "components_scope": "food_only",
        }
        self.assertTrue(vision_identity_needs_confirmation(item))
        self.assertTrue(web_identity_ready(item))
        self.assertTrue(_eligible_for_search(item))
        self.assertTrue(_web_enrichment_eligible(item))

        self.assertFalse(web_identity_ready(dict(item, name_zh="菜葉")))
        self.assertFalse(web_identity_ready(dict(item, identity_confirmation_id=None)))
        self.assertFalse(web_identity_ready(dict(item, preparation_method="unknown")))
        self.assertFalse(web_identity_ready(dict(item, validation_issues=["bad_state"])))

    def test_client_status_or_invented_confirmation_provenance_stays_blocked(self):
        base = {"name_zh": "青江菜", "confidence": 0.42, "validation_issues": [],
                "identity_confirmation_required": False, "food_state": "prepared",
                "preparation_method": "stir_fried", "components_scope": "food_only"}
        self.assertFalse(web_identity_ready(base))
        self.assertFalse(web_identity_ready(dict(
            base, identity_confirmation_source="model", identity_confirmation_id="client-id")))

    def test_global_vision_issues_mark_identity_as_unconfirmed(self):
        class Storage:
            def get_user(self, _user_id):
                return None

            def get_custom_foods(self, _user_id):
                return []

        parsed = {"items": [{"name_zh": "蘋果", "name_en": "apple", "confidence": 0.98,
                             "weight_confidence": 0.2, "estimated_weight_g": 100,
                             "food_state": "raw", "preparation_method": "mixed",
                             "components_scope": "food_only"}],
                  "validation_issues": ["response_warning"]}
        response = build_vision_food_response(parsed, Storage(), {}, {}, {"groups": []},
                                              [], [], "user-1", lambda food, *_: food)
        self.assertTrue(response["recognition_context"]["items"][0]["identity_confirmation_required"])


if __name__ == "__main__":
    unittest.main()
