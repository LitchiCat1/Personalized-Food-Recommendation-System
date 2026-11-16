import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from repositories.fdc_candidate_confirmation_repository import FdcCandidateConfirmationRepository
from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.fdc_profile_preview_repository import (
    FdcProfilePreviewRepository, FdcProfilePreviewRepositoryError,
)
from repositories.nutrition_profile_repository import NutritionProfileSourceRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_profile_preview_service import FdcProfilePreviewService
from services.fooddata_central_selection_service import CONFIRMATION_SCHEMA_VERSION

from test_fdc_profile_preview_service import (
    FakeClient, detail_document, reviewed_policy,
)


ITEM = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "蘋果",
    "confidence": 0.9, "weight_confidence": 0.8, "estimated_weight_g": 150,
    "food_state": "raw", "preparation_method": "mixed",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}
CANDIDATE = {
    "fdcId": "171688", "description": "Apples, raw, with skin",
    "dataType": "SR Legacy", "brandOwner": None, "foodCategory": "Fruit",
}


class FdcProfilePreviewRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.scan = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])
        self.snapshots = FdcCandidateSnapshotRepository(
            self.sql, scan_context_repository=self.scan, clock=lambda: self.now[0])
        self.confirmations = FdcCandidateConfirmationRepository(
            self.sql, snapshot_repository=self.snapshots, clock=lambda: self.now[0])
        self.sources = NutritionProfileSourceRepository(self.sql)
        self.sources.save_source_policy(reviewed_policy())
        self.scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM], ttl_seconds=120)
        self.snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="scan-1", scan_revision=0,
            candidates_by_item={ITEM["item_id"]: [CANDIDATE]})["snapshot"]
        self.confirmation = self.confirmations.record_confirmation(
            authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
            idempotency_key="confirm-key", confirmation={
                "schema_version": CONFIRMATION_SCHEMA_VERSION,
                "snapshot_digest": self.snapshot["snapshot_digest"], "scan_revision": 0,
                "items": [{"item_id": ITEM["item_id"], "decision": "confirm",
                           "candidate_fdc_id": "171688"}],
            })
        self.preview = self._make_preview()
        self.repo = FdcProfilePreviewRepository(
            self.sql, confirmation_repository=self.confirmations,
            scan_context_repository=self.scan, source_repository=self.sources,
            clock=lambda: self.now[0])
        self.saved = self.repo.save_preview(self.preview, preview_id="preview-1")

    def tearDown(self):
        self.sql.close()

    def _make_preview(self):
        service = FdcProfilePreviewService(
            confirmation_repository=self.confirmations,
            scan_context_repository=self.scan, source_repository=self.sources,
            detail_client_factory=lambda: FakeClient(detail_document()),
            clock=lambda: self.now[0], monotonic=lambda: 20.0)
        return service.preview(
            authenticated_user_id="u1", confirmation_id=self.confirmation["confirmation_id"],
            scan_id="scan-1", issued_scan_revision=1, item_id=ITEM["item_id"])

    def _accept(self, key="accept-key", user="u1"):
        return self.repo.accept_preview(authenticated_user_id=user,
                                        preview_id="preview-1", idempotency_key=key)

    def _save_legacy_generic_preview(self):
        # Simulate an old permissive policy and already-issued generic scan.
        policy = reviewed_policy()
        policy["accepted_names"].append("炒菜葉")
        self.sources.save_source_policy(policy, expected_revision=0)
        item = {**ITEM, "item_id": "legacy:0", "name_zh": "炒菜葉"}
        self.scan.save_scan_context(user_id="u1", scan_id="legacy", scan_revision=0,
                                    items=[item], ttl_seconds=120)
        snapshot = self.snapshots.save_candidates(
            user_id="u1", scan_id="legacy", scan_revision=0,
            candidates_by_item={item["item_id"]: [CANDIDATE]})["snapshot"]
        with patch("services.fooddata_central_selection_service.requires_food_identity_confirmation",
                   return_value=False), \
             patch("repositories.fdc_candidate_confirmation_repository.requires_food_identity_confirmation",
                   return_value=False):
            confirmation = self.confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="legacy", scan_revision=0,
                idempotency_key="legacy-confirm", confirmation={
                    "schema_version": CONFIRMATION_SCHEMA_VERSION,
                    "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
                    "items": [{"item_id": item["item_id"], "decision": "confirm",
                               "candidate_fdc_id": "171688"}],
                })
            service = FdcProfilePreviewService(
                confirmation_repository=self.confirmations, scan_context_repository=self.scan,
                source_repository=self.sources,
                detail_client_factory=lambda: FakeClient(detail_document()),
                clock=lambda: self.now[0], monotonic=lambda: 20.0)
            preview = service.preview(
                authenticated_user_id="u1", confirmation_id=confirmation["confirmation_id"],
                scan_id="legacy", issued_scan_revision=1, item_id=item["item_id"])
        return self.repo.save_preview(preview, preview_id="legacy-preview")

    def test_legacy_generic_preview_cannot_write_profile_or_change_evidence(self):
        saved = self._save_legacy_generic_preview()
        before = self.sql.query_one(
            "SELECT * FROM nutrition_fdc_profile_previews WHERE preview_id = ?", ("legacy-preview",))
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self.repo.accept_preview(authenticated_user_id="u1", preview_id="legacy-preview",
                                     idempotency_key="legacy-accept")
        self.assertEqual(caught.exception.code, "confirmation_required")
        self.assertEqual(self.repo.get_preview(
            authenticated_user_id="u1", preview_id="legacy-preview"), saved)
        self.assertEqual(self.sql.query_one(
            "SELECT * FROM nutrition_fdc_profile_previews WHERE preview_id = ?", ("legacy-preview",)), before)
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS count FROM nutrition_profiles")["count"], 0)

    def test_previously_accepted_generic_preview_keeps_idempotent_evidence_replay(self):
        self._save_legacy_generic_preview()
        with patch("repositories.fdc_profile_preview_repository.requires_food_identity_confirmation",
                   return_value=False):
            accepted = self.repo.accept_preview(
                authenticated_user_id="u1", preview_id="legacy-preview", idempotency_key="legacy-accept")
        replay = self.repo.accept_preview(
            authenticated_user_id="u1", preview_id="legacy-preview", idempotency_key="legacy-accept")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["profile_hash"], accepted["profile_hash"])
        self.assertEqual(self.sql.query_one("SELECT COUNT(*) AS count FROM nutrition_profiles")["count"], 1)
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self.repo.accept_preview(authenticated_user_id="u1", preview_id="legacy-preview",
                                     idempotency_key="different-key")
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_accept_writes_profile_consumes_preview_and_replays_same_key(self):
        accepted = self._accept()
        self.assertEqual(accepted["status"], "accepted")
        self.assertFalse(accepted["replayed"])
        self.assertEqual(accepted["profile"]["profile_id"], self.saved["profile_id"])
        self.assertEqual(accepted["profile"]["profile_hash"], self.saved["profile_hash"])
        self.assertEqual(self.repo.get_preview(
            authenticated_user_id="u1", preview_id="preview-1"), None)
        replay = self._accept()
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["profile_hash"], accepted["profile_hash"])
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept("another-key")
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_wrong_user_expiry_and_bad_idempotency_are_rejected(self):
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept(user="u2")
        self.assertEqual(caught.exception.code, "ownership_conflict")
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self.repo.accept_preview(authenticated_user_id="u1", preview_id="preview-1",
                                     idempotency_key="x" * 129)
        self.assertEqual(caught.exception.code, "invalid_request")
        self.now[0] = self.saved["expires_at"]
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept()
        self.assertEqual(caught.exception.code, "expired")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_duplicate_preview_id_requires_all_bindings_to_match(self):
        replay = self.repo.save_preview(self.preview, preview_id="preview-1")
        self.assertEqual(replay["profile_hash"], self.saved["profile_hash"])
        changed = dict(self.preview)
        changed["weight_g"] = 151
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self.repo.save_preview(changed, preview_id="preview-1")
        self.assertEqual(caught.exception.code, "idempotency_conflict")

        changed = dict(self.preview)
        changed["source_policy_revision"] = self.preview["source_policy_revision"] + 1
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self.repo.save_preview(changed, preview_id="preview-1")
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_policy_withdrawal_revision_and_portion_drift_fail_before_write(self):
        self.sources.withdraw_source_policy("usda-fdc-171688", expected_revision=0)
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept()
        self.assertEqual(caught.exception.code, "source_unavailable")
        self.assertEqual(self.repo.get_preview(
            authenticated_user_id="u1", preview_id="preview-1")["status"], "active")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_profile_insert_failure_rolls_back_preview_and_profile(self):
        original = self.sql.execute

        def fail_profile_insert(sql, params=()):
            if sql.startswith("INSERT INTO nutrition_profiles"):
                raise RuntimeError("simulated profile insert failure")
            return original(sql, params)

        with patch.object(self.sql, "execute", side_effect=fail_profile_insert):
            with self.assertRaisesRegex(RuntimeError, "profile insert"):
                self._accept()
        self.assertEqual(self.repo.get_preview(
            authenticated_user_id="u1", preview_id="preview-1")["status"], "active")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_portion_drift_fails_before_write(self):
        self.sql.execute("UPDATE nutrition_scan_contexts SET items = ? WHERE scan_id = ? AND scan_revision = ?",
                         (json.dumps([{**ITEM, "estimated_weight_g": 175}]), "scan-1", 1))
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept()
        self.assertEqual(caught.exception.code, "authorization_changed")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_identity_drift_fails_before_write(self):
        self.sql.execute("UPDATE nutrition_scan_contexts SET items = ? WHERE scan_id = ? AND scan_revision = ?",
                         (json.dumps([{**ITEM, "name_zh": "青菜"}]), "scan-1", 1))
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept()
        self.assertEqual(caught.exception.code, "authorization_changed")

    def test_preview_consume_failure_rolls_back_inserted_profile(self):
        original = self.sql.execute

        def fail_consume(sql, params=()):
            if sql.startswith("UPDATE nutrition_fdc_profile_previews"):
                raise RuntimeError("simulated consume failure")
            return original(sql, params)

        with patch.object(self.sql, "execute", side_effect=fail_consume):
            with self.assertRaisesRegex(RuntimeError, "consume failure"):
                self._accept()
        self.assertEqual(self.repo.get_preview(
            authenticated_user_id="u1", preview_id="preview-1")["status"], "active")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_stored_profile_or_binding_tampering_fails_closed(self):
        self.sql.execute("UPDATE nutrition_fdc_profile_previews SET profile_hash = ? WHERE preview_id = ?",
                         ("f" * 64, "preview-1"))
        with self.assertRaises(FdcProfilePreviewRepositoryError) as caught:
            self._accept()
        self.assertEqual(caught.exception.code, "profile_conflict")
        self.assertIsNone(self.sources.get_profile_for_user("u1", self.saved["profile_id"]))

    def test_restart_replay_survives_and_does_not_duplicate_profile(self):
        first = self._accept()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "restart.db")
            destination = sqlite3.connect(path)
            try:
                self.sql._conn.backup(destination)
            finally:
                destination.close()
            self.sql.close()
            restarted_sql = SqliteDatabase(path)
            try:
                restarted_source = NutritionProfileSourceRepository(restarted_sql)
                restarted_repo = FdcProfilePreviewRepository(
                    restarted_sql, source_repository=restarted_source, clock=lambda: self.now[0])
                replay = restarted_repo.accept_preview(
                    authenticated_user_id="u1", preview_id="preview-1", idempotency_key="accept-key")
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["profile_hash"], first["profile_hash"])
                self.assertEqual(restarted_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_profiles WHERE profile_id = ?",
                    (self.saved["profile_id"],))["count"], 1)
            finally:
                restarted_sql.close()

    def test_two_sqlite_connections_same_key_accept_once_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "preview.db")
            self.sql.close()
            first_sql = SqliteDatabase(path)
            scan = NutritionScanContextRepository(first_sql, clock=lambda: 1000.0)
            snapshots = FdcCandidateSnapshotRepository(
                first_sql, scan_context_repository=scan, clock=lambda: 1000.0)
            confirmations = FdcCandidateConfirmationRepository(
                first_sql, snapshot_repository=snapshots, clock=lambda: 1000.0)
            source = NutritionProfileSourceRepository(first_sql)
            source.save_source_policy(reviewed_policy())
            scan.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                   items=[ITEM], ttl_seconds=120)
            snapshot = snapshots.save_candidates(
                user_id="u1", scan_id="scan-1", scan_revision=0,
                candidates_by_item={ITEM["item_id"]: [CANDIDATE]})["snapshot"]
            confirmation = confirmations.record_confirmation(
                authenticated_user_id="u1", actor_id="u1", scan_id="scan-1", scan_revision=0,
                idempotency_key="confirm-key", confirmation={
                    "schema_version": CONFIRMATION_SCHEMA_VERSION,
                    "snapshot_digest": snapshot["snapshot_digest"], "scan_revision": 0,
                    "items": [{"item_id": ITEM["item_id"], "decision": "confirm",
                               "candidate_fdc_id": "171688"}],
                })
            service = FdcProfilePreviewService(
                confirmation_repository=confirmations, scan_context_repository=scan,
                source_repository=source, detail_client_factory=lambda: FakeClient(detail_document()),
                clock=lambda: 1000.0, monotonic=lambda: 20.0)
            preview = service.preview(
                authenticated_user_id="u1", confirmation_id=confirmation["confirmation_id"],
                scan_id="scan-1", issued_scan_revision=1, item_id=ITEM["item_id"])
            first_repo = FdcProfilePreviewRepository(first_sql, source_repository=source,
                                                     clock=lambda: 1000.0)
            first_repo.save_preview(preview, preview_id="race-preview")
            second_sql = SqliteDatabase(path)
            second_source = NutritionProfileSourceRepository(second_sql)
            second_repo = FdcProfilePreviewRepository(second_sql, source_repository=second_source,
                                                      clock=lambda: 1000.0)
            barrier = threading.Barrier(2)

            def accept(repo):
                barrier.wait()
                return repo.accept_preview(authenticated_user_id="u1", preview_id="race-preview",
                                           idempotency_key="same-key")

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(accept, (first_repo, second_repo)))
                self.assertEqual(sorted(result["replayed"] for result in results), [False, True])
                self.assertEqual(first_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_profiles WHERE profile_id = ?",
                    ("fdc-preview-race-preview",))["count"], 1)
            finally:
                second_sql.close()
                first_sql.close()


if __name__ == "__main__":
    unittest.main()
