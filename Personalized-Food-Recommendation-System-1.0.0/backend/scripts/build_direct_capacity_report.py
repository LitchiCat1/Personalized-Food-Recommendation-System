"""Reconcile actual concurrent capacity stages and their verification evidence."""

import argparse
import base64
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from build_direct_100_report import aggregate, write_csv


def build(run, burst_report):
    summary_path = next(run.glob("load_summary_*.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("finished_at") and not summary.get("cleanup_error")
    verification = summary["verification"]
    assert verification["accounts_valid"] == verification["accounts_checked"] > 0
    assert verification["pending_temporary_records"] == verification["outstanding_tokens"] == 0
    requests_path = run / f"load_requests_{summary['load_id']}.csv"
    with requests_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["ok"] = row["ok"] == "True"
        row["status"] = int(row["status"])
        row["latency_ms"] = float(row["latency_ms"])
    stages, business = [], []
    for index, stage in enumerate(summary["stages"]):
        selected = [r for r in rows[stage["row_start"]:stage["row_end"]] if r["phase"] == stage["phase"]]
        first = [r for r in selected if r["step"] == "fresh_session_first_request"]
        later = [r for r in selected if r["step"] != "fresh_session_first_request"]
        stats = aggregate(selected)
        assert stats["requests"] == stage["requests"] and stats["failed"] == stage["failed"]
        assert abs(stats["p95_ms"]-stage["p95_ms"]) < .011
        assert len(first) == stage["concurrency"]
        assert len({r["account"] for r in first}) == stage["concurrency"]
        first_stats, later_stats = aggregate(first), aggregate(later)
        assert first_stats["failed"] == stage["first_request"]["failed"]
        assert later_stats["failed"] == stage["later_api"]["failed"]
        business.extend(selected)
        stages.append({"index": index+1, "users": stage["concurrency"], "purpose": stage["purpose"],
            "duration_s": stage["duration_s"], "requested_seconds": stage["requested_seconds"],
            "completed": stage["completed"], "passed": stage["reference_pass"],
            "successful_users": stage["users_with_successful_cycles"], "failed_users": stage["users_with_failed_cycles"],
            **stats, "first_requests": first_stats["requests"], "first_failed": first_stats["failed"],
            "first_p95_ms": first_stats["p95_ms"], "later_requests": later_stats["requests"],
            "later_failed": later_stats["failed"], "later_p95_ms": later_stats["p95_ms"]})
    confirmation = next((s for s in stages if s["purpose"] == "long_confirmation"), None)
    neighbor = next((s for s in stages if s["purpose"] == "adjacent_failure_recheck"), None)
    highest = summary.get("highest_confirmed_users")
    if highest:
        assert confirmation["passed"] and confirmation["users"] == highest
        conclusion = f"本輪已驗證約 {highest} 人同時進行基本資料操作，持續 {confirmation['duration_s']:.3f} 秒，{confirmation['requests']:,} 次請求、{confirmation['failed']} 次失敗，整體 P95 {confirmation['p95_ms']/1000:.2f} 秒。"
    else:
        conclusion = "本輪沒有通過的長時間確認結果，不能據此給出新的穩定容量。"
    if neighbor:
        conclusion += f"相鄰 {neighbor['users']} 人補測" + ("通過，顯示邊界變動，尚未取得固定上限。" if neighbor["passed"] else f"未通過，{neighbor['first_failed']} 人首次連線失敗。")
    conclusion += "這是本次單一來源、公開連線路徑與操作頻率下的結果，並非後端或 Tailscale 的固定最大值。"
    burst_path = burst_report / "analysis.json"
    burst = json.loads(burst_path.read_text(encoding="utf-8"))
    evidence = {"conclusion": conclusion, "highest_confirmed_users": highest,
        "confirmation": confirmation, "neighbor_recheck": neighbor, "stages": stages,
        "verification": verification, "burst": burst, "business": aggregate(business),
        "error_types": dict(Counter(r["error_type"] for r in business if not r["ok"])),
        "health_failed": sum(not r["ok"] for r in rows if r["phase"] == "monitor"),
        "http_5xx": sum(r["status"] >= 500 for r in rows),
        "started_at": summary["started_at"], "finished_at": summary["finished_at"],
        "run": run.name, "target": summary["target"], "raw_summary": summary,
        "source_sha256": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in (summary_path, requests_path, burst_path)}}
    out = run / "report"
    out.mkdir(exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "stages.csv", stages)
    write_csv(out / "requests.csv", rows)
    write_csv(out / "verification.csv", verification["checks"])
    shutil.copyfile(burst_report / "01-direct-100.png", out / "02-direct-100.png")
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11})
    fig, ax = plt.subplots(figsize=(11, max(4.2, .52*len(stages)+1.8)))
    positions = list(range(len(stages)))
    ax.barh(positions, [s["users"] for s in stages], color=["#00876b" if s["passed"] else "#c43b45" for s in stages], height=.62)
    for i,s in enumerate(stages):
        ax.text(s["users"]+.4, i, f"{'通過' if s['passed'] else '未通過'}　{s['duration_s']:.0f} 秒　首次失敗 {s['first_failed']} 人", va="center", fontsize=10)
    ax.set_yticks(positions, [f"第 {s['index']} 次　{s['users']} 人" for s in stages])
    ax.invert_yaxis(); ax.set_xlim(0, max(s["users"] for s in stages)*1.8)
    ax.set_xlabel("本次要求的併發人數")
    ax.set_title("快速縮小容量範圍與較長時間確認", loc="left", fontweight="bold")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color="#e0e6e8"); ax.set_axisbelow(True)
    fig.text(.025, .02, "綠色為符合整級品質條件；紅色為未通過。失敗時提早結束該級後續循環，實測秒數如標示。", fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, 1)); fig.savefig(out / "01-capacity-search.png", dpi=180); plt.close(fig)
    method = "先讓 30 人直接同時開始，每人使用獨立 HTTP 工作階段。通過便往 45、70、100 人增加；失敗則確認較低人數，再以二分法縮小到相鄰人數。每級約 20 秒，最高短測通過者確認 120 秒，之後重測上方相鄰級別。每人首輪 8 次 API，之後每輪 7 次，輪間休息 4–6 秒；登入事先限流準備。"
    criteria = "整級完整測完、請求失敗率低於 1%、含首次連線的整體 P95 低於 2 秒、每人至少完成一輪，且有失敗流程的人數比例低於 1%。本輪級別均低於或等於 100 人，因此任何一人流程失敗即不通過；此時停止該級後續循環，已開始的請求仍完成或逾時。"
    limits = "只用一台電腦經公開 Funnel，另有健康檢查連線，沒有伺服器 CPU、記憶體、即時 TCP 或後端 access log。前輪 20 人曾通過約 60 秒，也曾準備失敗，顯示連線結果會變動。不能宣稱固定 18、19 或 20 人上限，也沒有證實由 Tailscale 限制人數。未測整頁載入、照片、外部 AI／Places 或數小時運作。"
    evidence.update({"method": method, "criteria": criteria, "limitations": limits})
    (out / "analysis.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    table = "".join(f"<tr><td>{s['index']}</td><td>{s['users']}</td><td>{s['duration_s']:.1f}</td><td>{s['requests']:,}</td><td>{s['failed']}</td><td>{'通過' if s['passed'] else '未通過'}</td></tr>" for s in stages)
    def img(name):
        encoded = base64.b64encode((out/name).read_bytes()).decode("ascii")
        return f'<img alt="壓力測試實測結果" src="data:image/png;base64,{encoded}">'
    (out / "index.html").write_text(f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>併發容量搜尋報告</title><style>body{{font:16px/1.8 system-ui,"Microsoft JhengHei",sans-serif;color:#192c30;margin:0}}main{{max-width:1000px;margin:auto;padding:24px}}h1{{font-size:28px}}h2{{font-size:21px}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #d9d9d9;padding:7px;text-align:center}}p{{overflow-wrap:anywhere}}</style><main><h1>併發容量搜尋報告</h1><p>{html.escape(conclusion)}</p>{img('01-capacity-search.png')}<h2>測試方法</h2><p>{method}</p><p>{criteria}</p><table><tr><th>次序</th><th>人數</th><th>實測秒</th><th>請求數</th><th>失敗數</th><th>結果</th></tr>{table}</table><h2>直接 100 人的對照</h2>{img('02-direct-100.png')}<p>直接 100 人突發測試中，{burst['completed_users']} 人完成整輪、{burst['incomplete_users']} 人首次連線失敗。這是另一情境，不能把完成者人數當作穩定容量。</p><h2>驗證與限制</h2><p>本回 {verification['accounts_valid']}/{verification['accounts_checked']} 個已使用帳號測後檢查通過，原紀錄均保留，臨時紀錄與本輪待登出憑證 0；其餘帳號未使用。{limits}</p><p><a href="stages.csv">各級統計</a> · <a href="requests.csv">逐筆請求</a> · <a href="verification.csv">測後驗證</a> · <a href="analysis.json">完整分析</a></p></main></html>''', encoding="utf-8")
    (out / "RESULTS.md").write_text("# 併發容量搜尋結果\n\n"+conclusion+"\n\n"+method+"\n\n"+criteria+"\n\n"+limits+"\n", encoding="utf-8")
    print(json.dumps({"highest_confirmed_users": highest, "neighbor": neighbor, "report": str(out)}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--burst-report", type=Path, required=True)
    args = parser.parse_args()
    build(args.run.resolve(), args.burst_report.resolve())
