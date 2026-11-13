"""Create the Word report for the latest direct 100-user attempt."""

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
    FONT, add_body, add_heading, add_page_number, add_picture,
    add_table, set_run_font,
)


def build(report):
    a = json.loads((report / "analysis.json").read_text(encoding="utf-8"))
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.7)
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
        style.paragraph_format.space_before = Pt(0 if name == "Normal" else 9)
        style.paragraph_format.space_after = Pt(7)
        snap = OxmlElement("w:snapToGrid")
        snap.set(qn("w:val"), "0")
        style._element.get_or_add_pPr().append(snap)
        if name != "Normal":
            style.font.bold = True
            style.paragraph_format.keep_with_next = True
    footer = section.footer.paragraphs[0]
    set_run_font(footer.add_run("NutriLens 直接 100 人壓力測試　"), 8.5, color="000000")
    add_page_number(footer)
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(title.add_run("NutriLens 直接 100 人壓力測試報告"), 23, True, "000000")
    date = datetime.fromisoformat(a["started_at"]).strftime("%Y 年 %m 月 %d 日")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(p.add_run(f"v1.0.0　{date}　100 人同時開始"), 11, color="000000")
    add_heading(doc, "本輪結果")
    add_body(doc, a["conclusion"])
    add_body(doc, f"本次 {a['first_request_failed_users']} 位未完成者在首次連線時就失敗；成功連線者之後的 {a['later_api']['requests']} 次資料操作全數成功。這次已讓 100 人一起嘗試，直接觀察到多人同時湧入時的失敗情況。")
    add_picture(doc, report / "01-direct-100.png", "圖一　100 人同時開始後的整輪完成情況")
    values = [("首次連線嘗試", a["first_request"]), ("連線後資料操作", a["later_api"]), ("全部計量請求", a["business"])]
    add_table(doc, ["範圍", "請求數", "成功", "失敗"],
        [(label, str(v["requests"]), str(v["success"]), str(v["failed"])) for label,v in values],
        widths=[2.8, 1.3, 1.3, 1.3], font_size=9.3)
    add_heading(doc, "白話測試方式")
    add_body(doc, a["method"])
    add_body(doc, "本輪沒有先逐級增加人數，也沒有因為無法全員暖機就跳過測試。所有人的嘗試都計入結果；100 人整輪未通過，因此未進入 100 人的 60 秒持續確認。")
    doc.add_page_break()

    add_heading(doc, "首次連線與後續操作耗時")
    latencies = [(label, str(v["requests"]), f"{v['p95_ms']/1000:.2f}", f"{v['max_ms']/1000:.2f}") for label,v in values[:2] if v["requests"]]
    add_table(doc, ["範圍", "嘗試次數", "P95 秒", "最慢秒"], latencies,
        widths=[2.8, 1.3, 1.3, 1.3], font_size=9.3)
    add_body(doc, "P95 表示約 95% 的嘗試在該時間內結束，包含失敗嘗試的等待時間；失敗結束不等於取得成功回應。後續 API 只涵蓋成功連線者，不能拿來代表全體 100 人的等待時間。")
    errors = "、".join(f"{name} {count} 次" for name,count in a["error_types"].items())
    add_body(doc, f"本輪失敗類型為 {errors}。ConnectTimeout 是建立連線逾時，SSLError 是 TLS 加密連線錯誤，尚無法僅憑這些類型定位哪一端造成。健康檢查失敗 {a['health_failed']} 次、HTTP 5xx 伺服器錯誤 {a['http_5xx']} 次。")
    add_heading(doc, "資料驗證")
    v = a["verification"]
    add_body(doc, f"測後 {v['accounts_valid']}/{v['accounts_checked']} 個帳號驗證通過，每個仍有原本 3 筆飲食紀錄，合計保留 300 筆。臨時紀錄 {v['pending_temporary_records']} 筆，本輪待登出憑證 {v['outstanding_tokens']} 組；本輪測試與清理程序已結束。")
    add_body(doc, f"目標為 {a['target']}，版本 v1.0.0；測前與測後回報相同的伺服器啟動時間。整體紀錄由 {a['started_at']} 至 {a['finished_at']}，包含限流登入及驗證清理；正式突發操作為 {a['duration_s']:.3f} 秒。")
    add_heading(doc, "容量結論")
    prior = a["previous_confirmation"]
    add_body(doc, f"本輪結果是 100 人一起開始時，只有 {a['completed_users']} 人完成整輪，不能說系統可穩定承載 100 人，也不能直接把 {a['completed_users']} 人當作穩定容量。前一輪已驗證約 {prior['users']} 人在每輪間休息 4–6 秒的條件下，持續 {prior['duration_s']:.3f} 秒、{prior['requests']:,} 次請求全成功；目前仍可將約 {prior['users']} 人視為該條件下的短時間容量參考。")
    add_body(doc, a["limitations"])
    add_body(doc, "若要找出真正的最大人數，需要同時觀察伺服器與網路連線狀態，並以更長時間、不同來源重測。本次數據不構成 Tailscale 官方固定連線上限的證據。")
    add_heading(doc, "數據來源", 2)
    add_body(doc, f"本輪批次 {a['run']}。同目錄 analysis.json、requests.csv、account_outcomes.csv 及 verification.csv 保存統計、來源 SHA256 與逐筆資料；前輪持續測試見 report-boundary-20261111。", after=0)
    for root in (doc._element, doc.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    doc.core_properties.title = "NutriLens 直接 100 人壓力測試報告"
    doc.core_properties.author = doc.core_properties.last_modified_by = ""
    output = report / "NutriLens_直接100人壓力測試報告.docx"
    doc.save(output)
    print(str(output).encode("ascii", "backslashreplace").decode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    build(parser.parse_args().report.resolve())
