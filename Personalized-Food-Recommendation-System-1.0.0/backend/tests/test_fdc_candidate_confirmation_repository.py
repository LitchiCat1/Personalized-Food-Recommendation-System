import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from repositories.fdc_candidate_confirmation_repository import (
    FdcCandidateConfirmationRepository,
    FdcCandidateConfirmationRepositoryError,
)
from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fooddata_central_selection_service import (
    CONFIRMATION_SCHEMA_VERSION,
    build_fdc_candidate_snapshot,
)


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


class FdcCandidateConfirmationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.snapshots = FdcCandidateSnapshotRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.confirmations = FdcCandidateConfirmationRepository(
            self.sql, snapshot_repository=self.snapshots, clock=lambda: self.now[0])
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120)
        self.snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: CANDIDATES})["snapshot"]

    def tearDown(self):
        self.sql.close()

    def _confirmation(self, decision="confirm", candidate_id="12345"):
        return {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "snapshot_digest": self.snapshot["snapshot_digest"],
            "scan_revision": 0,
            "items": [{"item_id": ITEM["item_id"], "decision": decision,
                        "candidate_fdc_id": candidate_id}],
        }

    def test_confirm_persists_actor_and_requires_new_revision_without_confidence_upgrade(self):
        result = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="confirm-1", confirmation=self._confirmation())
        self.assertEqual(result["status"], "confirmed_pending_revision")
        self.assertTrue(result["requires_new_scan_revision"])
        self.assertFalse(result["photo_confidence_changed"])
        self.assertEqual(result["actor_id"], "u1")
        self.assertEqual(result["snapshot_digest"], self.snapshot["snapshot_digest"])
        self.assertEqual(result["issued_scan_revision"], 1)
        self.assertTrue(result["requires_detail_replay"])
        old = self.scan.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                         include_inactive=True)
        new = self.scan.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=1)
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["items"], [ITEM])
        self.assertEqual(new["items"][0]["confidence"], ITEM["confidence"])
        self.assertEqual(result["items"][0]["confirmed_fdc_id"], "12345")

    def test_reject_and_defer_are_durable_but_never_authorize_id(self):
        rejected = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="reject-1", confirmation=self._confirmation("reject", None))
        self.assertEqual(rejected["status"], "rejected")
        self.assertFalse(rejected["requires_new_scan_revision"])
        self.assertIsNone(rejected["items"][0]["confirmed_fdc_id"])

        self.scan.save_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="scan-2", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: CANDIDATES})["snapshot"]
        self.snapshot = snapshot
        deferred = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-2", scan_revision=0,
            idempotency_key="defer-1", confirmation=self._confirmation("defer", None))
        self.assertEqual(deferred["status"], "confirmation_required")
        self.assertFalse(deferred["requires_new_scan_revision"])
        self.assertIsNone(deferred["items"][0]["confirmed_fdc_id"])
        self.assertIsNone(self.scan.get_scan_context(user_id="u1", scan_id="scan-2", scan_revision=1))

    def test_mixed_confirm_and_defer_issues_revision_but_keeps_deferred_item_unresolved(self):
        second_item = {**ITEM, "item_id": "scan-1:1", "name_zh": "青菜"}
        self.scan.save_scan_context(user_id="u1", scan_id="mixed", scan_revision=0,
                                    items=[ITEM, second_item], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="mixed", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: CANDIDATES, second_item["item_id"]: CANDIDATES})["snapshot"]
        confirmation = {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
            "items": [
                {"item_id": ITEM["item_id"], "decision": "confirm", "candidate_fdc_id": "12345"},
                {"item_id": second_item["item_id"], "decision": "defer", "candidate_fdc_id": None},
            ],
        }
        result = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="mixed", scan_revision=0,
            idempotency_key="mixed-key", confirmation=confirmation)
        self.assertEqual(result["issued_scan_revision"], 1)
        by_id = {item["item_id"]: item for item in result["items"]}
        self.assertEqual(by_id[ITEM["item_id"]]["status"], "confirmed_pending_revision")
        self.assertEqual(by_id[second_item["item_id"]]["status"], "confirmation_required")
        self.assertIsNone(by_id[second_item["item_id"]]["confirmed_fdc_id"])
        stored = self.confirmations.get_confirmation(
            authenticated_user_id="u1", confirmation_id=result["confirmation_id"],
            scan_id="mixed", issued_scan_revision=1)
        self.assertEqual([item["item_id"] for item in stored["confirmed_items"]], [ITEM["item_id"]])

    def test_legacy_generic_snapshot_cannot_issue_confirmation_revision(self):
        item = {**ITEM, "name_zh": "炒菜葉"}
        self.scan.save_scan_context(user_id="u1", scan_id="generic", scan_revision=0,
                                    items=[item], ttl_seconds=120)
        document = self.snapshots.save_candidates(
            user_id="u1", scan_id="generic", scan_revision=0,
            candidates_by_item={item["item_id"]: CANDIDATES})
        payload = {**self._confirmation(), "snapshot_digest": document["snapshot_digest"]}
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as error:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="generic", scan_revision=0,
                idempotency_key="generic-blocked", confirmation=payload)
        self.assertEqual(error.exception.code, "confirmation_required")
        self.assertIsNone(self.scan.get_scan_context(
            user_id="u1", scan_id="generic", scan_revision=1))
        self.assertEqual(self.scan.get_scan_context(
            user_id="u1", scan_id="generic", scan_revision=0)["items"], [item])
        self.assertEqual(self.snapshots.get_snapshot(
            user_id="u1", scan_id="generic", scan_revision=0), document)
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_confirmations "
            "WHERE idempotency_key = ?", ("generic-blocked",))["count"], 0)

    def test_already_issued_generic_confirmation_is_evidence_but_not_detail_authority(self):
        item = {**ITEM, "name_zh": "炒菜葉"}
        self.scan.save_scan_context(user_id="u1", scan_id="legacy", scan_revision=0,
                                    items=[item], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="legacy", scan_revision=0,
            candidates_by_item={item["item_id"]: CANDIDATES})["snapshot"]
        payload = {**self._confirmation(), "snapshot_digest": snapshot["snapshot_digest"]}
        # Simulate a persisted confirmation issued before the identity gate.
        with patch("services.fooddata_central_selection_service.requires_food_identity_confirmation",
                   return_value=False):
            issued = self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="legacy", scan_revision=0,
                idempotency_key="legacy-issued", confirmation=payload)
        before = self.sql.query_one(
            "SELECT result_payload FROM nutrition_fdc_candidate_confirmations WHERE confirmation_id = ?",
            (issued["confirmation_id"],))["result_payload"]
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as error:
            self.confirmations.get_confirmation(
                authenticated_user_id="u1", confirmation_id=issued["confirmation_id"],
                scan_id="legacy", issued_scan_revision=1)
        self.assertEqual(error.exception.code, "confirmation_required")
        replay = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="legacy", scan_revision=0,
            idempotency_key="legacy-issued", confirmation=payload)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["confirmation_id"], issued["confirmation_id"])
        self.assertEqual(self.sql.query_one(
            "SELECT result_payload FROM nutrition_fdc_candidate_confirmations WHERE confirmation_id = ?",
            (issued["confirmation_id"],))["result_payload"], before)
        self.assertEqual(self.scan.get_scan_context(
            user_id="u1", scan_id="legacy", scan_revision=1)["items"], [item])

    def test_idempotency_replays_exactly_and_conflicts_on_changed_request(self):
        first = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="same-key", confirmation=self._confirmation())
        replay = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="same-key", confirmation=self._confirmation())
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["confirmation_id"], first["confirmation_id"])
        self.assertEqual(replay["issued_scan_revision"], 1)
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_scan_contexts WHERE scan_id = ?", ("scan-1",)
        )["count"], 2)
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as error:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                idempotency_key="same-key", confirmation=self._confirmation("reject", None))
        self.assertEqual(error.exception.code, "idempotency_conflict")

    def test_confirmation_lookup_is_owner_revision_and_expiry_bound(self):
        result = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="lookup", confirmation=self._confirmation())
        stored = self.confirmations.get_confirmation(
            authenticated_user_id="u1", confirmation_id=result["confirmation_id"],
            scan_id="scan-1", issued_scan_revision=1)
        self.assertEqual(stored["confirmed_items"][0]["confirmed_fdc_id"], "12345")
        self.assertEqual(stored["issued_scan_revision"], 1)
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=2,
                                    items=[ITEM], ttl_seconds=120)
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as stale:
            self.confirmations.get_confirmation(
                authenticated_user_id="u1", confirmation_id=result["confirmation_id"])
        self.assertEqual(stale.exception.code, "stale_revision")
        self.now[0] = 1000
        self.assertIsNone(self.confirmations.get_confirmation(
            authenticated_user_id="u2", confirmation_id=result["confirmation_id"]))
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as wrong_revision:
            self.confirmations.get_confirmation(
                authenticated_user_id="u1", confirmation_id=result["confirmation_id"],
                issued_scan_revision=2)
        self.assertEqual(wrong_revision.exception.code, "revision_conflict")
        self.now[0] = 1120
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as expired:
            self.confirmations.get_confirmation(
                authenticated_user_id="u1", confirmation_id=result["confirmation_id"])
        self.assertEqual(expired.exception.code, "expired")

    def test_revision_and_confirmation_roll_back_together(self):
        original = self.scan.create_revision_in_transaction

        def fail_after_revision(**kwargs):
            original(**kwargs)
            raise RuntimeError("simulated confirmation insert failure")

        with patch.object(self.scan, "create_revision_in_transaction", side_effect=fail_after_revision):
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                self.confirmations.record_confirmation(
                    authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                    idempotency_key="rollback", confirmation=self._confirmation())
        self.assertEqual(self.sql.query_one(
            "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_confirmations WHERE idempotency_key = ?",
            ("rollback",))["count"], 0)
        self.assertIsNone(self.scan.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=1))
        self.assertEqual(self.scan.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0)["status"],
                         "active")

    def test_confirm_replay_survives_sqlite_restart_after_source_superseded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "confirm.db")
            self.sql.close()
            first_sql = SqliteDatabase(path)
            first_scan = NutritionScanContextRepository(first_sql, clock=lambda: 1000.0)
            first_snapshots = FdcCandidateSnapshotRepository(
                first_sql, scan_context_repository=first_scan, clock=lambda: 1000.0)
            first_confirmations = FdcCandidateConfirmationRepository(
                first_sql, snapshot_repository=first_snapshots, clock=lambda: 1000.0)
            first_scan.save_scan_context(user_id="u1", scan_id="restart-scan", scan_revision=0,
                                         items=[ITEM], ttl_seconds=120)
            snapshot = first_snapshots.save_candidates(
                user_id="u1", scan_id="restart-scan", scan_revision=0,
                candidates_by_item={ITEM["item_id"]: CANDIDATES})["snapshot"]
            confirmation = {**self._confirmation(), "snapshot_digest": snapshot["snapshot_digest"]}
            first = first_confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="restart-scan", scan_revision=0,
                idempotency_key="restart-key", confirmation=confirmation)
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second_scan = NutritionScanContextRepository(second_sql, clock=lambda: 1000.0)
                second_snapshots = FdcCandidateSnapshotRepository(
                    second_sql, scan_context_repository=second_scan, clock=lambda: 1000.0)
                second_confirmations = FdcCandidateConfirmationRepository(
                    second_sql, snapshot_repository=second_snapshots, clock=lambda: 1000.0)
                replay = second_confirmations.record_confirmation(
                    authenticated_user_id="u1", actor_id="u1", scan_id="restart-scan", scan_revision=0,
                    idempotency_key="restart-key", confirmation=confirmation)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["confirmation_id"], first["confirmation_id"])
                self.assertEqual(replay["issued_scan_revision"], 1)
                self.assertEqual(second_scan.get_scan_context(
                    user_id="u1", scan_id="restart-scan", scan_revision=1)["items"], [ITEM])
            finally:
                second_sql.close()

    def test_same_idempotency_key_is_atomic_across_sqlite_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "concurrent-confirm.db")
            self.sql.close()
            repositories = []
            for _ in range(2):
                sql = SqliteDatabase(path)
                scan = NutritionScanContextRepository(sql, clock=lambda: 1000.0)
                snapshots = FdcCandidateSnapshotRepository(
                    sql, scan_context_repository=scan, clock=lambda: 1000.0)
                confirmations = FdcCandidateConfirmationRepository(
                    sql, snapshot_repository=snapshots, clock=lambda: 1000.0)
                repositories.append((sql, scan, confirmations))
            first_sql, first_scan, first_confirmations = repositories[0]
            first_scan.save_scan_context(user_id="u1", scan_id="parallel-scan", scan_revision=0,
                                         items=[ITEM], ttl_seconds=120)
            first_snapshot_repo = FdcCandidateSnapshotRepository(
                first_sql, scan_context_repository=first_scan, clock=lambda: 1000.0)
            snapshot = first_snapshot_repo.save_candidates(
                user_id="u1", scan_id="parallel-scan", scan_revision=0,
                candidates_by_item={ITEM["item_id"]: CANDIDATES})["snapshot"]
            confirmation = {**self._confirmation(), "snapshot_digest": snapshot["snapshot_digest"]}
            barrier = threading.Barrier(2)

            def submit(repository):
                barrier.wait(timeout=5)
                return repository.record_confirmation(
                    authenticated_user_id="u1", actor_id="u1", scan_id="parallel-scan",
                    scan_revision=0, idempotency_key="parallel-key", confirmation=confirmation)

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(submit, [entry[2] for entry in repositories]))
                self.assertEqual(len({result["confirmation_id"] for result in results}), 1)
                self.assertEqual(sum(bool(result["replayed"]) for result in results), 1)
                self.assertTrue(all(result["issued_scan_revision"] == 1 for result in results))
                self.assertEqual(first_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_confirmations "
                    "WHERE user_id = ? AND idempotency_key = ?", ("u1", "parallel-key")
                )["count"], 1)
                self.assertEqual(first_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_scan_contexts WHERE scan_id = ?",
                    ("parallel-scan",)
                )["count"], 2)
            finally:
                for sql, _, _ in repositories:
                    sql.close()

    def test_wrong_actor_digest_snapshot_and_expiry_fail_closed(self):
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as actor:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u2", scan_id="scan-1", scan_revision=0,
                idempotency_key="actor", confirmation=self._confirmation())
        self.assertEqual(actor.exception.code, "wrong_actor")
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as digest:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                idempotency_key="digest", confirmation={**self._confirmation(), "snapshot_digest": "0" * 64})
        self.assertIn(digest.exception.code, {"snapshot_mismatch", "snapshot_unavailable"})
        self.now[0] = 1120
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as expired:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                idempotency_key="expired", confirmation=self._confirmation())
        self.assertIn(expired.exception.code, {"expired", "snapshot_unavailable"})

    def test_confirmation_cannot_use_client_snapshot_or_old_revision(self):
        forged = {**self._confirmation(), "items": [{"item_id": ITEM["item_id"],
                                                        "decision": "confirm",
                                                        "candidate_fdc_id": "99999"}]}
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as error:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                idempotency_key="forged", confirmation=forged)
        self.assertEqual(error.exception.code, "invalid_confirmation")
        with self.assertRaises(FdcCandidateConfirmationRepositoryError) as missing:
            self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=1,
                idempotency_key="old", confirmation=self._confirmation())
        self.assertIn(missing.exception.code, {"snapshot_unavailable", "scan_unavailable"})


if __name__ == "__main__":
    unittest.main()
