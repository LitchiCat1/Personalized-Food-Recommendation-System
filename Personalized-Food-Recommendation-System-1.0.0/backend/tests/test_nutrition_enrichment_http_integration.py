import base64
import time
import unittest
from unittest.mock import Mock, patch

from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.nutrition_authority_service import NutritionAuthorityService
from services.nutrition_profile_service import calculate_portion, profile_from_local_food

from test_api_routes import ApiTestBase


ITEM = {
    "item_id": "http-scan:0", "item_revision": 0, "name_zh": "網路補全測試食材",
    "confidence": 0.94, "weight_confidence": 0.8, "estimated_weight_g": 100,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}


class _SourceStub:
    def get_source_policy(self, source_id, *, revision=None):
        return {"source_id": source_id, "revision": revision, "status": "active"}

    def get_profile_for_user(self, user_id, profile_id, *, revision=None):
        return None


def _provider_item(item):
    profile = profile_from_local_food({
        "unit": "per 100g", "calories": 120, "protein": 5, "fat": 3,
        "carbs": 15, "sodium": 50, "fiber": 1, "sugar": 2,
        "saturated_fat": 1, "trans_fat": 0,
    })
    return {
        "item_id": item["item_id"], "item_revision": item["item_revision"],
        "original_visual_name": item["name_zh"], "status": "accepted", "origin": "web",
        "recognition_context": {"name_zh": item["name_zh"],
                                "estimated_weight_g": item["estimated_weight_g"]},
        "nutrition_profile": profile,
        "portion": calculate_portion(profile, item["estimated_weight_g"],
                                      portion_source="vision_estimate"),
    }


class NutritionEnrichmentHttpIntegrationTests(ApiTestBase):
    def _body(self, token, *, idempotency_key="http-authority-1"):
        return {
            "user_id": "user-a", "scan_id": "http-scan", "scan_revision": 0,
            "items": [ITEM], "idempotency_key": idempotency_key,
            "source_policy_id": "source-http", "source_policy_revision": 0,
            "scan_authority_token": token,
        }

    def test_authority_is_consumed_once_and_same_request_replays(self):
        clock = time.time()
        scan = NutritionScanContextRepository(clock=lambda: clock)
        requests = NutritionEnrichmentRequestRepository(clock=lambda: clock)
        quota = NutritionQuotaRepository(per_user_limit=2, global_limit=2, clock=lambda: clock)
        authority = NutritionAuthorityService({"active": b"h" * 32}, clock=lambda: clock)
        scan.save_scan_context(
            user_id="user-a", scan_id="http-scan", scan_revision=0,
            items=[ITEM], ttl_seconds=120, issued_at=clock,
        )
        token = authority.issue_scan_context(
            user_id="user-a", scan_id="http-scan", scan_revision=0,
            items=[ITEM], ttl_seconds=120,
        )

        def provider_factory(_missing, _known):
            def provider(_payload):
                return {"status": "complete", "result": {"items": [_provider_item(ITEM)]}}
            return provider

        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_enrichment_repository", requests), \
                patch.object(self.app_module, "nutrition_quota_repository", quota), \
                patch.object(self.app_module, "nutrition_profile_repository", _SourceStub()), \
                patch.object(self.app_module, "nutrition_cache_repository", None), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "nutrition_enrichment_provider_factory", side_effect=provider_factory):
            first = self.client.post(
                "/nutrition/enrichment", json=self._body(token), headers=self.auth_headers())
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.get_json()["status"], "complete")

            replay = self.client.post(
                "/nutrition/enrichment", json=self._body(token), headers=self.auth_headers())
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.get_json()["replayed"])

            rejected = self.client.post(
                "/nutrition/enrichment",
                json=self._body(token, idempotency_key="http-authority-2"),
                headers=self.auth_headers(),
            )
            self.assertEqual(rejected.status_code, 409)
            self.assertEqual(rejected.get_json()["error"]["code"], "scan_unavailable")

    def test_vision_route_returns_authority_token_for_persisted_scan(self):
        now = time.time()
        scan = NutritionScanContextRepository(clock=lambda: now)
        authority = NutritionAuthorityService({"active": b"v" * 32}, clock=lambda: now)
        parsed = {
            "items": [{
                "name_zh": "掃描流程測試食品", "confidence": 0.93,
                "weight_confidence": 0.8, "estimated_weight_g": 100,
                "food_state": "prepared", "preparation_method": "steamed",
                "components_scope": "food_only", "count": 1,
                "portion_description": "一份", "visual_evidence": "可見食品",
            }]
        }
        image = "iVBORw0KGgptb2NrLWltYWdl"

        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "get_gemini_api_keys", return_value=["test-key"]), \
                patch.object(self.app_module, "call_gemini_food_recognition_with_rotation", return_value=parsed):
            response = self.client.post(
                "/predict/vision-food",
                json={"image": image, "user_id": "user-a"},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        context = data["scan_context"]
        self.assertEqual(context["status"], "persisted")
        self.assertTrue(context.get("authority_token"))
        claims, _jti = authority.verify_with_jti(
            context["authority_token"], expected_type="scan_context", user_id="user-a", now=now)
        self.assertEqual(claims["scan_id"], data["scan_id"])
        self.assertEqual(claims["scan_revision"], data["scan_revision"])
        self.assertEqual(claims["items"], context["items"])
        self.assertNotIn("count", claims["items"][0])
        self.assertNotIn("visual_evidence", claims["items"][0])

    def test_vision_scan_persists_items_and_returns_authority_for_enrichment(self):
        clock = time.time()
        scan = NutritionScanContextRepository(clock=lambda: clock)
        authority = NutritionAuthorityService({"active": b"i" * 32}, clock=lambda: clock)
        parsed = {"items": [{
            "name_zh": "網路補全測試食材", "name_en": "test food", "confidence": 0.94,
            "weight_confidence": 0.8, "estimated_weight_g": 100,
            "food_state": "prepared", "preparation_method": "steamed",
            "components_scope": "food_only", "count": 1,
            "portion_description": "一份", "visual_evidence": "可見食品",
            "alternatives": [],
        }]}
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nscan").decode("ascii")
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "get_gemini_api_keys", return_value=["test-key"]), \
                patch.object(self.app_module, "call_gemini_food_recognition_with_rotation", return_value=parsed):
            response = self.client.post(
                "/predict/vision-food",
                json={"image": image, "user_id": "user-a"},
                headers=self.auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        context = response.get_json()["scan_context"]
        self.assertEqual(context["status"], "persisted")
        self.assertEqual(len(context["items"]), 1)
        self.assertNotIn("visual_evidence", context["items"][0])
        claims = authority.verify(
            context["authority_token"], expected_type="scan_context", user_id="user-a")
        self.assertEqual(claims["scan_id"], context["scan_id"])
        self.assertEqual(claims["items"], context["items"])

    def test_low_confidence_http_request_fails_before_authority_or_provider(self):
        clock = time.time()
        low_item = dict(ITEM, item_id="http-low:0", confidence=0.4)
        scan = NutritionScanContextRepository(clock=lambda: clock)
        requests = NutritionEnrichmentRequestRepository(clock=lambda: clock)
        quota = NutritionQuotaRepository(per_user_limit=2, global_limit=2, clock=lambda: clock)
        authority = NutritionAuthorityService({"active": b"l" * 32}, clock=lambda: clock)
        scan.save_scan_context(
            user_id="user-a", scan_id="http-low", scan_revision=0,
            items=[low_item], ttl_seconds=120, issued_at=clock,
        )
        token = authority.issue_scan_context(
            user_id="user-a", scan_id="http-low", scan_revision=0,
            items=[low_item], ttl_seconds=120,
        )
        body = {**self._body(token, idempotency_key="http-low"),
                "scan_id": "http-low", "items": [low_item]}

        class Cache:
            def get(self, **kwargs):
                self.called = True
                raise AssertionError("web cache must not be read")

        cache = Cache()
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_enrichment_repository", requests), \
                patch.object(self.app_module, "nutrition_quota_repository", quota), \
                patch.object(self.app_module, "nutrition_profile_repository", _SourceStub()), \
                patch.object(self.app_module, "nutrition_cache_repository", cache), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "make_local_nutrition_lookup", return_value=lambda item: {"status": "no_local_mapping"}), \
                patch.object(self.app_module, "nutrition_enrichment_provider_factory", side_effect=AssertionError("provider must not be built")):
            response = self.client.post(
                "/nutrition/enrichment", json=body, headers=self.auth_headers())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "confirmation_required")
        self.assertFalse(hasattr(cache, "called"))
        self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 0)
        # The one-time authority remains available because no enrichment was started.
        self.assertEqual(authority.verify(token, expected_type="scan_context", user_id="user-a")["scan_id"], "http-low")

    def test_generic_high_confidence_http_request_preserves_scan_without_cache_or_quota(self):
        clock = time.time()
        sql = SqliteDatabase(":memory:")
        self.addCleanup(sql.close)
        item = dict(ITEM, item_id="http-generic:0", name_zh="炒菜葉", confidence=0.99,
                    preparation_method="stir_fried", estimated_weight_g=70)
        scan = NutritionScanContextRepository(sql, clock=lambda: clock)
        requests = NutritionEnrichmentRequestRepository(sql, clock=lambda: clock)
        quota = NutritionQuotaRepository(sql, per_user_limit=2, global_limit=2, clock=lambda: clock)
        authority = NutritionAuthorityService({"active": b"g" * 32}, clock=lambda: clock)
        scan.save_scan_context(user_id="user-a", scan_id="http-generic", scan_revision=0,
                               items=[item], ttl_seconds=120, issued_at=clock)
        token = authority.issue_scan_context(user_id="user-a", scan_id="http-generic", scan_revision=0,
                                             items=[item], ttl_seconds=120)
        body = {**self._body(token, idempotency_key="http-generic"),
                "scan_id": "http-generic", "items": [item]}
        cache = Mock()
        cache.get.side_effect = AssertionError("generic items must not read web cache")
        provider_factory = Mock(side_effect=AssertionError("provider must not be constructed"))
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_enrichment_repository", requests), \
                patch.object(self.app_module, "nutrition_quota_repository", quota), \
                patch.object(self.app_module, "nutrition_profile_repository", _SourceStub()), \
                patch.object(self.app_module, "nutrition_cache_repository", cache), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "make_local_nutrition_lookup",
                             return_value=lambda _item: {"status": "no_local_mapping"}), \
                patch.object(self.app_module, "nutrition_enrichment_provider_factory", provider_factory):
            response = self.client.post("/nutrition/enrichment", json=body, headers=self.auth_headers())
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["error"]["code"], "confirmation_required")
        cache.get.assert_not_called()
        provider_factory.assert_not_called()
        quota_state = quota.quota_snapshot("user-a")
        self.assertEqual(quota_state["user_reserved"], 0)
        self.assertEqual(quota_state["user_consumed"], 0)
        self.assertIsNone(requests.get_by_idempotency_key(user_id="user-a", idempotency_key="http-generic"))
        persisted = scan.get_scan_context(user_id="user-a", scan_id="http-generic", scan_revision=0)
        self.assertEqual(persisted["status"], "active")
        self.assertEqual(persisted["items"], [item])
        self.assertEqual(sql.query_one("SELECT COUNT(*) AS count FROM nutrition_scan_authority_replays")["count"], 0)


if __name__ == "__main__":
    unittest.main()
