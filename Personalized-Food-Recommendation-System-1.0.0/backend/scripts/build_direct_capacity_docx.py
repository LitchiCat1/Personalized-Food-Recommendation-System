"""Create a concise Word report for the latest capacity search and 100-user run."""

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
    FONT, add_body, add_heading, add_page_number, add_picture, add_table, set_run_font,
)


def build(report):
    a = json.loads((report/"analysis.json").read_text(encoding="utf-8"))
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.7)
    section.left_margin = section.right_margin = Cm(2)
    section.footer_distance = Cm(.8)
    for grid in list(section._sectPr.findall(qn("w:docGrid"))):
        section._sectPr.remove(grid)
    for name,size in (("Normal",10.5),("Title",24),("Heading 1",16),("Heading 2",12.5)):
        style = doc.styles[name]
        style.font.name = FONT
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),FONT)
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string("000000")
        style.paragraph_format.space_before = Pt(0 if name=="Normal" else 9)
        style.paragraph_format.space_after = Pt(7)
        snap = OxmlElement("w:snapToGrid"); snap.set(qn("w:val"),"0")
        style._element.get_or_add_pPr().append(snap)
        if name!="Normal":
            style.font.bold = True
            style.paragraph_format.keep_with_next = True
    footer = section.footer.paragraphs[0]
    set_run_font(footer.add_run("NutriLens 併發容量測試　"),8.5,color="000000")
    add_page_number(footer)
    title = doc.add_paragraph(style="Title"); title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(title.add_run("NutriLens 併發容量測試報告"),24,True,"000000")
    date = datetime.fromisoformat(a["finished_at"]).strftime("%Y 年 %m 月 %d 日")
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(p.add_run(f"v1.0.0　{date}　直接啟動與容量邊界補測"),11,color="000000")
    add_heading(doc,"容量結論")
    add_body(doc,a["conclusion"])
    add_body(doc,"實務上請把本輪通過人數當作短時間測試的容量參考。前一輪 20 人曾完成約 60 秒確認，本輪重新建立連線時仍可能失敗，顯示邊界隨當時狀態變動；無法宣稱某一人數以上一定斷線。")
    add_heading(doc,"怎麼快速找出範圍")
    add_body(doc,a["method"])
    add_picture(doc,report/"01-capacity-search.png","圖一　各次容量試驗的要求人數與通過情況")
    doc.add_page_break()

    add_heading(doc,"每次試驗的實際數據")
    rows=[]
    for s in a["stages"]:
        rows.append((str(s["index"]),str(s["users"]),f"{s['duration_s']:.1f}",f"{s['requests']:,}",
            str(s["failed"]),f"{s['p95_ms']/1000:.2f}","通過" if s["passed"] else "未通過"))
    add_table(doc,["次序","人數","實測秒","請求數","失敗數","P95 秒","結果"],rows,
        widths=[.55,.6,.85,1.05,.8,.85,1.0],font_size=8.8)
    add_body(doc,"未通過的級別會提早結束後續循環，表中列實際秒數；所有人仍有首次嘗試的紀錄。請求數包含首次登入狀態驗證及後續資料操作，不含準備登入、健康檢查、最終驗證或登出。")
    add_body(doc,a["criteria"])
    add_heading(doc,"較長時間確認")
    c=a["confirmation"]
    if c:
        add_body(doc,f"{c['users']} 人確認實測 {c['duration_s']:.3f} 秒，{c['requests']:,} 次請求、{c['failed']} 次失敗，整體 P95 {c['p95_ms']/1000:.2f} 秒、最慢 {c['max_ms']/1000:.2f} 秒。首次連線共 {c['first_requests']} 次，失敗 {c['first_failed']} 次；其後 {c['later_requests']:,} 次 API 的 P95 {c['later_p95_ms']/1000:.2f} 秒，失敗 {c['later_failed']} 次。")
    n=a["neighbor_recheck"]
    if n:
        add_body(doc,f"上方相鄰 {n['users']} 人再次試驗：{'通過' if n['passed'] else '未通過'}，首次連線失敗 {n['first_failed']} 人，資料請求失敗 {n['later_failed']} 次。這是該次連線與操作的結果，不能據此判定所有使用者都會斷線。")
    add_body(doc,"P95 表示約 95% 的請求嘗試在該時間內結束，包含失敗嘗試；單次 API 時間不等於整頁載入或整輪完成時間。較長確認約兩分鐘，尚不足以代表數小時運作。")
    add_heading(doc,"測後資料驗證")
    v=a["verification"]
    add_body(doc,f"本回使用過的 {v['accounts_checked']} 個帳號均完成測後檢查，{v['accounts_valid']}/{v['accounts_checked']} 通過，每個仍有原本 3 筆紀錄。其餘帳號未使用；沒有新增帳號或保留紀錄。臨時紀錄 {v['pending_temporary_records']} 筆，本輪待登出憑證 {v['outstanding_tokens']} 組。")
    add_body(doc,f"健康檢查失敗 {a['health_failed']} 次，HTTP 5xx {a['http_5xx']} 次。各級業務錯誤分類："+"、".join(f"{k} {v} 次" for k,v in a["error_types"].items())+"。")
    doc.add_page_break()

    add_heading(doc,"直接 100 人的對照結果")
    b=a["burst"]
    add_body(doc,f"另一回已讓 100 人同時直接開始，{b['completed_users']} 人完成一輪、{b['incomplete_users']} 人在首次連線時失敗，實測 {b['duration_s']:.3f} 秒。成功連線後的 {b['later_api']['requests']} 次資料操作全成功，但這些完成人數不能當作穩定同時容量。")
    add_picture(doc,report/"02-direct-100.png","圖二　100 人一起開始時的整輪完成情況")
    add_table(doc,["請求範圍","次數","失敗數","P95 秒"],
        [("首次連線嘗試",str(b["first_request"]["requests"]),str(b["first_request"]["failed"]),f"{b['first_request']['p95_ms']/1000:.2f}"),
         ("連線成功後資料操作",str(b["later_api"]["requests"]),str(b["later_api"]["failed"]),f"{b['later_api']['p95_ms']/1000:.2f}")],
        widths=[2.8,1.2,1.2,1.3],font_size=9.2)
    add_heading(doc,"結論的適用範圍")
    add_body(doc,a["limitations"])
    add_body(doc,"若要定位真正瓶頸，下一步需同步比對伺服器本機與公開路徑、觀察 TCP 連線及主機資源，並由另一個網路來源重測。只加大同一來源的人數，無法區分負載產生器、家用網路、Funnel 與後端各自的限制。")
    add_heading(doc,"數據來源",2)
    start=datetime.fromisoformat(a["started_at"]).strftime("%Y-%m-%d %H:%M:%S")
    end=datetime.fromisoformat(a["finished_at"]).strftime("%Y-%m-%d %H:%M:%S")
    add_body(doc,f"容量搜尋時間為 {start} 至 {end}，時區 UTC+8，包含登入及驗證清理。目標 {a['target']}，v1.0.0。",after=4)
    add_body(doc,f"批次 {a['run']}；直接 100 人批次 {b['run']}。同目錄 analysis.json、stages.csv、requests.csv、verification.csv 保存原始來源 SHA256、逐級與逐筆數據。",after=0)
    for root in (doc._element,doc.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    doc.core_properties.title="NutriLens 併發容量測試報告"
    doc.core_properties.author=doc.core_properties.last_modified_by=""
    output=report/"NutriLens_併發容量測試報告.docx"
    doc.save(output)
    print(str(output).encode("ascii","backslashreplace").decode())


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("report",type=Path)
    build(parser.parse_args().report.resolve())
