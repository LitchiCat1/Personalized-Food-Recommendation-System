"""菜單分析先問 ChatGPT，失敗才換 Gemini。"""

import base64
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.nutrition_label_service import forget_forbidden_gemini_models  # noqa: E402
from services.openai_service import OPENAI_CHAT_URL, get_openai_models  # noqa: E402
from services.robust_restaurant_scraper_service import (  # noqa: E402
    enrich_restaurant_with_gemini,
    parse_menu_image_with_gemini,
)

SCRAPER = "services.robust_restaurant_scraper_service"
MENU = [{"name": "滷肉飯", "price": 40, "calories": 450, "protein": 12, "carbs": 60, "fat": 16, "sodium": 600}]
PHOTO = base64.b64encode(b"\x89PNG\r\n\x1a\nmenu-image").decode("ascii")


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def openai_reply(status, items=None, code=None):
    if status != 200:
        return FakeResponse(status, {"error": {"code": code, "message": f"openai {status}"}})
    content = json.dumps({"items": items or []}, ensure_ascii=False)
    return FakeResponse(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def gemini_reply(status, items=None):
    if status != 200:
        return FakeResponse(status, {"error": {"message": f"gemini {status}"}})
    text = json.dumps({"items": items or []}, ensure_ascii=False)
    return FakeResponse(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]})


class OpenAIFirstMenuTests(unittest.TestCase):
    def setUp(self):
        forget_forbidden_gemini_models()
        self.addCleanup(forget_forbidden_gemini_models)
        for target, value in (
            ("get_gemini_api_keys", ["gemini-key"]),
            ("get_gemini_models", ["m-lite"]),
            ("get_openai_api_key", "sk-test"),
            ("get_openai_models", ["gpt-a", "gpt-b"]),
        ):
            patcher = patch(f"{SCRAPER}.{target}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

    def fake_post(self, openai, gemini):
        def post(url, **kwargs):
            if url == OPENAI_CHAT_URL:
                model = kwargs["json"]["model"]
                self.calls.append(("openai", model))
                return openai(model, kwargs)
            self.calls.append(("gemini", url.split("/models/")[1].split(":")[0]))
            return gemini()
        return post

    def test_chatgpt_answers_first_and_gemini_is_not_asked(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(200, MENU), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertEqual(result["items"][0]["name"], "滷肉飯")
        self.assertEqual(self.calls, [("openai", "gpt-a")])

    def test_gemini_is_asked_when_chatgpt_fails(self):
        for failure in (openai_reply(500), openai_reply(429, code="insufficient_quota"), openai_reply(401)):
            self.calls.clear()
            post = self.fake_post(lambda model, kwargs, failure=failure: failure, lambda: gemini_reply(200, MENU))
            with patch(f"{SCRAPER}.requests.post", post):
                result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")
            self.assertTrue(result["items"], failure.status_code)
            self.assertEqual(self.calls[-1], ("gemini", "m-lite"))

    def test_gemini_is_asked_when_chatgpt_times_out(self):
        def slow(model, kwargs):
            raise requests.Timeout("slow")

        with patch(f"{SCRAPER}.requests.post", self.fake_post(slow, lambda: gemini_reply(200, MENU))):
            result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertTrue(result["items"])
        self.assertEqual(self.calls, [("openai", "gpt-a"), ("openai", "gpt-b"), ("gemini", "m-lite")])

    def test_gemini_is_asked_when_chatgpt_cannot_tell_what_the_venue_sells(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(200, []), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertTrue(result["items"])
        self.assertEqual(self.calls, [("openai", "gpt-a"), ("gemini", "m-lite")])

    def test_a_missing_chatgpt_model_falls_through_to_the_next_one(self):
        def by_model(model, kwargs):
            return openai_reply(404) if model == "gpt-a" else openai_reply(200, MENU)

        with patch(f"{SCRAPER}.requests.post", self.fake_post(by_model, lambda: gemini_reply(200, MENU))):
            result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertTrue(result["items"])
        self.assertEqual(self.calls, [("openai", "gpt-a"), ("openai", "gpt-b")])

    def test_both_saying_empty_is_no_items(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(200, []), lambda: gemini_reply(200, []))
        with patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("看不出賣什麼的店", "台南")
        self.assertEqual(result, {"items": [], "failure": "no_items"})

    def test_only_chatgpt_saying_empty_is_not_no_items(self):
        """Gemini 額度用完沒回答到，不能只憑 ChatGPT 一句看不出來就把店冷卻 6 小時。"""
        post = self.fake_post(lambda model, kwargs: openai_reply(200, []), lambda: gemini_reply(429))
        with patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("某店", "台南")
        self.assertEqual(result["failure"], "rate_limited")

    def test_chatgpt_quota_counts_as_rate_limited_when_gemini_cannot_answer(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(429), lambda: gemini_reply(404))
        with patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("某店", "台南")
        self.assertEqual(result["failure"], "rate_limited")

    def test_chatgpt_alone_works_without_gemini_keys(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(200, MENU), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.get_gemini_api_keys", return_value=[]), patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")
        self.assertTrue(result["items"])

        post = self.fake_post(lambda model, kwargs: openai_reply(401), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.get_gemini_api_keys", return_value=[]), patch(f"{SCRAPER}.requests.post", post):
            result = enrich_restaurant_with_gemini("樣板裡沒有的店", "台南")
        self.assertEqual(result, {"items": [], "failure": "unavailable"})

    def test_an_expired_budget_sends_nothing(self):
        def must_not_be_called(url, **kwargs):
            raise AssertionError("時間預算已過，不該再送請求")

        with patch(f"{SCRAPER}.requests.post", must_not_be_called):
            result = enrich_restaurant_with_gemini("某店", "台南", deadline=time.monotonic() - 1)
        self.assertEqual(result["failure"], "out_of_budget")

    def test_the_key_is_only_in_the_header(self):
        seen = {}

        def capture(model, kwargs):
            seen.update(kwargs)
            return openai_reply(200, MENU)

        with patch(f"{SCRAPER}.requests.post", self.fake_post(capture, lambda: gemini_reply(200, MENU))):
            enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertEqual(seen["headers"], {"Authorization": "Bearer sk-test"})
        self.assertNotIn("sk-test", json.dumps(seen["json"]))
        self.assertEqual(seen["json"]["response_format"], {"type": "json_object"})

    def test_menu_photo_is_read_by_chatgpt_first(self):
        seen = {}

        def capture(model, kwargs):
            seen.update(kwargs["json"])
            return openai_reply(200, MENU)

        with patch(f"{SCRAPER}.requests.post", self.fake_post(capture, lambda: gemini_reply(200, MENU))):
            result = parse_menu_image_with_gemini(PHOTO, "阿婆滷肉飯")

        self.assertEqual(result["recognition_status"], "recognized")
        self.assertEqual(result["recognition_model"], "gpt-a")
        self.assertEqual(self.calls, [("openai", "gpt-a")])
        image_part = seen["messages"][0]["content"][1]
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_menu_photo_falls_back_to_gemini(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(429), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.requests.post", post):
            result = parse_menu_image_with_gemini(PHOTO, "阿婆滷肉飯")

        self.assertEqual(result["recognition_status"], "recognized")
        self.assertEqual(result["recognition_model"], "m-lite")

    def test_menu_photo_reports_both_failures(self):
        # 新帳號沒錢時實際回的是 credit_balance_exhausted，不是文件上的 insufficient_quota
        for code in ("insufficient_quota", "credit_balance_exhausted"):
            post = self.fake_post(lambda model, kwargs, code=code: openai_reply(429, code=code),
                                  lambda: gemini_reply(429))
            with patch(f"{SCRAPER}.requests.post", post):
                result = parse_menu_image_with_gemini(PHOTO, "阿婆滷肉飯")

            self.assertEqual(result["recognition_status"], "error")
            self.assertIn("儲值", result["recognition_error"], code)
            self.assertIn("Gemini", result["recognition_error"])

    def test_menu_photo_with_only_chatgpt_reports_its_failure(self):
        post = self.fake_post(lambda model, kwargs: openai_reply(401), lambda: gemini_reply(200, MENU))
        with patch(f"{SCRAPER}.get_gemini_api_keys", return_value=[]), patch(f"{SCRAPER}.requests.post", post):
            result = parse_menu_image_with_gemini(PHOTO, "阿婆滷肉飯")

        self.assertEqual(result["recognition_status"], "error")
        self.assertIn("OPENAI_API_KEY", result["recognition_error"])
        self.assertNotIn(("gemini", "m-lite"), self.calls)


class OpenAIConfigTests(unittest.TestCase):
    def test_models_can_be_overridden_and_defaults_follow(self):
        with patch.dict(os.environ, {"OPENAI_MODELS": "gpt-x, gpt-4.1-mini"}):
            self.assertEqual(get_openai_models(), ["gpt-x", "gpt-4.1-mini", "gpt-4o-mini"])

    def test_no_key_means_gemini_only(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch(f"{SCRAPER}.get_gemini_api_keys", return_value=["gemini-key"]), \
                    patch(f"{SCRAPER}.get_gemini_models", return_value=["m-lite"]), \
                    patch(f"{SCRAPER}.requests.post", return_value=gemini_reply(200, MENU)) as post:
                result = enrich_restaurant_with_gemini("阿婆滷肉飯", "台南")

        self.assertTrue(result["items"])
        self.assertNotIn(OPENAI_CHAT_URL, [call.args[0] for call in post.call_args_list])


if __name__ == "__main__":
    unittest.main()
