import base64
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.robust_restaurant_scraper_service import (  # noqa: E402
    _extract_menu_items_from_response,
    parse_menu_image_with_gemini,
)
from services.nutrition_label_service import decode_image_base64  # noqa: E402


class MenuPhotoTests(unittest.TestCase):
    PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nmenu-image").decode("ascii")

    def test_png_payload_is_detected(self):
        _, payload, mime_type = decode_image_base64(self.PNG_BASE64)
        self.assertEqual(payload, self.PNG_BASE64)
        self.assertEqual(mime_type, "image/png")

    def test_response_parser_reads_all_parts_and_alias_fields(self):
        body = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [
                    {"text": '{"menu_items":[{"item_name":"炒飯","price":"60 元"}]}'},
                    {"text": ""},
                ]},
            }],
        }
        items, finish_reason = _extract_menu_items_from_response(body)
        self.assertEqual(finish_reason, "STOP")
        self.assertEqual(items[0]["name"], "炒飯")
        self.assertEqual(items[0]["price"], 60)

    @patch("services.robust_restaurant_scraper_service.get_gemini_models", return_value=["retired-model", "working-model"])
    @patch("services.robust_restaurant_scraper_service.get_gemini_api_keys", return_value=["test-key"])
    @patch("services.robust_restaurant_scraper_service.requests.post")
    def test_model_rotation_recovers_after_retired_model(self, post, _keys, _models):
        retired = Mock(status_code=404)
        retired.json.return_value = {"error": {"message": "model not found"}}
        working = Mock(status_code=200)
        working.json.return_value = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps({"items": [
                    {"name": "炒飯", "price": 60, "calories": 400, "protein": 12, "carbs": 55, "fat": 12}
                ]}, ensure_ascii=False)}]},
            }],
        }
        post.side_effect = [retired, working]

        result = parse_menu_image_with_gemini(self.PNG_BASE64, "家庭小吃")

        self.assertEqual(result["recognition_status"], "recognized")
        self.assertEqual(result["items"][0]["name"], "炒飯")
        self.assertEqual(post.call_count, 2)
        payload = post.call_args_list[1].kwargs["json"]
        image_part = payload["contents"][0]["parts"][1]
        self.assertEqual(image_part["inline_data"]["mime_type"], "image/png")
        self.assertNotIn("inlineData", image_part)

    @patch("services.robust_restaurant_scraper_service.get_gemini_api_keys", return_value=[])
    def test_missing_key_is_reported_instead_of_fake_menu(self, _keys):
        result = parse_menu_image_with_gemini(self.PNG_BASE64, "家庭小吃")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["recognition_status"], "error")
        self.assertIn("API key", result["recognition_error"])


if __name__ == "__main__":
    unittest.main()
