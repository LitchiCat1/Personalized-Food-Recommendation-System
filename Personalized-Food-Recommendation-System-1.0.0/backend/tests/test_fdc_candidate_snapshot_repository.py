import os
import tempfile
import unittest
from unittest.mock import patch

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository, FdcCandidateSnapshotRepositoryError
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fooddata_central_selection_service import build_fdc_candidate_snapshot


ITEM = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "糯米腸",
    "confidence": 0.92, "weight_confidence": 0.8, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "steamed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}
CANDIDATES = [{
    "fdcId": "12345", "description": "Glutinous rice sausage", "dataType": "Foundation",
    "brandOwner": None, "foodCategory": "Prepared foods",
}]


class FdcCandidateSnapshotRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.repo = FdcCandidateSnapshotRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120)
        self.snapshot = build_fdc_candidate_snapshot([ITEM], {ITEM["item_id"]: CANDIDATES}, scan_revision=0)

    def tearDown(self):
        self.sql.close()

    def test_persists_only_against_server_owned_scan_and_replays_idempotently(self):
        saved = self.repo.save_candidates(user_id="u1", scan_id="scan-1",
                                          scan_revision=0,
                                          candidates_by_item={ITEM["item_id"]: CANDIDATES})
        loaded = self.repo.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0,
                                        snapshot_digest=self.snapshot["snapshot_digest"])
        self.assertEqual(loaded["snapshot"], self.snapshot)
        replay = self.repo.save_candidates(user_id="u1", scan_id="scan-1",
                                           scan_revision=0,
                                           candidates_by_item={ITEM["item_id"]: CANDIDATES})
        self.assertEqual(replay["snapshot_digest"], saved["snapshot_digest"])

    def test_candidate_mapping_drift_cannot_replace_snapshot_for_same_revision(self):
        self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                  candidates_by_item={ITEM["item_id"]: CANDIDATES})
        changed_candidates = [{**CANDIDATES[0], "description": "Unrelated food"}]
        with self.assertRaises(FdcCandidateSnapshotRepositoryError) as error:
            self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                      candidates_by_item={ITEM["item_id"]: changed_candidates})
        self.assertEqual(error.exception.code, "snapshot_conflict")

    def test_empty_snapshot_without_search_evidence_does_not_qualify(self):
        item_id = ITEM["item_id"]
        scope = {"user_id": "u1", "scan_id": "scan-1", "scan_revision": 0}
        self.repo.save_candidates(**scope, candidates_by_item={item_id: []})
        self.assertFalse(self.repo.has_confirmed_search_miss(**scope, item_id=item_id))

    def test_search_miss_is_bound_to_user_scan_revision_item_and_expiry(self):
        item_id = ITEM["item_id"]
        scope = {"user_id": "u1", "scan_id": "scan-1", "scan_revision": 0}
        self.repo.save_candidates(
            **scope, candidates_by_item={item_id: []}, no_hit_item_ids=[item_id])
        reference = {**scope, "item_id": item_id}
        self.assertTrue(self.repo.has_confirmed_search_miss(**reference))
        for overrides in ({"user_id": "u2"}, {"scan_id": "scan-2"}, {"scan_revision": 1},
                          {"item_id": "scan-1:1"}):
            with self.subTest(overrides=overrides):
                self.assertFalse(self.repo.has_confirmed_search_miss(**{**reference, **overrides}))
        self.now[0] += 120
        self.assertFalse(self.repo.has_confirmed_search_miss(**reference))

    def test_wrong_user_revision_and_digest_are_rejected(self):
        self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                  candidates_by_item={ITEM["item_id"]: CANDIDATES})
        with self.assertRaises(FdcCandidateSnapshotRepositoryError) as wrong:
            self.repo.get_snapshot(user_id="u2", scan_id="scan-1", scan_revision=0)
        self.assertEqual(wrong.exception.code, "wrong_user")
        with self.assertRaises(FdcCandidateSnapshotRepositoryError) as digest:
            self.repo.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0,
                                   snapshot_digest="0" * 64)
        self.assertEqual(digest.exception.code, "snapshot_mismatch")
        with self.assertRaises(FdcCandidateSnapshotRepositoryError) as revision:
            self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=1,
                                      candidates_by_item={ITEM["item_id"]: CANDIDATES})
        self.assertEqual(revision.exception.code, "scan_unavailable")

    def test_new_scan_revision_invalidates_old_snapshot(self):
        self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                  candidates_by_item={ITEM["item_id"]: CANDIDATES})
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=1,
                                    items=[{**ITEM, "item_revision": 1, "name_zh": "新名稱"}],
                                    ttl_seconds=120)
        self.assertIsNone(self.repo.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0))
        stale = self.repo.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0,
                                       include_inactive=True)
        self.assertEqual(stale["status"], "superseded")

    def test_search_reservation_reclaims_expired_lease_and_rejects_stale_owner(self):
        first = self.repo.reserve_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="worker-a", lease_seconds=10,
        )
        follower = self.repo.reserve_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="worker-b", lease_seconds=10,
        )
        self.assertTrue(first["owner"])
        self.assertFalse(follower["owner"])

        self.now[0] += 11
        reclaimed = self.repo.reserve_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="worker-b", lease_seconds=10,
        )
        self.assertTrue(reclaimed["owner"])
        self.assertFalse(self.repo.release_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="worker-a",
        ))
        with self.assertRaises(FdcCandidateSnapshotRepositoryError) as stale:
            self.repo.save_candidates(
                user_id="u1", scan_id="scan-1", scan_revision=0,
                candidates_by_item={ITEM["item_id"]: CANDIDATES},
                reservation_owner="worker-a",
            )
        self.assertEqual(stale.exception.code, "reservation_lost")

        saved = self.repo.save_candidates(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: CANDIDATES},
            reservation_owner="worker-b",
        )
        self.assertEqual(saved["snapshot_digest"], self.snapshot["snapshot_digest"])
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_search_reservations"
        )["count"], 0)

    def test_failed_reservation_can_be_released_and_retried(self):
        first = self.repo.reserve_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="failed-worker", lease_seconds=10,
        )
        self.assertTrue(first["owner"])
        self.assertTrue(self.repo.fail_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="failed-worker", error_code="upstream_error",
        ))
        failure = self.repo.get_search_reservation(
            user_id="u1", scan_id="scan-1", scan_revision=0)
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["error_code"], "upstream_error")
        retry = self.repo.reserve_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="retry-worker", lease_seconds=10,
        )
        self.assertTrue(retry["owner"])
        self.assertEqual(retry["lease_owner"], "retry-worker")
        self.assertTrue(self.repo.release_search(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            lease_owner="retry-worker",
        ))

    def test_snapshot_and_reservation_completion_roll_back_together(self):
        self.repo.reserve_search(user_id="u1", scan_id="scan-1", scan_revision=0,
                                 lease_owner="worker-a")
        with patch.object(self.repo, "_finish_search_reservation",
                          side_effect=RuntimeError("fake commit failure")):
            with self.assertRaisesRegex(RuntimeError, "fake commit failure"):
                self.repo.save_candidates(
                    user_id="u1", scan_id="scan-1", scan_revision=0,
                    candidates_by_item={ITEM["item_id"]: []},
                    reservation_owner="worker-a",
                    no_hit_item_ids=[ITEM["item_id"]],
                )
        self.assertIsNone(self.repo.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0))
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS count FROM nutrition_fdc_search_no_hits")["count"], 0)
        reservation = self.repo.get_search_reservation(user_id="u1", scan_id="scan-1", scan_revision=0)
        self.assertEqual(reservation["status"], "pending")
        self.assertEqual(reservation["lease_owner"], "worker-a")

    def test_transaction_rechecks_do_not_acquire_scan_repository_python_lock(self):
        original_get = self.scan.get_scan_context

        def get_before_transaction(**kwargs):
            self.assertFalse(self.sql._conn.in_transaction,
                             "SQL writer transaction must not acquire the scan Python lock")
            return original_get(**kwargs)

        with patch.object(self.scan, "get_scan_context", side_effect=get_before_transaction), \
                patch.object(self.repo, "_lock") as snapshot_lock:
            snapshot_lock.__enter__.side_effect = AssertionError("durable path acquired snapshot lock")
            self.repo.reserve_search(user_id="u1", scan_id="scan-1", scan_revision=0,
                                     lease_owner="worker-a")
            self.repo.save_candidates(
                user_id="u1", scan_id="scan-1", scan_revision=0,
                candidates_by_item={ITEM["item_id"]: CANDIDATES}, reservation_owner="worker-a")
            with self.sql.transaction():
                self.assertIsNotNone(self.repo.get_snapshot(
                    user_id="u1", scan_id="scan-1", scan_revision=0))

    def test_snapshot_committed_before_reserve_does_not_create_another_lease(self):
        self.repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                  candidates_by_item={ITEM["item_id"]: CANDIDATES})
        replay = self.repo.reserve_search(user_id="u1", scan_id="scan-1", scan_revision=0,
                                          lease_owner="late-worker")
        self.assertFalse(replay["owner"])
        self.assertIsNone(replay["lease_owner"])
        self.assertIsNone(self.repo.get_search_reservation(user_id="u1", scan_id="scan-1", scan_revision=0))

    def test_wrong_owner_cannot_join_or_read_search_reservation(self):
        self.repo.reserve_search(user_id="u1", scan_id="scan-1", scan_revision=0,
                                 lease_owner="worker-a")
        for operation in (
                lambda: self.repo.reserve_search(user_id="u2", scan_id="scan-1", scan_revision=0,
                                                  lease_owner="worker-b"),
                lambda: self.repo.get_search_reservation(user_id="u2", scan_id="scan-1", scan_revision=0)):
            with self.assertRaises(FdcCandidateSnapshotRepositoryError) as wrong:
                operation()
            self.assertEqual(wrong.exception.code, "wrong_user")

    def test_expiry_and_restart_are_durable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "fdc.db")
            first_sql = SqliteDatabase(path)
            scan = NutritionScanContextRepository(first_sql, clock=lambda: self.now[0])
            repo = FdcCandidateSnapshotRepository(first_sql, scan_context_repository=scan,
                                                  clock=lambda: self.now[0])
            scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                   items=[ITEM], ttl_seconds=10)
            repo.save_candidates(user_id="u1", scan_id="scan-1", scan_revision=0,
                                 candidates_by_item={ITEM["item_id"]: CANDIDATES})
            first_sql.close()
            second_sql = SqliteDatabase(path)
            try:
                second_scan = NutritionScanContextRepository(second_sql, clock=lambda: self.now[0])
                second = FdcCandidateSnapshotRepository(second_sql, scan_context_repository=second_scan,
                                                        clock=lambda: self.now[0])
                self.assertEqual(second.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0)["snapshot"],
                                 self.snapshot)
                self.now[0] = 1010
                self.assertIsNone(second.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0))
                expired = second.get_snapshot(user_id="u1", scan_id="scan-1", scan_revision=0,
                                              include_inactive=True)
                self.assertEqual(expired["status"], "expired")
            finally:
                second_sql.close()


if __name__ == "__main__":
    unittest.main()
