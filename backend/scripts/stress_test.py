#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NutriLens 後端壓力測試腳本（零外部 API Key 消耗、自動備份與完整清理）

測試重點：
1. 多人同時使用完整流程（Mixed Read/Write User Journey）：
   模擬 N 位使用者在同一瞬間同時操作（更新健康檔案 -> 搜尋食物 -> 新增飲食紀錄 -> 修改紀錄 -> 查詢今日紀錄 -> 查詢 7 日歷史）。
2. 高併發 SQLite 寫入與鎖競爭（Pure DB Write & Lock Contention）：
   模擬 N 位使用者同時密集執行 POST /record、PATCH /records、DELETE /records，以及同筆紀錄高併發重複送出（Deduplication 競態測試）。
3. 多人同時登入（Concurrent Login / Bcrypt CPU 瓶頸與 IP 限流測試）：
   測試 bcrypt 密碼雜湊在多執行緒下的排隊延遲，以及同 IP 每分鐘 60 次限流保護。

安全性保證：
- 絕不呼叫任何會消耗 Gemini / OpenAI / Google Places 額度的路由。
- 測試前自動使用 SQLite 線上備份 API 建立備份。
- 所有測試資料皆使用獨立前綴（stress_test_u_），測試結束後於 finally 區塊 100% 清除並驗證資料表筆數與測試前完全一致。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import sqlite3
import statistics
import sys
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from repositories.sqlite_backup import backup_database  # noqa: E402
from repositories.sqlite_db import utc_iso  # noqa: E402

TEST_USER_PREFIX = "stress_test_u_"
TEST_RECORD_PREFIX = "stress_rec_"
DEFAULT_BASE_URL = "http://127.0.0.1:5000"


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100.0) * (len(sorted_values) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def summarize_latencies(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"min": 0.0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    s = sorted(latencies_ms)
    return {
        "min": round(s[0], 2),
        "avg": round(statistics.mean(s), 2),
        "p50": round(percentile(s, 50), 2),
        "p90": round(percentile(s, 90), 2),
        "p95": round(percentile(s, 95), 2),
        "p99": round(percentile(s, 99), 2),
        "max": round(s[-1], 2),
    }


def get_table_counts(db_path: str) -> dict[str, int]:
    tables = ("auth_users", "auth_sessions", "users", "records", "custom_foods", "restaurant_menus")
    counts: dict[str, int] = {}
    conn = sqlite3.connect(db_path, timeout=15)
    try:
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
    finally:
        conn.close()
    return counts


def provision_test_users_sqlite(
    base_url: str,
    db_path: str,
    count: int,
    password: str = "stress_pass_123",
) -> list[dict[str, str]]:
    """在 SQLite 批次建立壓測專用帳號與登入 token，只做一次密碼雜湊以節省前置準備時間。"""
    seed_email = f"{TEST_USER_PREFIX}seed"
    # 透過後端自身的 /auth/signup 產生一組真實的 bcrypt password_hash，不依賴本機 CLI 是否安裝 bcrypt
    cleanup_test_data_sqlite(db_path)
    seed_resp = requests.post(
        f"{base_url}/auth/signup",
        json={"email": seed_email, "password": password},
        timeout=10,
    )
    if seed_resp.status_code not in (200, 201):
        raise RuntimeError(f"無法建立壓測種子帳號 (HTTP {seed_resp.status_code}): {seed_resp.text}")

    now_iso = utc_iso()
    expires_iso = utc_iso(datetime.now(timezone.utc) + timedelta(days=1))

    users: list[dict[str, str]] = []
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    try:
        row = conn.execute(
            "SELECT password_hash FROM auth_users WHERE email = ?",
            (seed_email,),
        ).fetchone()
        if not row:
            raise RuntimeError("找不到壓測種子帳號的 password_hash")
        shared_password_hash = row[0]

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM auth_users WHERE email = ?)", (seed_email,))
            conn.execute("DELETE FROM auth_users WHERE email = ?", (seed_email,))
            for idx in range(1, count + 1):
                user_id = f"{TEST_USER_PREFIX}{idx:04d}"
                email = f"{user_id}"
                raw_token = f"stress_token_{idx:04d}_{hashlib.md5(user_id.encode()).hexdigest()}"
                token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

                conn.execute(
                    """
                    INSERT INTO auth_users (id, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET password_hash = excluded.password_hash
                    """,
                    (user_id, email, shared_password_hash, now_iso),
                )
                conn.execute(
                    """
                    INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (token_hash) DO UPDATE SET expires_at = excluded.expires_at
                    """,
                    (token_hash, user_id, expires_iso, now_iso),
                )
                users.append({
                    "user_id": user_id,
                    "email": email,
                    "password": password,
                    "token": raw_token,
                    "ip": f"10.250.{(idx // 250) % 250 + 1}.{(idx % 250) + 1}",
                })
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return users


def cleanup_test_data_sqlite(db_path: str) -> dict[str, int]:
    """清除所有帶有壓測前綴的帳號、Session、健康檔案與飲食紀錄。"""
    like_pattern = f"{TEST_USER_PREFIX}%"
    removed: dict[str, int] = {}
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            removed["records"] = conn.execute(
                "DELETE FROM records WHERE user_id LIKE ? OR client_record_id LIKE ?",
                (like_pattern, f"{TEST_RECORD_PREFIX}%"),
            ).rowcount
            removed["custom_foods"] = conn.execute(
                "DELETE FROM custom_foods WHERE user_id LIKE ?",
                (like_pattern,),
            ).rowcount
            removed["users"] = conn.execute(
                "DELETE FROM users WHERE user_id LIKE ?",
                (like_pattern,),
            ).rowcount
            removed["auth_sessions"] = conn.execute(
                "DELETE FROM auth_sessions WHERE user_id LIKE ?",
                (like_pattern,),
            ).rowcount
            removed["auth_users"] = conn.execute(
                "DELETE FROM auth_users WHERE id LIKE ?",
                (like_pattern,),
            ).rowcount
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return removed


def build_http_session(token: str | None = None, simulated_ip: str | None = None) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if simulated_ip:
        headers["Cf-Connecting-Ip"] = simulated_ip
    session.headers.update(headers)
    return session


def timed_request(
    session: requests.Session,
    method: str,
    url: str,
    expected_statuses: tuple[int, ...] = (200, 201),
    timeout: float = 15.0,
    **kwargs: Any,
) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        resp = session.request(method, url, timeout=timeout, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        ok = resp.status_code in expected_statuses
        return {
            "ok": ok,
            "status": resp.status_code,
            "latency_ms": elapsed_ms,
            "error": None if ok else f"HTTP {resp.status_code}: {resp.text[:120]}",
            "json": resp.json() if ok and resp.content else None,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "latency_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
            "json": None,
        }


# ─── Scenario 1: 多人同時使用完整流程（Mixed Read/Write User Journey） ─────────
def run_mixed_user_journey_level(
    base_url: str,
    users: list[dict[str, str]],
    concurrency: int,
) -> dict[str, Any]:
    selected_users = users[:concurrency]
    barrier = threading.Barrier(concurrency)

    def worker(user: dict[str, str], idx: int) -> dict[str, Any]:
        session = build_http_session(token=user["token"], simulated_ip=user["ip"])
        uid = user["user_id"]
        cid = f"{TEST_RECORD_PREFIX}journey_c{concurrency}_u{idx}_{int(time.time() * 1000)}"
        step_results: list[dict[str, Any]] = []

        try:
            barrier.wait(timeout=15.0)
        except threading.BrokenBarrierError:
            pass

        journey_start = time.perf_counter()

        # Step 1: POST /user (更新個人健康檔案 - DB Write)
        r1 = timed_request(
            session,
            "POST",
            f"{base_url}/user",
            json={
                "user_id": uid,
                "name": f"壓測使用者_{idx}",
                "gender": "male" if idx % 2 == 0 else "female",
                "weight": 68.0 + (idx % 15),
                "height": 168.0 + (idx % 12),
                "age": 26 + (idx % 20),
                "activity_level": "中等活動量",
                "activity_multiplier": 1.55,
                "health_conditions": ["高血壓"] if idx % 3 == 0 else [],
                "allergens": ["花生"] if idx % 4 == 0 else [],
                "target_weight": 65.0,
                "diet_type": "葷食",
                "profile_complete": True,
            },
        )
        r1["step"] = "POST /user"
        step_results.append(r1)

        # Step 2: GET /search/food (搜尋台灣食品資料庫 - Memory + DB Read)
        queries = ("雞胸肉", "燕麥", "無糖豆漿", "地瓜", "鮭魚", "花椰菜")
        q = queries[idx % len(queries)]
        r2 = timed_request(session, "GET", f"{base_url}/search/food", params={"q": q, "user_id": uid})
        r2["step"] = "GET /search/food"
        step_results.append(r2)

        # Step 3: POST /record (新增飲食紀錄 - DB Write)
        r3 = timed_request(
            session,
            "POST",
            f"{base_url}/record",
            json={
                "user_id": uid,
                "client_record_id": cid,
                "meal_type": "午餐",
                "foods": [
                    {
                        "name": "舒肥雞胸肉便當",
                        "calories": 520,
                        "protein": 42,
                        "carbs": 55,
                        "fat": 12,
                        "sodium": 480,
                        "fiber": 6,
                        "sugar": 4,
                        "saturated_fat": 3,
                        "trans_fat": 0,
                        "is_fried": False,
                    }
                ],
                "source": "manual",
            },
        )
        r3["step"] = "POST /record"
        step_results.append(r3)

        # Step 4: PATCH /records/<uid>/<cid> (修改飲食紀錄 - DB Transaction Write)
        r4 = timed_request(
            session,
            "PATCH",
            f"{base_url}/records/{uid}/{cid}",
            json={
                "foods": [
                    {
                        "name": "舒肥雞胸肉便當（加飯）",
                        "calories": 610,
                        "protein": 44,
                        "carbs": 75,
                        "fat": 13,
                        "sodium": 510,
                        "fiber": 7,
                        "sugar": 4,
                        "saturated_fat": 3,
                        "trans_fat": 0,
                        "is_fried": False,
                    }
                ]
            },
        )
        r4["step"] = "PATCH /records"
        step_results.append(r4)

        # Step 5: GET /records/<uid> (讀取今日飲食紀錄與營養目標 - DB Read)
        r5 = timed_request(session, "GET", f"{base_url}/records/{uid}")
        r5["step"] = "GET /records"
        step_results.append(r5)

        # Step 6: GET /history/<uid>?days=7 (讀取 7 日飲食歷史趨勢 - DB Range Read)
        r6 = timed_request(session, "GET", f"{base_url}/history/{uid}", params={"days": 7})
        r6["step"] = "GET /history"
        step_results.append(r6)

        journey_ms = (time.perf_counter() - journey_start) * 1000.0
        session.close()
        return {
            "user_id": uid,
            "journey_ms": journey_ms,
            "all_ok": all(s["ok"] for s in step_results),
            "steps": step_results,
        }

    wall_start = time.perf_counter()
    user_outcomes: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, user, i) for i, user in enumerate(selected_users)]
        for fut in as_completed(futures):
            user_outcomes.append(fut.result())
    wall_seconds = max(0.001, time.perf_counter() - wall_start)

    all_steps = [step for outcome in user_outcomes for step in outcome["steps"]]
    all_latencies = [step["latency_ms"] for step in all_steps]
    journey_latencies = [outcome["journey_ms"] for outcome in user_outcomes]
    succeeded_users = sum(1 for outcome in user_outcomes if outcome["all_ok"])
    succeeded_reqs = sum(1 for step in all_steps if step["ok"])
    total_reqs = len(all_steps)

    status_counts: dict[str, int] = {}
    per_step_latencies: dict[str, list[float]] = {}
    errors: list[str] = []
    for step in all_steps:
        code_key = str(step["status"])
        status_counts[code_key] = status_counts.get(code_key, 0) + 1
        per_step_latencies.setdefault(step["step"], []).append(step["latency_ms"])
        if not step["ok"] and step["error"] and len(errors) < 5:
            errors.append(f"{step['step']} -> {step['error']}")

    return {
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 3),
        "users_total": concurrency,
        "users_succeeded": succeeded_users,
        "user_success_rate_pct": round(succeeded_users / concurrency * 100.0, 2),
        "requests_total": total_reqs,
        "requests_succeeded": succeeded_reqs,
        "request_success_rate_pct": round(succeeded_reqs / total_reqs * 100.0, 2),
        "rps": round(total_reqs / wall_seconds, 2),
        "status_counts": status_counts,
        "request_latency_ms": summarize_latencies(all_latencies),
        "journey_latency_ms": summarize_latencies(journey_latencies),
        "per_step_p95_ms": {
            step_name: summarize_latencies(lats)["p95"]
            for step_name, lats in per_step_latencies.items()
        },
        "sample_errors": errors,
    }


# ─── Scenario 2: 高併發 SQLite 寫入與鎖競爭壓測（Pure DB Write Burst） ─────────
def run_db_write_contention_level(
    base_url: str,
    users: list[dict[str, str]],
    concurrency: int,
) -> dict[str, Any]:
    selected_users = users[:concurrency]
    barrier = threading.Barrier(concurrency)

    def worker(user: dict[str, str], idx: int) -> list[dict[str, Any]]:
        session = build_http_session(token=user["token"], simulated_ip=user["ip"])
        uid = user["user_id"]
        cid = f"{TEST_RECORD_PREFIX}write_c{concurrency}_u{idx}_{int(time.time() * 1000)}"
        ops: list[dict[str, Any]] = []

        try:
            barrier.wait(timeout=15.0)
        except threading.BrokenBarrierError:
            pass

        # Write 1: POST /record (INSERT)
        w1 = timed_request(
            session,
            "POST",
            f"{base_url}/record",
            json={
                "user_id": uid,
                "client_record_id": cid,
                "meal_type": "晚餐",
                "foods": [
                    {
                        "name": "滷肉飯便當",
                        "calories": 680,
                        "protein": 24,
                        "carbs": 82,
                        "fat": 28,
                        "sodium": 890,
                        "fiber": 3,
                        "sugar": 6,
                        "saturated_fat": 9,
                        "trans_fat": 0,
                        "is_fried": False,
                    }
                ],
                "source": "manual",
            },
        )
        w1["op"] = "INSERT /record"
        ops.append(w1)

        # Write 2: PATCH /records/<uid>/<cid> (BEGIN IMMEDIATE + UPDATE + SELECT)
        w2 = timed_request(
            session,
            "PATCH",
            f"{base_url}/records/{uid}/{cid}",
            json={
                "foods": [
                    {
                        "name": "滷肉飯便當（半飯）",
                        "calories": 540,
                        "protein": 23,
                        "carbs": 52,
                        "fat": 27,
                        "sodium": 850,
                        "fiber": 3,
                        "sugar": 5,
                        "saturated_fat": 9,
                        "trans_fat": 0,
                        "is_fried": False,
                    }
                ]
            },
        )
        w2["op"] = "UPDATE /records"
        ops.append(w2)

        # Write 3: DELETE /records/<uid>/<cid> (BEGIN IMMEDIATE + SELECT + DELETE)
        w3 = timed_request(
            session,
            "DELETE",
            f"{base_url}/records/{uid}/{cid}",
        )
        w3["op"] = "DELETE /records"
        ops.append(w3)

        session.close()
        return ops

    wall_start = time.perf_counter()
    all_ops: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, user, i) for i, user in enumerate(selected_users)]
        for fut in as_completed(futures):
            all_ops.extend(fut.result())
    wall_seconds = max(0.001, time.perf_counter() - wall_start)

    latencies = [op["latency_ms"] for op in all_ops]
    succeeded = sum(1 for op in all_ops if op["ok"])
    total = len(all_ops)
    status_counts: dict[str, int] = {}
    per_op_latencies: dict[str, list[float]] = {}
    errors: list[str] = []
    for op in all_ops:
        code_key = str(op["status"])
        status_counts[code_key] = status_counts.get(code_key, 0) + 1
        per_op_latencies.setdefault(op["op"], []).append(op["latency_ms"])
        if not op["ok"] and op["error"] and len(errors) < 5:
            errors.append(f"{op['op']} -> {op['error']}")

    return {
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 3),
        "writes_total": total,
        "writes_succeeded": succeeded,
        "write_success_rate_pct": round(succeeded / total * 100.0, 2),
        "writes_per_sec": round(total / wall_seconds, 2),
        "status_counts": status_counts,
        "write_latency_ms": summarize_latencies(latencies),
        "per_op_p95_ms": {
            op_name: summarize_latencies(lats)["p95"]
            for op_name, lats in per_op_latencies.items()
        },
        "sample_errors": errors,
    }


# ─── Scenario 2B: 同筆紀錄高併發重複送出競態測試（Deduplication Race） ─────────
def run_deduplication_race_test(
    base_url: str,
    user: dict[str, str],
    concurrency: int = 50,
) -> dict[str, Any]:
    """50 個執行緒在同一微秒送出完全相同的 (user_id, client_record_id)，驗證唯一索引與鎖定不會產生 500 或重複資料。"""
    uid = user["user_id"]
    shared_cid = f"{TEST_RECORD_PREFIX}dedupe_race_{int(time.time() * 1000)}"
    barrier = threading.Barrier(concurrency)

    def worker(idx: int) -> dict[str, Any]:
        session = build_http_session(token=user["token"], simulated_ip=f"10.251.1.{idx + 1}")
        try:
            barrier.wait(timeout=10.0)
        except threading.BrokenBarrierError:
            pass
        res = timed_request(
            session,
            "POST",
            f"{base_url}/record",
            expected_statuses=(200, 201),
            json={
                "user_id": uid,
                "client_record_id": shared_cid,
                "meal_type": "早餐",
                "foods": [
                    {
                        "name": "無糖豆漿加茶葉蛋",
                        "calories": 215,
                        "protein": 18,
                        "carbs": 12,
                        "fat": 10,
                        "sodium": 320,
                        "fiber": 2,
                        "sugar": 3,
                        "saturated_fat": 2,
                        "trans_fat": 0,
                        "is_fried": False,
                    }
                ],
                "source": "camera",
            },
        )
        session.close()
        return res

    wall_start = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall_seconds = max(0.001, time.perf_counter() - wall_start)

    created_201 = sum(1 for r in results if r["status"] == 201)
    deduped_200 = sum(1 for r in results if r["status"] == 200)
    failed = sum(1 for r in results if not r["ok"])

    return {
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 3),
        "created_201_count": created_201,
        "deduplicated_200_count": deduped_200,
        "failed_count": failed,
        "latency_ms": summarize_latencies([r["latency_ms"] for r in results]),
    }


# ─── Scenario 3: 多人同時登入壓測（Bcrypt CPU & IP Rate Limiter） ──────────────
def run_concurrent_login_test(
    base_url: str,
    users: list[dict[str, str]],
    concurrency: int,
    shared_ip: bool = False,
) -> dict[str, Any]:
    selected_users = users[:concurrency]
    barrier = threading.Barrier(concurrency)

    def worker(user: dict[str, str], idx: int) -> dict[str, Any]:
        ip = "10.252.99.99" if shared_ip else f"10.252.{(idx // 250) + 1}.{(idx % 250) + 1}"
        session = build_http_session(token=None, simulated_ip=ip)
        try:
            barrier.wait(timeout=15.0)
        except threading.BrokenBarrierError:
            pass
        res = timed_request(
            session,
            "POST",
            f"{base_url}/auth/login",
            expected_statuses=(200,),
            timeout=30.0,
            json={"email": user["email"], "password": user["password"]},
        )
        session.close()
        return res

    wall_start = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, user, i) for i, user in enumerate(selected_users)]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall_seconds = max(0.001, time.perf_counter() - wall_start)

    ok_200 = sum(1 for r in results if r["status"] == 200)
    rate_limited_429 = sum(1 for r in results if r["status"] == 429)
    other_fail = sum(1 for r in results if r["status"] not in (200, 429))

    return {
        "concurrency": concurrency,
        "shared_ip": shared_ip,
        "wall_seconds": round(wall_seconds, 3),
        "succeeded_200": ok_200,
        "rate_limited_429": rate_limited_429,
        "other_failed": other_fail,
        "logins_per_sec": round(ok_200 / wall_seconds, 2),
        "latency_ms": summarize_latencies([r["latency_ms"] for r in results if r["status"] == 200]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NutriLens 多人併發與 SQLite 鎖競爭壓力測試")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="後端網址（預設 http://127.0.0.1:5000）")
    parser.add_argument("--output-json", default="", help="輸出測試結果 JSON 檔案路徑")
    parser.add_argument("--extreme", action="store_true", help="加測 500、750、1000 人極限併發")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"[1/6] 檢查後端連線狀態：{base_url}/health ...")
    health_resp = requests.get(f"{base_url}/health", timeout=5)
    health_resp.raise_for_status()
    health_data = health_resp.json()
    db_path = health_data.get("database_path")
    if not db_path or not os.path.exists(db_path):
        print(f"[ERROR] 找不到本機 SQLite 資料庫路徑：{db_path}")
        return 1

    print(f"      後端版本：{health_data.get('app_version')} | 資料庫：{db_path}")
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    backup_file = backup_database(db_path, backup_dir, label="before-stress-test")
    print(f"[2/6] 已建立測試前資料庫安全備份：{backup_file}")

    baseline_counts = get_table_counts(db_path)
    print(f"      測試前資料表筆數：{json.dumps(baseline_counts, ensure_ascii=False)}")

    max_users_needed = 1000 if args.extreme else 300
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "database_path": db_path,
        "backup_file": backup_file,
        "baseline_counts": baseline_counts,
        "mixed_journey_levels": [],
        "db_write_contention_levels": [],
        "deduplication_race": {},
        "concurrent_login_distinct_ip": [],
        "concurrent_login_shared_ip": {},
    }

    try:
        print(f"[3/6] 正在準備 {max_users_needed} 組壓測專用隔離帳號與 Session Token ...")
        users = provision_test_users_sqlite(base_url, db_path, max_users_needed)

        # Scenario 1: 多人同時完整操作
        journey_levels = [1, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300]
        if args.extreme:
            journey_levels.extend([500, 750, 1000])
        print("\n[4/6] 場景一：多人同時使用完整流程（6 步讀寫混合：/user -> /search/food -> POST /record -> PATCH /records -> GET /records -> GET /history）")
        print(f"{'同時人數':>8} | {'成功率':>8} | {'吞吐量 RPS':>10} | {'單請求 P50':>10} | {'單請求 P95':>10} | {'單請求 P99':>10} | {'整套操作 P95':>12}")
        print("-" * 88)
        for level in journey_levels:
            res = run_mixed_user_journey_level(base_url, users, level)
            report["mixed_journey_levels"].append(res)
            rl = res["request_latency_ms"]
            jl = res["journey_latency_ms"]
            print(
                f"{level:>8} | {res['user_success_rate_pct']:>7.1f}% | {res['rps']:>10.1f} | "
                f"{rl['p50']:>8.1f}ms | {rl['p95']:>8.1f}ms | {rl['p99']:>8.1f}ms | {jl['p95'] / 1000.0:>10.2f}s"
            )

        # Scenario 2: 高併發資料庫寫入與鎖競爭
        write_levels = [10, 25, 50, 100, 150, 200, 300]
        if args.extreme:
            write_levels.extend([500, 750, 1000])
        print("\n[5/6] 場景二：高併發 SQLite 寫入與鎖競爭（每人連續執行 INSERT /record + UPDATE /records + DELETE /records）")
        print(f"{'同時人數':>8} | {'寫入成功率':>10} | {'寫入/秒':>10} | {'寫入 P50':>10} | {'寫入 P95':>10} | {'寫入 P99':>10} | {'寫入 Max':>10}")
        print("-" * 88)
        for level in write_levels:
            res = run_db_write_contention_level(base_url, users, level)
            report["db_write_contention_levels"].append(res)
            wl = res["write_latency_ms"]
            print(
                f"{level:>8} | {res['write_success_rate_pct']:>9.1f}% | {res['writes_per_sec']:>10.1f} | "
                f"{wl['p50']:>8.1f}ms | {wl['p95']:>8.1f}ms | {wl['p99']:>8.1f}ms | {wl['max']:>8.1f}ms"
            )

        # Scenario 2B: Deduplication Race
        dedupe_res = run_deduplication_race_test(base_url, users[0], concurrency=50)
        report["deduplication_race"] = dedupe_res
        print(
            f"\n      [同筆紀錄 50 執行緒同時送出競態測試] "
            f"新建(201): {dedupe_res['created_201_count']} 筆 | "
            f"去重攔截(200): {dedupe_res['deduplicated_200_count']} 筆 | "
            f"失敗(500等): {dedupe_res['failed_count']} 筆 | "
            f"P95: {dedupe_res['latency_ms']['p95']}ms"
        )

        # Scenario 3: 多人同時登入（Bcrypt CPU + IP Rate Limit）
        print("\n[6/6] 場景三：多人同時登入（POST /auth/login — Bcrypt 密碼雜湊 CPU 排隊與 IP 限流測試）")
        for login_n in (5, 10, 20, 40):
            lres = run_concurrent_login_test(base_url, users, login_n, shared_ip=False)
            report["concurrent_login_distinct_ip"].append(lres)
            ll = lres["latency_ms"]
            print(
                f"      [獨立 IP 同時 {login_n:>2} 人登入] 成功: {lres['succeeded_200']}/{login_n} | "
                f"吞吐量: {lres['logins_per_sec']:.1f} 人/秒 | "
                f"P50: {ll['p50']:.0f}ms | P95: {ll['p95']:.0f}ms | Max: {ll['max']:.0f}ms"
            )

        shared_ip_res = run_concurrent_login_test(base_url, users, 65, shared_ip=True)
        report["concurrent_login_shared_ip"] = shared_ip_res
        print(
            f"      [同一個 Wi-Fi / IP 同時 65 人登入] 成功(200): {shared_ip_res['succeeded_200']} | "
            f"觸發限流保護(429): {shared_ip_res['rate_limited_429']} | 其他失敗: {shared_ip_res['other_failed']}"
        )

    finally:
        print("\n[清理] 正在清除所有壓測產生的臨時帳號、Session 與飲食紀錄 ...")
        removed_counts = cleanup_test_data_sqlite(db_path)
        after_counts = get_table_counts(db_path)
        report["removed_counts"] = removed_counts
        report["after_counts"] = after_counts
        report["database_clean_verified"] = baseline_counts == after_counts
        print(f"      已清除測試資料：{json.dumps(removed_counts, ensure_ascii=False)}")
        print(f"      清理後資料表筆數：{json.dumps(after_counts, ensure_ascii=False)}")
        print(f"      與測試前完全一致：{report['database_clean_verified']}")

    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[完成] 完整壓測報告已存至：{args.output_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
