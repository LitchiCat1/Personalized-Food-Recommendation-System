import os
import tempfile
import threading
import os
import tempfile
import unittest

from repositories.nutrition_enrichment_repository import NutritionEnrichmentRequestRepository
from repositories.nutrition_quota_repository import NutritionQuotaRepository
from repositories.sqlite_db import SqliteDatabase
from repositories.scan_context_repository import NutritionScanContextRepository
from services.nutrition_enrichment_coordinator import (
    NutritionEnrichmentCoordinator,
    NutritionEnrichmentCoordinatorError,
)


ITEM = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "糯米腸",
    "confidence": 0.92, "weight_confidence": 0.8, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "roasted",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}


def route_result(item_id, status="complete"):
    """Build the minimal valid route envelope used by coordinator fixtures."""
    return {
        "status": status,
        "result": {
            "schema_version": "NutritionEnrichmentRouteV1",
            "items": [{"item_id": item_id}],
            "nutrition_coverage": {
                "schema_version": "NutritionCoverageV1",
                "nutrients": {},
                "included_item_ids": [item_id],
            },
        },
    }


class TimeoutErrorForTest(RuntimeError):
    code = "timeout"


class RateLimitedErrorForTest(RuntimeError):
    code = "rate_limited"


class NutritionEnrichmentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.scan = NutritionScanContextRepository(clock=lambda: self.now[0])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120, issued_at=self.now[0])
        self.requests = NutritionEnrichmentRequestRepository(clock=lambda: self.now[0], lease_seconds=10)
        self.quota = NutritionQuotaRepository(per_user_limit=3, global_limit=3,
                                              clock=lambda: self.now[0])
        self.calls = []

    def make(self, provider):
        return NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, request_repository=self.requests,
            quota_repository=self.quota, provider=provider, wait_timeout=0)

    def invoke(self, coordinator, key="key-1"):
        return coordinator.run(user_id="u1", scan_id="scan-1", scan_revision=0,
                               items=[ITEM], idempotency_key=key,
                               source_policy_id="web-policy", source_policy_revision=0)

    def test_idempotent_replay_never_calls_provider_twice(self):
        def provider(payload):
            self.calls.append(payload)
            return route_result(ITEM["item_id"])

        coordinator = self.make(provider)
        first = self.invoke(coordinator)
        second = self.invoke(coordinator)
        self.assertEqual(first["status"], "complete")
        self.assertTrue(second["replayed"])
        self.assertEqual(second["result"], first["result"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_policy_id_alias_is_canonicalized_before_authority_and_fingerprint(self):
        class SourceAlias:
            def resolve_source_policy_reference(self, reference, *, revision=None):
                if reference not in {"web-source", "web-policy"}:
                    return None
                return {"source_id": "web-source", "policy_id": "web-policy",
                        "revision": revision, "status": "active"}

        payloads = []
        coordinator = NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, profile_repository=SourceAlias(),
            request_repository=self.requests, quota_repository=self.quota,
            provider=lambda payload: payloads.append(payload) or route_result(ITEM["item_id"]),
            wait_timeout=0)
        output = coordinator.run(
            user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM],
            idempotency_key="policy-alias", source_policy_id="web-source",
            source_policy_revision=0)
        replay = coordinator.run(
            user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM],
            idempotency_key="policy-alias", source_policy_id="web-policy",
            source_policy_revision=0)
        self.assertEqual(output["status"], "complete")
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(payloads), 1)

    def test_retryable_failure_releases_quota_and_uses_new_reservation(self):
        def provider(payload):
            self.calls.append(payload)
            if len(self.calls) == 1:
                raise TimeoutErrorForTest("provider timeout")
            return route_result(ITEM["item_id"], "accepted")

        coordinator = self.make(provider)
        first = self.invoke(coordinator, key="retry")
        second = self.invoke(coordinator, key="retry")
        self.assertEqual(first["status"], "timeout")
        self.assertEqual(second["status"], "accepted")
        self.assertEqual(len(self.calls), 2)
        snapshot = self.quota.quota_snapshot("u1")
        self.assertEqual(snapshot["user_reserved"], 0)
        self.assertEqual(snapshot["user_consumed"], 1)

    def test_complete_route_result_cannot_introduce_unknown_item_id(self):
        coordinator = self.make(lambda payload: route_result("not-part-of-scan"))
        output = self.invoke(coordinator, key="unknown-item")
        self.assertEqual(output["status"], "invalid_output")
        self.assertEqual(self.quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_rate_limited_retry_releases_quota_and_retries_same_request(self):
        def provider(payload):
            self.calls.append(payload)
            if len(self.calls) == 1:
                raise RateLimitedErrorForTest("provider rate limited")
            return route_result(ITEM["item_id"])

        coordinator = self.make(provider)
        first = self.invoke(coordinator, key="rate-limit")
        second = self.invoke(coordinator, key="rate-limit")
        self.assertEqual(first["status"], "rate_limited")
        self.assertEqual(second["status"], "complete")
        self.assertEqual(len(self.calls), 2)
        snapshot = self.quota.quota_snapshot("u1")
        self.assertEqual(snapshot["user_reserved"], 0)
        self.assertEqual(snapshot["user_consumed"], 1)

    def test_single_flight_concurrent_call_waits_for_one_provider(self):
        provider_started = threading.Event()
        release_provider = threading.Event()

        def provider(payload):
            self.calls.append(payload)
            provider_started.set()
            self.assertTrue(release_provider.wait(2), "fake provider was not released")
            return route_result(ITEM["item_id"])

        coordinator = NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, request_repository=self.requests,
            quota_repository=self.quota, provider=provider, wait_timeout=2)
        results = []
        errors = []

        def invoke_in_thread():
            try:
                results.append(self.invoke(coordinator, key="single-flight"))
            except Exception as error:  # pragma: no cover - assertion below reports it
                errors.append(error)

        owner = threading.Thread(target=invoke_in_thread)
        follower = threading.Thread(target=invoke_in_thread)
        owner.start()
        self.assertTrue(provider_started.wait(1), "owner did not enter provider")
        follower.start()
        release_provider.set()
        owner.join(3)
        follower.join(3)

        self.assertFalse(owner.is_alive() or follower.is_alive())
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual({result["status"] for result in results}, {"complete"})
        self.assertEqual(sum(result["replayed"] for result in results), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_retryable_release_is_reconciled_after_release_call_crashes(self):
        class ReleaseFailsAfterCommit(NutritionQuotaRepository):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.failed = False

            def release(self, **kwargs):
                result = super().release(**kwargs)
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("simulated release response loss")
                return result

        quota = ReleaseFailsAfterCommit(per_user_limit=3, global_limit=3,
                                        clock=lambda: self.now[0])
        coordinator = NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, request_repository=self.requests,
            quota_repository=quota,
            provider=lambda payload: self.calls.append(payload) or
            ({"status": "timeout"} if len(self.calls) == 1 else route_result(ITEM["item_id"])),
            wait_timeout=0)
        first = self.invoke(coordinator, key="release-crash")
        second = self.invoke(coordinator, key="release-crash")
        self.assertEqual(first["status"], "timeout")
        self.assertEqual(second["status"], "complete")
        self.assertEqual(len(self.calls), 2)
        snapshot = quota.quota_snapshot("u1")
        self.assertEqual(snapshot["user_reserved"], 0)
        self.assertEqual(snapshot["user_consumed"], 1)

    def test_durable_replay_survives_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nutrition.sqlite3")
            first_db = SqliteDatabase(path)
            first_scan = NutritionScanContextRepository(first_db, clock=lambda: self.now[0])
            first_scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                         items=[ITEM], ttl_seconds=120, issued_at=self.now[0])
            first_requests = NutritionEnrichmentRequestRepository(
                first_db, clock=lambda: self.now[0], lease_seconds=10)
            first_quota = NutritionQuotaRepository(
                first_db, per_user_limit=3, global_limit=3, clock=lambda: self.now[0])
            first_calls = []
            first_coordinator = NutritionEnrichmentCoordinator(
                scan_context_repository=first_scan, request_repository=first_requests,
                quota_repository=first_quota,
                provider=lambda payload: first_calls.append(payload) or
                route_result(ITEM["item_id"]), wait_timeout=0)
            first = self.invoke(first_coordinator, key="restart-replay")
            request_id = first["request_id"]
            first_db.close()

            second_db = SqliteDatabase(path)
            try:
                second_scan = NutritionScanContextRepository(second_db, clock=lambda: self.now[0])
                second_requests = NutritionEnrichmentRequestRepository(
                    second_db, clock=lambda: self.now[0], lease_seconds=10)
                second_quota = NutritionQuotaRepository(
                    second_db, per_user_limit=3, global_limit=3, clock=lambda: self.now[0])
                second_calls = []
                second_coordinator = NutritionEnrichmentCoordinator(
                    scan_context_repository=second_scan, request_repository=second_requests,
                    quota_repository=second_quota,
                    provider=lambda payload: second_calls.append(payload) or
                    route_result(ITEM["item_id"]), wait_timeout=0)
                second = self.invoke(second_coordinator, key="restart-replay")
                self.assertEqual(first["status"], "complete")
                self.assertEqual(second["status"], "complete")
                self.assertTrue(second["replayed"])
                self.assertEqual(second["request_id"], request_id)
                self.assertEqual(first_calls and len(first_calls), 1)
                self.assertEqual(len(second_calls), 0)
                self.assertEqual(second_quota.quota_snapshot("u1")["user_consumed"], 1)
            finally:
                second_db.close()

    def test_budget_exceeded_is_terminal_invalid_output(self):
        class BudgetError(RuntimeError):
            code = "budget_exceeded"

        coordinator = self.make(lambda payload: (_ for _ in ()).throw(BudgetError("too large")))
        output = self.invoke(coordinator, key="budget")
        self.assertEqual(output["status"], "invalid_output")
        self.assertEqual(output["error"]["code"], "budget_exceeded")
        self.assertEqual(self.quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_replay_reconciles_quota_after_result_was_persisted_first(self):
        class CommitFailsOnce(NutritionQuotaRepository):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.failed = False

            def commit(self, **kwargs):
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("simulated finalize crash")
                return super().commit(**kwargs)

        quota = CommitFailsOnce(per_user_limit=3, global_limit=3, clock=lambda: self.now[0])
        calls = []
        coordinator = NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, request_repository=self.requests,
            quota_repository=quota,
            provider=lambda payload: calls.append(payload) or route_result(ITEM["item_id"]),
            wait_timeout=0)
        first = self.invoke(coordinator, key="finalize-crash")
        second = self.invoke(coordinator, key="finalize-crash")
        self.assertEqual(first["status"], "complete")
        self.assertTrue(second["replayed"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(quota.quota_snapshot("u1")["user_consumed"], 1)

    def test_withdrawn_or_expired_scan_is_rejected_before_provider_call(self):
        provider = lambda payload: self.calls.append(payload)
        coordinator = self.make(provider)
        self.now[0] = 1120.0
        output = self.invoke(coordinator, key="expired")
        self.assertEqual(output["status"], "source_conflict")
        self.assertFalse(self.calls)

    def test_source_withdrawal_during_provider_call_is_not_accepted(self):
        class FlappingSource:
            def __init__(self):
                self.reads = 0

            def get_source_policy(self, source_id, *, revision):
                self.reads += 1
                return {"source_id": source_id, "revision": revision} if self.reads == 1 else None

        source = FlappingSource()
        coordinator = NutritionEnrichmentCoordinator(
            scan_context_repository=self.scan, profile_repository=source,
            request_repository=self.requests, quota_repository=self.quota,
            provider=lambda payload: self.calls.append(payload) or route_result(ITEM["item_id"]),
            wait_timeout=0)
        output = self.invoke(coordinator, key="withdrawal-race")
        self.assertEqual(output["status"], "source_conflict")
        self.assertEqual(output["error"]["code"], "source_unavailable")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
