"""Create a Word update from the reconciled 10-user-stage report."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from build_stress_report_docx import (
    FONT, add_body, add_bullet, add_heading, add_page_number, add_picture,
    add_table, set_paragraph_spacing, set_run_font,
)


def build(report):
    data = json.loads((report / "analysis.json").read_text(encoding="utf-8"))
    stages = data["stages"]
    ten = [s for s in stages if s["purpose"] == "ten_user_step"]
    active = [s for s in stages if s["started"]]
    best = data["best_confirmation"]
    assert best and best["passed"] and best["failed"] == 0
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.9), Cm(1.7)
    section.left_margin = section.right_margin = Cm(2)
    section.footer_distance = Cm(.8)
    for grid in list(section._sectPr.findall(qn("w:docGrid"))):
        section._sectPr.remove(grid)
    for name, size in (("Normal", 10.5), ("Title", 24), ("Heading 1", 16), ("Heading 2", 12.5)):
        style = doc.styles[name]
        style.font.name = FONT
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string("000000")
        style.paragraph_format.space_before = Pt(0 if name == "Normal" else 10)
        style.paragraph_format.space_after = Pt(7)
        snap = OxmlElement("w:snapToGrid"); snap.set(qn("w:val"), "0")
        style._element.get_or_add_pPr().append(snap)
        if name != "Normal":
            style.font.bold = True
            style.paragraph_format.keep_with_next = True
    footer = section.footer.paragraphs[0]
    run = footer.add_run("NutriLens 壓力測試更新　每 10 人一級　")
    set_run_font(run, 8.5, color="000000")
    add_page_number(footer)
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(title.add_run("NutriLens 併發壓力測試更新報告"), 24, True, "000000")
    date = datetime.fromisoformat(data["runs"][-1]["started_at"]).strftime("%Y 年 %m 月 %d 日")
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_paragraph_spacing(p, after=16)
    set_run_font(p.add_run(f"v1.0.0　{date}　每次增加 10 人"), 11, color="000000")

    add_heading(doc, "本輪結論")
    add_body(doc, data["conclusion"])
    add_body(doc, f"若需要一個目前可採用的人數，建議以約 {best['users']} 人同時進行基本飲食資料操作，作為本輪短時間測試的容量參考。這個估計以已登入、成功建立連線、每輪讀寫後休息 4–6 秒為條件，不能視為所有功能或長時間使用的保證。")
    failed_levels = [s["users"] for s in ten if not s["started"]]
    add_body(doc, "本輪依序檢查 20、30、40、50、60、70、80、90、100 人。未能完整準備連線的級別為："+"、".join(str(n) for n in failed_levels)+" 人；這些級別沒有開始正式持續操作，無法提供該人數的業務延遲或斷線率。")
    add_body(doc, "20 人在前一回三次準備連線失敗，後一回曾成功並進入短測。結果會隨當時狀態改變，所以不能宣稱固定的 19 或 20 人上限。每 10 人的級距也無法判定 21–29 人的精確邊界。")
    add_heading(doc, "白話測試方式")
    add_bullet(doc, "沿用原有 100 個專用測試帳號與 300 筆保留紀錄，不再創帳號，也不修改其他使用者資料。登入事先完成，這輪主要測連線後的資料操作。")
    add_bullet(doc, "每個人使用獨立 HTTP 連線。先準備該級所有人的連線，全部成功才開始 20 秒短測；最高通過級別另做 60 秒確認。")
    add_bullet(doc, "每輪查食物、查飲食紀錄與歷史，接著新增、修改、確認、刪除一筆臨時紀錄，共 7 次請求，輪與輪之間休息 4–6 秒。")
    add_bullet(doc, "每 5 秒檢查網站健康狀態；結束後逐帳號驗證原有資料，清除臨時紀錄並登出本輪憑證。")
    doc.add_page_break()

    add_heading(doc, "每增加 10 人的連線結果")
    add_body(doc, "綠色表示成功準備連線的人，紅色表示準備連線失敗的人。只有整批人的連線都成功，才執行該人數的連續讀寫測試。這張圖不把部分人能連線算成整批通過。")
    add_picture(doc, report / "01-ten-user-steps.png", "圖一　各級連線準備成功與失敗人數")
    rows = []
    for s in ten:
        rows.append((str(s["users"]), f"{s['warmup_success']}/{s['warmup_requests']}", str(s["warmup_failed"]),
            "通過短測" if s["passed"] else ("未開始" if not s["started"] else "未通過"),
            f"{s['requests']:,}" if s["started"] else "無業務數據"))
    add_table(doc, ["要求人數", "連線準備成功", "連線失敗", "持續操作", "業務請求數"], rows,
        widths=[1.0, 1.4, 1.0, 1.25, 1.8], font_size=8.8)
    add_body(doc, "「未開始」不等於伺服器完全斷線，而是無法讓要求的人數全部準備好連線，因此未以不足的人數冒充完整併發測試。這也不能證明直接連到後端時會有相同容量。")
    doc.add_page_break()

    add_heading(doc, "真正開始持續操作的結果")
    add_body(doc, "下面只列有正式開始資料操作的級別。柱子越低，代表大部分請求等待越短；暖機失敗的級別沒有延遲資料，不畫成 0 秒。")
    add_picture(doc, report / "02-response-time.png", "圖二　已開始操作級別的 API 回應時間")
    rows = [(f"{s['users']} 人", f"{s['duration_s']:.0f}", f"{s['requests']:,}", str(s["failed"]),
             f"{s['p95_ms']/1000:.2f}", f"{s['p99_ms']/1000:.2f}") for s in active]
    add_table(doc, ["人數", "實測秒", "請求數", "失敗次數", "P95 秒", "P99 秒"], rows,
        widths=[.85, .95, 1.15, 1.1, 1.1, 1.1], font_size=9)
    add_body(doc, "P95 可理解為約 95% 的請求在該時間內回應，P99 是約 99%。這是單次 API 資料請求，不是整張網頁或整輪操作的完成時間。")
    add_body(doc, f"最高完成確認的是 {best['users']} 人：實測 {best['duration_s']:.3f} 秒，{best['requests']:,} 次請求、{best['failed']} 次失敗，P95 {best['p95_ms']/1000:.2f} 秒，最慢 {best['max_ms']/1000:.2f} 秒。兩回有效業務合計 {data['business_requests']:,} 次、失敗 {data['business_failed']} 次。")
    add_body(doc, "本次持續測試的參考條件為完整測完、請求失敗率低於 1%、P95 低於 2 秒、每人至少完成一輪，且有失敗流程的人數比例低於 1%。20 秒短測用來快速篩選，60 秒確認仍不足以代表數小時穩定使用。")
    doc.add_page_break()

    add_heading(doc, "資料驗證與測試範圍")
    add_body(doc, f"兩回合計執行 {data['verification_checks']} 次帳號檢查，涵蓋 {data['unique_accounts_verified']} 個不同帳號，檢查全部通過。原本 300 筆飲食紀錄保留，臨時紀錄 0、本輪待登出 token 0。健康檢查失敗 {data['health_failed']} 次，HTTP 5xx 伺服器錯誤 {data['http_5xx']} 次。")
    add_body(doc, f"連線準備階段另記錄到 {data['error_types'].get('SSLError', 0)} 次 TLS 連線錯誤，這些失敗已列入各級連線結果。正式業務的 0 失敗，並不表示全程所有連線都成功。")
    add_body(doc, "測試目標為 https://node.taile9a8dc.ts.net，版本 v1.0.0，後端回報 SQLite 與 Waitress。每位使用者以 HTTP/1.1 獨立連線操作，另有一條獨立健康檢查連線，這條連線也會占用公開路徑資源。")
    add_heading(doc, "容量結論的適用條件")
    add_bullet(doc, "這是單一負載產生器經公開 Funnel 的結果，沒有同學伺服器的 CPU、記憶體、資料庫、即時 TCP 連線數或 access log，無法把瓶頸歸因於後端或 Tailscale。")
    add_bullet(doc, "本機產生負載、網路與連線回收狀態也可能影響結果。20 人準備連線有時失敗、有時成功，已顯示當時狀態會影響測得的邊界。")
    add_bullet(doc, "沒有測完整瀏覽器載入、照片上傳、AI、Google Places 或數小時運作，因此容量數字限於本次基本資料操作。")
    add_bullet(doc, "本輪按使用者要求每次增加 10 人，沒有逐一測 21、22 到 29 人；不能從 20 人通過、30 人未開始推算精確最大人數。")
    add_heading(doc, "最後結論")
    add_body(doc, f"本次可支持的結論是：已驗證約 {best['users']} 人能在指定操作頻率下同時進行基本飲食資料操作，並通過約 {best['duration_s']:.0f} 秒的持續確認。這比原先只有 18 人的證據更完整，但真正的全系統極限仍未測得。")
    add_body(doc, "若要取得固定可重現的最大人數，下一步應以伺服器端監控、不同網路來源與更長時間重測確認連線瓶頸。官方 Funnel 文件未列 18 或 19 人的固定並行連線上限，本次測試不能當作該服務的官方限制。")
    add_heading(doc, "資料來源", 2)
    batches = [Path(p).parent.name for p in data["source_sha256"] if p.endswith(".json")]
    add_body(doc, "原始資料批次："+"、".join(batches)+"。完整數據與來源 SHA256 見同目錄 analysis.json、stages.csv、requests.csv 與 verification.csv。", after=4)
    add_body(doc, "Funnel 官方限制：https://tailscale.com/docs/features/tailscale-funnel#requirements-and-limitations。", after=0)
    for root in (doc._element, doc.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    doc.core_properties.title = "NutriLens 併發壓力測試更新報告"
    doc.core_properties.author = doc.core_properties.last_modified_by = ""
    output = report / "NutriLens_每10人階段壓力測試報告.docx"
    doc.save(output)
    print(str(output).encode("ascii", "backslashreplace").decode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    build(parser.parse_args().report.resolve())
