"""Local relay integration, credential isolation, and concurrent key leasing."""

import base64
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import ai_relay_service as relay
from services.nutrition_label_service import (
    call_gemini_nutrition_ocr_with_rotation,
    get_gemini_api_keys,
    get_gemini_models,
    probe_gemini_models,
)
from services.restaurant_ai_service import build_restaurant_ai_summary
from services.robust_restaurant_scraper_service import enrich_restaurant_with_gemini, parse_menu_image_with_gemini
from services.vision_food_service import call_gemini_food_recognition_with_rotation


KEYS = tuple(f"sk-local-test-{index}" for index in range(5))
MODEL = "[AN]local-vision-model"
PHOTO = base64.b64encode(b"\x89PNG\r\n\x1a\nlocal-test-image").decode("ascii")


class RelayConfigTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"NUTRILENS_SKIP_LOCAL_ENV": "1"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(relay._read_keys_file.cache_clear)

    def test_unit_test_mode_never_reads_real_key_file(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("real credentials must stay unread")):
            self.assertIsNone(relay.get_relay_config())

    def test_original_key_file_format_bom_and_exact_model(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key.txt"
            key_file.write_text(
                'Base URL "https://relay.example/v1/"\nAPI\u683c\u5f0f "OpenAI Compatible"\n'
                f'\u6307\u5b9a\u6a21\u578bID "{MODEL}"\n\n' + "\n".join((*KEYS, KEYS[0])),
                encoding="utf-8-sig",
            )
            with patch.dict(os.environ, {"AI_RELAY_KEYS_FILE": str(key_file)}):
                config = relay.get_relay_config()
                self.assertEqual(config.chat_url, "https://relay.example/v1/chat/completions")
                self.assertEqual(config.keys, KEYS)
                self.assertEqual(get_gemini_models(), [MODEL])
                self.assertEqual(get_gemini_api_keys("untrusted-client-key"), list(KEYS))
                self.assertNotIn(KEYS[0], repr(config))

    def test_complete_environment_overrides_file_and_legacy_keys(self):
        with patch.dict(os.environ, {
            "AI_BASE_URL": "https://relay.example/v1/", "AI_MODEL": MODEL,
            "AI_API_KEYS": ",".join((*KEYS, KEYS[0])), "AI_RELAY_KEYS_FILE": "missing-secret-file",
            "GEMINI_API_KEYS": "old-google-key", "OPENAI_API_KEY": "old-openai-key",
        }):
            self.assertEqual(get_gemini_api_keys("client-key"), list(KEYS))
            self.assertEqual(get_gemini_models(), [MODEL])

    def test_partial_environment_or_missing_explicit_file_fails_closed(self):
        for settings in ({"AI_MODEL": MODEL}, {"AI_RELAY_KEYS_FILE": "missing-secret-file"}):
            with self.subTest(settings=settings), patch.dict(os.environ, settings):
                with self.assertRaises(ValueError):
                    relay.get_relay_config()

    def test_local_file_is_loaded_without_environment_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "key.txt"
            key_file.write_text(f'Base URL "https://relay.example/v1"\n\u6307\u5b9a\u6a21\u578bID "{MODEL}"\n{KEYS[0]}', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.object(relay, "DEFAULT_KEYS_FILE", key_file):
                self.assertEqual(relay.get_relay_config().keys, (KEYS[0],))


class LocalRelayTests(unittest.TestCase):
    def setUp(self):
        self.state = state = SimpleNamespace(
            lock=threading.Lock(), calls=[], active=set(), overlap=False, peak=0,
            delay=0, statuses={}, body=None,
        )
        menu_item = {"name": "local meal", "name_zh": "local meal", "price": 50, "confidence": 0.9,
                     "calories": 500, "protein": 20, "carbs": 60, "fat": 20, "sodium": 500}
        content = json.dumps({"items": [menu_item], "product_name": "local product",
                              "nutrition_per_serving": {"calories": 500}, "restaurant_type": "local restaurant",
                              "likely_foods": ["local meal"], "health_tips": [], "confidence": "low"})
        state.body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                key = self.headers.get("Authorization", "").removeprefix("Bearer ")
                with state.lock:
                    state.calls.append((self.path, key, dict(self.headers), payload))
                    if key in state.active:
                        state.overlap = True
                    state.active.add(key)
                    state.peak = max(state.peak, len(state.active))
                if state.delay:
                    time.sleep(state.delay)
                status = state.statuses.get(key, 200)
                body = state.body if status == 200 else {"error": {"message": f"upstream echo {key}"}}
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                if status == 429:
                    self.send_header("Retry-After", "30")
                self.end_headers()
                with state.lock:
                    state.active.remove(key)
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        env = patch.dict(os.environ, {
            "NUTRILENS_SKIP_LOCAL_ENV": "1", "AI_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
            "AI_MODEL": MODEL, "AI_API_KEYS": ",".join(KEYS),
            "GEMINI_API_KEYS": "old-google-key", "OPENAI_API_KEY": "old-openai-key",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(relay._cached_pool.cache_clear)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_all_five_features_share_relay_keys_model_and_image_format(self):
        keys = get_gemini_api_keys("ignored-client-key")
        self.assertTrue(call_gemini_food_recognition_with_rotation(PHOTO, "image/png", keys)["items"])
        self.assertEqual(call_gemini_nutrition_ocr_with_rotation(PHOTO, "image/png", keys)["product_name"], "local product")
        self.assertEqual(build_restaurant_ai_summary({"name": "local restaurant"}, "all", [])["restaurant_type"], "local restaurant")
        self.assertTrue(enrich_restaurant_with_gemini("local restaurant", "local address")["items"])
        menu = parse_menu_image_with_gemini(PHOTO)
        self.assertEqual(menu["recognition_status"], "recognized")
        self.assertEqual(menu["recognition_model"], MODEL)
        self.assertEqual([call[1] for call in self.state.calls], list(KEYS))
        for index, (path, key, headers, payload) in enumerate(self.state.calls):
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(payload["model"], MODEL)
            self.assertNotIn("x-goog-api-key", {name.lower() for name in headers})
            self.assertNotIn(key, json.dumps(payload))
            if index in {0, 1, 4}:
                self.assertEqual(payload["messages"][0]["content"][1]["image_url"]["url"], f"data:image/png;base64,{PHOTO}")

    def test_simultaneous_first_use_has_one_pool_and_no_key_overlap(self):
        self.state.delay = 0.04
        barrier = threading.Barrier(12)

        def call(_index):
            barrier.wait(timeout=5)
            return relay.relay_chat("Return JSON", timeout=5)

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(call, range(12)))
        self.assertEqual(len(results), 12)
        self.assertEqual(len(self.state.calls), 12)
        self.assertFalse(self.state.overlap)
        self.assertGreater(self.state.peak, 1)
        self.assertLessEqual(self.state.peak, len(KEYS))
        counts = [sum(call[1] == key for call in self.state.calls) for key in KEYS]
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_429_rotates_and_cooldown_applies_to_other_features(self):
        self.state.statuses[KEYS[0]] = 429
        self.assertTrue(enrich_restaurant_with_gemini("local restaurant", "local address")["items"])
        for _ in range(5):
            call_gemini_nutrition_ocr_with_rotation(PHOTO, "image/png", get_gemini_api_keys())
        tried = [call[1] for call in self.state.calls]
        self.assertEqual(tried[:2], list(KEYS[:2]))
        self.assertEqual(tried.count(KEYS[0]), 1)

    def test_all_keys_failing_are_tried_once_without_legacy_fallback(self):
        self.state.statuses = dict.fromkeys(KEYS, 429)
        with self.assertRaises(requests.HTTPError) as error:
            call_gemini_food_recognition_with_rotation(PHOTO, "image/png", get_gemini_api_keys())
        self.assertEqual(error.exception.response.status_code, 429)
        self.assertEqual(len(self.state.calls), 5)
        for key in KEYS:
            self.assertNotIn(key, str(error.exception))
            self.assertNotIn(key, error.exception.response.text)
        self.assertIsNone(error.exception.request)
        with self.assertRaises(requests.HTTPError):
            relay.relay_chat("Return JSON")
        self.assertEqual(len(self.state.calls), 5)

    def test_auth_errors_and_missing_model_rotate_keys(self):
        self.state.statuses = dict(zip(KEYS, (401, 403, 404, 503, 200)))
        relay.relay_chat("Return JSON")
        self.assertEqual([call[1] for call in self.state.calls], list(KEYS))

    def test_bad_request_does_not_retry_and_invalid_reply_releases_key(self):
        self.state.statuses[KEYS[0]] = 400
        with self.assertRaises(requests.HTTPError):
            relay.relay_chat("Return JSON")
        self.assertEqual(len(self.state.calls), 1)
        self.state.body = {"choices": []}
        with self.assertRaises(ValueError):
            relay.relay_chat("Return JSON")
        pool = relay._key_pool(relay.get_relay_config().base_url, KEYS)
        self.assertEqual(pool._busy, set())

    def test_expired_deadline_sends_no_request(self):
        result = enrich_restaurant_with_gemini("local restaurant", "local address", deadline=time.monotonic() - 1)
        self.assertEqual(result, {"items": [], "failure": "out_of_budget"})
        self.assertEqual(self.state.calls, [])

    def test_waiting_for_busy_pool_respects_deadline(self):
        pool = relay._key_pool(relay.get_relay_config().base_url, KEYS)
        leased = [pool.acquire(set(), time.monotonic() + 1) for _ in KEYS]
        try:
            with self.assertRaises(requests.Timeout):
                relay.relay_chat("Return JSON", timeout=0.02)
            self.assertEqual(self.state.calls, [])
        finally:
            for key in leased:
                pool.release(key)

    def test_connection_failure_releases_key_and_uses_next_key(self):
        original_post = requests.post
        attempted = []

        def post(url, **kwargs):
            attempted.append(kwargs["headers"]["Authorization"])
            if len(attempted) == 1:
                raise requests.ConnectionError(f"sensitive echo {KEYS[0]}")
            return original_post(url, **kwargs)

        with patch.object(relay.requests, "post", post):
            relay.relay_chat("Return JSON")
        self.assertEqual(attempted, [f"Bearer {key}" for key in KEYS[:2]])

    def test_diagnostics_reports_no_secrets_and_uses_relay(self):
        report = probe_gemini_models(generate=True)
        self.assertEqual(report["generate_status"], "ok")
        self.assertEqual(report["key_count"], 5)
        for key in KEYS:
            self.assertNotIn(key, json.dumps(report))


if __name__ == "__main__":
    unittest.main()
