"""Locate the next repeatable quality failure using the existing test accounts.

All requests use the existing bounded CRUD flow. Authentication is paced and
performed only when another account is needed. No signup or retained writes.
"""

import argparse
from datetime import datetime
from pathlib import Path
import threading
import time

from remote_population_load import LoadTest
from remote_population_test import now, session


class BoundaryTest(LoadTest):
    def __init__(self, out, source, seconds=20, confirmation_seconds=60):
        out.mkdir(parents=True, exist_ok=False)
        super().__init__(out, seconds, confirmation_seconds, population_source=source)
        self.next_auth = 0
        self.attempts = {}
        self.report.update({
            "method": "adaptive boundary search; persistent independent account sessions; 7 CRUD requests per cycle; 4-6 seconds think time",
            "source_population": str(source), "max_accounts": 100,
            "confirmation_seconds": confirmation_seconds,
            "stage_seconds_requested": seconds,
            "reference": {"p95_ms_below": 2000, "request_failure_ratio_below": .01, "users_with_failed_cycles_ratio_below": .01},
            "note": "Highest passing level is specific to this client, route and workload. A warmup failure is not a sustained-business failure.",
        })

    def preflight(self):
        with session() as client:
            ok, health, _, _ = self.log.retry(client, "GET", "/health", step="initial_health", phase="preflight")
            if not ok or not isinstance(health, dict) or health.get("status") != "ok":
                raise RuntimeError("Preflight health failed")
            self.report["initial_health"] = health
            if health.get("app_version") != "v1.0.0":
                raise RuntimeError("Target version changed; previous capacity comparison is invalid")
            for account in list(self.log.tokens):
                if not self.log.logout(client, account):
                    raise RuntimeError("Could not recover tracked token")
        self.save()

    def ensure_accounts(self, count):
        with session() as client:
            for item in self.accounts[:count]:
                account = item["account"]
                if account in self.log.tokens:
                    continue
                if self.stop.is_set():
                    return False
                self.stop.wait(max(0, self.next_auth-time.monotonic()))
                started = time.monotonic()
                ok, data, status, _ = self.log.retry(client, "POST", "/auth/login", account,
                    step="login", phase="login", json={"email": account, "password": self.passwords[account]})
                self.next_auth = started+1.1
                if not ok:
                    raise RuntimeError(f"Authentication preparation failed with status {status}")
                _, uid = self.log.remember(account, data)
                if uid != item["uid"]:
                    raise RuntimeError("UID mismatch against original population")
                self.save()
                if len(self.log.tokens) % 10 == 0:
                    print(f"AUTH READY {len(self.log.tokens)}", flush=True)
        return not self.stop.is_set()

    def attempt(self, level, phase="steady", purpose="search"):
        if not self.ensure_accounts(level):
            return None
        self.attempts[level] = self.attempts.get(level, 0)+1
        index = len(self.log.rows)
        print(f"BOUNDARY TEST level={level} attempt={self.attempts[level]} purpose={purpose}", flush=True)
        passed = self.stage(level, phase)
        stage = self.report["stages"][-1]
        stage.update({"attempt": self.attempts[level], "purpose": purpose,
            "row_start": index, "row_end": len(self.log.rows), "finished_at": now()})
        self.save()
        self.stop.wait(1)
        return stage

    def search(self, fixed_levels=None):
        monitor = None
        try:
            self.preflight()
            # Do not retain the authentication connection while testing users.
            self.ensure_accounts(fixed_levels[0] if fixed_levels else 18)
            monitor = threading.Thread(target=self.monitor, daemon=True)
            monitor.start()
            if fixed_levels:
                self.report["requested_levels"] = fixed_levels
                self.report["method"] = "10-user increments; independent account HTTP sessions; 20-second business stages if all sessions warm; 7 CRUD calls per cycle; 4-6 second think time"
                passed, failed = [], []
                for level in fixed_levels:
                    if self.stop.is_set():
                        break
                    result = self.attempt(level, purpose="ten_user_step")
                    if result:
                        (passed if result["reference_pass"] else failed).append(level)
                highest = max(passed, default=None)
                self.report["short_test_passing_levels"] = passed
                self.report["failing_attempt_levels"] = failed
                self.report["highest_short_test_passing_level"] = highest
                if highest and not self.stop.is_set():
                    result = self.attempt(highest, phase="soak", purpose="confirm_highest_ten_user_step")
                    self.report["confirmation_passed"] = bool(result and result["reference_pass"])
                self.report["search_end"] = "Requested 10-user increments completed" if not self.stop.is_set() else "Stopped by monitoring"
                return
            passed = []
            failures = []
            baseline = self.attempt(18, purpose="baseline_recheck")
            if not baseline or not baseline["reference_pass"]:
                self.report["search_end"] = "18-user baseline did not pass; higher load not started"
                return
            passed.append(18)
            upper = None
            for level in (19, 20, 25, 40, 60, 80, 100):
                if self.stop.is_set():
                    break
                result = self.attempt(level)
                if not result:
                    break
                if result["reference_pass"]:
                    passed.append(level)
                    continue
                failures.append(level)
                retry = self.attempt(level, purpose="repeat_first_failure") if not self.stop.is_set() else None
                if retry and retry["reference_pass"]:
                    passed.append(level)
                    continue
                if retry:
                    failures.append(level)
                upper = level
                # Directly check 20 when the next level 19 fails, rather than
                # assuming a fixed cap from an untested neighbor.
                if level == 19 and not self.stop.is_set():
                    neighbor = self.attempt(20, purpose="check_above_first_boundary")
                    if neighbor and neighbor["reference_pass"]:
                        passed.append(20)
                        upper = None
                        continue
                    if neighbor:
                        failures.append(20)
                break
            lower = max(passed)
            while upper and upper-lower > 1 and not self.stop.is_set():
                middle = (lower+upper)//2
                result = self.attempt(middle, purpose="binary_refinement")
                if result and result["reference_pass"]:
                    passed.append(middle)
                    lower = middle
                elif result:
                    failures.append(middle)
                    upper = middle
                else:
                    break
            if not self.stop.is_set():
                confirmation = self.attempt(lower, phase="soak", purpose="confirm_highest_passing_level")
                self.report["confirmation_passed"] = bool(confirmation and confirmation["reference_pass"])
                if upper and not self.stop.is_set():
                    result = self.attempt(upper, purpose="final_boundary_recheck")
                    self.report["next_level_recheck_passed"] = bool(result and result["reference_pass"])
            self.report.update({"short_test_passing_levels": sorted(set(passed)),
                "failing_attempt_levels": failures, "highest_short_test_passing_level": lower,
                "adjacent_failing_level": upper,
                "search_end": "Adjacent boundary tested" if upper else "Reached 100 existing accounts without a repeated failure; upper limit not found"})
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
            print("BOUNDARY FINISHED", str(self.out / f"load_summary_{self.load_id}.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--confirm-seconds", type=int, default=60)
    parser.add_argument("--levels", help="Explicit levels, e.g. 20,30,40,50,60,70,80,90,100")
    args = parser.parse_args()
    if not 15 <= args.seconds <= 60 or not 30 <= args.confirm_seconds <= 180:
        raise SystemExit("Use 15-60 second search stages and 30-180 second confirmation")
    source = args.source.resolve()
    levels = [int(n) for n in args.levels.split(",")] if args.levels else None
    if levels and (any(n < 1 or n > 100 for n in levels) or levels != sorted(set(levels))):
        raise SystemExit("Explicit levels must be increasing unique values from 1 to 100")
    out = args.out or source.parent / ("boundary-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    BoundaryTest(out.resolve(), source, args.seconds, args.confirm_seconds).search(levels)
