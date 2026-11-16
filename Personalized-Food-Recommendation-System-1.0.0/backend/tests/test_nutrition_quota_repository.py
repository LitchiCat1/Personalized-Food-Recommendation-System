import os
import tempfile
import threading
import unittest

from repositories.nutrition_quota_repository import (
    NutritionQuotaRepository, NutritionQuotaRepositoryError,
)
from repositories.sqlite_db import SqliteDatabase


class NutritionQuotaRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1_700_000_000]
        self.sql = SqliteDatabase(":memory:")
        self.repo = NutritionQuotaRepository(
            self.sql, per_user_limit=2, global_limit=3, window_seconds=60,
            clock=lambda: self.clock[0])

    def tearDown(self):
        self.sql.close()

    def test_reservation_is_atomic_and_snapshot_counts_pending_usage(self):
        reservation = self.repo.reserve(user_id="u1", reservation_id="r1")
        self.assertEqual(reservation["status"], "pending")
        self.assertEqual(self.repo.quota_snapshot("u1")["user_reserved"], 1)
        self.assertEqual(self.repo.quota_snapshot("u1")["global_reserved"], 1)
        replay = self.repo.reserve(user_id="u1", reservation_id="r1")
        self.assertEqual(replay["reservation_id"], "r1")
        self.assertEqual(self.repo.quota_snapshot("u1")["user_reserved"], 1)

    def test_retryable_failure_releases_user_and_global_quota(self):
        self.repo.reserve(user_id="u1", reservation_id="r1")
        self.repo.release(user_id="u1", reservation_id="r1", status="timeout")
        snapshot = self.repo.quota_snapshot("u1")
        self.assertEqual(snapshot["user_reserved"], 0)
        self.assertEqual(snapshot["user_consumed"], 0)
        self.assertEqual(snapshot["global_used"], 0)
        second = self.repo.reserve(user_id="u1", reservation_id="r2")
        self.assertEqual(second["status"], "pending")

    def test_not_found_consumes_quota_but_has_no_result_cache(self):
        self.repo.reserve(user_id="u1", reservation_id="r1")
        result = self.repo.commit(user_id="u1", reservation_id="r1", status="not_found")
        self.assertEqual(result["status"], "not_found")
        self.assertNotIn("result", result)
        snapshot = self.repo.quota_snapshot("u1")
        self.assertEqual(snapshot["user_consumed"], 1)
        self.assertEqual(snapshot["global_consumed"], 1)
        self.repo.commit(user_id="u1", reservation_id="r1", status="not_found")
        # The second reservation is valid because the per-user limit is two.
        self.repo.reserve(user_id="u1", reservation_id="r2")
        self.repo.commit(user_id="u1", reservation_id="r2", status="success")
        with self.assertRaisesRegex(NutritionQuotaRepositoryError, "user enrichment quota"):
            self.repo.reserve(user_id="u1", reservation_id="r3")

    def test_terminal_status_is_idempotent_but_cannot_change_outcome(self):
        self.repo.reserve(user_id="u1", reservation_id="r1")
        first = self.repo.commit(user_id="u1", reservation_id="r1", status="success")
        replay = self.repo.commit(user_id="u1", reservation_id="r1", status="success")
        self.assertEqual(first["updated_at"], replay["updated_at"])
        with self.assertRaisesRegex(NutritionQuotaRepositoryError, "already completed"):
            self.repo.commit(user_id="u1", reservation_id="r1", status="not_found")

    def test_reservation_ownership_is_bound_to_user(self):
        self.repo.reserve(user_id="u1", reservation_id="r1")
        with self.assertRaisesRegex(NutritionQuotaRepositoryError, "another user"):
            self.repo.reserve(user_id="u2", reservation_id="r1")
        with self.assertRaisesRegex(NutritionQuotaRepositoryError, "another user"):
            self.repo.release(user_id="u2", reservation_id="r1")

    def test_limits_are_checked_across_users_and_window_rollover_is_independent(self):
        repo = NutritionQuotaRepository(self.sql, per_user_limit=5, global_limit=1,
                                        window_seconds=60, clock=lambda: self.clock[0])
        repo.reserve(user_id="u1", reservation_id="r1")
        with self.assertRaisesRegex(NutritionQuotaRepositoryError, "global enrichment quota"):
            repo.reserve(user_id="u2", reservation_id="r2")
        self.clock[0] += 60
        self.assertEqual(repo.reserve(user_id="u2", reservation_id="r2")["status"], "pending")

    def test_restart_preserves_consumed_quota_and_reservation_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "quota.db")
            first_sql = SqliteDatabase(path)
            first = NutritionQuotaRepository(first_sql, per_user_limit=1, global_limit=1,
                                             window_seconds=60, clock=lambda: self.clock[0])
            first.reserve(user_id="u1", reservation_id="r1")
            first.commit(user_id="u1", reservation_id="r1", status="not_found")
            first_sql.close()
            second_sql = SqliteDatabase(path)
            try:
                second = NutritionQuotaRepository(second_sql, per_user_limit=1, global_limit=1,
                                                  window_seconds=60, clock=lambda: self.clock[0])
                self.assertEqual(second.get_reservation("r1")["status"], "not_found")
                with self.assertRaisesRegex(NutritionQuotaRepositoryError, "user enrichment quota"):
                    second.reserve(user_id="u1", reservation_id="r2")
            finally:
                second_sql.close()

    def test_two_sqlite_connections_cannot_both_reserve_last_global_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "quota.db")
            sql_a, sql_b = SqliteDatabase(path), SqliteDatabase(path)
            a = NutritionQuotaRepository(sql_a, per_user_limit=2, global_limit=1,
                                         window_seconds=60, clock=lambda: self.clock[0])
            b = NutritionQuotaRepository(sql_b, per_user_limit=2, global_limit=1,
                                         window_seconds=60, clock=lambda: self.clock[0])
            barrier = threading.Barrier(2)
            results = []

            def reserve(repo, user, reservation):
                barrier.wait()
                try:
                    repo.reserve(user_id=user, reservation_id=reservation)
                    results.append("ok")
                except NutritionQuotaRepositoryError as error:
                    results.append(error.code)

            threads = [threading.Thread(target=reserve, args=(a, "u1", "r1")),
                       threading.Thread(target=reserve, args=(b, "u2", "r2"))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            sql_a.close()
            sql_b.close()
            self.assertEqual(sorted(results), ["global_quota_exceeded", "ok"])


if __name__ == "__main__":
    unittest.main()
