"""Bounded remote load test with persistent sessions and immediate CSV logging.

Run only against the authorized test host with the dedicated account CSV.
No profiles, real records, third-party APIs, or account settings are changed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import statistics
import threading
import time
import uuid

import psutil
import requests

BASE = "https://node.taile9a8dc.ts.net"
ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))
FIELDS = ["timestamp", "elapsed_s", "phase", "concurrency", "user_index", "step", "status", "ok", "latency_ms", "error_type", "error_detail", "validation_error"]


def quantile(values, fraction):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * fraction
    lo = int(k)
    return round(v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (k - lo), 2)


def summarize(rows, duration=None):
    values = [r["latency_ms"] for r in rows]
    success = sum(r["ok"] for r in rows)
    return {
        "requests": len(rows), "success": success, "failed": len(rows) - success,
        "success_pct": round(100 * success / len(rows), 3) if rows else None,
        "p50_ms": quantile(values, .5), "p95_ms": quantile(values, .95),
        "p99_ms": quantile(values, .99), "max_ms": max(values) if values else None,
        "duration_s": round(duration, 3) if duration else None,
        "rps": round(len(rows) / duration, 3) if duration else None,
    }


class Experiment:
    def __init__(self, out):
        self.start = time.perf_counter()
        self.rows = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.monitor_done = threading.Event()
        self.stage = "preparation"
        self.level = 0
        self.reason = None
        self.pending = set()
        self.clients = []
        self.resources = []
        self.checkpoints = []
        self.monitor_client = requests.Session()
        self.monitor_client.trust_env = False
        self.file = (out / "requests.csv").open("w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.file, fieldnames=FIELDS)
        self.writer.writeheader()
        self.out = out
        self.report = {
            "run_id": out.name, "target": BASE, "started_at": datetime.now(TAIPEI).isoformat(),
            "method": "persistent HTTP sessions; 7 operations per cycle; 4-6 s think time after each cycle",
            "server_resource_monitoring": False, "stages": [],
        }

    def request(self, session, method, path, user_index=-1, step="health", expected=(200,), validate=None, phase=None, level=None, **kwargs):
        phase = phase or self.stage
        level = self.level if level is None else level
        start = time.perf_counter()
        error_type = ""
        error_detail = ""
        validation_error = ""
        status = 0
        data = None
        retry_after = None
        try:
            response = session.request(method, BASE + path, timeout=(10, 20), **kwargs)
            status = response.status_code
            retry_after = response.headers.get("Retry-After")
            if response.content:
                try:
                    data = response.json()
                except ValueError:
                    error_type = "InvalidJSON"
            if status not in expected:
                error_type = f"HTTP_{status}"
            elif validate and not validate(data):
                validation_error = "response_contract_mismatch"
                error_type = "ValidationError"
        except requests.RequestException as exc:
            error_type = type(exc).__name__
            error_detail = str(exc)[:600]
        ok = status in expected and not error_type
        row = {
            "timestamp": datetime.now(TAIPEI).isoformat(timespec="milliseconds"),
            "elapsed_s": round(time.perf_counter() - self.start, 3),
            "phase": phase, "concurrency": level, "user_index": user_index,
            "step": step, "status": status, "ok": ok,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error_type": error_type, "error_detail": error_detail, "validation_error": validation_error,
        }
        with self.lock:
            self.rows.append(row)
            self.writer.writerow(row)
            self.file.flush()
        return ok, data, status, retry_after

    def stop_for(self, reason):
        if not self.stop.is_set():
            self.reason = reason
            print("STOP:", reason, flush=True)
            self.stop.set()

    def monitor(self):
        process = psutil.Process()
        process.cpu_percent()
        psutil.cpu_percent()
        streak = 0
        while not self.monitor_done.is_set():
            ok, data, _, _ = self.request(self.monitor_client, "GET", "/health", phase="monitor", validate=lambda d: isinstance(d, dict) and d.get("status") == "ok")
            streak = 0 if ok else streak + 1
            with self.lock:
                self.resources.append({
                    "timestamp": datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    "elapsed_s": round(time.perf_counter() - self.start, 3),
                    "phase": self.stage, "concurrency": self.level,
                    "generator_cpu_percent": process.cpu_percent(),
                    "generator_host_cpu_percent": psutil.cpu_percent(),
                    "generator_rss_mb": round(process.memory_info().rss / 1024**2, 2),
                    "server_started_at": data.get("started_at") if isinstance(data, dict) else None,
                })
                recent = [r for r in self.rows if r["phase"] in ("load", "soak") and r["elapsed_s"] >= time.perf_counter() - self.start - 30]
            if streak >= 3:
                self.stop_for("three consecutive failed health probes")
            if len(recent) >= 30 and sum(not r["ok"] for r in recent) / len(recent) > .05:
                self.stop_for("business request failure rate exceeded 5% over the recent 30-second window")
            self.monitor_done.wait(5)

    def prepare(self, account, index):
        session = requests.Session()
        session.trust_env = False
        ok, data, _, _ = self.request(
            session, "POST", "/auth/login", index, "login", phase="preparation",
            json={"email": account["account"], "password": account["password"]},
            validate=lambda d: isinstance(d, dict) and bool(d.get("access_token")) and bool(d.get("user", {}).get("id")),
        )
        if not ok:
            session.close()
            return None
        session.headers["Authorization"] = "Bearer " + data["access_token"]
        client = {"index": index, "session": session, "uid": data["user"]["id"]}
        # Register every successful login immediately so cleanup also covers preparation failures.
        with self.lock:
            self.clients.append(client)
        ok, before, _, _ = self.request(session, "GET", f"/records/{client['uid']}", index, "baseline", phase="preparation", params={"limit": 500})
        if not ok or not isinstance(before, dict):
            return None
        client["before_ids"] = sorted(r.get("client_record_id", "") for r in before.get("records", []))
        return client

    def cycle(self, client, level, phase, number):
        session, uid, index = client["session"], client["uid"], client["index"]
        record_id = f"stress_{self.out.name}_{index}_{number}_{uuid.uuid4().hex[:6]}"
        food = {"name": "壓測測試餐", "calories": 100, "protein": 5, "carbs": 10, "fat": 2, "sodium": 50, "fiber": 1, "sugar": 2, "saturated_fat": 1, "trans_fat": 0, "is_fried": False}
        def call(method, path, step, **kwargs):
            return self.request(session, method, path, index, step, phase=phase, level=level, **kwargs)
        call("GET", "/search/food", "search_food", params={"q": "雞", "user_id": uid, "limit": 5}, validate=lambda d: isinstance(d, dict) and isinstance(d.get("results"), list))
        call("GET", f"/records/{uid}", "records_before", validate=lambda d: isinstance(d, dict) and isinstance(d.get("records"), list))
        call("GET", f"/history/{uid}", "history", params={"days": 7}, validate=lambda d: isinstance(d, dict) and isinstance(d.get("daily"), list))
        with self.lock:
            self.pending.add((index, record_id))
        deleted = False
        try:
            ok, _, _, _ = call("POST", "/record", "record_create", expected=(201,), json={"user_id": uid, "client_record_id": record_id, "meal_type": "午餐", "foods": [food], "source": "manual"}, validate=lambda d: isinstance(d, dict) and d.get("record", {}).get("client_record_id") == record_id)
            if ok:
                changed = {**food, "calories": 120}
                call("PATCH", f"/records/{uid}/{record_id}", "record_update", json={"foods": [changed]}, validate=lambda d: isinstance(d, dict) and d.get("record", {}).get("total_calories") == 120)
                call("GET", f"/records/{uid}", "records_after", params={"limit": 500}, validate=lambda d: isinstance(d, dict) and sum(r.get("client_record_id") == record_id and r.get("total_calories") == 120 for r in d.get("records", [])) == 1)
                deleted, _, _, _ = call("DELETE", f"/records/{uid}/{record_id}", "record_delete")
        finally:
            if deleted:
                with self.lock:
                    self.pending.discard((index, record_id))
            else:
                ok, _, _, _ = self.request(session, "DELETE", f"/records/{uid}/{record_id}", index, "record_cleanup", expected=(200, 404), phase="cleanup", level=level)
                if ok:
                    with self.lock:
                        self.pending.discard((index, record_id))

    def run_stage(self, level, seconds, phase="load"):
        self.stage, self.level = "warmup", level
        selected = sorted(self.clients, key=lambda c: c["index"])[:level]
        with ThreadPoolExecutor(max_workers=5) as pool:
            warmed = list(pool.map(lambda c: self.request(c["session"], "GET", "/auth/user", c["index"], "warmup", phase="warmup", level=level)[0], selected))
        if not all(warmed):
            self.stop_for("warmup failed")
            return
        self.stage = phase
        begin = time.perf_counter()
        deadline = begin + seconds
        barrier = threading.Barrier(level)
        def worker(client):
            barrier.wait(timeout=20)
            counter = 0
            while time.perf_counter() < deadline and not self.stop.is_set():
                self.cycle(client, level, phase, counter)
                counter += 1
                # The model includes human think time and keeps writes below per-account limits.
                remaining = min(random.uniform(4, 6), max(0, deadline - time.perf_counter()))
                self.stop.wait(remaining)
        with ThreadPoolExecutor(max_workers=level) as pool:
            list(pool.map(worker, selected))
        duration = time.perf_counter() - begin
        with self.lock:
            rows = [r for r in self.rows if r["phase"] == phase and r["concurrency"] == level]
        summary = {"phase": phase, "concurrency": level, **summarize(rows, duration)}
        self.report["stages"].append(summary)
        self.save()
        print(json.dumps(summary, ensure_ascii=True), flush=True)

    def cleanup(self):
        self.stage = "cleanup"
        checks = []
        for client in sorted(self.clients, key=lambda c: c["index"]):
            session, uid, index = client["session"], client["uid"], client["index"]
            for pending_index, record_id in list(self.pending):
                if index != pending_index:
                    continue
                ok, _, _, retry = self.request(session, "DELETE", f"/records/{uid}/{record_id}", index, "final_delete", expected=(200, 404), phase="cleanup")
                if not ok and retry:
                    time.sleep(min(60, max(1, int(retry))))
                    ok, _, _, _ = self.request(session, "DELETE", f"/records/{uid}/{record_id}", index, "final_delete_retry", expected=(200, 404), phase="cleanup")
                if ok:
                    self.pending.discard((index, record_id))
            ok, data, _, _ = self.request(session, "GET", f"/records/{uid}", index, "baseline_verification", phase="cleanup", params={"limit": 500})
            after = sorted(r.get("client_record_id", "") for r in data.get("records", [])) if ok and isinstance(data, dict) else None
            checks.append({"user_index": index, "baseline_match": after is not None and after == client.get("before_ids"), "before_count": len(client["before_ids"]) if "before_ids" in client else None, "after_count": len(after) if after is not None else None})
            self.request(session, "POST", "/auth/logout", index, "logout", phase="cleanup")
            session.close()
        self.report["cleanup"] = {"pending": len(self.pending), "checks": checks, "all_baselines_match": bool(checks) and all(c["baseline_match"] for c in checks)}

    def save(self):
        self.report["finished_at"] = datetime.now(TAIPEI).isoformat()
        self.report["stop_reason"] = self.reason
        self.report["monitor"] = summarize([r for r in self.rows if r["phase"] == "monitor"])
        self.report["generator_resources"] = self.resources
        self.report["request_count_by_phase"] = {p: sum(r["phase"] == p for r in self.rows) for p in dict.fromkeys(r["phase"] for r in self.rows)}
        (self.out / "summary.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-seconds", type=int, default=60)
    parser.add_argument("--soak-seconds", type=int, default=180)
    parser.add_argument("--levels", default="1,5,10,15,18")
    args = parser.parse_args()
    levels = sorted({int(v) for v in args.levels.split(",")})
    if not levels or min(levels) < 1 or max(levels) > 50:
        parser.error("levels must be within 1..50")
    if not 10 <= args.stage_seconds <= 180 or not 0 <= args.soak_seconds <= 600:
        parser.error("stage seconds must be 10..180; soak seconds 0..600")
    run_id = "persistent-" + datetime.now(TAIPEI).strftime("%Y%m%d-%H%M%S")
    out = ROOT / "docs" / "stress-test" / "runs" / run_id
    out.mkdir(parents=True)
    experiment = Experiment(out)
    monitor = None
    print("OUTPUT", out, flush=True)
    try:
        health = requests.get(BASE + "/health", timeout=20)
        health.raise_for_status()
        experiment.report["initial_health"] = health.json()
        with (ROOT / "docs" / "stress-test" / "test_accounts_20261111.csv").open(encoding="utf-8-sig", newline="") as handle:
            accounts = list(csv.DictReader(handle))
        if len(accounts) != 50 or any(not a["account"].startswith("stress_test_20261111_") for a in accounts):
            raise ValueError("Expected exactly the 50 designated test accounts")
        accounts = accounts[:max(levels)]
        experiment.report["requested_levels"] = levels
        experiment.report["active_account_count"] = len(accounts)
        print(f"Preparing persistent sessions for {len(accounts)} dedicated accounts", flush=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            prepared = list(pool.map(lambda x: experiment.prepare(x[1], x[0]), enumerate(accounts)))
        if any(c is None for c in prepared):
            raise RuntimeError("One or more accounts failed preparation; no load test started")
        monitor = threading.Thread(target=experiment.monitor, daemon=True)
        monitor.start()
        for level in levels:
            if experiment.stop.is_set():
                break
            print("STAGE", level, args.stage_seconds, flush=True)
            experiment.run_stage(level, args.stage_seconds)
        if not experiment.stop.is_set() and args.soak_seconds:
            print("SOAK", max(levels), args.soak_seconds, flush=True)
            experiment.run_stage(max(levels), args.soak_seconds, "soak")
    except (Exception, KeyboardInterrupt) as exc:
        experiment.stop_for(type(exc).__name__ + ": " + str(exc))
    finally:
        experiment.monitor_done.set()
        if monitor:
            monitor.join(timeout=35)
        try:
            experiment.cleanup()
        finally:
            experiment.save()
            experiment.file.close()
            experiment.monitor_client.close()
    print("FINISHED", json.dumps({"stop_reason": experiment.reason, "cleanup": experiment.report.get("cleanup")}, ensure_ascii=True), flush=True)
    return 0 if not experiment.reason and experiment.report.get("cleanup", {}).get("all_baselines_match") else 1


if __name__ == "__main__":
    raise SystemExit(main())
