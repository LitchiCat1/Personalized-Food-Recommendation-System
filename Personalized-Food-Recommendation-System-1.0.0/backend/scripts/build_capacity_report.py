"""Build an offline report from saved measurements; never send test requests."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from remote_capacity_test import quantile, summarize

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "docs" / "stress-test" / "runs"
GREEN, BLUE, ORANGE, RED = "#00876b", "#2868b2", "#ad6900", "#c43b45"
INK, MUTED = "#192c30", "#52636a"
FUNNEL_DOC = "https://tailscale.com/docs/features/tailscale-funnel#requirements-and-limitations"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if "ok" in row:
            row["ok"] = str(row["ok"]).lower() == "true"
        for key in ("status", "level", "concurrency", "user_index", "held_before"):
            if key in row:
                row[key] = int(row[key])
        for key in ("latency_ms", "elapsed_s"):
            if key in row:
                row[key] = float(row[key])
    return rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", pad=17, color=INK, fontweight="bold")
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color="#e0e6e8", linewidth=.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#c4ced2")
    ax.tick_params(colors=MUTED)


def save_figure(fig, path, note):
    fig.text(.02, .02, note, fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build(persistent_dir):
    out = ROOT / "docs" / "stress-test" / "report-20261111"
    out.mkdir(exist_ok=True)
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11, "axes.titlesize": 14})
    burst, endpoint_rows, source_paths = [], [], []
    raw_bursts = {}
    burst_meta = []
    for stamp in ("20261111-213539", "20261111-214021"):
        request_path = RUNS / f"remote_requests_{stamp}.csv"
        metadata_path = RUNS / f"remote_summary_{stamp}.json"
        source_paths += [request_path, metadata_path]
        rows = read_csv(request_path)
        raw_bursts[stamp] = rows
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        burst_meta.append({key: metadata[key] for key in ("run_id", "started_at", "finished_at", "total_requests", "successful_requests", "cleanup")})
        for level in metadata["journey_levels"]:
            count = level["concurrency"]
            selected = [r for r in rows if r["level"] == count]
            assert len(selected) == level["requests"]
            initial = [r for r in selected if r["step"] == "auth_user"]
            later = [r for r in selected if r["step"] not in ("auth_user", "record_cleanup_retry")]
            redundant = [r for r in selected if r["step"] == "record_cleanup_retry"]
            business = initial + later
            burst.append({
                "run_id": stamp, "concurrency": count,
                "all_measured_requests": len(selected), "all_measured_failures": sum(not r["ok"] for r in selected),
                "duration_s": level["wall_seconds"], "all_measured_rps": round(len(selected) / level["wall_seconds"], 3),
                "business_requests": len(business), "business_failures": sum(not r["ok"] for r in business),
                "business_success_pct": round(100 * sum(r["ok"] for r in business) / len(business), 3),
                "initial_attempts": len(initial), "initial_failures": sum(not r["ok"] for r in initial),
                "initial_request_p95_ms": quantile([r["latency_ms"] for r in initial], .95),
                "later_api_requests": len(later), "later_api_failures": sum(not r["ok"] for r in later),
                "later_api_p95_ms": quantile([r["latency_ms"] for r in later], .95),
                "redundant_cleanup_requests": len(redundant), "expected_cleanup_404": sum(r["status"] == 404 for r in redundant),
            })
            for step in dict.fromkeys(r["step"] for r in selected):
                endpoint_rows.append({"run_id": stamp, "concurrency": count, "step": step, **summarize([r for r in selected if r["step"] == step])})

    attempts, stage_rows = [], []
    persistent_summary = None
    for path in sorted(RUNS.glob("persistent-*/summary.json")):
        request_path = path.parent / "requests.csv"
        source_paths += [request_path, path]
        metadata = json.loads(path.read_text(encoding="utf-8"))
        rows = read_csv(request_path)
        login = [r for r in rows if r["phase"] == "preparation" and r["step"] == "login"]
        monitor = [r for r in rows if r["phase"] == "monitor"]
        business = [r for r in rows if r["phase"] in ("load", "soak")]
        assert login, f"Login step name not recognized in {request_path}"
        attempts.append({
            "run_id": path.parent.name, "started_at": metadata["started_at"], "finished_at": metadata.get("finished_at"),
            "login_attempts": len(login), "login_success": sum(r["ok"] for r in login), "login_failed": sum(not r["ok"] for r in login),
            "business_requests": len(business), "business_failures": sum(not r["ok"] for r in business),
            "monitor_requests": len(monitor), "monitor_failures": sum(not r["ok"] for r in monitor),
            "stop_reason": metadata.get("stop_reason"), "error_types": dict(Counter(r["error_type"] for r in rows if not r["ok"])),
            "cleanup": metadata.get("cleanup"),
        })
        for stage in metadata["stages"]:
            selected = [r for r in rows if r["phase"] == stage["phase"] and r["concurrency"] == stage["concurrency"]]
            measured = summarize(selected, stage["duration_s"])
            assert measured["requests"] == stage["requests"] and measured["p95_ms"] == stage["p95_ms"]
            stage_rows.append({"run_id": path.parent.name, "phase": stage["phase"], "concurrency": stage["concurrency"], **measured, "run_stopped_early": bool(metadata.get("stop_reason")), "stop_reason": metadata.get("stop_reason")})
        if path.parent.resolve() == persistent_dir:
            persistent_summary = metadata
    assert persistent_summary is not None
    probe_path = sorted(RUNS.glob("connection_probe_*.csv"))[-1]
    source_paths.append(probe_path)
    probes = read_csv(probe_path)
    first = [r for r in burst if r["run_id"] == "20261111-213539"]
    repeat = next(r for r in burst if r["run_id"] == "20261111-214021")
    conclusion = "尚未測得最大可用人數。已完成 1–50 人短時間突發測試；持續操作補測因連線與健康檢查錯誤提前停止。約 19 個保留 Session 後的新連線失敗，是本次路徑的觀測，尚未定位原因。"
    evidence = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "target": persistent_summary["target"], "app_version": "v1.0.0", "conclusion": conclusion,
        "maximum_supported_users": None, "completed_sustained_stages": 0, "completed_soak": False,
        "owner_reported_environment": {"tailscale_version": "1.104.5", "funnel_enabled": True, "upstream": "http://127.0.0.1:5000", "source": "User relayed classmate's diagnostic output; not directly inspected", "reported_cached_menus": 36},
        "server_started_at_after_restart": persistent_summary["initial_health"]["started_at"],
        "deployment_comparability": "Burst tests preceded the 21:47 backend restart; persistent tests and connection probe followed it. Do not treat them as a single unchanged deployment.",
        "burst_runs": burst_meta, "burst_stages": burst, "persistent_attempts": attempts, "partial_stages": stage_rows,
        "connection_probe": probes,
        "tailscale_research": {"url": FUNNEL_DOC, "consulted_on": "2026-11-11", "finding": "Official Funnel limitations list non-configurable bandwidth limits, but no published 18/19 concurrent-connection cap. Absence of documentation does not establish unlimited capacity."},
        "measurement_notes": [
            "P95 uses linear interpolation over all recorded attempts, including failed attempts. Failure duration is not a successful response latency.",
            "First request includes client scheduling, DNS/TCP/TLS, network, ingress and backend time; no phase-level timing was captured.",
            "Later API requests follow the first request in the same requests.Session; retries/reconnections may still occur. Warm physical sockets were not independently verified.",
            "Burst all_measured_rps includes one redundant cleanup DELETE per user, normally returning expected 404. Business metrics exclude that request.",
            "The 18 prepared users were not all actively operating: only the one-user stage ran for 12.16 seconds, while all three independent health checks failed.",
            "The probe retained client Session objects; simultaneous live TCP socket count and any per-IP versus global cap were not independently verified.",
            "No server CPU/RAM/disk/network/DB monitoring; cause cannot be assigned to Tailscale, Waitress or SQLite.",
            "No browser rendering/assets, photo uploads, paid/external AI or Places requests were tested. No hours-long reliability result exists.",
            "Persistent test records returned to baseline and those logins were logged out. Earlier burst login tokens were not retained; owner cleanup or expiry is needed.",
        ],
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
    }
    (out / "analysis.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "burst_summary.csv", burst)
    write_csv(out / "stage_summary.csv", stage_rows)
    write_csv(out / "endpoint_summary.csv", endpoint_rows)
    write_csv(out / "connection_probe.csv", probes)
    write_csv(out / "preparation_summary.csv", [{k: v for k, v in r.items() if k not in ("cleanup", "error_types")} for r in attempts])

    x = [r["concurrency"] for r in first]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "短時間突發：延遲主要集中在新 Session 的首請求", "P95 請求耗時（秒）")
    for field, label, color, marker in [("initial_request_p95_ms", "首請求 /auth/user", RED, "s"), ("later_api_p95_ms", "同一流程後續 7 項 API", GREEN, "o")]:
        ax.plot(x, [r[field]/1000 for r in first], color=color, marker=marker, label=label, linewidth=2)
        ax.scatter([30], [repeat[field]/1000], edgecolors=color, facecolors="white", marker="D", s=70, zorder=4)
    ax.axhline(2, color=ORANGE, linestyle="--", label="2 秒參考線（尚非容量結論）")
    ax.annotate("50 人首請求 P95 17.54 秒", (50, first[-1]["initial_request_p95_ms"]/1000), xytext=(27, 19), arrowprops={"arrowstyle": "->", "color": MUTED})
    ax.annotate("30 人首輪：3 次 TLS EOF\n空心菱形：30 人重測", (30, first[4]["initial_request_p95_ms"]/1000), xytext=(6, 11), arrowprops={"arrowstyle": "->", "color": MUTED})
    ax.set_xticks(x); ax.set_xlabel("同時啟動的虛擬使用者數（每人只跑一輪流程）")
    ax.set_ylim(0, 22); ax.legend(loc="upper left", frameon=False, fontsize=10)
    save_figure(fig, out / "01-api-latency.png", "來源：21:35 首輪、21:40 重測。P95 含失敗嘗試耗時；後續 API 排除多餘的清理 DELETE。")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "唯讀連線探測：第 20 次失敗，釋放一個 Session 後成功", "請求完成／失敗耗時（秒）")
    for phase, ok, color, marker, label in [("hold", True, GREEN, "o", "保留既有 Session，新建 Session：HTTP 200"), ("hold", False, RED, "x", "新建 Session：TLS EOF"), ("after_releasing_one", True, BLUE, "^", "釋放一個後重試：HTTP 200")]:
        selected = [(i+1, r) for i, r in enumerate(probes) if r["phase"] == phase and (r["status"] == 200) == ok]
        ax.scatter([i for i, _ in selected], [r["latency_ms"]/1000 for _, r in selected], color=color, marker=marker, s=65, linewidths=2, label=label)
    ax.axvline(19.5, color="#a7b3b8", linestyle=":")
    ax.annotate("第 20 次：TLS EOF\n當時保留 19 個 Session", (20, probes[19]["latency_ms"]/1000), xytext=(11, .25), arrowprops={"arrowstyle": "->", "color": RED}, color=RED)
    ax.annotate("釋放一個，再連成功", (21, probes[-1]["latency_ms"]/1000), xytext=(13, 1.8), arrowprops={"arrowstyle": "->", "color": BLUE}, color=BLUE)
    ax.set_xlim(0, 22); ax.set_ylim(0, 2.5); ax.set_xticks([1, 5, 10, 15, 19, 20, 21])
    ax.set_xlabel("依序發出的 /health 請求（每次新建一個 HTTPS Session）")
    ax.legend(loc="upper left", frameon=False, fontsize=10)
    save_figure(fig, out / "02-connections.png", "只量測單一客戶端路徑；Session 數並非已驗證的即時 TCP 連線數，也不能換算成使用者上限。")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "短時間突發：各級實測吞吐量與失敗次數", "每秒完成／失敗的請求數（RPS）")
    bars = ax.bar(x, [r["all_measured_rps"] for r in first], width=2.5, color=BLUE)
    for rect, r in zip(bars, first):
        ax.text(rect.get_x()+rect.get_width()/2, rect.get_height()+.6, f"{r['all_measured_rps']:.1f}\n失敗 {r['all_measured_failures']}/{r['all_measured_requests']}", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(x); ax.set_xlabel("同時啟動的虛擬使用者數")
    ax.set_ylim(0, max(r["all_measured_rps"] for r in first)*1.3)
    save_figure(fig, out / "03-throughput.png", "每人 9 次計量請求，含 1 次預期 404 的清理重試；這是短時間吞吐量，不能當作可持續的最大 RPS。")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "持續操作補測：兩次準備失敗，一次被健康檢查中止", "登入嘗試數（次）")
    positions = list(range(len(attempts)))
    ax.bar(positions, [r["login_success"] for r in attempts], color=GREEN, label="登入成功", width=.55)
    ax.bar(positions, [r["login_failed"] for r in attempts], bottom=[r["login_success"] for r in attempts], color=RED, label="登入失敗（TLS）", width=.55)
    for pos, r in zip(positions, attempts):
        ax.text(pos, r["login_success"]/2, f"成功 {r['login_success']}", ha="center", va="center", color="white", fontweight="bold")
        if r["login_failed"]:
            ax.text(pos, r["login_success"]+r["login_failed"]/2, f"失敗 {r['login_failed']}", ha="center", va="center", color="white", fontweight="bold")
        else:
            ax.text(pos, r["login_success"]+2, "僅 1 人操作 12.16 秒\n健康檢查 3/3 失敗", ha="center", color=RED, fontsize=10)
    ax.set_xticks(positions, ["21:50\n50 帳號，5 路準備", "21:52\n50 帳號，依序準備", "21:57\n18 帳號，依序準備"])
    ax.set_ylim(0, 63); ax.legend(loc="upper right", frameon=False)
    save_figure(fig, out / "04-preparation.png", "前兩次未進入業務加壓。第三次只有 14 個業務請求；60 秒階梯與 180 秒持續測試均未完成。")

    def img(name, alt):
        encoded = base64.b64encode((out/name).read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{encoded}" alt="{html.escape(alt)}">'

    burst_table = "".join(f"<tr><td>{r['concurrency']}{'（重測）' if r['run_id'].endswith('214021') else ''}</td><td>{r['duration_s']:.3f}</td><td>{r['business_requests']}</td><td>{r['business_failures']}</td><td>{r['initial_request_p95_ms']/1000:.3f}</td><td>{r['later_api_p95_ms']/1000:.3f}</td><td>{r['all_measured_rps']:.2f}</td></tr>" for r in burst)
    stage_table = "".join(f"<tr><td>{r['concurrency']} 人（中止）</td><td>{r['duration_s']:.2f}</td><td>{r['requests']}</td><td>{r['failed']}</td><td>{r['p50_ms']/1000:.3f}</td><td>{r['p95_ms']/1000:.3f}</td><td>{r['rps']:.3f}</td></tr>" for r in stage_rows)
    clean = all(r["cleanup"].get("all_baselines_match") and not r["cleanup"].get("pending") for r in attempts)
    doc = f'''<!doctype html>
<html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NutriLens 壓力測試結果 2026-11-11</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:white;color:{INK};font:16px/1.75 system-ui,"Microsoft JhengHei",sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 20px 50px}}h1{{font-size:28px;line-height:1.4;margin:0 0 16px}}h2{{font-size:21px;margin:32px 0 12px}}p{{overflow-wrap:anywhere}}.meta,figcaption{{color:{MUTED}}}.outcome{{border-left:4px solid {ORANGE};padding:12px 16px;background:#fff4df}}img{{display:block;width:100%;height:auto;margin:22px 0 10px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}}td,th{{padding:9px;text-align:right;border-bottom:1px solid #dce4e7}}td:first-child,th:first-child{{text-align:left}}a{{color:{BLUE}}}code{{overflow-wrap:anywhere}}li{{margin:8px 0}}@media(max-width:500px){{main{{padding:18px 12px}}h1{{font-size:24px}}}}@media print{{main{{max-width:none;padding:0}}img{{break-inside:avoid}}}}</style></head><body><main>
<p class="meta">2026-11-11 · v1.0.0 · Asia/Taipei · 測試已停止</p>
<h1>NutriLens 壓力測試結果</h1><p class="outcome">{conclusion}</p>
<p>目標：<code>{html.escape(persistent_summary['target'])}</code><br>突發測試：21:35–21:38，30 人重測：21:40–21:42。補測與連線探測：21:50–21:58。<br>已準備 50 組專用帳號。第一輪 1,404 次、30 人重測 270 次計量請求；不含準備登入與額外清理。第一輪有 3 次 TLS EOF，重測無錯誤。</p>
<h2>大量使用者同時進來時，哪裡變慢？</h2>
{img('01-api-latency.png', '1 到 50 人突發測試，首請求 P95 上升至 17.54 秒，後續七項 API 的 P95 明顯較低；30 人首輪有 3 次 TLS EOF。')}
<p>每位使用者以新 Session 執行一次 /auth/user 與七項依序讀寫操作，最後多做一次刪除清理。首請求包含建立連線及伺服器處理的總耗時，尚無法分離 DNS、TCP、TLS、Funnel 或後端各自耗時。後續操作重用同一 Session，但沒有逐一驗證底層 socket 是否重用。</p>
<p>50 人首請求 P95 為 {first[-1]['initial_request_p95_ms']/1000:.2f} 秒，單次最慢 22.48 秒；後續七項 API 合併 P95 為 {first[-1]['later_api_p95_ms']/1000:.3f} 秒。30 人重測的首請求 P95 為 {repeat['initial_request_p95_ms']/1000:.2f} 秒。這是短時間流程結果，不能據此認定可長時間穩定供 50 人使用。先前「5 人是容量上限」的判讀已撤回：它只反映混合統計跨過了 2 秒參考線。</p>
<h2>18 或 19 是 Tailscale 官方限制嗎？</h2>
<p>查閱 <a href="{FUNNEL_DOC}">Tailscale Funnel 官方限制文件</a>（2026-11-11）：列出連接埠、TLS 與不可自行調整的頻寬限制，未列出 18／19 條同時連線的上限。文件沒有列出不代表無限容量。Funnel 提供公開存取，Serve 供 tailnet 內部存取；tailnet 成員／裝置配額不能直接當網站訪客上限。</p>
{img('02-connections.png', '前 19 次保留 Session 的 health 請求成功，第 20 次 TLS EOF，釋放一個後重試成功。')}
<p>這次唯讀探測由同一台電腦依序新建並保留 Session：前 19 次 HTTP 200，第 20 次在約 0.72 秒後 TLS EOF；關閉一個既有 Session、等待 2 秒後，新 Session 再次成功。這支持路徑中存在與佔用連線相關的現象，但未量測當時真正存活的 TCP socket 總數，亦未辨別單一 IP／全域／客戶端限制，不能稱為已證實的 Tailscale 上限。</p>
<p>同學回報：Tailscale 1.104.5，Funnel 已開啟並轉送到 http://127.0.0.1:5000；本機 /health 正常，餐廳菜單快取 36 份。此為同學提供的環境資訊，並非本測試直接登入主機查核。後端於 21:47 重啟；前面的突發測試在重啟前、連線探測與補測在重啟後，環境不能假定完全相同。</p>
<h2>短時間吞吐量與完整數據</h2>
{img('03-throughput.png', '短時間吞吐量在 40 人級別為 33.5 RPS，50 人降至 18.9 RPS，30 人首輪 3 次失敗。')}
<div class="scroll"><table><thead><tr><th>虛擬人數</th><th>持續秒</th><th>業務請求</th><th>業務失敗</th><th>首請求 P95 秒</th><th>後續 API P95 秒</th><th>含清理 RPS</th></tr></thead><tbody>{burst_table}</tbody></table></div>
<p>P95 為所有已記錄嘗試耗時的第 95 百分位，以線性插值計算，包含失敗嘗試。業務請求每人 8 次；RPS 欄每人 9 次，含多餘清理 DELETE（預期 404 計為符合預期），兩者分母不同。這些 RPS 不能當成可持續的最大處理量。</p>
<h2>持續操作測試為何沒有完成？</h2>
{img('04-preparation.png', '前兩次 50 帳號準備各成功 19、失敗 31；第三次 18 帳號準備成功，但獨立健康檢查三次均失敗。')}
<p>原規劃每級 60 秒，最後 180 秒持續操作，實際均未完成。前兩次在登入準備階段停止；第三次雖準備 18 組帳號，只有 1 人操作級別開始，12.16 秒後因獨立健康檢查連續三次 TLS 失敗而自動中止。不能將已登入 18 組或 14 次業務請求全部成功，解讀成 18 人穩定通過。以下僅列中止前觀測值。</p>
<div class="scroll"><table><thead><tr><th>實際操作</th><th>持續秒</th><th>業務請求</th><th>業務失敗</th><th>P50 秒</th><th>P95 秒</th><th>RPS</th></tr></thead><tbody>{stage_table}</tbody></table></div>
<p>補測每輪七項依序操作後停頓 4–6 秒。準備、暖機、健康檢查、清理均單獨記錄，未混入上表業務成功率。2 秒 P95、失敗率低於 1% 僅為暫定品質參考，尚未得到可通過完整流程的人數級別。</p>
<h2>資料驗證、限制與下一步</h2>
<p>原兩輪的測試紀錄已清理。三次補測的紀錄 ID 基線比對{'全部一致，待清理紀錄均為 0' if clean else '仍需檢查'}，成功取得的登入 token 皆有登出紀錄。前兩輪突發測試的歷史登入 token 未保存，需由擁有者清除或等待到期；50 組測試帳號依使用者決定保留。</p>
<p>未取得伺服器 CPU、記憶體、磁碟、網路或資料庫監控，無法判定是哪一層造成失敗。本次只測 API，未測瀏覽器畫面／靜態資源、上傳、Gemini、OpenAI、Google Places，亦未測數小時運行。</p>
<ol><li>先以手機行動網路確認外部能登入與完成操作，僅能驗證可達性。</li><li>同一時段比較伺服器 localhost／既有私有路徑與公開 Funnel，配合主機 TCP 連線數、Tailscale 診斷與後端 access log 定位。TLS 失敗時是否有後端 HTTP 紀錄，是關鍵線索。</li><li>再以第二台電腦／不同出口做小量對照，判斷門檻是否只出現在同一來源；問題定位後才恢復逐級與持續測試。</li></ol>
<h2>數據檔案</h2><p><a href="analysis.json">完整分析與來源 SHA256</a> · <a href="burst_summary.csv">突發各級 CSV</a> · <a href="endpoint_summary.csv">各 API CSV</a> · <a href="connection_probe.csv">逐筆連線探測 CSV</a> · <a href="preparation_summary.csv">登入準備 CSV</a> · <a href="stage_summary.csv">中止前操作 CSV</a></p>
<p>原始逐筆與執行摘要保留於相鄰 runs 目錄；本報告僅離線讀取資料產生，沒有再向遠端施加負載。報告未包含帳號密碼。</p></main></body></html>'''
    (out / "index.html").write_text(doc, encoding="utf-8")
    narrative = f"# NutriLens 壓力測試結果\n\n{conclusion}\n\n- 50 人短時間突發：首請求 P95 {first[-1]['initial_request_p95_ms']/1000:.2f} 秒，後續 API P95 {first[-1]['later_api_p95_ms']/1000:.3f} 秒。\n- 30 人首輪 3 次 TLS EOF，重測無錯誤。\n- 唯讀探測：保留 19 個 Session 後，第 20 次新連線失敗；關閉一個後重試成功。未驗證即時 socket 總數。\n- 持續測試未完成：前兩次準備各 19 成功／31 失敗；第三次只有 1 人操作 12.16 秒、14 次業務請求，健康檢查 3/3 失敗後停止。\n- 同學回報 Tailscale 1.104.5，Funnel 轉送到 127.0.0.1:5000。官方未公布 18/19 連線上限，已列不可自行調整的頻寬限制。\n- 突發測試在 21:47 重啟前，後續探測與補測在重啟後；不能假定部署條件完全一致。\n- 先前『5 人容量上限』的判讀撤回；最大可用人數仍未知。\n\n官方文件：{FUNNEL_DOC}\n\n完整圖表與限制見 index.html，逐級數據見 burst_summary.csv，詳細證據與來源雜湊見 analysis.json。\n"
    (out / "RESULTS.md").write_text(narrative, encoding="utf-8")
    print(json.dumps({"report": str(out / "index.html"), "conclusion": conclusion, "burst_levels": len(burst), "partial_stages": len(stage_rows), "probe_requests": len(probes), "cleanup_baselines_match": clean}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("persistent_dir", type=Path)
    build(parser.parse_args().persistent_dir.resolve())
