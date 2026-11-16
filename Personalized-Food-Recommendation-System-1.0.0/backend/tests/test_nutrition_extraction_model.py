"""Offline checks for bounded single-attempt nutrition relay selection."""

import math
import unittest
from unittest.mock import Mock, patch

import requests

from services import ai_relay_service as relay
from services import nutrition_extraction_model_service as model


PROMPT = {"instruction": "Return existing cell IDs only.", "data": '{"SOURCE_BLOCKS":[]}'}


class NutritionExtractionModelTests(unittest.TestCase):
    def setUp(self):
        self.config = self.enterContext(patch.object(model, "get_relay_config", return_value=object()))
        self.chat = self.enterContext(patch.object(model, "relay_chat", return_value=('{"items":[]}', "stop")))
        self.clock = self.enterContext(patch.object(model.time, "monotonic", return_value=100))

    def call(self, prompt=None, deadline=125):
        return model.select_nutrition_cells_with_relay(PROMPT if prompt is None else prompt, deadline=deadline)

    def assert_code(self, code, **kwargs):
        with self.assertRaises(model.NutritionExtractionModelError) as raised:
            self.call(**kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_complete_response_uses_single_attempt_and_shared_deadline(self):
        self.assertEqual(self.call(), '{"items":[]}')
        self.chat.assert_called_once_with(
            PROMPT["instruction"] + "\nUNTRUSTED_SOURCE_DATA_JSON:\n" + PROMPT["data"],
            max_tokens=4096, timeout=25, deadline=125, max_attempts=1,
        )

    def test_timeout_never_exceeds_remaining_budget(self):
        self.call(deadline=103.5)
        self.assertEqual(self.chat.call_args.kwargs["timeout"], 3.5)

    def test_expired_deadline_does_not_read_configuration_or_call_model(self):
        self.assert_code("timeout", deadline=100)
        self.config.assert_not_called()
        self.chat.assert_not_called()

    def test_invalid_deadline_does_not_read_configuration(self):
        for deadline in (None, True, "125", math.nan, math.inf, -math.inf, 10 ** 1000):
            with self.subTest(deadline=type(deadline).__name__):
                self.assert_code("invalid_input", deadline=deadline)
        self.config.assert_not_called()
        self.chat.assert_not_called()

    def test_prompt_requires_exact_separate_bounded_fields(self):
        prompts = [[], {}, {**PROMPT, "tools": []}, {**PROMPT, "data": None},
                   {**PROMPT, "data": ""}, {**PROMPT, "instruction": " "},
                   {**PROMPT, "instruction": "x" * (model.MAX_INSTRUCTION_BYTES + 1)},
                   {**PROMPT, "data": "x" * (model.MAX_DATA_BYTES + 1)},
                   {**PROMPT, "data": "\ud800"}]
        for prompt in prompts:
            with self.subTest(prompt_type=type(prompt).__name__):
                self.assert_code("invalid_input", prompt=prompt)
        self.config.assert_not_called()
        self.chat.assert_not_called()

    def test_unconfigured_or_invalid_configuration_is_unavailable(self):
        self.config.return_value = None
        self.assert_code("unavailable")
        for error in (ValueError("private configuration"), OSError("private key path")):
            self.config.side_effect = error
            raised = self.assert_code("unavailable")
            self.assertNotIn("private", str(raised))
        self.chat.assert_not_called()

    def test_truncated_unknown_and_filtered_finish_are_not_salvaged(self):
        for finish in ("length", None, "content_filter", "tool_calls", "STOP"):
            with self.subTest(finish=finish):
                self.chat.return_value = ('{"items":[]}', finish)
                self.assert_code("invalid_output")

    def test_missing_oversized_and_invalid_unicode_output_is_rejected(self):
        for response in (None, "", " ", "x" * (model.MAX_RESPONSE_BYTES + 1), "\ud800"):
            with self.subTest(response_type=type(response).__name__):
                self.chat.return_value = (response, "stop")
                self.assert_code("invalid_output")

    def test_transport_and_parse_failures_are_typed_and_sanitized(self):
        for error, code in ((requests.Timeout("secret upstream echo"), "timeout"),
                            (requests.HTTPError("secret upstream echo"), "upstream_error"),
                            (requests.ConnectionError("secret upstream echo"), "upstream_error"),
                            (ValueError("secret upstream echo"), "invalid_output")):
            with self.subTest(code=code):
                self.chat.reset_mock()
                self.chat.side_effect = error
                raised = self.assert_code(code)
                self.chat.assert_called_once()
                self.assertNotIn("secret", str(raised))
                self.assertTrue(raised.__suppress_context__)

    def test_response_arriving_after_deadline_is_not_accepted(self):
        self.clock.side_effect = [100, 126]
        self.assert_code("timeout")


class RelayAttemptBudgetTests(unittest.TestCase):
    def setUp(self):
        self.config = relay.RelayConfig("https://relay.example/v1", "test-model", ("fake-key-a", "fake-key-b"))
        self.enterContext(patch.object(relay, "get_relay_config", return_value=self.config))
        self.pool = Mock()
        self.pool.acquire.side_effect = self.config.keys
        self.enterContext(patch.object(relay, "_key_pool", return_value=self.pool))
        self.post = self.enterContext(patch.object(relay.requests, "post"))
        self.response = requests.Response()
        self.response.status_code = 429
        self.response._content = b'private upstream body'
        self.post.return_value = self.response

    def test_single_attempt_does_not_rotate_retryable_http_error(self):
        with self.assertRaises(requests.HTTPError) as raised:
            relay.relay_chat("select cells", max_attempts=1)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.pool.release.call_count, 1)
        self.assertNotIn("private", str(raised.exception))
        self.assertEqual(raised.exception.response.status_code, 429)

    def test_single_attempt_does_not_retry_timeout(self):
        self.post.side_effect = requests.Timeout("private request")
        with self.assertRaises(requests.Timeout):
            relay.relay_chat("select cells", max_attempts=1)
        self.assertEqual(self.post.call_count, 1)
        self.pool.release.assert_called_once()

    def test_legacy_default_still_rotates_keys(self):
        with self.assertRaises(requests.HTTPError):
            relay.relay_chat("legacy request")
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.pool.release.call_count, 2)

    def test_invalid_attempt_budget_fails_before_pool_or_request(self):
        for budget in (0, -1, True, 1.5, "1", 3):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    relay.relay_chat("select cells", max_attempts=budget)
        self.pool.acquire.assert_not_called()
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
