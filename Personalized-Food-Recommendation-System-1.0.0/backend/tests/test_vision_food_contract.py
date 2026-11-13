"""Offline input-boundary and cross-stage photo context regression tests."""

import json
import math
import unittest
from unittest.mock import Mock, patch

from services.nutrition_label_service import build_custom_food_search_result
from services.strict_json_service import parse_strict_model_json
from services.vision_food_service import (
    build_vision_food_response, call_gemini_food_recognition,
    build_food_recognition_prompt, normalize_confidence, normalize_weight, normalize_vision_result,
)


class Storage:
    def get_user(self, _user_id):
        return None

    def get_custom_foods(self, _user_id):
        return []


class StrictModelJsonTests(unittest.TestCase):
    def test_complete_object_and_outer_fence(self):
        for text in ('{"items": []}', '```json\n{"items": []}\n```'):
            self.assertEqual(parse_strict_model_json(text), {"items": []})

    def test_arrays_require_explicit_legacy_option(self):
        with self.assertRaises(ValueError):
            parse_strict_model_json("[]")
        self.assertEqual(parse_strict_model_json("[]", allow_array=True), [])

    def test_mixed_content_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for text in ('prefix {"items": []}', '{"items": []} suffix',
                     '{"items": [], "items": []}', '{"items": [{"x": 1, "x": 2}]}',
                     '{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}',
                     '```json\n{"items": []}', '{"items": [', 'null'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_strict_model_json(text)

    def test_size_limit_uses_utf8_bytes(self):
        with self.assertRaises(ValueError):
            parse_strict_model_json('{"name": "食"}', max_bytes=14)


class VisionRecognitionContractTests(unittest.TestCase):
    def response(self, items, database=None, **fields):
        return build_vision_food_response({"items": items, **fields}, Storage(), database or {}, {},
                                         {"groups": []}, [], [], None, build_custom_food_search_result)

    def test_invalid_confidence_never_becomes_a_medium_confidence_guess(self):
        for value in (None, True, False, "0.95", "95%", -0.1, 1.1, 95, math.nan, math.inf, 10**400):
            with self.subTest(value=value):
                self.assertEqual(normalize_confidence(value), 0)
                response = self.response([{"name_zh": "地瓜球", "confidence": value}])
                self.assertEqual(response["detections"], [])
                self.assertIn("信心過低", response["rejected_detections"][0]["reason"])
        self.assertEqual(normalize_confidence(0.95), 0.95)

    def test_invalid_weights_are_unknown_without_clamping_or_string_coercion(self):
        for value in (None, True, False, "100g", "100", -1, 0, 2001, math.nan, math.inf, 10**400):
            with self.subTest(value=value):
                self.assertIsNone(normalize_weight(value))
        self.assertEqual(normalize_weight(125.25), 125.2)

    def test_same_named_items_have_separate_ids_and_complete_unmatched_context(self):
        response = self.response([
            {"name_zh": "葉菜", "name_en": "leafy vegetable", "confidence": 0.8,
             "estimated_weight_g": 40, "weight_confidence": 0.4, "food_state": "prepared",
             "preparation_method": "stir_fried", "components_scope": "food_only", "count": 2},
            {"name_zh": "葉菜", "confidence": 0.9, "estimated_weight_g": 70},
        ], uncertainty_notes=["背景餐盤未納入"])
        first, second = response["rejected_detections"]
        self.assertNotEqual(first["item_id"], second["item_id"])
        context = first["recognition_context"]
        self.assertEqual(context["name_en"], "leafy vegetable")
        self.assertEqual(context["estimated_weight_g"], 40)
        self.assertEqual(context["weight_basis"], "total_edible_weight_g")
        self.assertEqual(context["count"], 2)
        self.assertEqual(context["food_state"], "prepared")
        self.assertEqual(context["preparation_method"], "stir_fried")
        self.assertEqual(context["components_scope"], "food_only")
        self.assertEqual(context["item_revision"], 0)
        self.assertEqual(response["recognition_context"]["uncertainty_notes"], ["背景餐盤未納入"])
        self.assertEqual(response["recognition_context"]["visual_completeness"], "not_verified")
        self.assertEqual(response["recognition_context"]["items"], [first["recognition_context"], second["recognition_context"]])
        json.dumps(response, allow_nan=False)

    def test_server_does_not_accept_model_assigned_ids(self):
        response = self.response([{"name_zh": "地瓜球", "confidence": 0.8, "item_id": "forged"}], scan_id="forged")
        self.assertNotEqual(response["scan_id"], "forged")
        self.assertNotEqual(response["rejected_detections"][0]["item_id"], "forged")

    def test_missing_and_invalid_semantic_fields_remain_unknown(self):
        for field in ("food_state", "preparation_method", "components_scope"):
            parsed = normalize_vision_result({"items": [{"name_zh": "白飯", "confidence": 0.9}]})
            self.assertEqual(parsed["items"][0][field], "unknown")
            self.assertIn(f"missing_{field}", parsed["items"][0]["validation_issues"])
            for value in (None, True, [], {}, "含湯", "not_an_enum"):
                with self.subTest(field=field, value=value):
                    parsed = normalize_vision_result({"items": [{"name_zh": "白飯", "confidence": 0.9, field: value}]})
                    item = parsed["items"][0]
                    self.assertEqual(item[field], "unknown")
                    self.assertIn(f"invalid_{field}", item["validation_issues"])
                    repeated = normalize_vision_result(parsed)
                    self.assertEqual(repeated["items"][0], item)

    def test_valid_enums_and_prompt_use_the_same_scope_and_method_values(self):
        prompt = build_food_recognition_prompt()
        for field, values in {
            "food_state": ("prepared", "raw", "dry", "unknown"),
            "preparation_method": ("boiled", "stir_fried", "pan_fried", "deep_fried", "roasted", "braised", "steamed", "mixed", "unknown"),
            "components_scope": ("food_only", "noodles_only", "whole_dish_with_broth", "with_sides", "unknown"),
        }.items():
            for value in values:
                parsed = normalize_vision_result({"items": [{"name_zh": "食品", "confidence": 0.9, field: value}]})
                self.assertEqual(parsed["items"][0][field], value)
                self.assertNotIn(f"invalid_{field}", parsed["items"][0]["validation_issues"])
                self.assertIn(value, prompt)

    def test_matched_context_keeps_total_weight_without_multiplying_count(self):
        profile = {"name_zh": "測試食品", "calories": 200, "protein": 5, "carbs": 30, "fat": 7,
                   "sodium": 30, "fiber": 1, "sugar": 2, "saturated_fat": 1, "trans_fat": 0}
        with patch("services.vision_food_service.find_vision_food_matches", return_value=[profile]):
            response = self.response([{"name_zh": "測試食品", "confidence": 0.9,
                                      "estimated_weight_g": 80, "count": 2}])
        detection = response["detections"][0]
        self.assertEqual(detection["nutrition"]["calories"], 160)
        self.assertEqual(detection["recognition_context"]["estimated_weight_g"], 80)
        self.assertEqual(detection["recognition_context"]["count"], 2)
        self.assertEqual(detection["item_id"], response["recognition_context"]["items"][0]["item_id"])

    def test_discarded_invalid_item_cannot_claim_complete_nutrition(self):
        profile = {"name_zh": "測試食品", "calories": 200, "protein": 5, "carbs": 30, "fat": 7, "sodium": 30}
        with patch("services.vision_food_service.find_vision_food_matches", return_value=[profile]):
            response = self.response([{"name_zh": "測試食品", "confidence": 0.9}, None])
        self.assertFalse(response["summary"]["nutrition_complete"])
        self.assertTrue(response["summary"]["requires_user_confirmation"])
        self.assertTrue(response["detections"][0]["needs_confirmation"])
        self.assertTrue(any("格式無效" in warning for warning in response["detections"][0]["warnings"]))
        self.assertIn("invalid_item_discarded", response["recognition_context"]["validation_issues"])

    def test_native_truncation_and_blocked_finishes_are_rejected_even_with_valid_json(self):
        for finish in ("MAX_TOKENS", "SAFETY", "RECITATION", None):
            response = Mock()
            response.json.return_value = {"candidates": [{"finishReason": finish,
                "content": {"parts": [{"text": '{"items": []}'}]}}]}
            with self.subTest(finish=finish), patch("services.vision_food_service.get_relay_config", return_value=None), \
                    patch("services.vision_food_service.requests.post", return_value=response), self.assertRaises(ValueError):
                call_gemini_food_recognition("not-an-image", "image/jpeg", "unused-test-key")

    def test_native_success_joins_text_parts_and_uses_strict_parser(self):
        response = Mock()
        response.json.return_value = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": '{"items":'}, {"text": ' []}'},
        ]}}]}
        with patch("services.vision_food_service.get_relay_config", return_value=None), \
                patch("services.vision_food_service.requests.post", return_value=response):
            self.assertEqual(call_gemini_food_recognition("not-an-image", "image/jpeg", "unused-test-key")["items"], [])


if __name__ == "__main__":
    unittest.main()
