"""Offline parity checks for the bounded live-photo diagnostic harness."""

import base64
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import probe_food_nutrition as probe


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5GQAAAAASUVORK5CYII="
)


class FoodProbeContractTests(unittest.TestCase):
    def run_job(self, text, finish="stop"):
        path = Mock()
        path.name = "synthetic.png"
        path.read_bytes.return_value = PNG
        with patch.object(probe, "call", return_value={"text": text, "finish_reason": finish}) as call, \
                patch.object(probe, "ground", return_value={"summary": {}}) as ground:
            result = probe.vision_job(path, 1)
        return result, call, ground

    def test_success_matches_production_finish_policy_and_retains_raw_output(self):
        text = '{"items":[{"name_zh":"food","confidence":0.9}]}'
        for finish in ("stop", None):
            with self.subTest(finish=finish):
                result, _, ground = self.run_job(text, finish)
                self.assertEqual(result["text"], text)
                self.assertNotIn("pipeline_error", result)
                self.assertEqual(result["raw_parsed"]["items"][0], {"name_zh": "food", "confidence": 0.9})
                self.assertEqual(result["parsed"]["items"][0]["food_state"], "unknown")
                self.assertNotIn("food_state", result["raw_parsed"]["items"][0])
                ground.assert_called_once_with(result["parsed"])

    def test_production_legacy_array_is_supported(self):
        result, _, ground = self.run_job('[{"name_zh":"food","confidence":0.9}]')
        self.assertIsInstance(result["raw_parsed"], list)
        self.assertEqual(result["parsed"]["items"][0]["name_zh"], "food")
        ground.assert_called_once()

    def test_mixed_prose_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for text in (
            'prefix {"items": []}', '{"items": []} suffix',
            '{"items": [], "items": []}',
            '{"items": [{"name_zh": "food", "confidence": NaN}]}',
            '{"items": [{"name_zh": "food", "confidence": 1e999}]}',
        ):
            with self.subTest(text=text):
                result, _, ground = self.run_job(text)
                self.assertEqual(result["text"], text)
                self.assertEqual(result["pipeline_error"], "ValueError")
                self.assertNotIn("raw_parsed", result)
                self.assertNotIn("response", result)
                ground.assert_not_called()

    def test_non_success_finishes_never_reach_grounding_even_with_valid_json(self):
        for finish in ("length", "max_tokens", "content_filter", "tool_calls", "STOP", "unknown"):
            with self.subTest(finish=finish):
                result, _, ground = self.run_job('{"items": []}', finish)
                self.assertEqual(result["text"], '{"items": []}')
                self.assertEqual(result["pipeline_error"], "ValueError")
                self.assertNotIn("raw_parsed", result)
                ground.assert_not_called()

    def test_png_mime_is_decoded_from_bytes_and_forwarded_to_call(self):
        result, call, _ = self.run_job('{"items": []}')
        self.assertEqual(result["image_mime_type"], "image/png")
        self.assertEqual(call.call_args.kwargs["image_mime_type"], "image/png")
        self.assertEqual(call.call_args.kwargs["image"], PNG)

    def test_normalization_failure_preserves_strict_parsed_json_and_text(self):
        text = '{"items": "invalid"}'
        result, _, ground = self.run_job(text)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["raw_parsed"], {"items": "invalid"})
        self.assertEqual(result["pipeline_error"], "ValueError")
        ground.assert_not_called()


if __name__ == "__main__":
    unittest.main()
