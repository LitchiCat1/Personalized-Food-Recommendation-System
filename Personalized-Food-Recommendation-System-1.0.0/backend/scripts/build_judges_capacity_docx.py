"""Rewrite the completed capacity report for reviewers, preserving measured facts."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from build_stress_report_docx import (
    add_body, add_heading, add_page_number, add_picture, add_table, set_run_font,
)


def build(report):
    data=json.loads((report/"analysis.json").read_text(encoding="utf-8"))
    c=data["confirmation"]
    comparisons=[s for s in data["stages"] if s["users"]==20]
    assert c["users"]==19 and c["passed"] and c["failed"]==0
    assert len(comparisons)==2 and all(s["first_failed"]==1 for s in comparisons)
    doc=Document(report/"NutriLens_併發容量測試報告.docx")
    for element in list(doc._element.body):
        if element.tag!=qn("w:sectPr"):
            doc._element.body.remove(element)
    footer=doc.sections[0].footer.paragraphs[0]
    footer.clear()
    set_run_font(footer.add_run("NutriLens 系統穩定容量評估　"),8.5,color="000000")
    add_page_number(footer)
    title=doc.add_paragraph(style="Title"); title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(title.add_run("NutriLens 系統穩定容量評估報告"),23,True,"000000")
    date=datetime.fromisoformat(data["finished_at"]).strftime("%Y 年 %m 月 %d 日")
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(p.add_run(f"v1.0.0　{date}　飲食核心操作的同時使用人數評估"),10.5,color="000000")
    add_heading(doc,"容量結論")
    add_body(doc,"本次測試條件下，建議以 19 人作為系統穩定同時使用人數上限。這個建議以所有使用者都能完成飲食資料操作為標準，作為目前系統展示與使用規劃的人數參考。")
    add_heading(doc,"以 19 人作為穩定人數上限的理由")
    add_body(doc,f"首先，19 人同時操作時，每個人都能完成流程。這組測試連續進行 {c['duration_s']:.3f} 秒，約兩分鐘內共發出 {c['requests']:,} 次請求，全部成功。測試包含查食物、查飲食紀錄與歷史，以及新增、修改、核對和刪除紀錄，涵蓋日常使用的核心動作。")
    add_body(doc,"其次，提高到 20 人後，兩次比較試驗都各有 1 人在首次連線時未完成，其餘 19 人完成流程。因此，若以「每一位使用者都能順利操作」來選擇穩定人數，19 人是這回重複比較後較合適的建議值。")
    add_body(doc,f"再看使用時的等待時間，19 人確認測試中，約 95% 的請求在 {c['p95_ms']/1000:.2f} 秒內結束，且全部成功。這表示該操作頻率下，多數資料請求能很快取得回應。")
    add_body(doc,"20 人在前一輪曾完成約 60 秒操作；綜合不同輪次的表現，報告採用全員成功且完成較長確認的 19 人，作為本次條件下的建議穩定上限。")
    add_picture(doc,report/"03-stable-capacity-reason.png","圖一　19 人持續確認與 20 人兩次比較的完成情況",width=6.5)
    doc.add_page_break()

    add_heading(doc,"白話測試方式")
    add_body(doc,"測試腳本從測試者的電腦，經公開網址連到同學架設的 v1.0.0 伺服器，模擬多人各自使用帳號操作。每位使用者有獨立的 HTTP 工作階段，每輪完成後休息 4–6 秒，再進行下一輪，模擬查詢與記錄飲食資料的節奏。")
    add_body(doc,"人數先從較高級別比較，再縮小範圍，依序測到 10、15、17、18、19 人；接著讓 19 人連續操作約兩分鐘，最後再以 20 人做一次對照。第一輪每人有 8 次請求，之後每輪 7 次，另每 5 秒檢查網站健康狀態。")
    add_heading(doc,"逐次測試結果")
    rows=[(str(s["index"]),str(s["users"]),f"{s['duration_s']:.1f}",f"{s['requests']:,}",str(s["failed"]),"通過" if s["passed"] else "調整人數") for s in data["stages"]]
    add_table(doc,["次序","同時人數","實測秒","請求數","失敗次數","判定"],rows,
        widths=[.55,.9,.9,1.25,1.0,1.3],font_size=9)
    add_body(doc,"表中秒數為實際執行時間。出現連線未完成時，腳本結束該級後續循環，再調整測試人數；通過條件包含全員完成至少一輪、依規劃時間持續操作，以及整體請求失敗率低於 1%、P95 低於 2 秒。P95 可白話理解為約 95% 的請求在該時間內結束。")
    add_heading(doc,"資料驗證與使用情境")
    v=data["verification"]
    add_body(doc,f"測試準備了 100 個專用帳號及 300 筆飲食紀錄。這回容量比較使用其中 {v['accounts_checked']} 個帳號，測後 {v['accounts_valid']}/{v['accounts_checked']} 個帳號驗證通過，各自原有 3 筆紀錄完整保留；該回臨時紀錄 {v['pending_temporary_records']} 筆，取得的登入憑證均已登出。")
    add_body(doc,"19 人的建議值對應本次從同一台測試電腦、經公開連線路徑進行的基本飲食資料操作，以及每輪間隔 4–6 秒的使用節奏。這些具體條件讓評估結果可與系統展示情境對照。")
    cutoff=datetime.fromisoformat(data["finished_at"]).strftime("%Y-%m-%d %H:%M:%S")
    add_body(doc,f"數據統計截至 {cutoff}（UTC+8）。測試目標為 {data['target']}。原始逐級與逐筆數據保存在同目錄 stages.csv、requests.csv、verification.csv 及 analysis.json。",after=0)
    for root in (doc._element,doc.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    doc.core_properties.title="NutriLens 系統穩定容量評估報告"
    doc.core_properties.author=doc.core_properties.last_modified_by=""
    output=report/"NutriLens_系統穩定容量評估報告_評審版.docx"
    doc.save(output)
    print(str(output).encode("ascii","backslashreplace").decode())


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("report",type=Path)
    build(parser.parse_args().report.resolve())
