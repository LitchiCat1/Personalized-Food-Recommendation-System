"""Create the authorized 100 test accounts and seed retained manual food records.

Only the designated remote host and accounts 051-150 are used. Logs exclude
credentials; outstanding tokens are kept separately for recoverable logout.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import threading
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://node.taile9a8dc.ts.net"
TAIPEI = timezone(timedelta(hours=8))
NUTRIENTS = ("calories", "protein", "carbs", "fat", "sodium", "fiber", "sugar", "saturated_fat", "trans_fat")
FIELDS = ["timestamp", "elapsed_s", "phase", "concurrency", "account", "step", "status", "ok", "latency_ms", "error_type", "error_detail", "record_id"]


def now():
    return datetime.now(TAIPEI).isoformat(timespec="milliseconds")


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def session():
    client = requests.Session()
    client.trust_env = False
    return client


class Log:
    def __init__(self, out, filename):
        self.out = out
        self.start = time.perf_counter()
        self.rows = []
        self.lock = threading.Lock()
        path = out / filename
        existing = path.exists() and path.stat().st_size > 0
        self.file = path.open("a", encoding="utf-8-sig", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=FIELDS)
        if not existing:
            self.writer.writeheader()
        self.tokens_path = out / "_active_sessions.json"
        self.tokens = json.loads(self.tokens_path.read_text(encoding="utf-8")) if self.tokens_path.exists() else {}

    def call(self, client, method, path, account="", step="health", phase="setup", level=0, expected=(200,), validate=None, record_id="", **kwargs):
        begin = time.perf_counter()
        status, data, error_type, detail, retry = 0, None, "", "", None
        try:
            response = client.request(method, BASE + path, timeout=(8, 15), allow_redirects=False, **kwargs)
            status = response.status_code
            retry = response.headers.get("Retry-After")
            try:
                data = response.json() if response.content else None
            except ValueError:
                error_type = "InvalidJSON"
            if status not in expected:
                error_type = f"HTTP_{status}"
                detail = str(data.get("error", ""))[:250] if isinstance(data, dict) else ""
            elif validate and not validate(data):
                error_type = "ValidationError"
        except requests.RequestException as exc:
            error_type, detail = type(exc).__name__, str(exc)[:500]
        ok = status in expected and not error_type
        row = {"timestamp": now(), "elapsed_s": round(time.perf_counter()-self.start, 3), "phase": phase, "concurrency": level, "account": account, "step": step, "status": status, "ok": ok, "latency_ms": round((time.perf_counter()-begin)*1000, 2), "error_type": error_type, "error_detail": detail, "record_id": record_id}
        with self.lock:
            self.rows.append(row)
            self.writer.writerow(row)
            self.file.flush()
        return ok, data, status, retry

    def retry(self, *args, **kwargs):
        for attempt in range(5):
            result = self.call(*args, **kwargs)
            if result[0] or (result[2] not in (0, 429, 502, 503, 504)):
                return result
            if attempt < 4:
                delay = min(120, max(2, int(result[3]))) if str(result[3]).isdigit() else 2 + attempt*2
                print(f"SETUP RETRY status={result[2]} wait={delay}s step={kwargs.get('step')}", flush=True)
                # Keep each wait bounded so the caller can observe progress.
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    time.sleep(min(20, end-time.monotonic()))
        return result

    def remember(self, account, data):
        token, uid = data.get("access_token"), data.get("user", {}).get("id")
        if not token or not uid or data.get("user", {}).get("email") != account:
            raise RuntimeError(f"Invalid authentication response for {account}")
        with self.lock:
            self.tokens[account] = {"token": token, "uid": uid, "issued_at": now()}
            save_json(self.tokens_path, self.tokens)
        return token, uid

    def logout(self, client, account):
        entry = self.tokens.get(account)
        if not entry:
            return True
        client.headers["Authorization"] = "Bearer " + entry["token"]
        ok, _, _, _ = self.retry(client, "POST", "/auth/logout", account, step="logout", phase="logout")
        if ok:
            with self.lock:
                self.tokens.pop(account, None)
                save_json(self.tokens_path, self.tokens)
        client.headers.pop("Authorization", None)
        return ok

    def close(self):
        self.file.close()


def initialize(out):
    path = out / "population.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    with (ROOT / "docs/stress-test/test_accounts_20261111.csv").open(encoding="utf-8-sig", newline="") as handle:
        password = next(csv.DictReader(handle))["password"]
    foods = list(json.loads((ROOT / "backend/nutrition_db.json").read_text(encoding="utf-8")).values())
    rng = random.Random(2026111102)
    accounts = []
    for index in range(51, 151):
        name = f"stress_test_20261111_{index:03d}"
        records = []
        for slot, meal in enumerate(("早餐", "午餐", "晚餐")):
            selected = []
            for food in rng.sample(foods, k=rng.randint(1, 3)):
                portion = rng.choice((.75, 1, 1.25, 1.5, 2))
                selected.append({"name": f"[壓測] {food['name_zh']} {portion*100:g}g", **{k: round(float(food.get(k, 0))*portion, 2) for k in NUTRIENTS}, "is_fried": False})
            timestamp = (datetime.now(TAIPEI)-timedelta(days=slot+1)).replace(hour=(8, 12, 18)[slot], minute=rng.randrange(60), second=0, microsecond=0).isoformat()
            records.append({"client_record_id": f"seed100_{out.name}_{index:03d}_{slot}", "meal_type": meal, "foods": selected, "timestamp": timestamp, "source": "manual"})
        accounts.append({"account": name, "status": "planned", "uid": None, "records": records, "verified": False})
    data = {"target": BASE, "created_at": now(), "retention": "Keep three seeded records per new account; no old account data modified", "accounts": accounts}
    with (out / "accounts_051-150.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["account", "password"])
        writer.writeheader()
        writer.writerows({"account": a["account"], "password": password} for a in accounts)
    save_json(path, data)
    return data


def records_match(data, expected):
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        return False
    records = data["records"]
    for record in expected:
        matches = [r for r in records if r.get("client_record_id") == record["client_record_id"]]
        if len(matches) != 1:
            return False
        if matches[0].get("meal_type") != record["meal_type"] or matches[0].get("source") != "manual":
            return False
        if [f.get("name") for f in matches[0].get("foods", [])] != [f["name"] for f in record["foods"]]:
            return False
        for nutrient in NUTRIENTS:
            total = round(sum(f[nutrient] for f in record["foods"]), 2)
            if abs(float(matches[0].get("total_"+nutrient, -1))-total) > .011:
                return False
    return True


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    population = initialize(out)
    with (out / "accounts_051-150.csv").open(encoding="utf-8-sig", newline="") as handle:
        passwords = {r["account"]: r["password"] for r in csv.DictReader(handle)}
    log, client = Log(out, "preparation_requests.csv"), session()
    summary = {"started_at": now(), "target": BASE, "accounts_requested": 100, "records_per_account": 3, "completed": False}
    try:
        # Recover only tokens created by this batch before resuming.
        for account in list(log.tokens):
            if not log.logout(client, account):
                raise RuntimeError("Could not logout a previously tracked session")
        ok, health, _, _ = log.retry(client, "GET", "/health", step="initial_health", validate=lambda d: isinstance(d, dict) and d.get("status") == "ok")
        if not ok:
            raise RuntimeError("Initial health check failed")
        summary["health"] = health
        ok, config, _, _ = log.retry(client, "GET", "/auth/config", step="signup_config")
        if not ok or config.get("signup") != "open":
            raise RuntimeError("Remote signup is not open")
        for item in population["accounts"]:
            if item["verified"]:
                continue
            account = item["account"]
            payload = {"email": account, "password": passwords[account]}
            client.headers.pop("Authorization", None)
            ok, auth, status, _ = log.retry(client, "POST", "/auth/signup", account, step="signup", expected=(201, 409), json=payload)
            if not ok:
                raise RuntimeError(f"Signup failed for {account}, status {status}")
            if status == 409:
                ok, auth, status, _ = log.retry(client, "POST", "/auth/login", account, step="recover_existing_account", json=payload)
                if not ok:
                    raise RuntimeError(f"Cannot recover designated account {account}")
                item["status"] = "existing_recovered"
            else:
                item["status"] = "created"
            token, uid = log.remember(account, auth)
            item["uid"] = uid
            save_json(out / "population.json", population)
            client.headers["Authorization"] = "Bearer " + token
            try:
                for record in item["records"]:
                    record_id = record["client_record_id"]
                    ok, _, status, _ = log.retry(client, "POST", "/record", account, step="seed_manual_record", expected=(200, 201), json={**record, "user_id": uid}, record_id=record_id, validate=lambda d, rid=record_id: isinstance(d, dict) and d.get("record", {}).get("client_record_id") == rid)
                    if not ok:
                        raise RuntimeError(f"Seed failed for {account}, status {status}")
                ok, _, _, _ = log.retry(client, "GET", f"/records/{uid}", account, step="verify_three_records", params={"limit": 500}, validate=lambda d: records_match(d, item["records"]))
                if not ok:
                    raise RuntimeError(f"Record verification failed for {account}")
                item["verified"] = True
                item["verified_at"] = now()
                save_json(out / "population.json", population)
                print(f"PREPARED {sum(a['verified'] for a in population['accounts'])}/100 {account} retained_records=3", flush=True)
            finally:
                if not log.logout(client, account):
                    raise RuntimeError(f"Logout failed for {account}; token retained for recovery")
        summary["completed"] = True
    except Exception as exc:
        summary["stop_reason"] = f"{type(exc).__name__}: {exc}"
        print("PREPARATION STOP", summary["stop_reason"], flush=True)
    finally:
        client.close()
        summary.update({"finished_at": now(), "accounts_created_or_recovered": sum(a["uid"] is not None for a in population["accounts"]), "accounts_verified": sum(a["verified"] for a in population["accounts"]), "retained_records_verified": 3*sum(a["verified"] for a in population["accounts"]), "outstanding_tokens": len(log.tokens)})
        save_json(out / "preparation_summary.json", summary)
        log.close()
        print("PREPARATION RESULT", json.dumps({k: v for k, v in summary.items() if k != "health"}, ensure_ascii=True), flush=True)
    return 0 if summary["completed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare",))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(prepare(args.out.resolve()))
