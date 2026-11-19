import unittest

from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from services.nutrition_enrichment_route_service import (
    NutritionEnrichmentRouteError,
    process_enrichment_request,
)
from services.nutrition_profile_service import profile_from_local_food
from services.nutrition_scan_context_adapter import (
    build_scan_context_items,
    persist_vision_scan_context,
)
from services.vision_food_service import build_vision_food_response


class _VisionStorage:
    def get_user(self, _user_id):
        return None

    def get_custom_foods(self, _user_id):
        return []


class _SourceRepository:
    def get_source_policy(self, source_id, *, revision=None):
        return {"source_id": source_id, "revision": revision, "status": "active"}

    def get_profile_for_user(self, user_id, profile_id, *, revision=None):
        return None


def _profile(name):
    return profile_from_local_food({
        "name_zh": name,
        "unit": "per 100g",
        "calories": 140,
        "protein": 5,
        "fat": 3,
        "carbs": 20,
        "sodium": 80,
        "fiber": 2,
        "sugar": 1,
        "saturated_fat": 0.5,
        "trans_fat": 0,
    })


class ScannerToEnrichmentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1000.0]
        self.scan = NutritionScanContextRepository(clock=lambda: self.clock[0])
        self.requests = NutritionEnrichmentRequestRepository(clock=lambda: self.clock[0])
        self.quota = NutritionQuotaRepository(
            per_user_limit=2, global_limit=2, clock=lambda: self.clock[0])
        self.source = _SourceRepository()

        # This is the shape returned by the real vision response builder.  It
        # deliberately includes presentation-only fields that must not enter
        # the authority snapshot.
        self.vision_response = build_vision_food_response(
            {
                "items": [
                    {
                        "name_zh": "糯米腸", "name_en": "sticky rice sausage",
                        "confidence": 0.93, "weight_confidence": 0.82,
                        "estimated_weight_g": 120, "food_state": "prepared",
                        "preparation_method": "steamed", "components_scope": "food_only",
                        "count": 2, "portion_description": "兩段",
                        "visual_evidence": "可見糯米腸切段", "alternatives": ["糯米腸"],
                    },
                    {
                        "name_zh": "青菜", "name_en": "leafy greens",
                        "confidence": 0.88, "weight_confidence": 0.7,
                        "estimated_weight_g": 60, "food_state": "prepared",
                        "preparation_method": "stir_fried", "components_scope": "food_only",
                        "count": 1, "portion_description": "一小碟",
                        "visual_evidence": "綠色葉菜", "alternatives": [],
                    },
                ]
            },
            _VisionStorage(), {}, {}, {"groups": []}, [], [], "u1",
            lambda food, *_args: food,
        )

    def _body(self, items, **overrides):
        body = {
            "user_id": "u1", "scan_id": self.vision_response["scan_id"],
            "scan_revision": self.vision_response["scan_revision"],
            "items": items, "idempotency_key": "scanner-route-1",
            "source_policy_id": "source-1", "source_policy_revision": 0,
        }
        body.update(overrides)
        return body

    def _run(self, body):
        profiles = {
            item["item_id"]: _profile(item["name_zh"])
            for item in build_scan_context_items(self.vision_response)
        }
        return process_enrichment_request(
            body, authenticated_user_id="u1", scan_context_repository=self.scan,
            profile_repository=self.source, request_repository=self.requests,
            quota_repository=self.quota, cache_repository=None,
            local_lookup=lambda item: {
                "status": "matched", "nutrition_profile": profiles[item["item_id"]]},
            feature_enabled=False,
        )

    def test_scanner_response_is_narrowed_and_route_accepts_complete_set(self):
        saved = persist_vision_scan_context(
            self.vision_response, user_id="u1", repository=self.scan, ttl_seconds=120)
        self.assertEqual(saved["scan_id"], self.vision_response["scan_id"])
        items = build_scan_context_items(self.vision_response)
        self.assertEqual(saved["items"], items)
        self.assertEqual(
            set(items[0]),
            {
                "item_id", "item_revision", "name_zh", "confidence", "weight_confidence",
                "estimated_weight_g", "food_state", "preparation_method", "components_scope",
                "brand", "variant", "validation_issues", "identity_confirmation_required",
            },
        )
        self.assertNotIn("name_en", items[0])
        self.assertNotIn("count", items[0])
        result = self._run(self._body(items))
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["local_only"])
        self.assertEqual(
            [item["item_id"] for item in result["result"]["items"]],
            [item["item_id"] for item in items],
        )

    def test_route_rejects_incomplete_scanner_item_set_before_local_or_provider(self):
        persist_vision_scan_context(
            self.vision_response, user_id="u1", repository=self.scan, ttl_seconds=120)
        items = build_scan_context_items(self.vision_response)
        calls = []

        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(self._body(items[:1]))
        self.assertEqual(raised.exception.code, "item_set_mismatch")
        self.assertEqual(calls, [])

    def test_scanner_retry_is_idempotent_for_the_same_revision_and_item_set(self):
        first = persist_vision_scan_context(
            self.vision_response, user_id="u1", repository=self.scan, ttl_seconds=120)
        retry = persist_vision_scan_context(
            self.vision_response, user_id="u1", repository=self.scan, ttl_seconds=120)
        self.assertEqual(retry["item_set_hash"], first["item_set_hash"])
        self.assertEqual(retry["items"], first["items"])


if __name__ == "__main__":
    unittest.main()
