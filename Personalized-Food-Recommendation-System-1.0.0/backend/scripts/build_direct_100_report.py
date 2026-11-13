"""Reconcile a completed direct 100-user run and plot its actual outcomes."""

import argparse
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def aggregate(rows):
    values = [float(r["latency_ms"]) for r in rows]
    return {
        "requests": len(rows), "success": sum(r["ok"] for r in rows),
        "failed": sum(not r["ok"] for r in rows),
        "p95_ms": round(statistics.quantiles(values, n=100, method="inclusive")[94], 2) if len(values) > 1 else (values[0] if values else None),
        "max_ms": max(values) if values else None,
    }


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build(run):
    summary_path = next(run.glob("load_summary_*.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("finished_at") and not summary.get("cleanup_error")
    verify = summary["verification"]
    assert verify["accounts_checked"] == verify["accounts_valid"] == 100
    assert verify["pending_temporary_records"] == verify["outstanding_tokens"] == 0
    csv_path = run / f"load_requests_{summary['load_id']}.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["ok"] = row["ok"] == "True"
        row["status"] = int(row["status"])
        row["latency_ms"] = float(row["latency_ms"])
    burst = next(s for s in summary["stages"] if s["purpose"] == "direct_100_simultaneous_users")
    business = [r for r in rows[burst["row_start"]:burst["row_end"]] if r["phase"] == "burst"]
    first = [r for r in business if r["step"] == "fresh_session_first_request"]
    later = [r for r in business if r["step"] != "fresh_session_first_request"]
    assert len(first) == 100 and len({r["account"] for r in first}) == 100
    stats = aggregate(business)
    assert stats["requests"] == burst["requests"] and stats["failed"] == burst["failed"]
    assert abs(stats["p95_ms"] - burst["p95_ms"]) < .011
    accounts = defaultdict(list)
    for row in business:
        accounts[row["account"]].append(row)
    steps = {"fresh_session_first_request", "search_food", "read_seed_records", "history", "temp_create", "temp_update", "verify_updated_record", "temp_delete"}
    outcomes = []
    for account, attempts in sorted(accounts.items()):
        completed = len(attempts) == 8 and all(r["ok"] for r in attempts) and {r["step"] for r in attempts} == steps
        outcomes.append({"account": account, "completed": completed, "requests": len(attempts),
            "failed_requests": sum(not r["ok"] for r in attempts),
            "first_request_ok": next(r["ok"] for r in attempts if r["step"] == "fresh_session_first_request")})
    completed = sum(o["completed"] for o in outcomes)
    assert completed == burst["users_with_successful_cycles"]
    assert 100 - completed == burst["users_with_failed_cycles"]
    confirmation = next((s for s in summary["stages"] if s["purpose"] == "conditional_100_user_confirmation"), None)
    conclusion = f"100 人同時嘗試連線與操作，{completed} 人完成整輪、{100-completed} 人未完成，實測 {burst['duration_s']:.3f} 秒。"
    conclusion += "本輪未通過 100 人同時操作的品質條件。" if not burst["reference_pass"] else "這證明完成一輪突發操作，持續容量需另看補測。"
    method = "使用原有 100 個專用帳號，依網站限流事先登入。登入完成後關閉準備連線，以同步起跑點讓 100 個獨立 HTTP 工作階段同時嘗試。每人先驗證登入，再查食物、查紀錄與歷史，接著新增、修改、核對、刪除一筆臨時飲食紀錄，共 8 次依序請求。首次連線失敗者結束該人的流程，沒有反覆重試。"
    limits = "這是 100 人同時湧入的一輪突發測試，不是 100 人維持數分鐘的測試。完成整輪的人數不能當作穩定同時容量。單一負載產生器經公開 Funnel，另有獨立健康檢查連線；未取得伺服器 CPU、記憶體、TCP 或後端紀錄，無法把瓶頸歸因於 Tailscale 或後端。未測整頁載入、照片、AI 或 Places。"
    source_paths = [summary_path, csv_path]
    previous_path = run.parents[1] / "report-boundary-20261111" / "analysis.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    source_paths.append(previous_path)
    analysis = {
        "conclusion": conclusion, "method": method, "limitations": limits,
        "run": run.name, "started_at": summary["started_at"], "finished_at": summary["finished_at"],
        "target": summary["target"], "requested_users": 100, "completed_users": completed,
        "incomplete_users": 100-completed, "first_request_failed_users": sum(not r["ok"] for r in first),
        "duration_s": burst["duration_s"], "burst_passed": burst["reference_pass"],
        "business": stats, "first_request": aggregate(first), "later_api": aggregate(later),
        "error_types": dict(Counter(r["error_type"] for r in business if not r["ok"])),
        "health_failed": sum(not r["ok"] for r in rows if r["phase"] == "monitor"),
        "http_5xx": sum(r["status"] >= 500 for r in rows),
        "initial_health": summary["initial_health"], "final_health": summary["final_health"],
        "verification": verify, "confirmation": confirmation, "stop_reason": summary["stop_reason"],
        "previous_confirmation": previous["best_confirmation"],
        "source_sha256": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
    }
    out = run / "report"
    out.mkdir(exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "requests.csv", rows)
    write_csv(out / "account_outcomes.csv", outcomes)
    write_csv(out / "verification.csv", verify["checks"])
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 12})
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.barh([0], [completed], color="#00876b", label="完成整輪")
    ax.barh([0], [100-completed], left=[completed], color="#c43b45", label="未完成")
    for count, left in ((completed, 0), (100-completed, completed)):
        if count:
            ax.text(left+count/2, 0, f"{count} 人", ha="center", va="center", color="white", fontsize=18, fontweight="bold")
    ax.set_yticks([0], ["100 人\n同時開始"])
    ax.set_xlim(0, 100); ax.set_ylim(-.8, .8); ax.set_xlabel("人數")
    ax.set_title("100 人一起操作，多少人完成整輪？", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="upper center", ncol=2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.text(.03, .025, "每人最多 8 次 API 請求；這是一輪突發結果，完成者人數不代表穩定同時容量。", fontsize=10)
    fig.tight_layout(rect=(0, .09, 1, 1)); fig.savefig(out / "01-direct-100.png", dpi=180); plt.close(fig)
    metrics = [("首次連線嘗試", analysis["first_request"]), ("連線成功後的 API", analysis["later_api"])]
    table = "".join(f"<tr><td>{label}</td><td>{v['requests']}</td><td>{v['failed']}</td><td>{v['p95_ms']/1000:.2f}</td></tr>" for label,v in metrics if v["requests"])
    image = base64.b64encode((out / "01-direct-100.png").read_bytes()).decode("ascii")
    prior = analysis["previous_confirmation"]
    previous_text = f"前一輪已驗證 {prior['users']} 人持續 {prior['duration_s']:.3f} 秒、{prior['requests']:,} 次請求全部成功。它的工作負載與本次突發不同，應分開解讀。"
    text = f"# 直接 100 人壓力測試結果\n\n{conclusion}\n\n{method}\n\n{limits}\n\n{previous_text}\n\n測後 100/100 帳號驗證通過，300 筆原紀錄保留，臨時紀錄與本輪待登出憑證 0。\n"
    (out / "RESULTS.md").write_text(text, encoding="utf-8")
    (out / "index.html").write_text(f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>直接 100 人壓力測試結果</title><style>body{{font:16px/1.8 system-ui,"Microsoft JhengHei",sans-serif;color:#192c30;margin:0}}main{{max-width:960px;margin:auto;padding:24px}}h1{{font-size:28px}}h2{{font-size:21px}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #d9d9d9;padding:8px;text-align:center}}p{{overflow-wrap:anywhere}}</style><main><h1>直接 100 人壓力測試結果</h1><p>{html.escape(conclusion)}</p><img alt="100 人完成與未完成人數" src="data:image/png;base64,{image}"><h2>白話測試方法</h2><p>{method}</p><h2>請求回應時間</h2><table><tr><th>範圍</th><th>請求數</th><th>失敗數</th><th>P95 秒</th></tr>{table}</table><p>耗時包含失敗嘗試；連線成功後的 API 只涵蓋成功建立連線者，不代表全體 100 人。</p><h2>結論與適用範圍</h2><p>{limits}</p><p>{previous_text}</p><p>100/100 帳號測後驗證通過；保留原本 300 筆紀錄，臨時紀錄與本輪待登出憑證均為 0。健康檢查失敗 {analysis['health_failed']} 次，HTTP 5xx {analysis['http_5xx']} 次。</p><p><a href="requests.csv">逐筆數據</a> · <a href="account_outcomes.csv">各帳號結果</a> · <a href="verification.csv">測後驗證</a> · <a href="analysis.json">完整分析</a></p></main></html>''', encoding="utf-8")
    print(json.dumps({"completed_users": completed, "first_request_failed_users": analysis["first_request_failed_users"], "report": str(out)}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    build(parser.parse_args().run.resolve())
