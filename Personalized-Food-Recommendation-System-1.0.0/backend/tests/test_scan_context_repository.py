import os
import tempfile
import threading
import unittest

from repositories.scan_context_repository import (
    NutritionScanContextRepository,
    ScanContextRepositoryError,
    item_set_hash,
)
from repositories.sqlite_db import SqliteDatabase


ITEM_A = {
    "item_id": "scan-1:0", "item_revision": 0, "name_zh": "糯米腸",
    "confidence": 0.92, "weight_confidence": 0.8, "estimated_weight_g": 120,
    "food_state": "prepared", "preparation_method": "roasted",
    "components_scope": "food_only", "brand": None, "variant": None,
    "validation_issues": [],
}
ITEM_B = {**ITEM_A, "item_id": "scan-1:1", "name_zh": "青菜"}


class ScanContextRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.sql = SqliteDatabase(":memory:")
        self.repo = NutritionScanContextRepository(self.sql, clock=lambda: self.now[0])

    def tearDown(self):
        self.sql.close()

    def test_round_trip_and_complete_set_is_order_independent(self):
        saved = self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                            items=[ITEM_A, ITEM_B], ttl_seconds=120)
        self.assertEqual(saved["item_set_hash"], item_set_hash([ITEM_A, ITEM_B]))
        loaded = self.repo.assert_complete_item_set(user_id="u1", scan_id="scan-1", scan_revision=0,
                                                   items=[ITEM_B, ITEM_A])
        self.assertEqual(loaded["items"], [ITEM_A, ITEM_B])
        # Retrying the same scanner write with a transport reorder is idempotent.
        retry = self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                            items=[ITEM_B, ITEM_A], ttl_seconds=120)
        self.assertEqual(retry["item_set_hash"], saved["item_set_hash"])

    def test_missing_duplicate_or_changed_items_are_rejected(self):
        self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM_A, ITEM_B])
        with self.assertRaisesRegex(ScanContextRepositoryError, "complete scan item set") as missing:
            self.repo.assert_complete_item_set(user_id="u1", scan_id="scan-1", scan_revision=0,
                                               items=[ITEM_A])
        self.assertEqual(missing.exception.code, "item_set_mismatch")
        with self.assertRaises(ScanContextRepositoryError):
            self.repo.assert_complete_item_set(user_id="u1", scan_id="scan-1", scan_revision=0,
                                               items=[ITEM_A, ITEM_A])
        changed = {**ITEM_B, "item_revision": 1}
        with self.assertRaisesRegex(ScanContextRepositoryError, "complete scan item set"):
            self.repo.assert_complete_item_set(user_id="u1", scan_id="scan-1", scan_revision=0,
                                               items=[ITEM_A, changed])

    def test_user_binding_and_revision_advancement(self):
        self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM_A])
        with self.assertRaisesRegex(ScanContextRepositoryError, "another user") as wrong:
            self.repo.get_scan_context(user_id="u2", scan_id="scan-1", scan_revision=0)
        self.assertEqual(wrong.exception.code, "wrong_user")
        with self.assertRaisesRegex(ScanContextRepositoryError, "another user"):
            self.repo.save_scan_context(user_id="u2", scan_id="scan-1", scan_revision=1, items=[ITEM_A])
        with self.assertRaisesRegex(ScanContextRepositoryError, "advance one"):
            self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=2, items=[ITEM_A])
        saved = self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=1, items=[ITEM_A])
        self.assertEqual(saved["scan_revision"], 1)
        self.assertIsNone(self.repo.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0))
        with self.assertRaisesRegex(ScanContextRepositoryError, "no longer current") as stale:
            self.repo.consume_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                           items=[ITEM_A])
        self.assertEqual(stale.exception.code, "stale_revision")
        self.assertEqual(self.repo.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                                    include_inactive=True)["status"], "superseded")

    def test_expiry_and_consumption_are_durable_states(self):
        self.repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM_A], ttl_seconds=10)
        self.now[0] = 1010
        self.assertIsNone(self.repo.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0))
        expired = self.repo.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                             include_inactive=True)
        self.assertEqual(expired["status"], "expired")

        self.now[0] = 3000
        self.repo.save_scan_context(user_id="u1", scan_id="scan-3", scan_revision=0,
                                    items=[ITEM_A], ttl_seconds=10)
        self.now[0] = 3010
        with self.assertRaisesRegex(ScanContextRepositoryError, "has expired"):
            self.repo.consume_scan_context(user_id="u1", scan_id="scan-3", scan_revision=0,
                                           items=[ITEM_A], jti="expired-jti")
        self.assertEqual(self.repo.get_scan_context(user_id="u1", scan_id="scan-3", scan_revision=0,
                                                    include_inactive=True)["status"], "expired")

        self.now[0] = 2000
        self.repo.save_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                    items=[ITEM_A], ttl_seconds=10)
        consumed = self.repo.consume_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                                  items=[ITEM_A], jti="jti-1")
        self.assertEqual(consumed["status"], "consumed")
        with self.assertRaisesRegex(ScanContextRepositoryError, "already been consumed") as replay:
            self.repo.consume_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                           items=[ITEM_A], jti="jti-1")
        self.assertEqual(replay.exception.code, "replayed")

    def test_jti_is_bound_to_context_and_durable_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "scan.db")
            first_sql = SqliteDatabase(path)
            first = NutritionScanContextRepository(first_sql, clock=lambda: 1000.0)
            first.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM_A])
            first.consume_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                       items=[ITEM_A], jti="jti-1")
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second = NutritionScanContextRepository(second_sql, clock=lambda: 1000.0)
                self.assertEqual(second.get_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                                        include_inactive=True)["status"], "consumed")
                with self.assertRaisesRegex(ScanContextRepositoryError, "already been consumed"):
                    second.consume_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                                items=[ITEM_A], jti="jti-1")
            finally:
                second_sql.close()

    def test_replayed_jti_cannot_be_bound_to_another_scan_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "scan-jti-conflict.db")
            first_sql = SqliteDatabase(path)
            first = NutritionScanContextRepository(first_sql, clock=lambda: 1000.0)
            first.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                    items=[ITEM_A])
            first.save_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                    items=[ITEM_B])
            first.consume_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                       items=[ITEM_A], jti="shared-jti")
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second = NutritionScanContextRepository(second_sql, clock=lambda: 1000.0)
                with self.assertRaisesRegex(ScanContextRepositoryError,
                                             "bound to another scan") as conflict:
                    second.consume_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0,
                                                items=[ITEM_B], jti="shared-jti")
                self.assertEqual(conflict.exception.code, "replay_conflict")
                self.assertEqual(
                    second.get_scan_context(user_id="u1", scan_id="scan-2", scan_revision=0)["status"],
                    "active",
                )
            finally:
                second_sql.close()

    def test_concurrent_sqlite_consumption_allows_one_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "scan.db")
            setup = SqliteDatabase(path)
            setup_repo = NutritionScanContextRepository(setup, clock=lambda: 1000.0)
            setup_repo.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM_A])
            setup.close()
            sql_a, sql_b = SqliteDatabase(path), SqliteDatabase(path)
            a = NutritionScanContextRepository(sql_a, clock=lambda: 1000.0)
            b = NutritionScanContextRepository(sql_b, clock=lambda: 1000.0)
            results = []
            barrier = threading.Barrier(2)

            def consume(repo, jti):
                barrier.wait()
                try:
                    repo.consume_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0,
                                              items=[ITEM_A], jti=jti)
                    results.append("ok")
                except ScanContextRepositoryError as error:
                    results.append(error.code)

            threads = [threading.Thread(target=consume, args=(a, "jti-a")),
                       threading.Thread(target=consume, args=(b, "jti-b"))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            sql_a.close(); sql_b.close()
            self.assertEqual(results.count("ok"), 1)
            self.assertEqual(len(results), 2)
            self.assertIn(results[0], {"ok", "replayed"})

    def test_two_sqlite_connections_replay_same_revision_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "scan.db")
            sql_a, sql_b = SqliteDatabase(path), SqliteDatabase(path)
            a = NutritionScanContextRepository(sql_a, clock=lambda: 1000.0)
            b = NutritionScanContextRepository(sql_b, clock=lambda: 1000.0)
            first = a.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM_A])
            second = b.save_scan_context(user_id="u1", scan_id="scan-1", scan_revision=0, items=[ITEM_A])
            self.assertEqual(first["item_set_hash"], second["item_set_hash"])
            sql_a.close(); sql_b.close()

    def test_identity_decision_survives_sqlite_reopen_and_changes_item_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "scan.db")
            first_sql = SqliteDatabase(path)
            first = NutritionScanContextRepository(first_sql, clock=lambda: 1000.0)
            item = dict(ITEM_A, identity_confirmation_required=True)
            saved = first.save_scan_context(user_id="u1", scan_id="identity-scan",
                                            scan_revision=0, items=[item])
            first_sql.close()

            second_sql = SqliteDatabase(path)
            try:
                second = NutritionScanContextRepository(second_sql, clock=lambda: 1000.0)
                loaded = second.get_scan_context(user_id="u1", scan_id="identity-scan",
                                                 scan_revision=0)
                self.assertEqual(loaded["items"], [item])
                self.assertEqual(loaded["item_set_hash"], saved["item_set_hash"])
                with self.assertRaises(ScanContextRepositoryError) as mismatch:
                    second.assert_complete_item_set(
                        user_id="u1", scan_id="identity-scan", scan_revision=0,
                        items=[dict(item, identity_confirmation_required=False)])
                self.assertEqual(mismatch.exception.code, "item_set_mismatch")
            finally:
                second_sql.close()

    def test_identity_confirmation_state_must_be_boolean(self):
        with self.assertRaises(ScanContextRepositoryError) as raised:
            self.repo.save_scan_context(user_id="u1", scan_id="bad-identity",
                                        scan_revision=0,
                                        items=[dict(ITEM_A, identity_confirmation_required="false")])
        self.assertEqual(raised.exception.code, "invalid_items")


if __name__ == "__main__":
    unittest.main()
