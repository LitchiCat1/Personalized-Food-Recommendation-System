"""Offline fixtures distinguish dataset failures from legitimate lookup misses."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_api_routes import ApiTestBase

from services.nutrition_database_service import (
    NutritionDatasetUnavailable,
    build_nutrition_dataset_context,
    load_official_nutrition_dataset,
    load_usda_foods,
)


def profile(**overrides):
    return dict(name_zh="test food", source="USDA FNDDS", unit="per 100g",
                calories=120, protein=2, carbs=20, fat=3, sodium=15, **overrides)


class NutritionDatasetHealthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nutrition_db_usda.json"

    def write(self, foods):
        self.path.write_text(json.dumps(foods), encoding="utf-8")

    def load(self, **kwargs):
        return load_official_nutrition_dataset(self.directory.name, "USDA FNDDS", **kwargs)

    def test_missing_file_is_unavailable_and_compatibility_loader_raises(self):
        result = self.load()
        self.assertEqual(result["health"]["reason"], "missing_file")
        self.assertEqual(result["health"]["status"], "unavailable")
        with self.assertRaises(NutritionDatasetUnavailable) as error:
            load_usda_foods(self.directory.name)
        self.assertEqual(error.exception.health["reason"], "missing_file")

    def test_corrupt_json_duplicate_keys_and_nonfinite_constants_are_unavailable(self):
        for raw in ('{"food":', '{"food": {}, "food": {}}', '{"food": NaN}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                self.assertEqual(self.load()["health"]["reason"], "invalid_json")

    def test_empty_or_non_object_dataset_is_unavailable(self):
        for value in ({}, [], [{"food": profile()}], None):
            with self.subTest(value=value):
                self.write(value)
                self.assertEqual(self.load()["health"]["reason"], "invalid_shape")

    def test_invalid_profiles_are_not_treated_as_empty_success(self):
        for field, value in (("calories", True), ("protein", -1), ("sodium", "15"),
                             ("fat", 10 ** 400), ("calories", float("inf")),
                             ("source", "untrusted"), ("unit", "per serving"),
                             ("name_zh", ""), ("aliases", "test food"), ("fiber", False)):
            with self.subTest(field=field, value=value):
                food = profile()
                food[field] = value
                self.write({"test": food})
                self.assertEqual(self.load()["health"]["status"], "unavailable")
                self.assertEqual(self.load()["foods"], {})

    def test_missing_core_key_rejects_schema_but_explicit_null_remains_missing(self):
        food = profile()
        del food["protein"]
        self.write({"test": food})
        self.assertEqual(self.load()["health"]["reason"], "invalid_profile")
        food["protein"] = None
        self.write({"test": food})
        result = self.load()
        self.assertEqual(result["health"]["status"], "available")
        self.assertEqual(result["health"]["incomplete_core_profiles"], 1)
        self.assertIsNone(result["foods"]["test"]["protein"])

    def test_valid_dataset_has_snapshot_hash_without_claiming_hash_verification(self):
        self.write({"test": profile()})
        result = self.load()
        self.assertEqual(result["health"]["status"], "available")
        self.assertEqual(result["health"]["record_count"], 1)
        self.assertEqual(result["health"]["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result["health"]["hash_verification"], "not_configured")
        self.assertEqual(load_usda_foods(self.directory.name), result["foods"])

    def test_expected_output_checksum_is_enforced(self):
        self.write({"test": profile()})
        result = self.load(expected_sha256="0" * 64)
        self.assertEqual(result["health"]["reason"], "checksum_mismatch")
        self.assertEqual(result["health"]["hash_verification"], "mismatch")
        result = self.load(expected_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result["health"]["status"], "available")
        self.assertEqual(result["health"]["hash_verification"], "verified")

    def test_one_layer_failure_retains_healthy_layer_and_blocks_web_fallback(self):
        self.write({"test": profile()})
        usda = self.load()
        tfda = load_official_nutrition_dataset(self.directory.name, "TFDA")
        context = build_nutrition_dataset_context({"TFDA": tfda["health"], "USDA FNDDS": usda["health"]})
        self.assertEqual(len(usda["foods"]), 1)
        self.assertFalse(context["official_layers_available"])
        self.assertFalse(context["automatic_web_fallback_enabled"])
        self.assertEqual(context["web_fallback_block_reason"], "official_dataset_unavailable")

    def test_available_layers_do_not_implicitly_enable_web_fallback(self):
        context = build_nutrition_dataset_context({source: {"status": "available"}
                                                  for source in ("TFDA", "USDA FNDDS")})
        self.assertTrue(context["official_layers_available"])
        self.assertFalse(context["automatic_web_fallback_enabled"])
        self.assertEqual(context["web_fallback_block_reason"], "feature_not_enabled")

    def test_current_snapshots_validate_without_modification(self):
        base = Path(__file__).resolve().parents[1]
        for source in ("TFDA", "USDA FNDDS"):
            with self.subTest(source=source):
                result = load_official_nutrition_dataset(base, source)
                self.assertEqual(result["health"]["status"], "available")
                self.assertGreater(result["health"]["record_count"], 2000)


class NutritionDatasetRouteTests(ApiTestBase):
    def test_health_exposes_layer_failure_without_enabling_paid_fallback(self):
        health = {"TFDA": {"status": "available"},
                  "USDA FNDDS": {"status": "unavailable", "reason": "missing_file"}}
        with patch.object(self.app_module, "NUTRITION_DATASET_HEALTH", health):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["nutrition_dataset_health"], health)
        self.assertFalse(body["official_layers_available"])
        self.assertFalse(body["automatic_web_fallback_enabled"])
        self.assertEqual(body["web_fallback_block_reason"], "official_dataset_unavailable")

    def test_scan_retains_healthy_match_and_reports_unavailable_layer(self):
        health = {"TFDA": {"status": "available"},
                  "USDA FNDDS": {"status": "unavailable", "reason": "invalid_json"}}
        food = profile()
        food["source"] = "TFDA"
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nmock-image").decode("ascii")
        with self.mock_auth("user-a"), patch.object(self.app_module, "NUTRITION_DATASET_HEALTH", health), \
                patch.object(self.app_module, "TFDA_DB", {"test food": food}), \
                patch.object(self.app_module, "get_gemini_api_keys", return_value=["test-key"]), \
                patch.object(self.app_module, "call_gemini_food_recognition_with_rotation", return_value={"items": [
                    {"name_zh": "test food", "confidence": 0.99, "estimated_weight_g": 100},
                    {"name_zh": "unmapped food", "confidence": 0.99, "estimated_weight_g": 100},
                ]}), patch("requests.post", side_effect=AssertionError("Unexpected network call")):
            response = self.client.post("/predict/vision-food", json={"image": image, "user_id": "user-a"},
                                        headers=self.auth_headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["summary"]["total_items"], 1)
        self.assertEqual(body["summary"]["total_calories"], 120)
        self.assertEqual(len(body["rejected_detections"]), 1)
        self.assertFalse(body["summary"]["nutrition_complete"])
        self.assertEqual(body["nutrition_dataset_health"], health)
        self.assertFalse(body["automatic_web_fallback_enabled"])


if __name__ == "__main__":
    unittest.main()
