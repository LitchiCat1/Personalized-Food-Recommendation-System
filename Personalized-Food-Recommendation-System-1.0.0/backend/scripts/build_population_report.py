"""Create charts and a portable report from the second test's saved evidence."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from remote_capacity_test import quantile, summarize
from remote_population_test import now, save_json

GREEN, BLUE, RED, ORANGE, INK = "#00876b", "#2868b2", "#c43b45", "#ad6900", "#192c30"


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["ok"] = row["ok"].lower() == "true"
        row["concurrency"], row["status"] = int(row["concurrency"]), int(row["status"])
        row["elapsed_s"], row["latency_ms"] = float(row["elapsed_s"]), float(row["latency_ms"])
    return rows


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", color=INK, pad=16, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c4ced2")
    ax.grid(axis="y", color="#e0e6e8"); ax.set_axisbelow(True)


def save(fig, path, note):
    fig.text(.02, .02, note, fontsize=9, color="#52636a")
    fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build(out):
    summary_paths = sorted(out.glob("load_summary_*.json"))
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in summary_paths]
    if not runs or any("finished_at" not in run for run in runs):
        raise ValueError("All load runs must finish before the final report is built")
    annotation_path = out / "run_annotations.json"
    annotations = json.loads(annotation_path.read_text(encoding="utf-8")) if annotation_path.exists() else {}
    summary = {**runs[-1], "started_at": runs[0]["started_at"], "stages": [], "source_runs": runs, "run_annotations": annotations}
    requests, request_paths = [], []
    origin = datetime.fromisoformat(summary["started_at"])
    for run in runs:
        request_path = out / f"load_requests_{run['load_id']}.csv"
        request_paths.append(request_path)
        for row in csv_rows(request_path):
            row.update({"run_id": run["load_id"], "run_elapsed_s": row["elapsed_s"], "elapsed_s": (datetime.fromisoformat(row["timestamp"])-origin).total_seconds()})
            if row["phase"] == "steady" and annotations.get(run["load_id"], {}).get("steady_valid_for_capacity") is False:
                row["phase"] = "invalidated_steady"
            requests.append(row)
        summary["stages"].extend({**s, "run_id": run["load_id"]} for s in run["stages"] if not (s["phase"] == "steady" and annotations.get(run["load_id"], {}).get("steady_valid_for_capacity") is False))
    preparation_path = out / "preparation_summary.json"
    prep = json.loads(preparation_path.read_text(encoding="utf-8"))
    population_path = out / "population.json"
    population = json.loads(population_path.read_text(encoding="utf-8"))
    report = out / "report"
    report.mkdir(exist_ok=True)
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11, "axes.titlesize": 14})
    burst = [s for s in summary["stages"] if s["phase"] == "burst" and s.get("started")]
    steady = [s for s in summary["stages"] if s["phase"] == "steady"]
    soaks = [s for s in summary["stages"] if s["phase"] == "soak"]
    passed = [s["concurrency"] for s in steady if s.get("reference_pass")]
    soak_passed = bool(soaks) and all(s.get("reference_pass") for s in soaks)
    highest = max(passed, default=0)
    verification = summary.get("verification", {})
    conclusion = f"新增 {prep['accounts_verified']} 組帳號、{prep['retained_records_verified']} 筆飲食紀錄。"
    if highest:
        conclusion += f"持續操作參考門檻通過至 {highest} 人（每級 {summary['stage_seconds_requested']} 秒），最高通過級別的 {summary['soak_seconds_requested']} 秒補測{'通過' if soak_passed else '未通過或未完成'}。"
    else:
        conclusion += "沒有通過完整持續操作參考門檻的級別。"
    conclusion += "此為本次操作頻率與路徑的結果，系統最大可用人數仍未確定。"
    phase_stats = [{"phase": phase, **summarize([r for r in requests if r["phase"] == phase]), "errors": dict(Counter(r["error_type"] for r in requests if r["phase"] == phase and not r["ok"]))} for phase in dict.fromkeys(r["phase"] for r in requests)]
    endpoint_stats = []
    for phase, level, step in dict.fromkeys((r["phase"], r["concurrency"], r["step"]) for r in requests):
        endpoint_stats.append({"phase": phase, "concurrency": level, "step": step, **summarize([r for r in requests if (r["phase"], r["concurrency"], r["step"]) == (phase, level, step)])})
    for stage in summary["stages"]:
        if stage.get("started"):
            selected = [r for r in requests if r["phase"] == stage["phase"] and r["concurrency"] == stage["concurrency"] and r["run_id"] == stage["run_id"]]
            assert len(selected) == stage["requests"]
            assert summarize(selected, stage["duration_s"])["p95_ms"] == stage["p95_ms"]
    business = [r for r in requests if r["phase"] in ("burst", "steady", "soak")]
    evidence = {"generated_at": now(), "conclusion": conclusion, "maximum_supported_users": None, "preparation": prep, "load": summary, "business": summarize(business), "phase_statistics": phase_stats,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in summary_paths+request_paths+[preparation_path, population_path, out / "preparation_requests.csv"]+([annotation_path] if annotation_path.exists() else [])},
        "limitations": ["Single load generator; no remote host CPU/RAM/DB/network metrics.", "requests HTTP/1.1 API traffic; no browser/static-assets, photo uploads or external AI/Places requests.", "A successful short burst is not proof of sustained capacity. First request and later API samples have different denominators when first requests fail.", "One persistent health-check session also uses the tested ingress path.", "Failed attempts are included in latency percentiles; their duration is not a successful response latency.", "Steady stages stop at the first quality-reference failure; higher levels are untested for sustained use.", "Retained seed data are deliberate manual records; only this run's temporary records are deleted."]}
    save_json(report / "analysis.json", evidence)
    write_csv(report / "stages.csv", [{k: v for k, v in s.items() if not isinstance(v, dict)} for s in summary["stages"]])
    write_csv(report / "burst_connections.csv", [{"concurrency": s["concurrency"], "users": s["concurrency"], "successful_users": s["users_with_successful_cycles"], "users_with_failure": s["users_with_failed_cycles"], "requests": s["requests"], "failed": s["failed"], "first_requests": s["first_request"]["requests"], "first_failed": s["first_request"]["failed"], "first_p95_ms": s["first_request"]["p95_ms"], "later_requests": s["later_api"]["requests"], "later_failed": s["later_api"]["failed"], "later_p95_ms": s["later_api"]["p95_ms"]} for s in burst])
    write_csv(report / "endpoints.csv", endpoint_stats)
    write_csv(report / "account_verification.csv", verification.get("checks", []))
    write_csv(report / "requests_combined.csv", requests)
    write_csv(report / "retained_records.csv", [{"account": a["account"], "uid": a["uid"], "record_id": r["client_record_id"], "timestamp": r["timestamp"], "meal_type": r["meal_type"], "source": r["source"], "food_names": " / ".join(f["name"] for f in r["foods"]), **{"total_"+k: round(sum(f[k] for f in r["foods"]), 2) for k in ("calories", "protein", "carbs", "fat", "sodium", "fiber", "sugar", "saturated_fat", "trans_fat")}} for a in population["accounts"] for r in a["records"]])

    x = [s["concurrency"] for s in burst]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "突發測試：首請求與後續 API 的延遲", "P95 嘗試耗時（秒）")
    for key, label, color, marker in [("first_request", "新 Session 首請求", RED, "s"), ("later_api", "首請求成功後的 API", GREEN, "o")]:
        ax.plot(x, [(s[key]["p95_ms"] or 0)/1000 for s in burst], color=color, marker=marker, linewidth=2, label=label)
    ax.axhline(2, color=ORANGE, linestyle="--", label="2 秒品質參考")
    ax.set_xticks(x); ax.set_xlabel("同時啟動的虛擬使用者數（各跑一輪）"); ax.set_ylim(bottom=0)
    ax.legend(frameon=False)
    save(fig, report / "01-burst-latency.png", "首請求失敗者不再執行後續操作；兩條線樣本不同，需合看成功率。延遲包含失敗嘗試。")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    style(ax, "大家同時開始操作：有多少人完成？", "每批使用者的比例（%）")
    positions = list(range(len(burst)))
    successful = [100*s["users_with_successful_cycles"]/s["concurrency"] for s in burst]
    ax.bar(positions, successful, width=.65, color=GREEN, label="完成整個操作流程")
    ax.bar(positions, [100-v for v in successful], bottom=successful, width=.65, color=RED, label="未完成（首請求失敗）")
    for pos, s, value in zip(positions, burst, successful):
        ax.text(pos, value/2, f"完成\n{s['users_with_successful_cycles']} 人", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        failed = s["concurrency"]-s["users_with_successful_cycles"]
        if 100-value >= 15:
            ax.text(pos, value+(100-value)/2, f"未完成\n{failed} 人", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        elif failed:
            ax.text(pos, 102, f"未完成 {failed} 人", ha="center", va="bottom", color=RED, fontsize=9)
    ax.set_xticks(positions, [str(n) for n in x]); ax.set_xlabel("同時開始操作的人數"); ax.set_ylim(0, 125)
    ax.set_yticks([0, 25, 50, 75, 100]); ax.legend(frameon=False, loc="upper left", ncol=2, fontsize=10)
    save(fig, report / "02-burst-success.png", "每根柱子代表一批人。綠色越多，代表越多人能完成；紅色代表這次未能進入後續操作。")

    active = [s for s in steady+soaks if s.get("started")]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    positions = list(range(len(active)))
    labels = [f"{s['concurrency']} 人\n{s['duration_s']:.0f} 秒" + (" 持續" if s["phase"] == "soak" else "") for s in active]
    style(ax, "登入後持續使用：大部分操作要等多久？", "約 95% 的 API 請求在此時間內回應（秒）")
    ax.bar(positions, [s["p95_ms"]/1000 for s in active], width=.6, color=[GREEN if s["reference_pass"] else RED for s in active])
    ax.axhline(2, color=ORANGE, linestyle="--", label="本次採用的 2 秒參考線")
    for pos, s in zip(positions, active):
        ax.text(pos, s["p95_ms"]/1000+.04, f"{s['p95_ms']/1000:.2f} 秒\n失敗 {s['failed']} 次", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(positions, labels); ax.set_xlabel("同時使用人數，以及這批人實際連續使用的時間")
    ax.set_ylim(0, max([2.5]+[s["p95_ms"]/1000*1.3 for s in active])); ax.legend(frameon=False)
    if not active:
        ax.text(.5, .5, "沒有開始的持續操作級別", ha="center", transform=ax.transAxes)
    save(fig, report / "03-steady.png", "柱子越低表示等待越短；這是單次 API 請求的時間，不是完整網頁載入或整輪操作時間。")

    fig, (a, b) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    health = [r for r in requests if r["phase"] == "monitor"]
    style(a, "測試期間：健康檢查與業務錯誤", "健康檢查耗時（秒）")
    for ok, color, label, marker in [(True, GREEN, "健康檢查成功", "o"), (False, RED, "健康檢查失敗", "x")]:
        selected = [r for r in health if r["ok"] == ok]
        a.scatter([r["elapsed_s"]/60 for r in selected], [r["latency_ms"]/1000 for r in selected], color=color, label=label, marker=marker, s=20)
    a.set_ylim(bottom=0); a.legend(frameon=False)
    style(b, "", "每 10 秒失敗數")
    last = max((r["elapsed_s"] for r in business), default=0)
    buckets = list(range(int(last//10)+1))
    b.bar([(i*10+5)/60 for i in buckets], [sum(not r["ok"] for r in business if int(r["elapsed_s"]//10) == i) for i in buckets], width=8/60, color=RED)
    b.set_xlabel("自登入準備開始的經過時間（分鐘）")
    save(fig, report / "04-health-errors.png", "健康檢查、登入、暖機、業務、清理各自記錄；此圖只顯示監測與 burst／steady／soak 業務錯誤。")

    def image(name, alt):
        encoded = base64.b64encode((report/name).read_bytes()).decode("ascii")
        return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{encoded}">'
    def td(value):
        return f"<td>{html.escape(str(value))}</td>"
    burst_table = "".join("<tr>"+"".join(td(v) for v in [s["concurrency"], f"{s['users_with_successful_cycles']}/{s['concurrency']}", s["requests"], s["failed"], f"{s['first_request']['p95_ms']/1000:.3f}", f"{s['later_api']['p95_ms']/1000:.3f}" if s["later_api"]["p95_ms"] is not None else "無資料", f"{s['duration_s']:.2f}"])+"</tr>" for s in burst)
    sustained_table = ""
    for s in steady+soaks:
        values = [s["phase"], s["concurrency"], "通過參考" if s.get("reference_pass") else ("未開始：暖機失敗" if not s.get("started") else "未通過／中止"), f"{s['duration_s']:.2f}" if s.get("started") else "未開始", s.get("requests", 0), s.get("failed", "無業務請求"), f"{s['p95_ms']/1000:.3f}" if s.get("p95_ms") is not None else "無資料"]
        sustained_table += "<tr>"+"".join(td(v) for v in values)+"</tr>"
    errors = Counter(r["error_type"] for r in requests if not r["ok"])
    resources = [point for run in runs for point in run.get("generator_resources", [])]
    generator_host_peak = max((point["local_host_cpu_percent"] for point in resources), default=0)
    generator_process_peak = max((point["local_process_cpu_percent"] for point in resources), default=0)
    warmup_failures = [s for s in steady+soaks if not s.get("started")]
    stop_text = summary.get("stop_reason") or summary.get("steady_staircase_stopped_reason") or "已達本次規劃級別"
    largest_burst = max(burst, key=lambda s: s["concurrency"], default=None)
    plain_burst = f"{largest_burst['concurrency']} 人同時開始時，{largest_burst['users_with_successful_cycles']} 人完成，{largest_burst['concurrency']-largest_burst['users_with_successful_cycles']} 人在一開始連線失敗。" if largest_burst else "沒有完成同時開始操作的測試。"
    plain_steady = f"已登入後，{highest} 人通過每級 {summary['stage_seconds_requested']} 秒的連續操作；再測 {summary['soak_seconds_requested']} 秒的結果為{'通過' if soak_passed else '未通過或未完成'}。" if highest else "尚無人數級別完成並通過持續操作測試。"
    plain_limit = f"增加到 {warmup_failures[0]['concurrency']} 人時，準備連線就有失敗，未開始該級連續操作。" if warmup_failures else "尚無法從本輪測試定出真正的人數上限。"
    doc = f'''<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>新增 100 帳號壓測結果</title>
<style>*{{box-sizing:border-box}}body{{margin:0;color:#192c30;background:white;font:16px/1.75 system-ui,"Microsoft JhengHei",sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 20px 50px}}h1{{font-size:28px;line-height:1.4}}h2{{font-size:21px;margin-top:32px}}.outcome{{border-left:4px solid #ad6900;background:#fff4df;padding:12px 16px}}.meta{{color:#52636a}}img{{display:block;width:100%;height:auto;margin:24px 0}}table{{border-collapse:collapse;width:100%;white-space:nowrap;font-variant-numeric:tabular-nums}}td,th{{text-align:right;padding:9px;border-bottom:1px solid #dce4e7}}td:first-child,th:first-child{{text-align:left}}.scroll{{overflow:auto}}p,li{{overflow-wrap:anywhere}}a{{color:#2868b2}}@media(max-width:500px){{main{{padding:18px 12px}}h1{{font-size:24px}}}}@media print{{img{{break-inside:avoid}}main{{padding:0;max-width:none}}}}</style></head><body><main>
<p class="meta">2026-11-11 · v1.0.0 · Asia/Taipei · 新增帳號批次 {html.escape(out.name)}</p><h1>100 組新帳號與隨機飲食紀錄：併發測試結果</h1><p class="outcome">{html.escape(conclusion)}</p>
<h2>先看實際使用結果</h2><ul><li><strong>大家一起開始：</strong>{html.escape(plain_burst)}</li><li><strong>已登入後繼續使用：</strong>{html.escape(plain_steady)}</li><li><strong>目前的限制：</strong>{html.escape(plain_limit)}這些結果只適用於本次操作頻率與網路路徑，不能保證真實使用者的所有功能都一樣。</li></ul>
<h2>圖一：大家一起開始，有多少人完成？</h2><p>每根柱子是一批同時開始的人。綠色是整輪完成，紅色是未完成。這裡的「開始」是已持有登入憑證後建立新連線，登入密碼驗證在準備階段另行完成。</p>{image('02-burst-success.png', '各批同時開始的人，完成與未完成的人數及比例')}
<h2>我們怎麼測？</h2><p>先新增 100 個測試帳號，每人放入 3 筆隨機飲食紀錄，讓測試時真的有資料可查。接著用程式同時操作多個不同帳號，實際向網站發送請求；不是只在紙上估算。</p><ol><li><strong>測「大家一起進來」：</strong>分批模擬 1、5、10、20、30、50、75、100 人，同時建立連線。每個人要完成查食物、查飲食與歷史紀錄、新增一筆、修改、確認內容及刪除；有一步失敗，就不算這個人整輪成功。</li><li><strong>測「登入後一直用」：</strong>先讓這一批人連上，再重複上述讀寫操作，每輪結束休息 4–6 秒，模擬使用者閱讀或思考。每種人數先測 1 分鐘，通過的最高人數再測 3 分鐘。</li><li><strong>看會不會斷線或弄錯資料：</strong>每 5 秒檢查網站是否回應，同時驗證新增、修改、刪除的內容。測完再逐帳號確認原本 3 筆紀錄仍正確，測試臨時紀錄已刪除。</li></ol><p>本次以「大部分請求 2 秒內回應、錯誤比例低於 1%」作為品質參考。測試的是程式對網站的資料操作，沒有包含網頁畫面載入、照片辨識或 AI 功能。</p>
<p>目標：{summary['target']}<br>準備：{prep['started_at']} 至 {prep['finished_at']}<br>併發測試（含登入與最終驗證）：{summary['started_at']} 至 {summary['finished_at']}<br>停止／結束原因：{html.escape(stop_text)}</p>
<h2>帳號與飲食紀錄</h2><p>新增 stress_test_20261111_051–150 共 {prep['accounts_created_or_recovered']} 組，每帳號早餐／午餐／晚餐各一筆，共 {prep['retained_records_verified']} 筆 source=manual。食物從本機既有營養資料庫抽樣，隨機份量 75–200g，每餐 1–3 項；這是合成測試紀錄。逐帳號驗證 ID 唯一性、食物名稱、餐別、來源及所有營養總量。帳號沿用原測試密碼，另存私有帳號 CSV，報告未含密碼或 token。</p>
<p>三筆保留紀錄的日期在建立時的前三天（11 月 8–10 日），可從歷史紀錄查看。測試後再次檢查 {verification.get('accounts_checked', 0)} 組帳號，其中 {verification.get('accounts_valid', 0)} 組仍恰有原本 3 筆紀錄，且沒有臨時紀錄。待清理臨時紀錄 {verification.get('pending_temporary_records', '未知')}，尚待登出 token {verification.get('outstanding_tokens', '未知')}。原 001–050 與其他使用者資料未作為寫入目標。</p>
<details><summary>查看每個人數的詳細數據與首請求延遲</summary><p>首請求含連線建立與後端處理，後續操作只統計首請求成功的人。P95 可理解為約 95% 的嘗試耗時在此值以下；失敗嘗試也計入，因此需搭配成功人數一起看。每人原定 8 個業務請求，級間間隔 5 秒，每級僅一輪。</p>{image('01-burst-latency.png', '各突發級別的首請求與後續 API P95')}
<div class="scroll"><table><thead><tr><th>人數</th><th>整輪成功人數</th><th>實際請求</th><th>失敗</th><th>首請求 P95 秒</th><th>後續 API P95 秒</th><th>測量秒</th></tr></thead><tbody>{burst_table}</tbody></table></div></details>
<h2>圖二：已登入後，連續操作是否順暢？</h2><p>{html.escape(plain_steady)}圖中柱子越低，代表等待越短。數字是「約 95% 的 API 請求在幾秒內回應」；例如 0.20 秒表示約 95% 的請求不到五分之一秒就收到回應，並非完成整張網頁的時間。</p>
{image('03-steady.png', '各人數及持續時間的大部分 API 請求回應秒數，附失敗次數')}
<details><summary>查看持續測試的完整數據與通過條件</summary><p>每級規劃 {summary['stage_seconds_requested']} 秒。只為本級建立 Session，暖機後重用；每輪 7 個依序讀寫請求後停頓 4–6 秒。通過參考門檻的最高級別另規劃 {summary['soak_seconds_requested']} 秒。參考條件：全程完成、業務失敗率低於 1%、P95 低於 2 秒、每人至少一輪成功且有失敗流程的人數比例低於 1%。暖機失敗的級別不算開始業務操作，更高持續級別不繼續增加。</p>
<div class="scroll"><table><thead><tr><th>情境</th><th>人數</th><th>結果</th><th>實測秒</th><th>業務請求</th><th>失敗</th><th>P95 秒</th></tr></thead><tbody>{sustained_table}</tbody></table></div>
<p>暖機失敗而未開始業務的級別：{html.escape('、'.join(str(s['concurrency'])+' 人' for s in warmup_failures) or '無')}。此門檻是本次測試定義，無法直接推算所有瀏覽器與操作頻率的容量。</p>
<p>執行修正說明：第一回的 1 人持續級別因監測視窗誤含前一段突發錯誤而提早停止，僅 1.832 秒／7 次成功請求，不列入持續容量結果。監測已修正為只計當前情境與當前人數，並通過離線回歸檢查後，只重測持續操作。原突發資料與中止紀錄均保留，合併逐筆 CSV 將該小段標為 invalidated_steady。</p>
</details><details><summary>查看連線錯誤與健康檢查圖</summary>{image('04-health-errors.png', '測試期間健康檢查耗時與每十秒業務失敗數')}
<p>獨立健康檢查每 5 秒一次，連續 3 次失敗即停止。持續操作最近 30 秒業務失敗率超過 5% 或 5xx 超過 5%（至少 30 個樣本）也停止；短時間突發包含新連線失敗，因此另看其整輪失敗率。所有階段錯誤分類：{html.escape(str(dict(errors)))}。HTTP status=0 表示未取得 HTTP 回應，不是伺服器傳回的狀態碼。</p>
<p>Tailscale 版本先前由同學回報為 1.104.5，Funnel 到 127.0.0.1:5000；本輪沒有直接檢查主機設定。<a href="https://tailscale.com/docs/features/tailscale-funnel#requirements-and-limitations">官方 Funnel 文件</a>未列出 18／19 條並行連線上限，僅有不可自行調整的頻寬等限制。本次觀測不能直接定義為 Tailscale 官方限制。</p>
</details>
<h2>可用範圍與數據</h2><p>本次使用單一負載產生器及 HTTP/1.1 API，包含一條獨立健康檢查 Session。P95 採線性插值且包含失敗嘗試耗時；失敗耗時不是成功回應時間。沒有取得遠端 CPU、記憶體、磁碟、網路或 SQLite 指標；analysis.json 中的資源值只屬本機負載產生器。本機整體 CPU 採樣最高 {generator_host_peak:.1f}%，測試程序最高 {generator_process_peak:.1f}%（程序數值可跨多個核心而超過 100%），因此端到端延遲也可能受到負載產生器影響。未測完整瀏覽器載入、照片上傳、Gemini、OpenAI、Google Places 或數小時運行。短時間 100 人突發、100 帳號存在與 100 人持續可用，是不同結果。</p>
<p><a href="analysis.json">完整分析與來源 SHA256</a> · <a href="stages.csv">各級 CSV</a> · <a href="burst_connections.csv">首請求／後續操作 CSV</a> · <a href="endpoints.csv">各 API CSV</a> · <a href="account_verification.csv">測後帳號驗證 CSV</a> · <a href="retained_records.csv">300 筆保留紀錄清單</a> · <a href="requests_combined.csv">兩回逐筆請求合併 CSV</a></p><p class="meta">圖表已內嵌，可單獨分享 HTML；所有量測原始檔與摘要保留在本批次目錄。</p></main></body></html>'''
    (report / "index.html").write_text(doc, encoding="utf-8")
    markdown_stages = "\n".join(
        f"| {s['concurrency']} 人 | {s['duration_s']:.0f} 秒 | {s['requests']:,} | {s['failed']} | {s['p95_ms']/1000:.2f} 秒 |"
        for s in active
    )
    markdown = f"""# 新增 100 帳號壓測結果

{conclusion}

## 實際結果

- 大家一起開始：{plain_burst}這是持有登入憑證後建立新連線，密碼驗證已提前完成。
- 保持連線繼續使用：{plain_steady}
- 下一級：{plain_limit}更高持續級別未測，不能把 18 人當作絕對上限。

## 我們怎麼測？

先新增 {prep['accounts_verified']} 個獨立測試帳號，每人用腳本放入並驗證 3 筆隨機飲食紀錄，共 {prep['retained_records_verified']} 筆。程式實際向網站發送請求，同時操作不同帳號。

1. 測大家一起開始：分批模擬 {'、'.join(str(n) for n in x)} 人同時建立新連線，各跑一輪操作。查食物、查飲食與歷史紀錄、新增、修改、確認內容及刪除，都成功才算整輪完成。
2. 測已連上後一直用：每種人數先測 {summary['stage_seconds_requested']} 秒，重複上述讀寫操作，每輪後休息 4–6 秒，模擬閱讀或思考。通過的最高人數再測 {summary['soak_seconds_requested']} 秒。
3. 看斷線和資料正確性：每 5 秒檢查網站是否回應，同時驗證讀寫內容；測後逐帳號確認保留紀錄正確、臨時紀錄已清掉。

品質參考為完整測完、請求失敗率低於 1%、約 95% 的請求在 2 秒內回應，且每人至少成功一輪、有失敗流程的人數比例低於 1%。回應時間是單次 API 請求耗時，不是整張網頁或整輪操作時間。

## 簡單圖表

每根柱子代表一批同時開始的人。綠色是完成整輪，紅色是未完成。

![同時開始操作的完成與未完成人數](02-burst-success.png)

下面的柱子越低，表示大部分操作等得越短。數字是約 95% 的 API 請求在幾秒內回應。

![保持連線後的回應時間與失敗次數](03-steady.png)

| 同時使用人數 | 實測時間 | 請求數 | 失敗次數 | 約 95% 請求的回應時間 |
| --- | --- | --- | --- | --- |
{markdown_stages}

## 測後資料與限制

測後驗證 {verification.get('accounts_valid', 0)}/{verification.get('accounts_checked', 0)} 帳號通過，各保留原 3 筆紀錄；待刪臨時紀錄 {verification.get('pending_temporary_records')}，本輪待登出 token {verification.get('outstanding_tokens')}。保留紀錄在 11 月 8–10 日，可從歷史紀錄查看；帳密另存，不在本報告內。

這是單一電腦經公開 Funnel 路徑的 API 測試，沒有遠端主機資源監控，本機產生負載也可能影響延遲。未測完整瀏覽器載入、照片辨識、外部 AI／Places 或數小時運行，不能把結果直接套用到所有功能。Tailscale 官方文件未列出 18／19 條並行連線上限，本次結果不能證明有此官方限制。

第一回持續測試因監測視窗誤含突發錯誤而提前停止，該段 1.832 秒／7 次成功請求保留但不列入容量結果。修正並通過離線回歸檢查後，只重測持續部分。

[可單獨分享、圖表已內嵌的 HTML 報告](index.html) · [完整分析與來源雜湊](analysis.json) · [各級數據](stages.csv) · [逐筆請求](requests_combined.csv) · [300 筆保留紀錄](retained_records.csv)
"""
    (report / "RESULTS.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"report": str(report / "index.html"), "burst_levels": x, "steady_passed": passed, "soak_passed": soak_passed, "verified_accounts": verification.get("accounts_valid")}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    build(parser.parse_args().out.resolve())
