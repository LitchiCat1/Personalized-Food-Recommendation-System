import base64
from copy import deepcopy
from io import BytesIO
import json
import os
import time
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_candidate_search_service import FdcCandidateSearchService
from services.nutrition_authority_service import NutritionAuthorityService
from services.nutrition_profile_service import calculate_portion, profile_from_local_food
from services.tfda_structured_label_service import build_tfda_label_profile, read_tfda_label_export
from services.web_nutrition_service import NutritionSourceRegistry

from test_api_routes import ApiTestBase
from test_tfda_structured_label_service import IDENTITY, label_row
from test_web_nutrition import HEALTH, FakeModel, FakeTavily, fixture as web_fixture


ITEM = {
    "item_id": "http-scan:0", "item_revision": 0, "name_zh": "網路補全測試食材",
    "confidence": 0.94, "weight_confidence": 0.8, "estimated_weight_g": 100,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [], "identity_confirmation_required": False,
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
    def _body(self, token, *, idempotency_key="http-authority-1", item=ITEM):
        return {
            "user_id": "user-a", "scan_id": "http-scan", "scan_revision": 0,
            "items": [item], "idempotency_key": idempotency_key,
            "source_policy_id": "source-http", "source_policy_revision": 0,
            "scan_authority_token": token,
        }

    def test_authority_is_consumed_once_and_same_request_replays(self):
        self._check_search_before_enrichment(confirmed_no_hits=True)

    def test_empty_raw_search_without_zero_hit_evidence_cannot_start_enrichment(self):
        self._check_search_before_enrichment(confirmed_no_hits=False)

    def test_structured_label_is_returned_as_preview_for_the_original_vision_scan(self):
        self._check_search_before_enrichment(confirmed_no_hits=True, structured_label=True)

    def test_sqlite_policy_limits_real_factory_and_blocks_drift_before_cache(self):
        item, policy, document = web_fixture()
        other_policy = deepcopy(policy)
        other_policy["policy_id"] = "other-policy"
        other_policy["source_spec"].update(source_id="other-source", source_url="https://example.org/other")
        other_document = dict(document, url=other_policy["source_spec"]["source_url"])
        registry = NutritionSourceRegistry([other_policy, policy])
        self.assertEqual(len(registry.compatible(item)), 2)
        tavily = FakeTavily([other_document, document])
        tavily.close = Mock()
        model = FakeModel()
        cache = Mock()
        cache.get.return_value = None
        db = SqliteDatabase(":memory:")
        self.addCleanup(db.close)
        profiles = NutritionProfileSourceRepository(db)
        profiles.save_source_policy(other_policy)
        profiles.save_source_policy(policy)
        approved = profiles.save_source_policy(policy, expected_revision=0)
        scan = NutritionScanContextRepository(db)
        scan_ref = {"scan_id": "http-scan", "scan_revision": 0}
        scan.save_scan_context(user_id="user-a", **scan_ref, items=[item], ttl_seconds=120)
        authority = NutritionAuthorityService({"active": b"t" * 32})
        token = authority.issue_scan_context(user_id="user-a", **scan_ref, items=[item], ttl_seconds=120)
        body = dict(self._body(token, item=item), source_policy_id=approved["source_id"],
                    source_policy_revision=approved["revision"])
        quota = NutritionQuotaRepository(db, per_user_limit=2, global_limit=2)
        lookup = lambda _item: {"status": "no_local_mapping"}
        with self.mock_auth("user-a"), \
                patch.dict(os.environ, {"TAVILY_API_KEY": "invalid key"}), \
                patch.object(self.app_module, "PRODUCTION_SOURCE_REGISTRY", registry), \
                patch.object(self.app_module, "NUTRITION_DATASET_HEALTH", HEALTH), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "nutrition_enrichment_repository", NutritionEnrichmentRequestRepository(db)), \
                patch.object(self.app_module, "nutrition_quota_repository", quota), \
                patch.object(self.app_module, "nutrition_profile_repository", profiles), \
                patch.object(self.app_module, "nutrition_cache_repository", cache), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "_require_official_nutrition_miss"), \
                patch.object(self.app_module, "make_local_nutrition_lookup", return_value=lookup), \
                patch.object(self.app_module, "select_nutrition_cells_with_relay", model), \
                patch.object(self.app_module, "TavilyClient", wraps=self.app_module.TavilyClient,
                             return_value=tavily) as client:
            def submit(payload):
                return self.client.post("/nutrition/enrichment", json=payload, headers=self.auth_headers())

            stale = submit(dict(body, source_policy_revision=0))
            self.assertEqual(stale.get_json()["error"]["code"], "revision_conflict")
            cache.get.assert_not_called()
            invalid_key = submit(body)
            self.assertEqual(invalid_key.get_json()["error"]["code"], "provider_unavailable")
            client.assert_not_called()
            self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 0)

            os.environ["TAVILY_API_KEY"] = "offline-test-key"
            response = submit(body)
            self.assertEqual(response.status_code, 200, response.get_json())
            details = response.get_json()["result"]["items"][0]["nutrition_profile"]["source_details"]
            self.assertEqual(details["source_id"], approved["source_id"])
            self.assertEqual(details["policy_id"], approved["policy_id"])
            self.assertEqual(details["source_policy_revision"], approved["revision"])
            self.assertEqual(details["source_url"], document["url"])
            self.assertEqual([list(urls) for _, urls, _ in tavily.searches], [[document["url"]]])
            self.assertEqual([list(urls) for urls, _ in tavily.extracts], [[document["url"]]])
            self.assertEqual(len(model.calls), 1)
            tavily.close.assert_called_once()

            drift = dict(policy, compatibility_review="Changed without registry review")
            newer = profiles.save_source_policy(drift, expected_revision=approved["revision"])
            cache.get.reset_mock()
            rejected = submit(dict(body, source_policy_revision=newer["revision"]))
            self.assertEqual(rejected.get_json()["error"]["code"], "source_conflict")
            profiles.withdraw_source_policy(approved["source_id"], expected_revision=newer["revision"])
            withdrawn = submit(body)
            self.assertEqual(withdrawn.get_json()["error"]["code"], "source_unavailable")
            cache.get.assert_not_called()
            client.assert_called_once()
            self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 1)

    def _check_search_before_enrichment(self, *, confirmed_no_hits, structured_label=False):
        item = ITEM
        clock = time.time()
        db = SqliteDatabase(":memory:")
        self.addCleanup(db.close)
        scan = NutritionScanContextRepository(db, clock=lambda: clock)
        snapshots = FdcCandidateSnapshotRepository(
            db, scan_context_repository=scan, clock=lambda: clock)
        requests = NutritionEnrichmentRequestRepository(db, clock=lambda: clock)
        quota = NutritionQuotaRepository(db, per_user_limit=2, global_limit=2, clock=lambda: clock)
        fdc_client = Mock()
        fdc_client.search_foods.return_value = {"candidates": [], "confirmed_no_hits": confirmed_no_hits}
        official_health = {source: {"status": "available"} for source in ("TFDA", "USDA FNDDS")}
        local_lookup = (self.app_module.make_local_nutrition_lookup(
            self.app_module.storage, self.app_module.TFDA_DB, "user-a",
            self.app_module.build_custom_food_search_result,
        ) if structured_label else Mock(return_value={"status": "no_local_mapping"}))
        fdc_search = FdcCandidateSearchService(
            scan_context_repository=scan, snapshot_repository=snapshots,
            local_lookup_factory=lambda user_id: local_lookup,
            client_factory=lambda: fdc_client, official_health=official_health)
        authority = NutritionAuthorityService({"active": b"h" * 32}, clock=lambda: clock)
        scan_ref = {"scan_id": "http-scan", "scan_revision": 0}
        if not structured_label:
            scan.save_scan_context(
                user_id="user-a", **scan_ref, items=[item], ttl_seconds=120, issued_at=clock,
            )
            token = authority.issue_scan_context(
                user_id="user-a", **scan_ref, items=[item], ttl_seconds=120,
            )

        def provider_factory(_missing, _known, *, resolved_source):
            def provider(payload):
                entry = _provider_item(item)
                if structured_label:
                    self.assertEqual(payload["items"], [item])
                    archive = BytesIO()
                    with ZipFile(archive, "w") as bundle:
                        bundle.writestr("188_5.json", json.dumps([label_row()], ensure_ascii=False))
                    rows = read_tfda_label_export(archive.getvalue())
                    entry.update(status="partial", nutrition_profile=build_tfda_label_profile(rows, **IDENTITY),
                                 portion=calculate_portion(None, None))
                entry["nutrition_profile"]["source_details"].update(
                    source_id=resolved_source["source_id"], source_policy_revision=resolved_source["revision"])
                return {"items": [entry]}
            return provider

        cache = Mock()
        cache.get.return_value = None
        with self.mock_auth("user-a"), \
                patch.object(self.app_module, "nutrition_scan_context_repository", scan), \
                patch.object(self.app_module, "fdc_candidate_snapshot_repository", snapshots), \
                patch.object(self.app_module, "fdc_candidate_route_enabled", True), \
                patch.object(self.app_module, "fdc_candidate_search_service", fdc_search), \
                patch.object(self.app_module, "nutrition_enrichment_repository", requests), \
                patch.object(self.app_module, "nutrition_quota_repository", quota), \
                patch.object(self.app_module, "nutrition_profile_repository", _SourceStub()), \
                patch.object(self.app_module, "nutrition_cache_repository", cache), \
                patch.object(self.app_module, "NUTRITION_DATASET_HEALTH", official_health), \
                patch.object(self.app_module, "make_local_nutrition_lookup", return_value=local_lookup), \
                patch.object(self.app_module, "nutrition_authority_service", authority), \
                patch.object(self.app_module, "nutrition_enrichment_route_enabled", True), \
                patch.object(self.app_module, "PRODUCTION_SOURCE_REGISTRY", Mock()), \
                patch.object(self.app_module, "nutrition_enrichment_provider_factory", side_effect=provider_factory) as factory:
            if structured_label:
                prediction = self._predict_structured_label_fixture()
                context = prediction["scan_context"]
                self.assertEqual(context["status"], "persisted")
                scan_ref = {field: context[field] for field in ("scan_id", "scan_revision")}
                self.assertEqual(scan_ref, {field: prediction[field] for field in scan_ref})
                token = context["authority_token"]
                item, = context["items"]
                self.assertEqual(item["name_zh"], IDENTITY["product_name"])
                self.assertEqual(local_lookup(item)["status"], "no_local_mapping")
            body = {**self._body(token, item=item), **scan_ref}
            pending = self.client.post(
                "/nutrition/enrichment", json=body, headers=self.auth_headers())
            self.assertEqual(pending.status_code, 409)
            self.assertEqual(pending.get_json()["error"]["code"], "official_nutrition_pending")
            cache.get.assert_not_called()
            factory.assert_not_called()
            self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 0)

            official = self.client.post("/nutrition/fdc/candidates",
                                        json=scan_ref,
                                        headers=self.auth_headers())
            self.assertEqual(official.status_code, 200)
            self.assertEqual(official.get_json()["status"], "empty")
            fdc_client.search_foods.assert_called_once()
            if structured_label:
                self.assertEqual(fdc_client.search_foods.call_args.args, (IDENTITY["product_name"],))
                self.assertTrue(snapshots.has_confirmed_search_miss(
                    user_id="user-a", **scan_ref, item_id=item["item_id"]))

            if not confirmed_no_hits:
                blocked = self.client.post(
                    "/nutrition/enrichment", json=body, headers=self.auth_headers())
                self.assertEqual(blocked.status_code, 409)
                self.assertEqual(blocked.get_json()["error"]["code"], "official_nutrition_pending")
                cache.get.assert_not_called()
                factory.assert_not_called()
                self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 0)
                self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM nutrition_scan_authority_replays")["count"], 0)
                return

            with patch.dict(official_health, {"TFDA": {"status": "unavailable"}}):
                unavailable = self.client.post(
                    "/nutrition/enrichment", json=body, headers=self.auth_headers())
                self.assertEqual(unavailable.status_code, 503)
                self.assertEqual(unavailable.get_json()["error"]["code"], "local_unavailable")
                cache.get.assert_not_called()
                factory.assert_not_called()

            with patch.object(self.app_module.fdc_reviewed_selection_service.registry,
                              "compatible", return_value=[object()]):
                pending = self.client.post(
                    "/nutrition/enrichment", json=body, headers=self.auth_headers())
                self.assertEqual(pending.get_json()["error"]["code"], "official_nutrition_pending")
                cache.get.assert_not_called()
                factory.assert_not_called()

            first = self.client.post(
                "/nutrition/enrichment", json=body, headers=self.auth_headers())
            self.assertEqual(first.status_code, 200)
            first_body = first.get_json()
            self.assertEqual(first_body["status"], "partial" if structured_label else "complete")
            if structured_label:
                result = first_body["result"]
                preview = result["items"][0]
                profile = preview["nutrition_profile"]
                details = profile["source_details"]
                self.assertEqual(profile["per_100g"]["calories"], 487.2)
                self.assertEqual(profile["per_100g"]["sodium"], 47)
                self.assertIsNone(profile["per_100g"]["fiber"])
                self.assertEqual(preview["item_id"], item["item_id"])
                for field, expected in IDENTITY.items():
                    self.assertEqual(details["manufacturer_label"][field], expected)
                self.assertEqual(details["source_url"], "https://data.gov.tw/dataset/33575")
                self.assertIsNone(preview["portion"]["weight_g"])
                self.assertEqual(result["nutrition_coverage"]["nutrients"]["calories"]["known_sum"], 0)
                cache.put_success.assert_not_called()

            replay = self.client.post(
                "/nutrition/enrichment", json=body, headers=self.auth_headers())
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.get_json()["replayed"])
            self.assertEqual(replay.get_json()["result"], first_body["result"])
            self.assertEqual(quota.quota_snapshot("user-a")["user_used"], 1)

            rejected = self.client.post(
                "/nutrition/enrichment",
                json={**body, "idempotency_key": "http-authority-2"},
                headers=self.auth_headers(),
            )
            self.assertEqual(rejected.status_code, 409)
            self.assertEqual(rejected.get_json()["error"]["code"], "scan_unavailable")

    def _predict_structured_label_fixture(self):
        parsed = {"items": [{
            "name_zh": IDENTITY["product_name"], "brand": IDENTITY["publisher"],
            "confidence": 0.95, "weight_confidence": 0.35, "estimated_weight_g": 30,
            "food_state": "prepared", "preparation_method": "roasted",
            "components_scope": "food_only", "count": 1,
        }]}
        image = base64.b64encode(b"\x89PNG\r\n\x1a\nscan").decode("ascii")
        with patch.object(self.app_module, "get_gemini_api_keys", return_value=["test-key"]), \
                patch.object(self.app_module, "call_gemini_food_recognition_with_rotation",
                             return_value=parsed) as recognize:
            response = self.client.post(
                "/predict/vision-food", json={"image": image, "user_id": "user-a"},
                headers=self.auth_headers())
        recognize.assert_called_once()
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

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
