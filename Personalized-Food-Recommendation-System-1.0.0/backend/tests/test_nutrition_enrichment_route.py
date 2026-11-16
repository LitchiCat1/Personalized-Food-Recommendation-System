import unittest

from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from services.nutrition_authority_service import NutritionAuthorityService
from services.nutrition_enrichment_route_service import (
    NutritionEnrichmentRouteError,
    process_enrichment_request,
)
from services.nutrition_profile_service import calculate_portion, profile_from_local_food


ITEM = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "不存在的食材",
    "confidence": 0.94, "weight_confidence": 0.8, "estimated_weight_g": 100,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}


class SourceStub:
    def get_source_policy(self, source_id, *, revision=None):
        return {"source_id": source_id, "revision": revision, "status": "active"}

    def get_profile_for_user(self, user_id, profile_id, *, revision=None):
        return None


def _provider_item(item, *, profile=None, status="accepted", origin="web"):
    profile = profile or profile_from_local_food({
        "unit": "per 100g", "calories": 120, "protein": 5, "fat": 3,
        "carbs": 15, "sodium": 50, "fiber": 1, "sugar": 2,
        "saturated_fat": 1, "trans_fat": 0,
    })
    return {
        "item_id": item["item_id"], "item_revision": item["item_revision"],
        "original_visual_name": item["name_zh"], "status": status, "origin": origin,
        "recognition_context": {
            "name_zh": item["name_zh"],
            "estimated_weight_g": item.get("estimated_weight_g"),
        },
        "nutrition_profile": profile,
        "portion": calculate_portion(profile, item.get("estimated_weight_g"),
                                      portion_source="vision_estimate"),
    }


class NutritionEnrichmentRouteTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1000.0]
        self.scan = NutritionScanContextRepository(clock=lambda: self.clock[0])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120, issued_at=self.clock[0])
        for index in (2, 3):
            variant = dict(ITEM, item_id=f"scan-{index}:0", name_zh=f"不存在的食材{index}")
            self.scan.save_scan_context(user_id="u1", scan_id=f"scan-{index}", scan_revision=0,
                                        items=[variant], ttl_seconds=120, issued_at=self.clock[0])
        low_confidence = dict(ITEM, item_id="scan-low:0", confidence=0.4)
        self.scan.save_scan_context(user_id="u1", scan_id="scan-low", scan_revision=0,
                                    items=[low_confidence], ttl_seconds=120, issued_at=self.clock[0])
        flagged = dict(ITEM, item_id="scan-flagged:0", validation_issues=["ambiguous_name"])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-flagged", scan_revision=0,
                                    items=[flagged], ttl_seconds=120, issued_at=self.clock[0])
        self.requests = NutritionEnrichmentRequestRepository(clock=lambda: self.clock[0])
        self.quota = NutritionQuotaRepository(per_user_limit=2, global_limit=2,
                                              clock=lambda: self.clock[0])
        self.source = SourceStub()
        self.authority = NutritionAuthorityService(
            {"current": b"a" * 32}, active_kid="current", clock=lambda: self.clock[0])

    def _body(self, **overrides):
        body = {
            "user_id": "u1", "scan_id": "scan-1", "scan_revision": 0,
            "items": [ITEM], "idempotency_key": "route-test-1",
            "source_policy_id": "source-1", "source_policy_revision": 0,
        }
        body.update(overrides)
        return body

    def _run(self, body=None, *, local=None, provider_factory=None, enabled=True,
             authority_service=None, cache=None):
        return process_enrichment_request(
            body or self._body(), authenticated_user_id="u1",
            scan_context_repository=self.scan, profile_repository=self.source,
            request_repository=self.requests, quota_repository=self.quota,
            cache_repository=cache, local_lookup=local or (lambda item: {"status": "no_local_mapping"}),
            provider_factory=provider_factory, feature_enabled=enabled,
            authority_service=authority_service,
        )

    def test_item_set_mismatch_is_rejected_before_provider(self):
        changed = dict(ITEM, name_zh="改過的食材")
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(self._body(items=[changed]), provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(raised.exception.code, "item_set_mismatch")

    def test_expired_scan_is_rejected(self):
        self.clock[0] = 1120
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(raised.exception.code, "scan_unavailable")

    def test_revoked_and_superseded_scans_are_rejected(self):
        self.scan.revoke_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0)
        with self.assertRaises(NutritionEnrichmentRouteError) as revoked:
            self._run(provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(revoked.exception.code, "scan_unavailable")

        item_v2 = dict(ITEM, item_revision=1, name_zh="不存在的食材新版")
        self.scan.save_scan_context(user_id="u1", scan_id="scan-4", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120, issued_at=self.clock[0])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-4", scan_revision=1,
                                    items=[item_v2], ttl_seconds=120, issued_at=self.clock[0])
        with self.assertRaises(NutritionEnrichmentRouteError) as stale:
            self._run(self._body(scan_id="scan-4"), provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(stale.exception.code, "scan_unavailable")

    def test_local_match_never_enters_provider_or_quota(self):
        profile = profile_from_local_food({
            "unit": "per 100g", "calories": 100, "protein": 5, "fat": 2,
            "carbs": 10, "sodium": 50, "fiber": 1, "sugar": 1,
            "saturated_fat": 0.5, "trans_fat": 0,
        })
        output = self._run(local=lambda item: {"status": "matched", "nutrition_profile": profile},
                           provider_factory=lambda *_: self.fail("provider called"), enabled=False)
        self.assertEqual(output["status"], "complete")
        self.assertTrue(output["local_only"])
        self.assertEqual(self.quota.quota_snapshot("u1")["user_reserved"], 0)

    def test_missing_local_data_uses_provider_once_and_replays(self):
        calls = []

        def provider_factory(missing, known):
            def provider(payload):
                calls.append(payload)
                return {"status": "complete", "result": {"items": [_provider_item(payload["items"][0])]}}
            return provider

        first = self._run(provider_factory=provider_factory)
        second = self._run(provider_factory=provider_factory)
        self.assertEqual(first["status"], "complete")
        self.assertTrue(second["replayed"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_complete_web_profile_is_written_to_positive_cache_after_durable_result(self):
        profile = profile_from_local_food({
            "unit": "per 100g", "calories": 200, "protein": 6, "carbs": 30,
            "fat": 6, "sodium": 300, "fiber": 2, "sugar": 1,
            "saturated_fat": 2, "trans_fat": 0,
        }, source_details={
            "source_id": "source-1", "source_url": "https://example.com/source-1",
            "content_hash": "a" * 64, "retrieved_at": "2026-11-14T00:00:00Z",
            "adapter_version": "fixture-v1", "retrieval_version": "fixture-v1",
        })
        writes = []

        class Cache:
            def get(self, **kwargs):
                return None

            def put_success(self, **kwargs):
                writes.append(kwargs)

        def factory(missing, known):
            def provider(payload):
                return {"status": "complete", "result": {"items": [{
                    **_provider_item(ITEM, profile=profile),
                }]}}
            return provider

        output = process_enrichment_request(
            self._body(), authenticated_user_id="u1", scan_context_repository=self.scan,
            profile_repository=self.source, request_repository=self.requests,
            quota_repository=self.quota, cache_repository=Cache(),
            local_lookup=lambda item: {"status": "no_local_mapping"},
            provider_factory=factory, feature_enabled=True,
        )
        self.assertEqual(output["status"], "complete")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["food_identity"]["name"], ITEM["name_zh"])
        self.assertEqual(writes[0]["source_id"], "source-1")

    def test_policy_id_alias_is_resolved_before_cache_lookup(self):
        class SourceAlias(SourceStub):
            def resolve_source_policy_reference(self, reference, *, revision=None):
                if reference not in {"source-1", "policy-1"}:
                    return None
                return {"source_id": "source-1", "policy_id": "policy-1",
                        "revision": revision, "status": "active"}

        looked_up = []

        class Cache:
            def get(self, **kwargs):
                looked_up.append(kwargs)
                return None

        def factory(_missing, _known):
            return lambda payload: {"status": "complete", "result": {
                "items": [_provider_item(payload["items"][0])]}}

        output = process_enrichment_request(
            self._body(source_policy_id="policy-1", idempotency_key="policy-alias"),
            authenticated_user_id="u1", scan_context_repository=self.scan,
            profile_repository=SourceAlias(), request_repository=self.requests,
            quota_repository=self.quota, cache_repository=Cache(),
            local_lookup=lambda item: {"status": "no_local_mapping"},
            provider_factory=factory, feature_enabled=True,
        )
        self.assertEqual(output["status"], "complete")
        self.assertEqual(looked_up[0]["source_id"], "source-1")

    def test_mixed_local_and_web_items_rebuild_complete_coverage(self):
        item2 = dict(ITEM, item_id="scan-mixed:1", name_zh="第二個測試食材")
        self.scan.save_scan_context(
            user_id="u1", scan_id="scan-mixed", scan_revision=0,
            items=[ITEM, item2], ttl_seconds=120, issued_at=self.clock[0])
        local_profile = profile_from_local_food({
            "unit": "per 100g", "calories": 100, "protein": 5, "fat": 2,
            "carbs": 10, "sodium": 50, "fiber": 1, "sugar": 1,
            "saturated_fat": 0.5, "trans_fat": 0,
        })
        web_profile = profile_from_local_food({
            "unit": "per 100g", "calories": 200, "protein": 6, "fat": 6,
            "carbs": 30, "sodium": 300, "fiber": 2, "sugar": 1,
            "saturated_fat": 2, "trans_fat": 0,
        })

        def factory(_missing, _known):
            web_item = {
                "item_id": item2["item_id"], "item_revision": item2["item_revision"],
                "original_visual_name": item2["name_zh"], "status": "accepted", "origin": "web",
                "recognition_context": {"name_zh": item2["name_zh"],
                                        "estimated_weight_g": item2["estimated_weight_g"]},
                "nutrition_profile": web_profile,
                "portion": calculate_portion(web_profile, item2["estimated_weight_g"],
                                              portion_source="vision_estimate"),
            }
            return lambda _payload: {"status": "complete", "result": {"items": [web_item]}}

        output = self._run(
            self._body(scan_id="scan-mixed", items=[ITEM, item2], idempotency_key="mixed-coverage"),
            local=lambda item: {"status": "matched", "nutrition_profile": local_profile}
            if item["item_id"] == ITEM["item_id"] else {"status": "no_local_mapping"},
            provider_factory=factory)
        self.assertEqual(output["status"], "complete")
        result = output["result"]
        self.assertEqual(set(result["nutrition_coverage"]["included_item_ids"]),
                         {ITEM["item_id"], item2["item_id"]})
        self.assertEqual(result["nutrition_coverage"]["nutrients"]["calories"]["known_items"], 2)

    def test_malformed_complete_provider_item_is_persisted_as_invalid_output(self):
        def factory(_missing, _known):
            return lambda _payload: {
                "status": "complete",
                "result": {"items": [{"item_id": ITEM["item_id"]}]},
            }

        output = self._run(provider_factory=factory, enabled=True)
        self.assertEqual(output["status"], "invalid_output")
        self.assertIsInstance(output["result"], dict)

    def test_partial_web_profile_is_not_written_to_positive_cache(self):
        profile = profile_from_local_food({
            "unit": "per 100g", "calories": 200, "protein": 6, "carbs": 30,
            "fat": 6, "sodium": None, "fiber": None, "sugar": None,
            "saturated_fat": None, "trans_fat": None,
        }, source_details={
            "source_id": "source-1", "source_url": "https://example.com/source-1",
            "content_hash": "a" * 64, "retrieved_at": "2026-11-14T00:00:00Z",
            "adapter_version": "fixture-v1", "retrieval_version": "fixture-v1",
        })
        writes = []

        class Cache:
            def get(self, **kwargs):
                return None

            def put_success(self, **kwargs):
                writes.append(kwargs)

        def factory(missing, known):
            return lambda payload: {"status": "partial", "result": {"items": [
                _provider_item(ITEM, profile=profile, status="partial")
            ]}}

        output = process_enrichment_request(
            self._body(idempotency_key="partial-cache"), authenticated_user_id="u1",
            scan_context_repository=self.scan, profile_repository=self.source,
            request_repository=self.requests, quota_repository=self.quota,
            cache_repository=Cache(), local_lookup=lambda item: {"status": "no_local_mapping"},
            provider_factory=factory, feature_enabled=True,
        )
        self.assertEqual(output["status"], "partial")
        self.assertFalse(writes)

    def test_feature_disabled_is_fail_closed_after_local_miss(self):
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(enabled=False, provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(raised.exception.code, "feature_disabled")

    def test_low_confidence_item_requires_confirmation_before_web_provider(self):
        item = dict(ITEM, item_id="scan-low:0", confidence=0.4)
        calls = []
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(self._body(scan_id="scan-low", items=[item]),
                      provider_factory=lambda *_: calls.append(True))
        self.assertEqual(raised.exception.code, "confirmation_required")
        self.assertFalse(calls)
        self.assertEqual(self.quota.quota_snapshot("u1")["user_reserved"], 0)

    def test_validation_flag_requires_confirmation_before_web_provider(self):
        item = dict(ITEM, item_id="scan-flagged:0", validation_issues=["ambiguous_name"])
        calls = []
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(self._body(scan_id="scan-flagged", items=[item]),
                      provider_factory=lambda *_: calls.append(True))
        self.assertEqual(raised.exception.code, "confirmation_required")
        self.assertFalse(calls)
        self.assertEqual(self.quota.quota_snapshot("u1")["user_reserved"], 0)

    def test_low_confidence_item_does_not_read_web_cache(self):
        item = dict(ITEM, item_id="scan-low:0", confidence=0.4)

        class Cache:
            def get(self, **kwargs):
                raise AssertionError("web cache must not be read for an unconfirmed item")

        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(self._body(scan_id="scan-low", items=[item]), cache=Cache(),
                      provider_factory=lambda *_: self.fail("provider called"))
        self.assertEqual(raised.exception.code, "confirmation_required")

    def test_generic_name_blocks_cache_provider_and_quota_even_with_high_confidence(self):
        class Cache:
            def get(self, **kwargs):
                raise AssertionError("web cache must not be read for a generic food")

        for index, name in enumerate(("炒菜葉", "葉菜", "清炒綠色葉菜")):
            with self.subTest(name=name):
                scan_id = f"scan-generic-{index}"
                item = dict(ITEM, item_id=scan_id + ":0", name_zh=name, confidence=0.95)
                self.scan.save_scan_context(user_id="u1", scan_id=scan_id, scan_revision=0,
                                            items=[item], ttl_seconds=120, issued_at=self.clock[0])
                with self.assertRaises(NutritionEnrichmentRouteError) as raised:
                    self._run(self._body(scan_id=scan_id, items=[item]), cache=Cache(),
                              provider_factory=lambda *_: self.fail("provider factory called"))
                self.assertEqual(raised.exception.code, "confirmation_required")
                persisted = self.scan.get_scan_context(user_id="u1", scan_id=scan_id, scan_revision=0)
                self.assertEqual(persisted["items"], [item])
                quota = self.quota.quota_snapshot("u1")
                self.assertEqual(quota["user_reserved"], 0)
                self.assertEqual(quota["user_consumed"], 0)

    def test_generic_local_hit_retains_existing_local_authority_boundary(self):
        # This repair gates fallback; it does not redefine curated local mappings.
        item = dict(ITEM, item_id="scan-generic-local:0", name_zh="炒菜葉", confidence=0.95)
        self.scan.save_scan_context(user_id="u1", scan_id="scan-generic-local", scan_revision=0,
                                    items=[item], ttl_seconds=120, issued_at=self.clock[0])
        profile = _provider_item(item)["nutrition_profile"]
        result = self._run(self._body(scan_id="scan-generic-local", items=[item]),
                           local=lambda _: {"status": "matched", "nutrition_profile": profile},
                           provider_factory=lambda *_: self.fail("provider factory called"))
        self.assertTrue(result["local_only"])
        self.assertEqual(result["result"]["items"][0]["origin"], "local")
        self.assertEqual(result["result"]["items"][0]["recognition_context"]["name_zh"], "炒菜葉")

    def test_authority_token_is_consumed_durably_before_provider(self):
        token = self.authority.issue_scan_context(
            user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM])
        calls = []

        def factory(missing, known):
            def provider(payload):
                calls.append(payload)
                return {"status": "complete", "result": {"items": [_provider_item(payload["items"][0])]}}
            return provider

        first = self._run(
            self._body(scan_authority_token=token), provider_factory=factory,
            authority_service=self.authority)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(len(calls), 1)
        replay = self._run(
            self._body(scan_authority_token=token), provider_factory=factory,
            authority_service=self.authority)
        self.assertEqual(replay["status"], "complete")
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(calls), 1)
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(
                self._body(scan_authority_token=token, idempotency_key="authority-replay"),
                provider_factory=factory, authority_service=self.authority)
        self.assertEqual(raised.exception.code, "scan_unavailable")

    def test_authority_token_must_match_server_owned_scan(self):
        token = self.authority.issue_scan_context(
            user_id="u1", scan_id="scan-2", scan_revision=0,
            items=[dict(ITEM, item_id="scan-2:0", name_zh="不存在的食材2")])
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(
                self._body(scan_authority_token=token),
                provider_factory=lambda *_: self.fail("provider called"),
                authority_service=self.authority)
        self.assertEqual(raised.exception.code, "authority_conflict")

    def test_configured_authority_requires_token(self):
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            self._run(provider_factory=lambda *_: self.fail("provider called"),
                      authority_service=self.authority)
        self.assertEqual(raised.exception.code, "invalid_request")

    def test_source_revision_is_checked_before_provider_factory(self):
        class Withdrawn(SourceStub):
            def get_source_policy(self, source_id, *, revision=None):
                return None

        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            process_enrichment_request(
                self._body(), authenticated_user_id="u1", scan_context_repository=self.scan,
                profile_repository=Withdrawn(), request_repository=self.requests,
                quota_repository=self.quota, cache_repository=None,
                local_lookup=lambda item: {"status": "no_local_mapping"},
                provider_factory=lambda *_: self.fail("provider factory called"), feature_enabled=True,
            )
        self.assertEqual(raised.exception.code, "source_unavailable")

    def test_profile_hash_mismatch_is_rejected_before_provider_factory(self):
        class ProfileMismatch(SourceStub):
            def get_profile_for_user(self, user_id, profile_id, *, revision=None):
                return {"profile_hash": "0" * 64, "source_id": "source-1"}

        body = self._body(profiles=[{
            "profile_id": "profile-1", "profile_hash": "1" * 64,
            "source_id": "source-1", "profile_revision": 0,
        }])
        with self.assertRaises(NutritionEnrichmentRouteError) as raised:
            process_enrichment_request(
                body, authenticated_user_id="u1", scan_context_repository=self.scan,
                profile_repository=ProfileMismatch(), request_repository=self.requests,
                quota_repository=self.quota, cache_repository=None,
                local_lookup=lambda item: {"status": "no_local_mapping"},
                provider_factory=lambda *_: self.fail("provider factory called"), feature_enabled=True,
            )
        self.assertEqual(raised.exception.code, "profile_conflict")

    def test_user_quota_is_enforced_by_coordinator(self):
        calls = []

        def factory(missing, known):
            def provider(payload):
                calls.append(payload)
                return {"status": "complete", "result": {"items": [
                    _provider_item(payload["items"][0])
                ]}}
            return provider

        for index in range(2):
            scan_id = "scan-1" if index == 0 else "scan-2"
            item = ITEM if index == 0 else dict(ITEM, item_id="scan-2:0", name_zh="不存在的食材2")
            output = self._run(self._body(scan_id=scan_id, items=[item], idempotency_key=f"quota-{index}"), provider_factory=factory)
            self.assertEqual(output["status"], "complete")
        item = dict(ITEM, item_id="scan-3:0", name_zh="不存在的食材3")
        output = self._run(self._body(scan_id="scan-3", items=[item], idempotency_key="quota-exhausted"), provider_factory=factory)
        self.assertEqual(output["status"], "busy")
        self.assertEqual(output["error"]["code"], "quota_unavailable")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
