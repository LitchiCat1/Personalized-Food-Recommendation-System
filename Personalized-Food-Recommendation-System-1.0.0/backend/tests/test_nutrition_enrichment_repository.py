import unittest

from repositories.sqlite_db import SqliteDatabase
from repositories.nutrition_enrichment_repository import (
    NutritionEnrichmentRequestRepository,
    NutritionEnrichmentRepositoryError,
)


class NutritionEnrichmentRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1_700_000_000.0]
        self.sql = SqliteDatabase(":memory:")
        self.repo = NutritionEnrichmentRequestRepository(
            self.sql, lease_seconds=30, clock=lambda: self.now[0]
        )
        self.payload = {"scan_id": "scan-1", "scan_revision": 2, "items": [{"item_id": "i-1"}]}
        self.fp = "a" * 64

    def test_same_request_replays_durable_result(self):
        first = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload, request_revision=2)
        self.assertTrue(first.owner)
        first.complete("accepted", {"calories": 123})
        replay = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload, request_revision=2)
        self.assertFalse(replay.owner)
        self.assertTrue(replay.replay)
        outcome = replay.wait(0)
        self.assertEqual(outcome.status, "accepted")
        self.assertEqual(outcome.result, {"calories": 123})

    def test_changed_body_or_revision_is_conflict(self):
        lease = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload, request_revision=2)
        with self.assertRaisesRegex(NutritionEnrichmentRepositoryError, "another request"):
            self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                            request={"different": True}, request_revision=2)
        with self.assertRaisesRegex(NutritionEnrichmentRepositoryError, "another request"):
            self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                            request=self.payload, request_revision=3)
        lease.abort()

    def test_fingerprint_is_unique_across_idempotency_keys_and_users(self):
        lease = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload)
        follower = self.repo.begin(user_id="u-1", idempotency_key="k-2", fingerprint=self.fp,
                                   request=self.payload)
        self.assertFalse(follower.owner)
        with self.assertRaisesRegex(NutritionEnrichmentRepositoryError, "another user"):
            self.repo.begin(user_id="u-2", idempotency_key="k-3", fingerprint=self.fp,
                            request=self.payload)
        lease.abort()

    def test_expired_pending_lease_can_be_reclaimed(self):
        first = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload)
        self.now[0] += 31
        second = self.repo.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                 request=self.payload)
        self.assertTrue(second.owner)
        with self.assertRaisesRegex(NutritionEnrichmentRepositoryError, "current lease owner"):
            first.complete("accepted", {})
        second.complete("accepted", {"ok": True})

    def test_retryable_and_not_found_status_can_be_retried(self):
        for index, status in enumerate(("timeout", "not_found")):
            fingerprint = (hex(index + 10)[2:] + "b" * 64)[:64]
            lease = self.repo.begin(user_id="u-1", idempotency_key=f"k-{index}", fingerprint=fingerprint,
                                    request=self.payload)
            lease.complete(status)
            retry = self.repo.begin(user_id="u-1", idempotency_key=f"k-{index}", fingerprint=fingerprint,
                                    request=self.payload)
            self.assertTrue(retry.owner)
            retry.abort()

    def test_restart_reads_result_from_same_sqlite_file(self):
        import tempfile
        import os
        path = tempfile.mktemp(suffix=".db")
        try:
            first_sql = SqliteDatabase(path)
            first = NutritionEnrichmentRequestRepository(first_sql, clock=lambda: self.now[0])
            lease = first.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                request=self.payload)
            lease.complete("accepted", {"persisted": True})
            second_sql = SqliteDatabase(path)
            second = NutritionEnrichmentRequestRepository(second_sql, clock=lambda: self.now[0])
            replay = second.begin(user_id="u-1", idempotency_key="k-1", fingerprint=self.fp,
                                 request=self.payload)
            self.assertEqual(replay.wait(0).result, {"persisted": True})
            first_sql.close()
            second_sql.close()
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_restart_reclaims_expired_pending_lease_and_increments_attempts(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "lease-restart.db")
            first_sql = SqliteDatabase(path)
            first = NutritionEnrichmentRequestRepository(
                first_sql, lease_seconds=30, clock=lambda: self.now[0])
            original = first.begin(user_id="u-1", idempotency_key="lease-restart",
                                   fingerprint=self.fp, request=self.payload,
                                   request_revision=2, lease_owner="old-worker")
            self.assertTrue(original.owner)
            first_sql.close()

            self.now[0] += 31
            second_sql = SqliteDatabase(path)
            try:
                second = NutritionEnrichmentRequestRepository(
                    second_sql, lease_seconds=30, clock=lambda: self.now[0])
                reclaimed = second.begin(user_id="u-1", idempotency_key="lease-restart",
                                         fingerprint=self.fp, request=self.payload,
                                         request_revision=2, lease_owner="new-worker")
                self.assertTrue(reclaimed.owner)
                self.assertEqual(reclaimed.get()["attempts"], 2)
                reclaimed.complete("accepted", {"reclaimed": True})
                self.assertEqual(second.get(reclaimed.request_id)["status"], "accepted")
            finally:
                second_sql.close()

    def test_retryable_result_can_be_retried_after_restart_without_duplicate_request(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "retry-restart.db")
            first_sql = SqliteDatabase(path)
            first = NutritionEnrichmentRequestRepository(
                first_sql, lease_seconds=30, clock=lambda: self.now[0])
            lease = first.begin(user_id="u-1", idempotency_key="retry-restart",
                                fingerprint=self.fp, request=self.payload,
                                request_revision=2)
            lease.complete("timeout", error={"retryable": True})
            request_id = lease.request_id
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second = NutritionEnrichmentRequestRepository(
                    second_sql, lease_seconds=30, clock=lambda: self.now[0])
                retry = second.begin(user_id="u-1", idempotency_key="retry-restart",
                                     fingerprint=self.fp, request=self.payload,
                                     request_revision=2)
                self.assertTrue(retry.owner)
                document = retry.get()
                self.assertEqual(document["request_id"], request_id)
                self.assertEqual(document["attempts"], 2)
                self.assertEqual(document["status"], "pending")
                self.assertIsNone(document["error"])
                retry.complete("accepted", {"retry": "succeeded"})
            finally:
                second_sql.close()

if __name__ == "__main__":
    unittest.main()
