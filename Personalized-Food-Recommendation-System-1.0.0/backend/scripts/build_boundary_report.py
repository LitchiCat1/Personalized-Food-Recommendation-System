"""Reconcile completed boundary tests and create shareable data and charts."""

import argparse
import base64
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def percentile(values, p):
    return round(statistics.quantiles(values, n=100, method="inclusive")[p-1], 2) if len(values) > 1 else values[0]


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows(rows)


def main(runs, out):
    out.mkdir(parents=True, exist_ok=True)
    sources, stages, combined, summaries = {}, [], [], []
    for directory in runs:
        path = next(directory.glob("load_summary_*.json"))
        summary = json.loads(path.read_text(encoding="utf-8"))
        assert summary.get("finished_at") and not summary.get("cleanup_error")
        assert not summary["verification"]["outstanding_tokens"]
        assert not summary["verification"]["pending_temporary_records"]
        assert summary["verification"]["accounts_valid"] == summary["verification"]["accounts_checked"]
        csv_path = directory / f"load_requests_{summary['load_id']}.csv"
        for source in (path, csv_path):
            sources[str(source.resolve())] = hashlib.sha256(source.read_bytes()).hexdigest()
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        for i, row in enumerate(rows):
            row["ok"] = row["ok"] == "True"
            row["latency_ms"] = float(row["latency_ms"])
            row["concurrency"] = int(row["concurrency"])
            row["status"] = int(row["status"])
            combined.append({"run": directory.name, "row_index": i, **row})
        for i, stage in enumerate(summary["stages"]):
            selected = rows[stage["row_start"]:stage["row_end"]]
            warm = [r for r in selected if r["phase"] == "warmup" and r["concurrency"] == stage["concurrency"]]
            business = [r for r in selected if r["phase"] == stage["phase"] and r["concurrency"] == stage["concurrency"]]
            if stage["started"]:
                assert len(business) == stage["requests"]
                assert sum(not r["ok"] for r in business) == stage["failed"]
                assert abs(percentile([r["latency_ms"] for r in business], 95)-stage["p95_ms"]) < .011
            else:
                assert not business
                assert len(warm) == stage["warmup"]["requests"]
                assert sum(not r["ok"] for r in warm) == stage["warmup"]["failed"]
            stages.append({"run": directory.name, "stage_index": i, "purpose": stage["purpose"],
                "phase": stage["phase"], "users": stage["concurrency"], "attempt": stage["attempt"],
                "started": stage["started"], "passed": stage["reference_pass"],
                "warmup_requests": len(warm), "warmup_success": sum(r["ok"] for r in warm),
                "warmup_failed": sum(not r["ok"] for r in warm),
                "duration_s": stage.get("duration_s"), "requests": len(business),
                "failed": sum(not r["ok"] for r in business), "p95_ms": stage.get("p95_ms"),
                "p99_ms": stage.get("p99_ms"), "max_ms": stage.get("max_ms")})
        summaries.append(summary)
    ten = [s for s in stages if s["purpose"] == "ten_user_step"]
    assert [s["users"] for s in ten] == list(range(20, 101, 10))
    active = [s for s in stages if s["started"]]
    confirmed = [s for s in active if s["phase"] == "soak" and s["passed"]]
    highest = max((s["users"] for s in confirmed), default=None)
    best = next((s for s in reversed(confirmed) if s["users"] == highest), None)
    conclusion = (
        f"本輪已驗證最高 {highest} 人保持連線操作約 {best['duration_s']:.0f} 秒，"
        f"{best['requests']:,} 次請求全部成功，約 95% 在 {best['p95_ms']/1000:.2f} 秒內回應。"
        if best else "本輪沒有完成並通過的持續確認級別。"
    )
    conclusion += "這是本次路徑與操作頻率的通過證據，真正的系統最大容量仍未確定。"
    checks = [{"run": directory.name, **check} for directory, summary in zip(runs, summaries) for check in summary["verification"]["checks"]]
    evidence = {"conclusion": conclusion, "highest_confirmed_users": highest, "best_confirmation": best,
        "maximum_supported_users": None, "stages": stages, "source_sha256": sources,
        "runs": summaries, "error_types": dict(Counter(r["error_type"] for r in combined if not r["ok"])),
        "unique_accounts_verified": len({c["account"] for c in checks}), "verification_checks": len(checks),
        "health_failed": sum(not r["ok"] for r in combined if r["phase"] == "monitor"),
        "http_5xx": sum(r["status"] >= 500 for r in combined),
        "request_count": len(combined), "business_requests": sum(s["requests"] for s in active),
        "business_failed": sum(s["failed"] for s in active),
        "limitations": ["Single load generator, one public network path, no remote host monitoring.",
            "One independent health-check Session additionally uses the ingress path.",
            "Short 20-second search stages and 60-second confirmations do not establish long-term capacity.",
            "A warmup failure prevents starting the requested business cohort; unstarted cohorts have no business latency.",
            "20-user warmup results differed across attempts; no fixed global or Tailscale limit established."]}
    (out / "analysis.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "stages.csv", stages)
    write_csv(out / "requests.csv", combined)
    write_csv(out / "verification.csv", checks)
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11})
    green, red = "#00876b", "#c43b45"
    fig, ax = plt.subplots(figsize=(11, 5.4))
    positions = list(range(len(ten)))
    ready = [s["warmup_success"] for s in ten]
    failed = [s["warmup_failed"] for s in ten]
    ax.bar(positions, ready, color=green, label="成功準備連線")
    ax.bar(positions, failed, bottom=ready, color=red, label="準備連線失敗")
    for i, s in enumerate(ten):
        ax.text(i, s["warmup_success"]/2, str(s["warmup_success"]), ha="center", va="center", color="white", fontweight="bold")
        if s["warmup_failed"]:
            ax.text(i, s["warmup_success"]+s["warmup_failed"]/2, str(s["warmup_failed"]), ha="center", va="center", color="white", fontweight="bold")
    ax.set_xticks(positions, [str(s["users"]) for s in ten]); ax.set_xlabel("本級要求同時使用的人數")
    ax.set_ylabel("人數"); ax.set_title("每增加 10 人，是否都能準備好連線？", loc="left", fontweight="bold")
    ax.set_ylim(0, 115); ax.legend(frameon=False, loc="upper left", ncol=2)
    ax.grid(axis="y", color="#e0e6e8"); ax.set_axisbelow(True); ax.spines[["top", "right"]].set_visible(False)
    fig.text(.03, .02, "連線全部準備成功，才開始該級的持續讀寫；綠色人數不是完整業務操作的成功人數。", fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, 1)); fig.savefig(out / "01-ten-user-steps.png", dpi=180); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    positions = list(range(len(active)))
    ax.bar(positions, [s["p95_ms"]/1000 for s in active], color=[green if s["passed"] else red for s in active], width=.6)
    for i, s in enumerate(active):
        ax.text(i, s["p95_ms"]/1000+.025, f"{s['p95_ms']/1000:.2f} 秒\n失敗 {s['failed']} 次", ha="center", fontsize=10)
    ax.set_xticks(positions, [f"{s['users']} 人\n{s['duration_s']:.0f} 秒" for s in active])
    ax.set_ylabel("約 95% API 請求的回應秒數"); ax.set_title("真正開始連續操作的級別，回應要等多久？", loc="left", fontweight="bold")
    ax.set_ylim(0, max(.5, max(s["p95_ms"]/1000 for s in active)*1.6))
    ax.grid(axis="y", color="#e0e6e8"); ax.set_axisbelow(True); ax.spines[["top", "right"]].set_visible(False)
    fig.text(.03, .02, "暖機失敗的級別沒有業務回應數據，因此不畫成 0 秒；這是 API 時間，不是整頁載入時間。", fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, 1)); fig.savefig(out / "02-response-time.png", dpi=180); plt.close(fig)

    method = "沿用既有 100 個專用帳號與 300 筆保留紀錄，沒有再創帳號。先補測 18、19、20 人，再依使用者要求以 20、30、40、50、60、70、80、90、100 人逐級檢查。每個帳號各自保持 HTTP 連線，查食物、查紀錄與歷史、新增、修改、驗證、刪除臨時紀錄，每輪後休息 4–6 秒。每級先測 20 秒，最高通過級別再測 60 秒；若無法完整準備連線，該級不開始業務操作。"
    variability = "20 人在第一回三次準備連線失敗，第二回曾成功開始操作。這表示準備連線的結果會隨當時狀態變動，不能宣稱有固定的 19 人上限，也無法只由客戶端數據判斷瓶頸來自 Tailscale 或後端。"
    table_rows = "".join(f"<tr><td>{s['users']}</td><td>{s['warmup_success']}/{s['warmup_requests']}</td><td>{'通過短測' if s['passed'] else ('未開始業務' if not s['started'] else '未通過')}</td><td>{s['requests'] if s['started'] else '未開始'}</td></tr>" for s in ten)
    def image(name):
        return '<img alt="壓力測試實測圖表" src="data:image/png;base64,'+base64.b64encode((out / name).read_bytes()).decode("ascii")+'">'
    doc = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>每 10 人一級壓力測試報告</title><style>body{{font:16px/1.8 system-ui,"Microsoft JhengHei",sans-serif;color:#192c30;margin:0}}main{{max-width:1000px;margin:auto;padding:24px}}h1{{font-size:28px}}h2{{font-size:21px}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #d9d9d9;padding:8px;text-align:center}}p{{overflow-wrap:anywhere}}a{{color:#205493}}</style><main><h1>每 10 人一級壓力測試報告</h1><p>{html.escape(conclusion)}</p><h2>怎麼測</h2><p>{method}</p><h2>20 到 100 人的結果</h2>{image('01-ten-user-steps.png')}<table><tr><th>要求人數</th><th>成功準備連線</th><th>結果</th><th>業務請求數</th></tr>{table_rows}</table><p>{variability}</p><h2>有開始操作的人數</h2>{image('02-response-time.png')}<h2>資料與限制</h2><p>測後已驗證 {evidence['unique_accounts_verified']} 個不同帳號，臨時紀錄與本輪待登出憑證均為 0。健康檢查失敗 {evidence['health_failed']} 次，HTTP 5xx {evidence['http_5xx']} 次。保留原本 300 筆紀錄。</p><p>這是單一電腦經公開 Funnel 的 HTTP/1.1 資料操作，另有一條健康檢查連線。沒有遠端資源或 TCP 監控，也未測完整瀏覽器、照片、AI、Places 或數小時運行。請以最高完成補測人數作為本次通過證據，不能稱為全系統固定上限。</p><p><a href="stages.csv">各級數據</a> · <a href="requests.csv">逐筆請求</a> · <a href="verification.csv">測後帳號驗證</a> · <a href="analysis.json">來源與完整分析</a></p></main></html>'''
    (out / "index.html").write_text(doc, encoding="utf-8")
    (out / "RESULTS.md").write_text("# 每 10 人一級壓力測試結果\n\n"+conclusion+"\n\n"+method+"\n\n"+variability+"\n", encoding="utf-8")
    print(json.dumps({"highest_confirmed_users": highest, "stages": len(stages), "business_requests": evidence["business_requests"], "verified_accounts": evidence["unique_accounts_verified"], "report": str(out / "index.html")}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    main([p.resolve() for p in args.runs], args.out.resolve())
