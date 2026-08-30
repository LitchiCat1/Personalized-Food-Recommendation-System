import base64
import os
import unittest
from unittest.mock import MagicMock, patch

from services.robust_restaurant_scraper_service import parse_menu_image_with_gemini


class MenuPhotoParsingTests(unittest.TestCase):
    def test_invalid_image_is_rejected_before_gemini_request(self):
        with patch.dict(os.environ, {"GEMINI_API_KEYS": "test-key"}, clear=True):
            with patch("services.robust_restaurant_scraper_service.requests.post") as request:
                result = parse_menu_image_with_gemini("not-base64", "測試店")

        self.assertEqual(result["items"], [])
        self.assertIn("Base64", result["error"])
        request.assert_not_called()

    def test_missing_gemini_key_returns_actionable_error(self):
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nmenu").decode("ascii")
        with patch.dict(os.environ, {}, clear=True):
            with patch("services.robust_restaurant_scraper_service.requests.post") as request:
                result = parse_menu_image_with_gemini(image, "測試店")

        self.assertEqual(result["items"], [])
        self.assertIn("Gemini API key", result["error"])
        request.assert_not_called()

    def test_data_uri_mime_type_is_forwarded_to_gemini(self):
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nmenu").decode("ascii")
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"items":[{"name":"清蒸雞胸","price":120,"protein":30,"carbs":20,"fat":8,"sodium":300}]}'
                    }]
                }
            }]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEYS": "test-key"}, clear=True):
            with patch("services.robust_restaurant_scraper_service.requests.post", return_value=response) as request:
                result = parse_menu_image_with_gemini(f"data:image/png;base64,{image}", "測試店")

        self.assertEqual(result["items"][0]["name"], "清蒸雞胸")
        payload = request.call_args.kwargs["json"]
        inline_data = payload["contents"][0]["parts"][1]["inlineData"]
        self.assertEqual(inline_data["mimeType"], "image/png")
        self.assertEqual(inline_data["data"], image)


if __name__ == "__main__":
    unittest.main()
