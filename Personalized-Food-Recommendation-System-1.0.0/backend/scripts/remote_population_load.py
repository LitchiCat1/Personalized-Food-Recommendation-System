"""Bounded burst and persistent-session testing of the seeded 100 accounts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
import json
from pathlib import Path
import random
import threading
import time

import psutil

from remote_capacity_test import summarize
from remote_population_test import BASE, Log, now, records_match, save_json, session


class LoadTest:
    def __init__(self, out, seconds, soak_seconds, population_source=None):
        self.out = out
        source = population_source or out
        self.population = json.loads((source / "population.json").read_text(encoding="utf-8"))
        self.accounts = self.population["accounts"]
        if len(self.accounts) != 100 or not all(a["verified"] and a["uid"] for a in self.accounts):
            raise ValueError("All 100 new accounts must have three verified records")
        with (source / "accounts_051-150.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.passwords = {r["account"]: r["password"] for r in csv.DictReader(handle)}
        self.load_id = datetime.now().strftime("%H%M%S")
        self.log = Log(out, f"load_requests_{self.load_id}.csv")
        self.stop, self.monitor_done = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.pending = set()
        self.phase, self.level = "login", 0
        self.seconds, self.soak_seconds = seconds, soak_seconds
        self.report = {"target": BASE, "started_at": now(), "load_id": self.load_id, "accounts": 100, "retained_records_per_account": 3, "stage_seconds_requested": seconds, "soak_seconds_requested": soak_seconds, "stages": [], "generator_resources": [], "stop_reason": None, "maximum_supported_users": None, "remote_resource_monitoring": False}

    def save(self):
        self.report["updated_at"] = now()
        self.report["health"] = summarize([r for r in self.log.rows if r["phase"] == "monitor"])
        self.report["outstanding_tokens"] = len(self.log.tokens)
        self.report["pending_temporary_records"] = len(self.pending)
        save_json(self.out / f"load_summary_{self.load_id}.json", self.report)

    def stop_for(self, reason):
        with self.lock:
            if not self.stop.is_set():
                self.report["stop_reason"] = reason
                print("LOAD STOP", reason, flush=True)
                self.stop.set()

    def login(self):
        with session() as client:
            for account in list(self.log.tokens):
                if not self.log.logout(client, account):
                    raise RuntimeError("Prior tracked token could not be logged out")
            ok, health, _, _ = self.log.retry(client, "GET", "/health", step="initial_health", phase="preflight")
            if not ok or not isinstance(health, dict) or health.get("status") != "ok":
                raise RuntimeError("Preflight health failed")
            self.report["initial_health"] = health
            next_auth = 0
            for index, item in enumerate(self.accounts):
                # Respect the default shared-IP authentication limit of 60/minute.
                self.stop.wait(max(0, next_auth-time.monotonic()))
                started = time.monotonic()
                account = item["account"]
                ok, data, status, _ = self.log.retry(client, "POST", "/auth/login", account, step="login", phase="login", json={"email": account, "password": self.passwords[account]})
                next_auth = started + 1.1
                if not ok:
                    raise RuntimeError(f"Login failed: {account}, status {status}")
                _, uid = self.log.remember(account, data)
                if uid != item["uid"]:
                    raise RuntimeError("Authentication UID differs from seeded account")
                if (index+1) % 10 == 0:
                    print(f"LOGIN {index+1}/100; only one preparation HTTP session retained", flush=True)
                self.save()

    def monitor(self):
        process = psutil.Process()
        process.cpu_percent(); psutil.cpu_percent()
        streak = 0
        with session() as client:
            while not self.monitor_done.is_set():
                ok, data, _, _ = self.log.call(client, "GET", "/health", step="health", phase="monitor", level=self.level, validate=lambda d: isinstance(d, dict) and d.get("status") == "ok")
                streak = 0 if ok else streak+1
                self.report["generator_resources"].append({"timestamp": now(), "phase": self.phase, "concurrency": self.level, "local_process_cpu_percent": process.cpu_percent(), "local_host_cpu_percent": psutil.cpu_percent(), "local_process_rss_mb": round(process.memory_info().rss/1024**2, 2), "server_started_at": data.get("started_at") if isinstance(data, dict) else None})
                if streak >= 3:
                    self.stop_for("three consecutive failed health checks")
                if isinstance(data, dict) and data.get("started_at") != self.report["initial_health"].get("started_at"):
                    self.stop_for("server restart observed during load test")
                phase, level = self.phase, self.level
                recent = [r for r in self.log.rows if r["phase"] == phase and r["concurrency"] == level and r["elapsed_s"] >= time.perf_counter()-self.log.start-30]
                if len(recent) >= 30 and sum(r["status"] >= 500 for r in recent)/len(recent) > .05:
                    self.stop_for("HTTP 5xx exceeded 5% over the last 30 seconds")
                if self.phase in ("steady", "soak") and len(recent) >= 30 and sum(not r["ok"] for r in recent)/len(recent) > .05:
                    self.stop_for("persistent business errors exceeded 5% over the last 30 seconds")
                self.monitor_done.wait(5)

    def authorized_session(self, item):
        client = session()
        client.headers["Authorization"] = "Bearer " + self.log.tokens[item["account"]]["token"]
        return client

    def cycle(self, item, client, phase, level, number, first_request=False):
        account, uid = item["account"], item["uid"]
        rid = f"temp100_{self.out.name}_{self.load_id}_{account[-3:]}_{phase}_{number}"
        food = dict(item["records"][number % 3]["foods"][0])
        def call(method, path, step, **kwargs):
            return self.log.call(client, method, path, account, step, phase, level, **kwargs)
        if first_request:
            ok, _, _, _ = call("GET", "/auth/user", "fresh_session_first_request", validate=lambda d: isinstance(d, dict) and d.get("user", {}).get("id") == uid)
            if not ok or self.stop.is_set():
                return False
        results = []
        results.append(call("GET", "/search/food", "search_food", params={"q": "雞", "user_id": uid, "limit": 5}, validate=lambda d: isinstance(d, dict) and isinstance(d.get("results"), list))[0])
        results.append(call("GET", f"/records/{uid}", "read_seed_records", params={"limit": 500}, validate=lambda d: records_match(d, item["records"]))[0])
        results.append(call("GET", f"/history/{uid}", "history", params={"days": 7}, validate=lambda d: isinstance(d, dict) and isinstance(d.get("daily"), list))[0])
        if not all(results) or self.stop.is_set():
            return False
        with self.lock:
            self.pending.add((account, uid, rid))
        deleted = False
        try:
            ok, _, _, _ = call("POST", "/record", "temp_create", expected=(201,), record_id=rid, json={"user_id": uid, "client_record_id": rid, "meal_type": "午餐", "foods": [food], "source": "manual"}, validate=lambda d: isinstance(d, dict) and d.get("record", {}).get("client_record_id") == rid)
            results.append(ok)
            if not ok:
                return False
            changed = {**food, "calories": round(food["calories"]+17, 2)}
            results.append(call("PATCH", f"/records/{uid}/{rid}", "temp_update", record_id=rid, json={"foods": [changed]}, validate=lambda d: isinstance(d, dict) and abs(float(d.get("record", {}).get("total_calories", -1))-changed["calories"]) < .011)[0])
            results.append(call("GET", f"/records/{uid}", "verify_updated_record", params={"limit": 500}, record_id=rid, validate=lambda d: records_match(d, item["records"]) and sum(r.get("client_record_id") == rid and abs(float(r.get("total_calories", -1))-changed["calories"]) < .011 for r in d.get("records", [])) == 1)[0])
            deleted, _, _, _ = call("DELETE", f"/records/{uid}/{rid}", "temp_delete", record_id=rid)
            results.append(deleted)
            return all(results)
        finally:
            if not deleted:
                deleted, _, _, _ = self.log.call(client, "DELETE", f"/records/{uid}/{rid}", account, "cleanup_uncertain_temp", "cleanup", level, expected=(200, 404), record_id=rid)
            if deleted:
                with self.lock:
                    self.pending.discard((account, uid, rid))

    def stage(self, level, phase):
        self.phase, self.level = phase, level
        clients = [(item, self.authorized_session(item)) for item in self.accounts[:level]]
        failed_users, cycles, successful_users = set(), 0, set()
        start_rows = len(self.log.rows)
        warmed = True
        begin = time.perf_counter()
        try:
            if phase != "burst":
                def warm(pair):
                    item, client = pair
                    return self.log.call(client, "GET", "/auth/user", item["account"], "fresh_session_first_request", "warmup", level, validate=lambda d: isinstance(d, dict) and d.get("user", {}).get("id") == item["uid"])[0]
                with ThreadPoolExecutor(max_workers=min(5, level)) as pool:
                    warmed = all(list(pool.map(warm, clients)))
                if not warmed:
                    self.report["stages"].append({"phase": phase, "concurrency": level, "started": False, "completed": False, "reason": "warmup connection failed", "reference_pass": False, "warmup": summarize([r for r in self.log.rows[start_rows:] if r["phase"] == "warmup"])})
                    self.save()
                    print(f"STAGE {phase} {level}: warmup connection failed; business load not started", flush=True)
                    return False
            begin = time.perf_counter()
            requested = self.soak_seconds if phase == "soak" else self.seconds
            deadline = begin + requested
            barrier = threading.Barrier(level)
            def worker(pair):
                nonlocal cycles
                item, client = pair
                barrier.wait(timeout=30)
                number = 0
                while not self.stop.is_set():
                    ok = self.cycle(item, client, phase, level, number, first_request=(phase == "burst"))
                    with self.lock:
                        cycles += 1
                        if ok:
                            successful_users.add(item["account"])
                        else:
                            failed_users.add(item["account"])
                    number += 1
                    if phase == "burst" or time.perf_counter() >= deadline:
                        break
                    self.stop.wait(min(random.uniform(4, 6), max(0, deadline-time.perf_counter())))
                    if time.perf_counter() >= deadline:
                        break
            with ThreadPoolExecutor(max_workers=level) as pool:
                list(pool.map(worker, clients))
            duration = time.perf_counter()-begin
            rows = [r for r in self.log.rows[start_rows:] if r["phase"] == phase and r["concurrency"] == level]
            measured = summarize(rows, duration)
            complete = not self.stop.is_set() and (phase == "burst" or duration >= requested*.98)
            passed = complete and measured["requests"] > 0 and measured["failed"]/measured["requests"] < .01 and measured["p95_ms"] < 2000 and len(failed_users)/level < .01 and len(successful_users) == level
            stage = {"phase": phase, "concurrency": level, "started": True, "completed": complete, "reference_pass": passed, "cycle_count": cycles, "users_with_failed_cycles": len(failed_users), "users_with_successful_cycles": len(successful_users), **measured}
            if phase == "burst":
                stage["first_request"] = summarize([r for r in rows if r["step"] == "fresh_session_first_request"])
                stage["later_api"] = summarize([r for r in rows if r["step"] != "fresh_session_first_request"])
            self.report["stages"].append(stage)
            print("STAGE", json.dumps(stage, ensure_ascii=True), flush=True)
            self.save()
            return passed
        finally:
            for _, client in clients:
                client.close()

    def cleanup(self):
        checks = []
        with session() as client:
            for account, uid, rid in list(self.pending):
                client.headers["Authorization"] = "Bearer " + self.log.tokens[account]["token"]
                ok, _, _, _ = self.log.retry(client, "DELETE", f"/records/{uid}/{rid}", account, step="final_temp_delete", phase="cleanup", expected=(200, 404), record_id=rid)
                if ok:
                    self.pending.discard((account, uid, rid))
            for item in self.accounts:
                account = item["account"]
                if account not in self.log.tokens:
                    continue
                client.headers["Authorization"] = "Bearer " + self.log.tokens[account]["token"]
                ok, data, _, _ = self.log.retry(client, "GET", f"/records/{item['uid']}", account, step="final_seed_verification", phase="verification", params={"limit": 500}, validate=lambda d, a=item: records_match(d, a["records"]))
                temp_count = sum(r.get("client_record_id", "").startswith("temp100_") for r in data.get("records", [])) if ok else None
                checks.append({"account": account, "seed_records_valid": ok, "temporary_records_remaining": temp_count, "record_count": len(data.get("records", [])) if ok else None})
                self.log.logout(client, account)
            client.headers.pop("Authorization", None)
            ok, health, _, _ = self.log.retry(client, "GET", "/health", step="final_health", phase="verification")
            self.report["final_health"] = health if ok else None
        self.report["verification"] = {"accounts_checked": len(checks), "accounts_valid": sum(c["seed_records_valid"] and c["temporary_records_remaining"] == 0 and c["record_count"] == 3 for c in checks), "checks": checks, "pending_temporary_records": len(self.pending), "outstanding_tokens": len(self.log.tokens)}
        print("FINAL VERIFICATION", json.dumps({k: v for k, v in self.report["verification"].items() if k != "checks"}), flush=True)

    def run(self, burst_levels, steady_levels):
        monitor = None
        try:
            self.login()
            monitor = threading.Thread(target=self.monitor, daemon=True)
            monitor.start()
            for level in burst_levels:
                if self.stop.is_set():
                    break
                self.stage(level, "burst")
                self.stop.wait(5)
            highest_passed = 0
            for level in steady_levels:
                if self.stop.is_set():
                    break
                if not self.stage(level, "steady"):
                    self.report["steady_staircase_stopped_reason"] = f"{level} users did not pass reference; higher sustained levels not attempted"
                    break
                highest_passed = level
                self.stop.wait(5)
            if highest_passed and not self.stop.is_set():
                self.report["highest_tested_passing_steady_level"] = highest_passed
                self.report["soak_passed"] = self.stage(highest_passed, "soak")
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
            print("LOAD FINISHED", str(self.out / f"load_summary_{self.load_id}.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--burst-levels", default="1,5,10,20,30,50,75,100")
    parser.add_argument("--steady-levels", default="1,5,10,15,18,20,30,50,75,100")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--soak-seconds", type=int, default=180)
    args = parser.parse_args()
    burst = [int(v) for v in args.burst_levels.split(",") if v]
    steady = [int(v) for v in args.steady_levels.split(",") if v]
    if any(v < 1 or v > 100 for v in burst+steady) or not 10 <= args.seconds <= 120 or not 10 <= args.soak_seconds <= 300:
        raise SystemExit("Use 1-100 users, 10-120 second stages and 10-300 second soak")
    LoadTest(args.out.resolve(), args.seconds, args.soak_seconds).run(burst, steady)
