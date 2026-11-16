import multiprocessing
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from repositories.fdc_candidate_snapshot_repository import FdcCandidateSnapshotRepository
from repositories.scan_context_repository import NutritionScanContextRepository
from repositories.sqlite_db import SqliteDatabase
from services.fdc_candidate_search_service import FdcCandidateSearchError, FdcCandidateSearchService
from services.fooddata_central_client import FoodDataCentralClientError


ITEM = {
    "item_id": "multiprocess-scan:0", "item_revision": 0,
    "name_zh": "糯米腸", "confidence": 0.92, "weight_confidence": 0.8,
    "estimated_weight_g": 120, "food_state": "prepared",
    "preparation_method": "steamed", "components_scope": "food_only",
    "brand": None, "variant": None, "validation_issues": [],
}
HEALTH = {"TFDA": {"status": "available"}, "USDA FNDDS": {"status": "available"}}
CANDIDATE = {
    "fdcId": "12345", "description": "Glutinous rice sausage",
    "dataType": "Foundation", "brandOwner": None,
    "foodCategory": "Prepared foods",
}


class _ObservedSnapshotRepository(FdcCandidateSnapshotRepository):
    def __init__(self, *args, follower_joined, **kwargs):
        super().__init__(*args, **kwargs)
        self.follower_joined = follower_joined

    def reserve_search(self, **kwargs):
        result = super().reserve_search(**kwargs)
        if not result["owner"]:
            self.follower_joined.set()
        return result


class _SharedFakeClient:
    def __init__(self, *, provider_entered, release_provider, call_count, fail_first=False):
        self.provider_entered = provider_entered
        self.release_provider = release_provider
        self.call_count = call_count
        self.fail_first = fail_first

    def search_foods(self, query, *, deadline, page_size):
        with self.call_count.get_lock():
            first_call = self.call_count.value == 0
            self.call_count.value += 1
        if first_call:
            self.provider_entered.set()
            if not self.release_provider.wait(10):
                raise RuntimeError("test provider was not released")
            if self.fail_first:
                raise FoodDataCentralClientError("upstream_error", "fake failure")
        return {"candidates": [CANDIDATE]}

    def close(self):
        pass


def _candidate_worker(path, *, barrier, provider_entered, release_provider,
                      call_count, follower_joined, result_queue, fail_first=False,
                      wall_time=None):
    sql = None
    try:
        sql = SqliteDatabase(path)
        clock = time.time if wall_time is None else lambda: wall_time
        scan = NutritionScanContextRepository(sql, clock=clock)
        snapshots = _ObservedSnapshotRepository(
            sql, scan_context_repository=scan, follower_joined=follower_joined, clock=clock)
        service = FdcCandidateSearchService(
            scan_context_repository=scan,
            snapshot_repository=snapshots,
            local_lookup_factory=lambda _user_id: lambda _item: {"status": "no_local_mapping"},
            client_factory=lambda: _SharedFakeClient(
                provider_entered=provider_entered,
                release_provider=release_provider,
                call_count=call_count,
                fail_first=fail_first,
            ),
            official_health=HEALTH,
            reservation_lease_seconds=5,
            reservation_wait_seconds=8,
            reservation_poll_seconds=0.02,
        )
        if barrier is not None:
            barrier.wait(timeout=10)
        result = service.create_snapshot(
            authenticated_user_id="user-a", scan_id="multiprocess-scan", scan_revision=0)
        result_queue.put({"ok": True, "digest": result["snapshot_digest"], "pid": os.getpid()})
    except BaseException as error:
        result_queue.put({"ok": False, "code": getattr(error, "code", None),
                          "error": f"{type(error).__name__}: {error}", "pid": os.getpid()})
    finally:
        if sql is not None:
            sql.close()


class FdcCandidateSearchMultiprocessTests(unittest.TestCase):
    @staticmethod
    def _stop_worker(worker):
        if worker.pid is not None:
            if worker.is_alive():
                worker.terminate()
            worker.join(5)

    def test_two_processes_share_one_search_and_restarted_process_replays_snapshot(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "candidate-search.sqlite3")
            setup_sql = SqliteDatabase(path)
            scan = NutritionScanContextRepository(setup_sql)
            FdcCandidateSnapshotRepository(setup_sql, scan_context_repository=scan)
            scan.save_scan_context(
                user_id="user-a", scan_id="multiprocess-scan", scan_revision=0,
                items=[ITEM], ttl_seconds=120,
            )
            setup_sql.close()

            barrier = context.Barrier(2)
            provider_entered = context.Event()
            release_provider = context.Event()
            follower_joined = context.Event()
            call_count = context.Value("i", 0)
            results = context.Queue()
            workers = [context.Process(
                target=_candidate_worker,
                kwargs={
                    "path": path, "barrier": barrier,
                    "provider_entered": provider_entered,
                    "release_provider": release_provider,
                    "call_count": call_count,
                    "follower_joined": follower_joined,
                    "result_queue": results,
                },
            ) for _ in range(2)]
            for worker in workers:
                self.addCleanup(self._stop_worker, worker)
            try:
                for worker in workers:
                    worker.start()
                self.assertTrue(provider_entered.wait(10), "no process entered the fake provider")
                self.assertTrue(follower_joined.wait(10), "no process joined the active reservation")
            finally:
                release_provider.set()

            for worker in workers:
                worker.join(15)
                self.assertFalse(worker.is_alive(), "candidate worker did not exit")
                self.assertEqual(worker.exitcode, 0)
            results = [results.get(timeout=5), results.get(timeout=5)]
            self.assertTrue(all(result["ok"] for result in results), results)
            self.assertEqual(len({result["digest"] for result in results}), 1)
            self.assertEqual(len({result["pid"] for result in results}), 2)
            self.assertEqual(call_count.value, 3)

            replay_queue = context.Queue()
            replay = context.Process(
                target=_candidate_worker,
                kwargs={
                    "path": path, "barrier": None,
                    "provider_entered": provider_entered,
                    "release_provider": release_provider,
                    "call_count": call_count,
                    "follower_joined": follower_joined,
                    "result_queue": replay_queue,
                },
            )
            replay.start()
            self.addCleanup(self._stop_worker, replay)
            replay.join(15)
            self.assertFalse(replay.is_alive(), "restart replay worker did not exit")
            self.assertEqual(replay.exitcode, 0)
            replay_result = replay_queue.get(timeout=5)
            self.assertTrue(replay_result["ok"], replay_result)
            self.assertEqual(replay_result["digest"], results[0]["digest"])
            self.assertEqual(call_count.value, 3)

            verify_sql = SqliteDatabase(path)
            try:
                self.assertEqual(verify_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_snapshots"
                )["count"], 1)
                self.assertEqual(verify_sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_search_reservations"
                )["count"], 0)
            finally:
                verify_sql.close()

    def test_provider_failure_releases_reservation_for_immediate_retry(self):
        sql = SqliteDatabase(":memory:")
        try:
            scan = NutritionScanContextRepository(sql)
            snapshots = FdcCandidateSnapshotRepository(sql, scan_context_repository=scan)
            scan.save_scan_context(
                user_id="user-a", scan_id="retry-scan", scan_revision=0,
                items=[{**ITEM, "item_id": "retry-scan:0"}], ttl_seconds=120,
            )
            attempts = []

            class _FailOnceClient:
                def search_foods(self, query, *, deadline, page_size):
                    attempts.append(query)
                    if len(attempts) == 1:
                        raise FoodDataCentralClientError("upstream_error", "fake failure")
                    return {"candidates": [CANDIDATE]}

                def close(self):
                    pass

            service = FdcCandidateSearchService(
                scan_context_repository=scan,
                snapshot_repository=snapshots,
                local_lookup_factory=lambda _user_id: lambda _item: {"status": "no_local_mapping"},
                client_factory=_FailOnceClient,
                official_health=HEALTH,
                reservation_lease_seconds=5,
                reservation_wait_seconds=1,
                reservation_poll_seconds=0.01,
            )
            with self.assertRaises(FdcCandidateSearchError) as failed:
                service.create_snapshot(
                    authenticated_user_id="user-a", scan_id="retry-scan", scan_revision=0)
            self.assertEqual(getattr(failed.exception, "code", None), "upstream_error")
            self.assertEqual(sql.query_one(
                "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_search_reservations"
            )["count"], 1)
            failure = snapshots.get_search_reservation(
                user_id="user-a", scan_id="retry-scan", scan_revision=0)
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["error_code"], "upstream_error")

            result = service.create_snapshot(
                authenticated_user_id="user-a", scan_id="retry-scan", scan_revision=0)
            self.assertEqual(result["snapshot"]["items"][0]["candidates"][0]["fdcId"], "12345")
            self.assertEqual(len(attempts), 4)
            self.assertEqual(sql.query_one(
                "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_search_reservations"
            )["count"], 0)
        finally:
            sql.close()

    def test_failed_owner_notifies_concurrent_followers_without_serial_retry_storm(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "candidate-search-failure.sqlite3")
            setup_sql = SqliteDatabase(path)
            scan = NutritionScanContextRepository(setup_sql)
            FdcCandidateSnapshotRepository(setup_sql, scan_context_repository=scan)
            scan.save_scan_context(
                user_id="user-a", scan_id="multiprocess-scan", scan_revision=0,
                items=[ITEM], ttl_seconds=120,
            )
            setup_sql.close()

            barrier = context.Barrier(2)
            provider_entered = context.Event()
            release_provider = context.Event()
            follower_joined = context.Event()
            call_count = context.Value("i", 0)
            results = context.Queue()
            workers = [context.Process(
                target=_candidate_worker,
                kwargs={
                    "path": path, "barrier": barrier,
                    "provider_entered": provider_entered,
                    "release_provider": release_provider,
                    "call_count": call_count,
                    "follower_joined": follower_joined,
                    "result_queue": results,
                    "fail_first": True,
                },
            ) for _ in range(2)]
            for worker in workers:
                self.addCleanup(self._stop_worker, worker)
            try:
                for worker in workers:
                    worker.start()
                self.assertTrue(provider_entered.wait(10), "no process entered the fake provider")
                self.assertTrue(follower_joined.wait(10), "no process joined the active reservation")
            finally:
                release_provider.set()

            for worker in workers:
                worker.join(15)
                self.assertFalse(worker.is_alive(), "failed candidate worker did not exit")
                self.assertEqual(worker.exitcode, 0)
            failures = [results.get(timeout=5), results.get(timeout=5)]
            self.assertTrue(all(not result["ok"] for result in failures), failures)
            self.assertTrue(all(result["code"] == "upstream_error" for result in failures), failures)
            self.assertEqual(call_count.value, 1)

            retry_queue = context.Queue()
            retry = context.Process(
                target=_candidate_worker,
                kwargs={
                    "path": path, "barrier": None,
                    "provider_entered": provider_entered,
                    "release_provider": release_provider,
                    "call_count": call_count,
                    "follower_joined": follower_joined,
                    "result_queue": retry_queue,
                },
            )
            retry.start()
            self.addCleanup(self._stop_worker, retry)
            retry.join(15)
            self.assertFalse(retry.is_alive(), "retry worker did not exit")
            self.assertEqual(retry.exitcode, 0)
            retried = retry_queue.get(timeout=5)
            self.assertTrue(retried["ok"], retried)
            self.assertEqual(call_count.value, 4)

    def test_terminated_owner_is_reclaimed_after_durable_lease_expiry(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "candidate-search-crash.sqlite3")
            sql = SqliteDatabase(path)
            scan = NutritionScanContextRepository(sql, clock=lambda: 1000.0)
            FdcCandidateSnapshotRepository(sql, scan_context_repository=scan, clock=lambda: 1000.0)
            scan.save_scan_context(
                user_id="user-a", scan_id="multiprocess-scan", scan_revision=0,
                items=[ITEM], ttl_seconds=120,
            )
            sql.close()
            entered, release, joined = context.Event(), context.Event(), context.Event()
            calls = context.Value("i", 0)
            owner = context.Process(target=_candidate_worker, kwargs={
                "path": path, "barrier": None, "provider_entered": entered,
                "release_provider": release, "call_count": calls,
                "follower_joined": joined, "result_queue": context.Queue(), "wall_time": 1000.0,
            })
            owner.start()
            self.addCleanup(self._stop_worker, owner)
            try:
                self.assertTrue(entered.wait(10), "owner did not enter the blocked provider")
            finally:
                self._stop_worker(owner)
            self.assertEqual(calls.value, 1)

            sql = SqliteDatabase(path)
            try:
                pending = sql.query_one("SELECT status, lease_expires_at "
                                        "FROM nutrition_fdc_candidate_search_reservations")
                self.assertEqual(pending["status"], "pending")
                self.assertEqual(pending["lease_expires_at"], 1005.0)
                self.assertEqual(sql.query_one(
                    "SELECT COUNT(*) AS count FROM nutrition_fdc_candidate_snapshots"
                )["count"], 0)
            finally:
                sql.close()

            # Advance the repository clock, rather than sleeping for a real lease.
            # A killed process may leave its multiprocessing synchronization
            # primitives unusable. The restarted worker gets fresh events.
            successor_release = context.Event()
            successor_release.set()
            outcome = context.Queue()
            successor = context.Process(target=_candidate_worker, kwargs={
                "path": path, "barrier": None, "provider_entered": context.Event(),
                "release_provider": successor_release, "call_count": calls,
                "follower_joined": context.Event(), "result_queue": outcome, "wall_time": 1006.0,
            })
            successor.start()
            self.addCleanup(self._stop_worker, successor)
            successor.join(15)
            self.assertFalse(successor.is_alive(), "successor did not exit")
            self.assertEqual(successor.exitcode, 0)
            self.assertTrue(outcome.get(timeout=5)["ok"])
            self.assertEqual(calls.value, 4)

    def test_follower_polling_uses_one_claim_transaction_and_does_not_retry(self):
        sql = SqliteDatabase(":memory:")
        try:
            scan = NutritionScanContextRepository(sql)
            snapshots = FdcCandidateSnapshotRepository(sql, scan_context_repository=scan)
            scan.save_scan_context(
                user_id="user-a", scan_id="multiprocess-scan", scan_revision=0,
                items=[ITEM], ttl_seconds=120,
            )
            snapshots.reserve_search(user_id="user-a", scan_id="multiprocess-scan",
                                     scan_revision=0, lease_owner="active-owner")
            service = FdcCandidateSearchService(
                scan_context_repository=scan, snapshot_repository=snapshots,
                local_lookup_factory=lambda _user: self.fail("follower ran local lookup"),
                client_factory=lambda: self.fail("follower constructed provider"),
                official_health=HEALTH,
                reservation_wait_seconds=0.06, reservation_poll_seconds=0.01,
            )
            with patch.object(sql, "transaction", wraps=sql.transaction) as transactions, \
                    patch.object(snapshots, "get_search_reservation",
                                 wraps=snapshots.get_search_reservation) as reads:
                with self.assertRaises(FdcCandidateSearchError) as waiting:
                    service.create_snapshot(authenticated_user_id="user-a",
                                            scan_id="multiprocess-scan", scan_revision=0)
                self.assertEqual(waiting.exception.code, "single_flight_timeout")
                self.assertEqual(transactions.call_count, 1)
                self.assertGreaterEqual(reads.call_count, 2)
        finally:
            sql.close()


if __name__ == "__main__":
    unittest.main()
