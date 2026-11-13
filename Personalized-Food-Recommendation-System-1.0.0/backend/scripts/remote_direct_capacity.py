"""Bracket capacity with actual concurrent CRUD, without an all-user warmup gate."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from datetime import datetime
import random
import threading
import time

from remote_capacity_boundary import BoundaryTest
from remote_capacity_test import summarize
from remote_population_test import now


class DirectCapacityTest(BoundaryTest):
    def measure(self, level, seconds, purpose):
        if not self.ensure_accounts(level):
            return None
        index = len(self.report["stages"])
        phase = f"capacity_{index}"
        self.phase, self.level = phase, level
        clients = [(item, self.authorized_session(item)) for item in self.accounts[:level]]
        row_start = len(self.log.rows)
        barrier = threading.Barrier(level)
        cohort_failed = threading.Event()
        successful, failed = set(), set()
        cycles = 0
        begin = time.perf_counter()
        deadline = begin + seconds
        print(f"DIRECT CAPACITY {level} users, {seconds}s, {purpose}", flush=True)
        try:
            def worker(pair):
                nonlocal cycles
                item, client = pair
                barrier.wait(timeout=30)
                number = 0
                while not self.stop.is_set():
                    # Every user gets an initial attempt even if another fails.
                    ok = self.cycle(item, client, phase, level, number, first_request=(number == 0))
                    with self.lock:
                        cycles += 1
                        (successful if ok else failed).add(item["account"])
                    if not ok:
                        cohort_failed.set()
                    number += 1
                    if cohort_failed.is_set() or time.perf_counter() >= deadline:
                        break
                    cohort_failed.wait(min(random.uniform(4, 6), max(0, deadline-time.perf_counter())))
                    if cohort_failed.is_set() or time.perf_counter() >= deadline:
                        break
            with ThreadPoolExecutor(max_workers=level) as pool:
                list(pool.map(worker, clients))
            duration = time.perf_counter() - begin
            selected = [r for r in self.log.rows[row_start:] if r["phase"] == phase]
            first = [r for r in selected if r["step"] == "fresh_session_first_request"]
            later = [r for r in selected if r["step"] != "fresh_session_first_request"]
            stats = summarize(selected, duration)
            complete = duration >= seconds*.98 and not self.stop.is_set() and not cohort_failed.is_set()
            passed = (complete and stats["requests"] > 0 and stats["failed"]/stats["requests"] < .01
                and stats["p95_ms"] < 2000 and len(failed)/level < .01 and len(successful) == level)
            stage = {"phase": phase, "purpose": purpose, "concurrency": level, "requested_seconds": seconds,
                "started": True, "completed": complete, "reference_pass": passed, "cycle_count": cycles,
                "users_with_successful_cycles": len(successful), "users_with_failed_cycles": len(failed),
                "first_request": summarize(first), "later_api": summarize(later),
                "row_start": row_start, "row_end": len(self.log.rows), "finished_at": now(), **stats}
            self.report["stages"].append(stage)
            self.save()
            print("CAPACITY RESULT", json.dumps(stage, ensure_ascii=True), flush=True)
            return stage
        finally:
            for _, client in clients:
                client.close()
            self.stop.wait(1)

    def search_direct(self):
        monitor = None
        self.report.update({"method": "Adaptive coarse search then binary refinement; every account directly starts cold; independent sessions; 8 first-cycle requests then 7; 4-6 second think time",
            "note": "One failed user ends further cycles for that cohort after in-flight cycles finish. Health/restart/5xx global stops remain. No fixed system-wide capacity is inferred.",
            "search_seconds": self.seconds, "confirmation_seconds": self.soak_seconds})
        try:
            self.preflight()
            if not self.ensure_accounts(30):
                return
            monitor = threading.Thread(target=self.monitor, daemon=True)
            monitor.start()
            lower, upper = None, None
            for level in (30, 45, 70, 100):
                if self.stop.is_set():
                    return
                result = self.measure(level, self.seconds, "coarse_search")
                if result and result["reference_pass"]:
                    lower = level
                else:
                    upper = level
                    break
            if lower is None:
                for level in (20, 10, 1):
                    if self.stop.is_set():
                        return
                    result = self.measure(level, self.seconds, "find_current_baseline")
                    if result and result["reference_pass"]:
                        lower = level
                        break
                    upper = level
            if lower is None:
                self.report["search_end"] = "No passing baseline in this run"
                return
            while upper and upper-lower > 1 and not self.stop.is_set():
                middle = (lower+upper)//2
                result = self.measure(middle, self.seconds, "binary_refinement")
                if result and result["reference_pass"]:
                    lower = middle
                else:
                    upper = middle
            if self.stop.is_set():
                return
            confirmation = self.measure(lower, self.soak_seconds, "long_confirmation")
            self.report.update({"highest_short_passing_users": lower, "adjacent_failed_users": upper,
                "confirmation_passed": bool(confirmation and confirmation["reference_pass"]),
                "highest_confirmed_users": lower if confirmation and confirmation["reference_pass"] else None})
            if upper and not self.stop.is_set():
                recheck = self.measure(upper, self.seconds, "adjacent_failure_recheck")
                self.report["adjacent_failure_recheck_passed"] = bool(recheck and recheck["reference_pass"])
            self.report["search_end"] = "Bounded search finished; inspect confirmation and neighbor recheck for variability"
        except Exception as exc:
            self.stop_for(f"{type(exc).__name__}: {exc}")
        finally:
            self.monitor_done.set()
            if monitor:
                monitor.join(timeout=30)
            try:
                self.cleanup()
            except Exception as exc:
                self.report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            self.report["finished_at"] = now()
            self.save()
            self.log.close()
            print("DIRECT CAPACITY FINISHED", str(self.out / f"load_summary_{self.load_id}.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--confirm-seconds", type=int, default=120)
    args = parser.parse_args()
    if not 15 <= args.seconds <= 60 or not 60 <= args.confirm_seconds <= 180:
        raise SystemExit("Use 15-60 second search stages and 60-180 second confirmation")
    source = args.source.resolve()
    out = source.parent / ("direct-capacity-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    DirectCapacityTest(out, source, args.seconds, args.confirm_seconds).search_direct()
