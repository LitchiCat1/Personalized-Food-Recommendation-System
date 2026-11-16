import threading
import time
import unittest

from services.nutrition_enrichment_guard_service import (
    NutritionEnrichmentGuard, NutritionEnrichmentGuardError,
    build_enrichment_request_fingerprint,
)


ITEM = {
    "item_id": "item-1", "item_revision": 0, "name_zh": "烤糯米腸",
    "confidence": 0.9, "weight_confidence": 0.7, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "roasted", "components_scope": "food_only",
    "brand": None, "variant": None, "validation_issues": [],
}
PROFILE = {"profile_id": "profile-1", "profile_hash": "a" * 64,
           "source_id": "usda-fdc-1", "profile_revision": 0}


def fingerprint(*, weight=120, user="user-1", scan_revision=0, policy_revision=1):
    item = dict(ITEM, estimated_weight_g=weight)
    return build_enrichment_request_fingerprint(
        user_id=user, scan_id="scan-1", scan_revision=scan_revision,
        items=[item], profiles=[PROFILE], source_policy_id="policy-1",
        source_policy_revision=policy_revision,
    )


class NutritionEnrichmentGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1_700_000_000]
        self.guard = NutritionEnrichmentGuard(per_user_limit=2, global_limit=2, window_seconds=60,
                                              clock=lambda: self.clock[0])

    def test_fingerprint_normalizes_item_and_profile_order_but_binds_authority_fields(self):
        other = dict(ITEM, item_id="item-2", item_revision=1, name_zh="白飯")
        reversed_a = build_enrichment_request_fingerprint(
            user_id="user-1", scan_id="scan-1", scan_revision=0,
            items=[other, ITEM], profiles=[PROFILE], source_policy_id="policy-1", source_policy_revision=1)
        reversed_b = build_enrichment_request_fingerprint(
            user_id="user-1", scan_id="scan-1", scan_revision=0,
            items=[ITEM, other], profiles=[PROFILE], source_policy_id="policy-1", source_policy_revision=1)
        self.assertEqual(reversed_a, reversed_b)
        self.assertNotEqual(reversed_a, fingerprint(weight=121))
        self.assertNotEqual(reversed_a, fingerprint(user="user-2"))
        self.assertNotEqual(reversed_a, fingerprint(policy_revision=2))

    def test_same_idempotency_key_with_different_fingerprint_is_conflict(self):
        lease = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "another request"):
            self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint(weight=121))
        lease.complete("accepted", {"items": ["item-1"]})

    def test_same_fingerprint_cannot_share_result_across_users(self):
        lease = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "another user"):
            self.guard.begin(user_id="user-2", idempotency_key="request-2", fingerprint=fingerprint())
        lease.abort()

    def test_same_fingerprint_single_flight_deduplicates_concurrent_requests(self):
        first = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        second = self.guard.begin(user_id="user-1", idempotency_key="request-2", fingerprint=fingerprint())
        self.assertTrue(first.owner)
        self.assertFalse(second.owner)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(second.wait(1)))
        thread.start()
        time.sleep(0.01)
        first.complete("accepted", {"calories": 123})
        thread.join(1)
        self.assertEqual(outcome[0].status, "accepted")
        self.assertEqual(outcome[0].result, {"calories": 123})
        replay = self.guard.begin(user_id="user-1", idempotency_key="request-3", fingerprint=fingerprint()).wait(0)
        self.assertEqual(replay.status, "accepted")
        self.assertEqual(replay.result, {"calories": 123})

    def test_timeout_releases_quota_and_allows_retry(self):
        first = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        self.assertEqual(self.guard.quota_snapshot("user-1")["user_used"], 1)
        self.assertEqual(first.complete("timeout").status, "timeout")
        self.assertEqual(self.guard.quota_snapshot("user-1")["user_used"], 0)
        retry = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        self.assertTrue(retry.owner)
        retry.abort()

    def test_not_found_consumes_quota_but_is_not_cached_as_success(self):
        first = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        first.complete("not_found")
        self.assertEqual(self.guard.quota_snapshot("user-1")["user_used"], 1)
        retry = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        self.assertTrue(retry.owner)
        retry.abort()

    def test_per_user_and_global_limits_are_atomic(self):
        first = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        second = self.guard.begin(user_id="user-2", idempotency_key="request-2", fingerprint=fingerprint(user="user-2"))
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "global"):
            self.guard.begin(user_id="user-3", idempotency_key="request-3", fingerprint=fingerprint(user="user-3"))
        first.complete("accepted", {})
        second.abort()
        limited = NutritionEnrichmentGuard(per_user_limit=1, global_limit=3, window_seconds=60,
                                           clock=lambda: self.clock[0])
        held = limited.begin(user_id="user-1", idempotency_key="request-4", fingerprint=fingerprint(weight=121))
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "user"):
            limited.begin(user_id="user-1", idempotency_key="request-5", fingerprint=fingerprint(weight=122))
        held.abort()

    def test_committed_quota_resets_at_window_boundary(self):
        lease = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        lease.complete("accepted", {})
        self.assertEqual(self.guard.quota_snapshot("user-1")["user_used"], 1)
        self.clock[0] += 60
        self.assertEqual(self.guard.quota_snapshot("user-1")["user_used"], 0)

    def test_fingerprint_rejects_sensitive_or_duplicate_input(self):
        with self.assertRaises(NutritionEnrichmentGuardError):
            build_enrichment_request_fingerprint(
                user_id="user-1", scan_id="scan-1", scan_revision=0,
                items=[dict(ITEM, health_conditions=["private"])], profiles=[],
                source_policy_id="policy-1", source_policy_revision=1)
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "unique"):
            build_enrichment_request_fingerprint(
                user_id="user-1", scan_id="scan-1", scan_revision=0,
                items=[ITEM, ITEM], profiles=[], source_policy_id="policy-1", source_policy_revision=1)
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "profile"):
            build_enrichment_request_fingerprint(
                user_id="user-1", scan_id="scan-1", scan_revision=0,
                items=[ITEM], profiles=None, source_policy_id="policy-1", source_policy_revision=1)

    def test_huge_numbers_and_clock_fail_with_typed_errors(self):
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "invalid"):
            build_enrichment_request_fingerprint(
                user_id="user-1", scan_id="scan-1", scan_revision=0,
                items=[dict(ITEM, estimated_weight_g=10 ** 5000)], profiles=[],
                source_policy_id="policy-1", source_policy_revision=1)
        invalid_clock = NutritionEnrichmentGuard(clock=lambda: 10 ** 5000)
        with self.assertRaisesRegex(NutritionEnrichmentGuardError, "clock"):
            invalid_clock.quota_snapshot("user-1")

    def test_old_completed_entries_are_pruned_but_pending_is_retained(self):
        done = self.guard.begin(user_id="user-1", idempotency_key="request-1", fingerprint=fingerprint())
        done.complete("accepted", {"ok": True})
        pending = self.guard.begin(user_id="user-2", idempotency_key="request-2", fingerprint=fingerprint(user="user-2"))
        self.clock[0] += 60
        follower = self.guard.begin(user_id="user-2", idempotency_key="request-3", fingerprint=fingerprint(user="user-2"))
        self.assertFalse(follower.owner)
        self.assertFalse(follower.replay)
        # The pending old entry still joins its original single-flight.
        self.assertTrue(pending.owner)
        pending.abort()
        fresh = self.guard.begin(user_id="user-1", idempotency_key="request-4", fingerprint=fingerprint())
        self.assertTrue(fresh.owner)
        fresh.abort()


if __name__ == "__main__":
    unittest.main()

