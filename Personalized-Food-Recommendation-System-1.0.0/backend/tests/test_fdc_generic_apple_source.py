"""Reviewed matching keeps unknown cultivar distinct from unknown skin state."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.food_identity_service import requires_food_identity_confirmation
from services.nutrition_scan_context_adapter import persist_vision_scan_context
from services.nutrition_source_admission_service import validate_source_admission
from services.vision_food_service import build_vision_food_response, normalize_vision_result
from services.web_nutrition_service import NutritionSourceRegistry
from test_vision_food_contract import Storage
from services.nutrition_label_service import build_custom_food_search_result


CANDIDATES = Path(__file__).resolve().parents[1] / "config" / "nutrition_source_candidates"


class FdcGenericAppleSourceTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.policies = []
        for fdc_id in ("1750340", "171688"):
            candidate = json.loads((CANDIDATES / f"usda-fdc-{fdc_id}.json").read_text(encoding="utf-8"))
            self.policies.append(validate_source_admission(candidate["policy"], candidate["admission_review"]))
        self.registry = NutritionSourceRegistry(self.policies)
        self.item = {"name_zh": "蘋果", "name_en": "apple", "confidence": 0.9,
                     "weight_confidence": 0.65, "estimated_weight_g": 150,
                     "food_state": "raw", "preparation_method": "mixed",
                     "components_scope": "food_only", "brand": None, "variant": "with_skin"}

    def test_unknown_cultivar_matches_only_real_generic_source_without_renaming(self):
        original = deepcopy(self.item)
        self.assertFalse(requires_food_identity_confirmation(self.item["name_zh"]))
        for policies in (self.policies, list(reversed(self.policies))):
            matches = NutritionSourceRegistry(policies).compatible(self.item)
            self.assertEqual([value["source_spec"]["fdc_id"] for value in matches], ["171688"])
            self.assertIn("Food Distribution Program", matches[0]["source_spec"]["food_identity"]["name"])
        self.assertEqual(self.item, original)

    def test_fuji_still_requires_explicit_reviewed_fuji_identity(self):
        fuji = dict(self.item, name_zh="生鮮帶皮富士蘋果", variant="fuji_with_skin")
        self.assertEqual([value["source_spec"]["fdc_id"] for value in self.registry.compatible(fuji)], ["1750340"])
        self.assertEqual(self.registry.compatible(dict(fuji, name_zh="蘋果")), [])

    def test_unknown_skin_peeled_prepared_brand_and_scope_never_become_generic_apple(self):
        for changes in ({"variant": None}, {"variant": "without_skin"},
                        {"name_zh": "去皮蘋果"}, {"name_zh": "蘋果汁"}, {"name_zh": "富士蘋果"},
                        {"food_state": "prepared"}, {"food_state": "unknown"},
                        {"food_state": "dry"}, {"preparation_method": "unknown"},
                        {"preparation_method": "roasted"}, {"brand": "test-brand"},
                        {"components_scope": "with_sides"}, {"components_scope": "unknown"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.registry.compatible(dict(self.item, **changes)), [])

    def test_actual_vision_context_preserves_skin_and_brand_through_sqlite(self):
        sql = SqliteDatabase(":memory:")
        self.addCleanup(sql.close)
        repository = NutritionScanContextRepository(sql, clock=lambda: 1000.0)
        for brand in (None, "visible-label-brand"):
            item = dict(self.item, brand=brand)
            response = build_vision_food_response(
                {"items": [item]}, Storage(), {}, {}, {"groups": []}, [], [], None,
                build_custom_food_search_result)
            saved = persist_vision_scan_context(response, user_id="test-owner", repository=repository)
            scanned = saved["items"][0]
            self.assertEqual(scanned["name_zh"], "蘋果")
            self.assertEqual(scanned["variant"], "with_skin")
            self.assertEqual(scanned["brand"], brand)
            self.assertEqual(scanned["confidence"], self.item["confidence"])
            self.assertEqual(scanned["weight_confidence"], self.item["weight_confidence"])
            self.assertEqual(len(self.registry.compatible(scanned)), 1 if brand is None else 0)

    def test_optional_identity_fields_validate_without_silent_authority(self):
        for field in ("brand", "variant"):
            absent = normalize_vision_result({"items": [dict(self.item, **{field: None})]})["items"][0]
            self.assertIsNone(absent[field])
            for value in (True, [], {}, "", "x" * 301, "with_skin\n"):
                with self.subTest(field=field, value=value):
                    parsed = normalize_vision_result({"items": [dict(self.item, **{field: value})]})
                    normalized = parsed["items"][0]
                    self.assertIsNone(normalized[field])
                    self.assertIn("invalid_" + field, normalized["validation_issues"])
                    self.assertEqual(normalize_vision_result(parsed)["items"][0], normalized)
                    self.assertEqual(normalized["confidence"], self.item["confidence"])


if __name__ == "__main__":
    unittest.main()
