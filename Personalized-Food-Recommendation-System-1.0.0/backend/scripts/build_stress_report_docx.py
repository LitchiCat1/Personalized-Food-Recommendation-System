"""Build a reader-friendly Word report from the completed stress-test evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "docs" / "stress-test" / "runs" / "population-20261111-2230"
REPORT = RUN / "report"
OUT = REPORT / "NutriLens_系統壓力測試報告.docx"

FONT = "Microsoft JhengHei"
INK = "1F2D33"
BLUE = "205493"
LIGHT_BLUE = "EAF2F8"
GREEN = "00876B"
LIGHT_GREEN = "E8F5F0"
RED = "C43B45"
LIGHT_RED = "FBECEE"
GRAY = "D9D9D9"
LIGHT_GRAY = "F5F7F8"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = GRAY, size: str = "6") -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top=100, start=130, bottom=100, end=130) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_run_font(run, size: float | None = None, bold: bool | None = None, color: str = INK) -> None:
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), FONT)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_paragraph_spacing(paragraph, before=0, after=6, line=1.2) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line
    snap = paragraph._p.get_or_add_pPr().find(qn("w:snapToGrid"))
    if snap is None:
        snap = OxmlElement("w:snapToGrid")
        paragraph._p.get_or_add_pPr().append(snap)
    snap.set(qn("w:val"), "0")


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("第 ")
    set_run_font(run, 9, color="6B777C")
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr)
    run._r.append(fld_char2)
    run2 = paragraph.add_run(" 頁")
    set_run_font(run2, 9, color="6B777C")


def add_heading(doc, text, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    set_run_font(run, 16 if level == 1 else 12.5, True, "000000")
    return p


def add_body(doc, text, after=7):
    p = doc.add_paragraph(style="Normal")
    set_paragraph_spacing(p, after=after, line=1.28)
    p.paragraph_format.line_spacing = Pt(16)
    run = p.add_run(text)
    set_run_font(run, 10.5)
    return p


def add_bold_lead(doc, lead, text):
    p = doc.add_paragraph(style="Normal")
    set_paragraph_spacing(p, after=6, line=1.25)
    r1 = p.add_run(lead)
    set_run_font(r1, 10.5, True, INK)
    r2 = p.add_run(text)
    set_run_font(r2, 10.5)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    set_paragraph_spacing(p, after=3, line=1.2)
    p.paragraph_format.line_spacing = Pt(16)
    run = p.add_run(text)
    set_run_font(run, 10.5)
    return p


def add_table(doc, headers, rows, widths=None, header_fill=BLUE, font_size=9.1):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        set_cell_shading(cell, header_fill)
        set_cell_border(cell)
        set_cell_margins(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_paragraph_spacing(p, after=0, line=1.0)
        run = p.add_run(str(header))
        set_run_font(run, font_size, True, "FFFFFF")
        if widths:
            cell.width = Inches(widths[i])
    repeat_header = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat_header)
    for row_index, row in enumerate(rows):
        cells = table.add_row().cells
        no_split = OxmlElement("w:cantSplit")
        table.rows[-1]._tr.get_or_add_trPr().append(no_split)
        for i, value in enumerate(row):
            cell = cells[i]
            set_cell_shading(cell, "FFFFFF" if row_index % 2 == 0 else LIGHT_GRAY)
            set_cell_border(cell)
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if widths:
                cell.width = Inches(widths[i])
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.CENTER
            set_paragraph_spacing(p, after=0, line=1.0)
            run = p.add_run(str(value))
            set_run_font(run, font_size)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def add_picture(doc, path: Path, caption: str, width=6.6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    run = p.add_run()
    shape = run.add_picture(str(path), width=Inches(width))
    shape._inline.docPr.set("descr", caption)
    set_paragraph_spacing(p, after=2, line=1.0)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_paragraph_spacing(cap, after=9, line=1.0)
    r = cap.add_run(caption)
    set_run_font(r, 9, color="5D6B70")


def load_data():
    with (REPORT / "stages.csv").open(encoding="utf-8-sig", newline="") as f:
        stages = list(csv.DictReader(f))
    with (REPORT / "burst_connections.csv").open(encoding="utf-8-sig", newline="") as f:
        burst_details = {row["concurrency"]: row for row in csv.DictReader(f)}
    with (RUN / "preparation_summary.json").open(encoding="utf-8") as f:
        preparation = json.load(f)
    with (RUN / "load_summary_224007.json").open(encoding="utf-8") as f:
        load = json.load(f)
    return stages, burst_details, preparation, load


def build():
    stages, burst_details, preparation, load = load_data()
    burst = [s for s in stages if s["phase"] == "burst"]
    sustained = [s for s in stages if s["phase"] in ("steady", "soak") and s["started"] == "True"]
    soak18 = next(s for s in sustained if s["phase"] == "soak")
    assert preparation["accounts_verified"] == 100
    assert preparation["retained_records_verified"] == 300
    assert (soak18["concurrency"], soak18["requests"], soak18["failed"], soak18["p95_ms"]) == ("18", "3619", "0", "340.62")
    assert burst[-1]["users_with_successful_cycles"] == "39"
    assert load["verification"]["accounts_valid"] == 100

    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.9)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)
    for grid in list(section._sectPr.findall(qn("w:docGrid"))):
        section._sectPr.remove(grid)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = FONT
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(10.5)
    no_grid = OxmlElement("w:snapToGrid")
    no_grid.set(qn("w:val"), "0")
    normal._element.get_or_add_pPr().append(no_grid)
    for name, size, color in (("Title", 25, "000000"), ("Heading 1", 16, "000000"), ("Heading 2", 12.5, "000000")):
        style = styles[name]
        style.font.name = FONT
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(12 if name != "Title" else 0)
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.keep_with_next = True
    if "Caption" not in styles:
        styles.add_style("Caption", WD_STYLE_TYPE.PARAGRAPH)
    styles["Caption"].font.name = FONT
    styles["Caption"].font.size = Pt(9)

    footer = section.footer.paragraphs[0]
    footer.text = "NutriLens 系統壓力測試報告　2026 年 11 月 11 日"
    for run in footer.runs:
        set_run_font(run, 8.5, color="000000")
    footer.add_run("　")
    add_page_number(footer)

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(10)
    title_run = title.add_run("NutriLens 系統壓力測試報告")
    set_run_font(title_run, 25, True, "000000")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_paragraph_spacing(subtitle, after=22, line=1.1)
    r = subtitle.add_run("v1.0.0　公開測試路徑　2026 年 11 月 11 日")
    set_run_font(r, 11, color="000000")

    add_heading(doc, "結論", 1)
    add_body(doc, "依本次測試結果，若使用者已經完成登入，並以本次測試的操作頻率使用飲食紀錄、歷史查詢與資料新增修改刪除功能，系統目前可先以約 18 人同時持續使用作為實務估計。18 人完成約 3 分鐘的持續測試，3,619 次請求全部成功，約 95% 的請求在 0.34 秒內回應。")
    add_body(doc, "18 人是已連線使用者的短時間測試參考，尚未證明數小時或所有功能都可穩定運作。增加到 20 人時，測試程式在暖機建立連線階段就發生失敗，未開始該級正式資料操作；本輪沒有測試 19 人持續使用。因此，真正最大容量與連線失敗原因仍未確定。")
    add_table(doc, ["問題", "測試得到的答案", "解讀"], [
        ("大約可同時使用幾人", "約 18 人", "目前已驗證可持續操作的最高級別"),
        ("18 人是否會斷線", "3 分鐘內請求全數成功", "僅代表本次 API 操作與網路路徑"),
        ("20 人是否可以使用", "尚未通過暖機連線", "20 人及以上仍未完成持續容量驗證"),
        ("100 人一起連入", "39 人完成、61 人首請求失敗", "短時間大量建立連線時有明顯失敗"),
    ], widths=[1.45, 1.85, 3.15])
    doc.add_page_break()

    add_heading(doc, "測試目的與範圍", 1)
    add_body(doc, "本次壓力測試的目的，是了解多人同時使用時，網站是否能建立連線、完成基本飲食資料操作，以及在連續使用一段時間後是否出現逾時、斷線或資料錯誤。測試目標為 https://node.taile9a8dc.ts.net，遠端回報版本為 v1.0.0，後端使用 SQLite 與 Waitress。")
    add_body(doc, "測試只使用專用測試帳號，沒有把原有使用者資料作為寫入目標，也沒有呼叫 OpenAI、Google Places、照片辨識或其他外部付費功能。每個測試帳號保留 3 筆飲食紀錄，測試過程另建臨時紀錄，完成後刪除並再次驗證。")

    add_heading(doc, "測試準備", 2)
    add_table(doc, ["項目", "內容"], [
        ("測試帳號", "新增 100 組，編號 stress_test_20261111_051 到 150"),
        ("飲食紀錄", "每個帳號 3 筆，共 300 筆；每筆 1 到 3 種食物，份量 75 到 200 公克"),
        ("資料驗證", "檢查帳號、紀錄 ID、食物、餐別、來源與營養總量"),
        ("測試路徑", "單一電腦經公開 Tailscale Funnel 呼叫 HTTP API"),
        ("資料保留", "300 筆準備資料保留；臨時測試紀錄 0 筆；本輪追蹤 token 0 個"),
    ], widths=[1.35, 5.1])

    add_heading(doc, "測試方式", 1)
    add_body(doc, "測試分成兩種情況。第一種是突發測試，讓已持有登入憑證的人在同一時間建立新連線；密碼驗證已在準備時完成。第二種是持續測試，模擬已連線的人反覆查看與修改資料，每輪之間保留 4 到 6 秒的閱讀或思考時間。")
    add_bullet(doc, "突發測試依序測試 1、5、10、20、30、50、75、100 人。每位使用者完成查食物、查飲食與歷史紀錄、新增臨時紀錄、修改、確認及刪除；其中一步失敗，就不算該使用者完成整輪流程。")
    add_bullet(doc, "持續測試依序測試 1、5、10、15、18 人，每級約 60 秒。最高通過級別 18 人再進行約 3 分鐘的補測。")
    add_bullet(doc, "獨立健康檢查每 5 秒執行一次。測試結束後，逐一檢查 100 個帳號是否仍保有正確的 3 筆紀錄，並確認臨時紀錄已清除。")
    add_body(doc, "本次的持續測試品質參考為：完整測完、請求失敗率低於 1%、約 95% 的 API 請求在 2 秒內回應、每人至少成功一輪，且有失敗流程的人數比例低於 1%。圖表中的 P95 就是約 95% 的請求低於該耗時；這是單次資料請求時間，不等於完整網頁載入時間。")
    doc.add_page_break()

    add_heading(doc, "突發測試結果", 1)
    add_body(doc, "突發測試觀察多人同時建立連線後能否完成操作。1、5、10 人都完成整輪；20 人起出現首請求失敗。當同時開始的人數增加，初次連線等待時間與失敗人數都明顯增加。")
    add_picture(doc, REPORT / "02-burst-success.png", "圖一　同時開始一輪操作時的完成與未完成使用者")
    add_body(doc, "100 人同時開始時，39 人完成整輪操作，61 人在首請求階段失敗。首請求失敗的使用者不會再執行後續操作，因此這張圖回答的是「能不能成功開始並完成一輪」，不是「伺服器已經接受了 100 人並讓他們持續使用」。")
    burst_rows = []
    for row in burst:
        detail = burst_details[row["concurrency"]]
        burst_rows.append((
            row["concurrency"],
            f"{row['users_with_successful_cycles']}/{row['concurrency']}",
            row["failed"],
            f"{float(detail['first_p95_ms'])/1000:.2f}",
            f"{float(detail['later_p95_ms'])/1000:.2f}" if detail["later_p95_ms"] else "無資料",
        ))
    add_table(doc, ["同時開始人數", "完成整輪", "失敗請求", "首請求 P95 秒", "後續 API P95 秒"], burst_rows, widths=[1.2, 1.25, 1.0, 1.45, 1.55], font_size=8.6)
    add_body(doc, "首請求包含建立新連線與後端處理，後續 API 只統計首請求成功的人，兩者樣本不同。表中 P95 包含失敗嘗試耗時，必須搭配成功人數判讀。突發首請求共失敗 126 次，其中 106 次為 SSL 連線錯誤、20 次為連線逾時；本次未觀察到 HTTP 5xx 伺服器錯誤。")

    doc.add_page_break()
    add_heading(doc, "持續測試結果", 1)
    add_body(doc, "持續測試讓每位使用者反覆執行相同的資料操作，並在每輪之間停頓。這比較接近使用者登入後正常查詢與記錄飲食的情境。1 到 18 人的 60 秒級別都完成，且業務請求沒有失敗。")
    add_picture(doc, REPORT / "03-steady.png", "圖二　已建立連線後的持續操作回應時間")
    sustained_rows = []
    for row in sustained:
        duration = float(row["duration_s"])
        sustained_rows.append((
            f"{row['concurrency']} 人" + (" 補測" if row["phase"] == "soak" else ""),
            f"{duration:.0f}",
            row["requests"],
            row["failed"],
            f"{float(row['p95_ms'])/1000:.2f}",
            f"{float(row['p99_ms'])/1000:.2f}",
        ))
    add_table(doc, ["同時使用人數", "時間 秒", "請求數", "失敗數", "P95 秒", "P99 秒"], sustained_rows, widths=[1.35, 1.0, 1.1, 1.0, 1.0, 1.0], font_size=8.8)
    add_body(doc, "18 人的 3 分鐘補測共 3,619 次請求，全部成功；P95 為 0.34 秒，P99 為 0.66 秒，最慢的一次為 1.56 秒。20 人在暖機建立連線時失敗，沒有進入正式業務操作，所以 20 人以上不能從本輪資料推定。")
    add_body(doc, "上表所有已開始的有效持續級別共 7,133 次業務請求，全部成功。健康檢查沒有形成連續失敗，但這不能排除未測功能或更長時間使用時出現問題。表中的約 181 秒為 180.786 秒四捨五入，與規劃的 3 分鐘相符。")

    doc.add_page_break()
    add_heading(doc, "資料正確性與測試後檢查", 1)
    add_body(doc, "測試完成後，100 個新增帳號全部通過檢查，每個帳號仍有原本 3 筆保留紀錄，共 300 筆。每筆紀錄的 ID、食物名稱、餐別、來源與營養加總均符合建立時的資料。測試期間新增的臨時紀錄已刪除，本輪追蹤的登入 token 已全部登出。")

    add_heading(doc, "限制與解讀方式", 1)
    add_body(doc, "本報告的 18 人是「在本次操作頻率、單一負載產生器與公開 Funnel 網路路徑下，已完成 3 分鐘持續測試的最高級別」。它可作為目前規劃同時使用人數的保守參考，但不代表所有功能、所有網路來源或長時間運行都會得到相同結果。")
    add_bullet(doc, "沒有取得同學電腦的 CPU、記憶體、磁碟、SQLite 鎖等待、TCP 連線數與 Tailscale access log，因此無法判斷瓶頸一定來自後端、家用電腦或 Funnel。")
    add_bullet(doc, "測試使用 HTTP API，沒有涵蓋完整瀏覽器靜態資源、照片上傳、照片辨識、OpenAI、Google Places 或數小時的長時間運行。")
    add_bullet(doc, "產生負載的本機 CPU 採樣最高曾達 99.9%，也可能影響連線與延遲；未排除本機或網路因素，不能只把錯誤歸因於伺服器。")
    add_bullet(doc, "100 人同時建立連線的結果與 18 人穩定持續操作是不同情境；前者顯示大量同時進入時會有連線失敗，後者顯示已連線使用者在較低操作頻率下可穩定完成測試。")
    add_bullet(doc, "Tailscale Funnel 官方文件沒有列出 18 或 19 條並行連線的固定上限，本次測試結果不能當作 Tailscale 官方限制。")

    add_heading(doc, "最終結論", 1)
    add_body(doc, "以目前取得的證據，這個系統可以先估計為約 18 人同時進行基本飲食資料操作。這個估計的依據是 18 人完成約 3 分鐘的持續測試，3,619 次請求全部成功，且約 95% 的請求在 0.34 秒內回應。")
    add_body(doc, "實際部署時，建議把 18 人視為目前已驗證的容量參考，不要直接當成固定上限；若需要容納 20 人以上，應先改善或觀測暖機連線失敗的原因，再由伺服器端資源與 access log 佐證後重新測試。100 人同時湧入的結果也提醒我們，短時間大量連入時，系統可能無法讓所有人同時開始操作。")

    add_heading(doc, "資料來源與修正紀錄", 2)
    add_body(doc, "本報告使用 2026 年 11 月 11 日第二輪資料。首回監測視窗誤含前段突發錯誤，造成 1 人持續測試在 1.832 秒後提前停止；該 7 次成功請求保留但不列容量，修正後只重測持續部分。原始數據、來源 SHA256 與測後驗證保存在同批次的 analysis.json、stages.csv 及 requests_combined.csv。", after=4)
    add_body(doc, "測試批次：population-20261111-2230。Funnel 官方限制參考：https://tailscale.com/docs/features/tailscale-funnel#requirements-and-limitations（2026 年 11 月 11 日查閱）。", after=0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.title = "NutriLens 系統壓力測試報告"
    doc.core_properties.subject = "同時使用人數與連線成功率"
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    for root in (doc._element, doc.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
