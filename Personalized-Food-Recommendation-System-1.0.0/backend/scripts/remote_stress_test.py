#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""遠端 v1.0.0 壓測：使用專用帳號測試讀寫流程，並透過 API 清理資料。

這支腳本不讀取或修改遠端資料庫檔案，也不呼叫 Gemini、OCR、Places 等付費 API。
每位虛擬使用者只建立一筆帶有本次 run 前綴的紀錄，流程結束後立即刪除；最後再做
一次 API 清理與殘留驗證。帳號密碼由本機 CSV 提供，不會寫入結果 JSON/CSV。
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import json
import math
import os
import statistics
import threading
import time
from typing import Any

import requests


DEFAULT_BASE_URL = "https://node.taile9a8dc.ts.net"
DEFAULT_ACCOUNTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "stress-test",
    "test_accounts_20261111.csv",
)
LEVELS = (1, 5, 10, 20, 30, 40, 50)
REQUEST_TIMEOUT_SECONDS = 30.0
LATENCY_REFERENCE_MS = 2000.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min_ms": 0.0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
    return {
        "min_ms": round(min(values), 2),
        "avg_ms": round(statistics.mean(values), 2),
        "p50_ms": round(percentile(values, 50), 2),
        "p95_ms": round(percentile(values, 95), 2),
        "p99_ms": round(percentile(values, 99), 2),
        "max_ms": round(max(values), 2),
    }


def load_accounts(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    accounts = [{"email": row["account"].strip(), "password": row["password"]} for row in rows]
    if not accounts or any(not item["email"] or not item["password"] for item in accounts):
        raise ValueError("帳號 CSV 必須包含 account,password，且不可有空值")
    return accounts


def timed_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected: tuple[int, ...] = (200,),
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000.0
        ok = response.status_code in expected
        return {
            "ok": ok,
            "status": response.status_code,
            "latency_ms": round(elapsed, 2),
            "error": None if ok else f"HTTP {response.status_code}: {response.text[:180]}",
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "latency_ms": round(elapsed, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def login_account(base_url: str, account: dict[str, str]) -> dict[str, Any]:
    session = requests.Session()
    result = timed_request(
        session,
        "POST",
        f"{base_url}/auth/login",
        expected=(200,),
        json={"email": account["email"], "password": account["password"]},
    )
    result["email"] = account["email"]
    if result["ok"]:
        try:
            payload = session.post(
                f"{base_url}/auth/login",
                json={"email": account["email"], "password": account["password"]},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            payload = None
        # The first request above already consumed the login. Use its body only when available
        # through a second request would be wasteful; re-login is avoided below by direct helper.
    session.close()
    return result


def login_with_token(base_url: str, account: dict[str, str]) -> dict[str, Any]:
    session = requests.Session()
    started = time.perf_counter()
    try:
        response = session.post(
            f"{base_url}/auth/login",
            json={"email": account["email"], "password": account["password"]},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        result: dict[str, Any] = {
            "ok": response.status_code == 200,
            "status": response.status_code,
            "latency_ms": round(elapsed, 2),
            "email": account["email"],
            "error": None if response.status_code == 200 else f"HTTP {response.status_code}: {response.text[:180]}",
        }
        if response.status_code == 200:
            payload = response.json()
            result["token"] = payload["access_token"]
            result["user_id"] = payload["user"]["id"]
        return result
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "email": account["email"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        session.close()


def make_food(name: str, calories: float) -> dict[str, Any]:
    return {
        "name": name,
        "calories": calories,
        "protein": 5,
        "carbs": 10,
        "fat": 2,
        "sodium": 50,
        "fiber": 1,
        "sugar": 2,
        "saturated_fat": 1,
        "trans_fat": 0,
        "is_fried": False,
    }


def run_user_journey(base_url: str, auth: dict[str, Any], level: int, index: int, barrier: threading.Barrier, run_prefix: str) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth['token']}", "Content-Type": "application/json"})
    user_id = auth["user_id"]
    client_record_id = f"{run_prefix}_l{level:03d}_u{index:03d}"
    steps: list[dict[str, Any]] = []
    created = False
    try:
        try:
            barrier.wait(timeout=20)
        except threading.BrokenBarrierError:
            pass

        def step(name: str, method: str, url: str, expected=(200,), **kwargs: Any) -> dict[str, Any]:
            result = timed_request(session, method, url, expected=expected, **kwargs)
            result.update({"step": name, "level": level, "user_index": index, "user_id": user_id, "endpoint": url.split(base_url, 1)[-1]})
            steps.append(result)
            return result

        step("auth_user", "GET", f"{base_url}/auth/user")
        step("search_food", "GET", f"{base_url}/search/food", params={"q": "雞胸肉", "user_id": user_id, "limit": 5})
        step("records_before", "GET", f"{base_url}/records/{user_id}")
        step("history", "GET", f"{base_url}/history/{user_id}")
        create = step(
            "record_create",
            "POST",
            f"{base_url}/record",
            expected=(200, 201),
            json={
                "user_id": user_id,
                "client_record_id": client_record_id,
                "meal_type": "午餐",
                "foods": [make_food("壓測測試餐", 100 + index)],
                "source": "manual",
            },
        )
        created = create["status"] in (200, 201)
        if created:
            step(
                "record_update",
                "PATCH",
                f"{base_url}/records/{user_id}/{client_record_id}",
                json={"foods": [make_food("壓測測試餐（更新）", 120 + index)]},
            )
            step("records_after", "GET", f"{base_url}/records/{user_id}")
            step("record_delete", "DELETE", f"{base_url}/records/{user_id}/{client_record_id}")
        else:
            steps.append({"ok": False, "status": 0, "latency_ms": 0.0, "error": "record_create failed; update/delete skipped", "step": "record_update", "level": level, "user_index": index, "user_id": user_id, "endpoint": f"/records/{user_id}/{client_record_id}"})
    finally:
        if created:
            # 若前面的刪除失敗，最後仍嘗試一次；404 代表前面已清掉。
            cleanup = timed_request(session, "DELETE", f"{base_url}/records/{user_id}/{client_record_id}", expected=(200, 404))
            cleanup.update({"step": "record_cleanup_retry", "level": level, "user_index": index, "user_id": user_id, "endpoint": f"/records/{user_id}/{client_record_id}"})
            steps.append(cleanup)
        session.close()
    return steps


def summarize_level(level: int, results: list[dict[str, Any]], wall_seconds: float, user_count: int) -> dict[str, Any]:
    latencies = [item["latency_ms"] for item in results]
    status_counts: dict[str, int] = {}
    errors: list[str] = []
    for item in results:
        key = str(item["status"])
        status_counts[key] = status_counts.get(key, 0) + 1
        if not item["ok"] and item.get("error") and len(errors) < 8:
            errors.append(f"{item['step']}: {item['error']}")
    successful_users = sum(
        1
        for index in range(user_count)
        if all(item["ok"] for item in results if item["user_index"] == index)
    )
    return {
        "concurrency": level,
        "users": user_count,
        "requests": len(results),
        "successful_requests": sum(1 for item in results if item["ok"]),
        "failed_requests": sum(1 for item in results if not item["ok"]),
        "request_success_rate_pct": round(sum(1 for item in results if item["ok"]) / max(1, len(results)) * 100, 2),
        "successful_users": successful_users,
        "user_success_rate_pct": round(successful_users / max(1, user_count) * 100, 2),
        "wall_seconds": round(wall_seconds, 3),
        "rps": round(len(results) / max(0.001, wall_seconds), 2),
        "latency": latency_summary(latencies),
        "status_counts": status_counts,
        "sample_errors": errors,
    }


def cleanup_residual_records(base_url: str, auths: list[dict[str, Any]], run_prefix: str) -> dict[str, Any]:
    removed = 0
    remaining: list[str] = []
    errors: list[str] = []
    for auth in auths:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {auth['token']}"})
        uid = auth["user_id"]
        try:
            response = session.get(f"{base_url}/records/{uid}", timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code != 200:
                errors.append(f"{auth['email']}: GET records HTTP {response.status_code}")
                continue
            records = response.json().get("records", [])
            for record in records:
                client_id = str(record.get("client_record_id") or "")
                if not client_id.startswith(run_prefix):
                    continue
                deleted = session.delete(f"{base_url}/records/{uid}/{client_id}", timeout=REQUEST_TIMEOUT_SECONDS)
                if deleted.status_code == 200:
                    removed += 1
                else:
                    remaining.append(client_id)
        except Exception as exc:
            errors.append(f"{auth['email']}: {type(exc).__name__}: {exc}")
        finally:
            session.close()
    return {"removed": removed, "remaining": remaining, "errors": errors, "clean": not remaining and not errors}


def render_report(report: dict[str, Any], output_path: str) -> None:
    levels = report["journey_levels"]
    max_latency = max([LATENCY_REFERENCE_MS] + [item["latency"]["p95_ms"] for item in levels])
    chart_height = 280
    chart_top = 25
    chart_bottom = 235
    chart_left = 70
    chart_right = 870
    max_scale = max(2500.0, math.ceil(max_latency / 500.0) * 500.0)

    def y(value: float) -> float:
        return chart_bottom - (value / max_scale) * (chart_bottom - chart_top)

    def x(index: int) -> float:
        return chart_left + index * ((chart_right - chart_left) / max(1, len(levels) - 1))

    p95_points = " ".join(f"{x(i):.1f},{y(item['latency']['p95_ms']):.1f}" for i, item in enumerate(levels))
    p50_points = " ".join(f"{x(i):.1f},{y(item['latency']['p50_ms']):.1f}" for i, item in enumerate(levels))
    grid = []
    for tick in range(0, int(max_scale) + 1, 500):
        grid.append(f'<line x1="{chart_left}" y1="{y(tick):.1f}" x2="{chart_right}" y2="{y(tick):.1f}" stroke="#dbe6e0"/><text x="{chart_left - 10}" y="{y(tick) + 4:.1f}" text-anchor="end" fill="#63736c">{tick / 1000:g}s</text>')
    dots = []
    labels = []
    for i, item in enumerate(levels):
        dots.append(f'<circle cx="{x(i):.1f}" cy="{y(item["latency"]["p50_ms"]):.1f}" r="5" fill="#1f9d72"/><circle cx="{x(i):.1f}" cy="{y(item["latency"]["p95_ms"]):.1f}" r="5" fill="#2f80ed"/>')
        labels.append(f'<text x="{x(i):.1f}" y="258" text-anchor="middle" fill="#14201b">{item["concurrency"]}</text>')

    rows = []
    for item in levels:
        rows.append(
            "<tr>"
            f"<td>{item['concurrency']}</td><td>{item['requests']}</td>"
            f"<td>{item['request_success_rate_pct']:.1f}%</td><td>{item['user_success_rate_pct']:.1f}%</td>"
            f"<td>{item['rps']:.1f}</td><td>{item['latency']['p50_ms']:.0f}ms</td>"
            f"<td>{item['latency']['p95_ms']:.0f}ms</td><td>{item['latency']['max_ms']:.0f}ms</td></tr>"
        )

    title = html.escape(f"NutriLens v1.0.0 遠端壓力測試報告 {report['run_id']}")
    summary = html.escape(report.get("conclusion", ""))
    document = f'''<!doctype html>
<html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{--bg:#f6f8f7;--surface:#fff;--ink:#14201b;--muted:#63736c;--line:#dbe6e0;--green:#1f9d72;--blue:#2f80ed;--orange:#ed8a19;--red:#d94b4b}}*{{box-sizing:border-box}}body{{margin:0;padding:32px 20px 48px;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1080px;margin:auto}}h1,h2,p{{margin:0}}h1{{font-size:28px;line-height:1.2}}h2{{font-size:18px;margin-bottom:14px}}.eyebrow{{color:var(--green);font-weight:700;letter-spacing:.04em;margin-bottom:8px}}.muted{{color:var(--muted)}}.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:24px 0}}.stat,section{{background:var(--surface);border:1px solid var(--line);border-radius:8px}}.stat{{padding:16px}}.stat-label{{color:var(--muted);font-size:13px}}.stat-value{{font-size:26px;font-weight:700;margin-top:3px}}section{{padding:20px;margin-top:16px}}.chart-wrap{{overflow-x:auto}}svg{{display:block;width:100%;min-width:680px;height:auto}}.legend{{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:13px}}.legend span::before{{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:var(--green)}}.legend .p95::before{{background:var(--blue)}}.legend .threshold::before{{background:var(--orange)}}.callout{{border-left:4px solid var(--orange);padding:10px 12px;background:#fff7e8;margin-top:16px}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}th,td{{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line)}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-weight:600}}.ok{{color:var(--green);font-weight:700}}.footer{{margin-top:18px;font-size:13px;color:var(--muted)}}@media(max-width:700px){{body{{padding:22px 12px 36px}}h1{{font-size:23px}}.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}section{{padding:14px}}}}
</style></head><body><main>
<p class="eyebrow">NUTRILENS / REMOTE STRESS TEST</p><h1>v1.0.0 遠端壓力測試報告</h1><p class="muted">目標：{html.escape(report['base_url'])} · 執行：{html.escape(report['started_at'])} · 僅測試專用帳號</p>
<div class="summary"><div class="stat"><div class="stat-label">最高併發</div><div class="stat-value">{levels[-1]['concurrency']}</div></div><div class="stat"><div class="stat-label">總請求數</div><div class="stat-value">{report['total_requests']}</div></div><div class="stat"><div class="stat-label">整體成功率</div><div class="stat-value ok">{report['overall_success_rate_pct']:.1f}%</div></div><div class="stat"><div class="stat-label">最高 P95</div><div class="stat-value">{max(item['latency']['p95_ms'] for item in levels)/1000:.2f}s</div></div></div>
<section><h2>併發增加時的延遲</h2><div class="chart-wrap"><svg viewBox="0 0 900 300" role="img" aria-labelledby="latency-title latency-desc"><title id="latency-title">併發與 P50、P95 延遲</title><desc id="latency-desc">綠線是 P50，藍線是 P95，橘色虛線是 2 秒參考線。</desc>{''.join(grid)}<line x1="{chart_left}" y1="{y(LATENCY_REFERENCE_MS):.1f}" x2="{chart_right}" y2="{y(LATENCY_REFERENCE_MS):.1f}" stroke="#ed8a19" stroke-width="2" stroke-dasharray="7 6"/><text x="{chart_right}" y="{y(LATENCY_REFERENCE_MS)-7:.1f}" text-anchor="end" fill="#ed8a19">2 秒參考線</text><polyline points="{p50_points}" fill="none" stroke="#1f9d72" stroke-width="4"/><polyline points="{p95_points}" fill="none" stroke="#2f80ed" stroke-width="4"/>{''.join(dots)}{''.join(labels)}<text x="470" y="290" text-anchor="middle" fill="#63736c">同時使用者數</text></svg></div><div class="legend"><span>P50</span><span class="p95">P95</span><span class="threshold">2 秒參考線</span></div><div class="callout">{summary}</div></section>
<section><h2>各併發級別數據</h2><div class="chart-wrap"><table><thead><tr><th>併發</th><th>請求</th><th>請求成功率</th><th>使用者成功率</th><th>RPS</th><th>P50</th><th>P95</th><th>最大</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>清理結果</h2><p class="muted">測試專用紀錄清理：{report['cleanup']['removed']} 筆；殘留：{len(report['cleanup']['remaining'])} 筆；清理狀態：<span class="ok">{'通過' if report['cleanup']['clean'] else '需人工檢查'}</span>。</p><p class="footer">原始請求資料：remote_requests_{report['run_id']}.csv · 級別摘要：remote_levels_{report['run_id']}.csv · JSON：remote_summary_{report['run_id']}.json</p></section>
</main></body></html>'''
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(document)


def write_csv(path: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="NutriLens v1.0.0 遠端專用帳號壓力測試")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--accounts-file", default=DEFAULT_ACCOUNTS)
    parser.add_argument("--output-dir", default=os.path.join(os.path.dirname(DEFAULT_ACCOUNTS), "runs"))
    parser.add_argument("--levels", default=",".join(str(level) for level in LEVELS))
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    levels = tuple(sorted({int(item.strip()) for item in args.levels.split(",") if item.strip()}))
    accounts = load_accounts(args.accounts_file)
    if max(levels) > len(accounts):
        raise ValueError(f"最高併發 {max(levels)} 超過帳號數 {len(accounts)}")
    os.makedirs(args.output_dir, exist_ok=True)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    run_prefix = f"stress_remote_{run_id}"
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    print(f"[1/4] 登入 {len(accounts)} 組壓測帳號（不輸出密碼）...", flush=True)
    login_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(5, len(accounts))) as pool:
        futures = [pool.submit(login_with_token, base_url, account) for account in accounts]
        for future in as_completed(futures):
            login_results.append(future.result())
    login_results.sort(key=lambda item: item["email"])
    failed_logins = [item for item in login_results if not item["ok"]]
    if failed_logins:
        print(f"[STOP] 登入失敗 {len(failed_logins)} 組，未開始寫入型壓測。", flush=True)
        for item in failed_logins[:8]:
            print(f"       {item['email']}: {item.get('error')}", flush=True)
        return 2
    auths = login_results
    print(f"      登入成功 {len(auths)}/{len(accounts)}", flush=True)

    journey_levels: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    print("[2/4] 執行逐級混合讀寫流程：" + ", ".join(str(level) for level in levels), flush=True)
    for level in levels:
        selected = auths[:level]
        barrier = threading.Barrier(level)
        wall_started = time.perf_counter()
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=level) as pool:
            futures = [pool.submit(run_user_journey, base_url, auth, level, index, barrier, run_prefix) for index, auth in enumerate(selected)]
            for future in as_completed(futures):
                results.extend(future.result())
        wall_seconds = max(0.001, time.perf_counter() - wall_started)
        summary = summarize_level(level, results, wall_seconds, level)
        journey_levels.append(summary)
        request_rows.extend(results)
        print(
            f"      {level:>3} 人 | 請求成功率 {summary['request_success_rate_pct']:>5.1f}% | 使用者成功率 {summary['user_success_rate_pct']:>5.1f}% | "
            f"RPS {summary['rps']:>6.1f} | P50 {summary['latency']['p50_ms']:>7.0f}ms | P95 {summary['latency']['p95_ms']:>7.0f}ms | Max {summary['latency']['max_ms']:>7.0f}ms",
            flush=True,
        )
        if summary["request_success_rate_pct"] < 95.0:
            print("[STOP] 此級別請求失敗率超過 5%，停止繼續加壓。", flush=True)
            break
        time.sleep(3)

    print("[3/4] 清理本次 run 的殘留紀錄...", flush=True)
    cleanup = cleanup_residual_records(base_url, auths, run_prefix)
    print(f"      移除 {cleanup['removed']} 筆，殘留 {len(cleanup['remaining'])} 筆，clean={cleanup['clean']}", flush=True)

    total_requests = sum(item["requests"] for item in journey_levels)
    successful_requests = sum(item["successful_requests"] for item in journey_levels)
    overall_success_rate = successful_requests / max(1, total_requests) * 100
    last_level = journey_levels[-1]
    conclusion = (
        f"本次測試最高完成級別為 {last_level['concurrency']} 個同時使用者；"
        f"該級別請求成功率 {last_level['request_success_rate_pct']:.1f}%，P95 {last_level['latency']['p95_ms']:.0f}ms。"
        "這是本次測試條件下的觀測結果，不等於系統理論上限。"
    )
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": base_url,
        "app_version": "v1.0.0",
        "database": "local-sqlite",
        "scenario": "authenticated mixed read/write journey; no paid APIs",
        "account_count": len(auths),
        "levels_requested": list(levels),
        "levels_completed": [item["concurrency"] for item in journey_levels],
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "overall_success_rate_pct": round(overall_success_rate, 2),
        "login_summary": {
            "attempted": len(login_results),
            "successful": len([item for item in login_results if item["ok"]]),
            "latency": latency_summary([item["latency_ms"] for item in login_results]),
        },
        "journey_levels": journey_levels,
        "cleanup": cleanup,
        "latency_reference_ms": LATENCY_REFERENCE_MS,
        "conclusion": conclusion,
    }
    json_path = os.path.join(args.output_dir, f"remote_summary_{run_id}.json")
    requests_path = os.path.join(args.output_dir, f"remote_requests_{run_id}.csv")
    levels_path = os.path.join(args.output_dir, f"remote_levels_{run_id}.csv")
    html_path = os.path.join(args.output_dir, f"remote_report_{run_id}.html")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    write_csv(requests_path, request_rows, ["level", "user_index", "user_id", "step", "endpoint", "status", "ok", "latency_ms", "error"])
    level_rows = []
    for item in journey_levels:
        level_rows.append({
            "concurrency": item["concurrency"],
            "requests": item["requests"],
            "successful_requests": item["successful_requests"],
            "failed_requests": item["failed_requests"],
            "request_success_rate_pct": item["request_success_rate_pct"],
            "user_success_rate_pct": item["user_success_rate_pct"],
            "rps": item["rps"],
            **item["latency"],
        })
    write_csv(levels_path, level_rows, list(level_rows[0].keys()) if level_rows else ["concurrency"])
    render_report(report, html_path)
    print("[4/4] 完成", flush=True)
    print(f"      JSON: {json_path}", flush=True)
    print(f"      CSV:  {requests_path}", flush=True)
    print(f"      圖表: {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
