# Phase2 前端分階段驗收

最近交付：Phase2b2a送出／重試完整性，詳[下方結果](#phase2b2a-送出與重試完整性)。以下Phase2b1數字與限制保留為當批歷史，由後續段落說明已完成的修正。

版本保護：使用者明定v1.0.1只更換AI模型，保留原基準bb81e92；本企劃其餘改動在v1.0.2作本機提交隔離，無push／部署。下文「未commit」描述測試當下狀態。模型／金鑰設定、本機DB、使用者新增照片及無關外層規劃不加入提交。

## Phase2b1 前端基礎

日期：2026-11-14；工作分支v1.0.2，原基準bb81e92。依使用者要求建立分支並保留未提交修改，沒有新commit或部署。現行流程見[企劃書第26節](../../plans/2026-11-13-web-nutrition-fallback.md)。

本批完成獨立nullable型別、原格計算／coverage、顯式v2 API，以及版本化queue、舊retry固定時間／餐別和queue錯誤提示。既有scanner、OCR、今日、編輯、趨勢與推薦仍未轉成v2，不能宣稱全鏈完成。

| 自動檢查 | 結果 |
| --- | --- |
| 新原格換算／coverage | 15項通過，含null／0／排他上界、單位、未知重量、原格往返、極值 |
| 新API transport | 14項通過，Python純服務產snapshot、socket禁用、mock fetch；非真HTTP整合 |
| 新queue／metadata | 16項通過，mock storage遷移／失敗保留／版本／並行／跨日／衝突 |
| 全部前端Node測試 | 114通過，0失敗／略過，985ms |
| typecheck／lint／build:web | 均退出0 |

結果見[frontend-foundations-regression.json](frontend-foundations-regression.json)。重建：`node tools/verify_nutrition_frontend.mjs --output docs/food-nutrition-evaluation/2026-11-14/frontend-foundations-regression.json`。原始執行日誌留系統暫存，不把環境／原始日誌寫入公開manifest。Node module-type提示及Expo既有套件版本提示不代表本批產品例外。

渲染流程：`http://localhost:8092/scanner` → future queue schema使讀取失敗 → 顯示資料保留提示 → 關閉提示 → 切手動搜尋並輸入白飯 → 原queue仍在 → 重載恢復提示。Browser plugin未提供，使用Playwright CLI；假session及所有API回應僅在隔離瀏覽器攔截，未連正式DB或付費服務。

| UI檢查 | 結果 |
| --- | --- |
| 頁面／標題 | scanner／NutriLens 個人化飲食推薦 |
| 非空白／無framework overlay | 通過 |
| Console | 0 errors；1項既有pointerEvents deprecation warning |
| 375／390／430／768／1440寬 | 無頁面或alert水平溢位，alert未超出視窗 |
| 截圖 | 390x844與1440x1000已目視確認換行與關閉鈕 |
| 互動與資料保留 | 關閉、輸入及重載通過，future queue原值仍在 |

截圖位於測試機暫存，未加入repo：[手機](C:/Users/botto/AppData/Local/Temp/nutrition-v2-mobile.png)、[桌面](C:/Users/botto/AppData/Local/Temp/nutrition-v2-desktop.png)。畫面既有v1.0.1徽章是應用release文字，本次只建立v1.0.2工作分支，未改release metadata。

獨立審查發現並修正：假完整coverage、未解IDs遺失、point／bound矛盾、必要metadata遺失、POST去重混版、queue必填型別及舊retry忽略固定時間。嚴格回應檢查亦發現營養欄位陣列順序差異，已對齊後端並補未解項跨語言比對。

限制：queue mutex只保護單runtime，跨tab原子性與混版衝突合併未完成；目前偵測兩key並存就停下保留。v2尚無UI dispatcher；live legacy submit未在按下時固定時間，首次跨午夜失敗仍可能採較晚日期。重送後optimistic今日、preview revision／警告與全部nullable顯示、OCR小於值與推薦尚待接線。沒有真手機、真登入、照片／秤重準確率、真Postgres／Mongo或完整後端HTTP驗收。本輪未改後端，未重跑先前733項。

automatic_web_fallback_enabled仍false；本批0模型／Tavily呼叫、0實際使用者資料庫修改，先前67模型嘗試及17 Tavily請求總量不變。

## Phase2b2a 送出與重試完整性

日期2026-11-14；v1.0.2，未commit／部署，既有修改及使用者照片保留。完成範圍是舊scanner／manual／OCR送出與queue完整性；nullable v2 UI及dispatcher仍未接線。詳[企劃書第27節](../../plans/2026-11-13-web-nutrition-fallback.md#27-第五批phase-2b2a-送出與重試完整性)。

| 檢查 | 結果 |
| --- | --- |
| 新submission流程 | 13項；真helper／queue／serializer＋mock fetch，含臺灣00:03日期／跨午夜、固定body、write-ahead、改稿攔截、saved標記及帳號／API隔離 |
| 新lock／target | 12項；mock共用鎖兩store、並行修改／遷移、無鎖不讀寫、原後端綁定與舊未綁定阻擋 |
| 全部前端Node測試 | 139通過，0失敗／略過 |
| typecheck／lint／build:web | 均退出0，最後一次包含新草稿identity、OCR固定ID及舊401事件session guard |
| 後端測試 | 後端未改，本批未重跑既有733項 |

重建：`node tools/verify_nutrition_frontend.mjs --output docs/food-nutrition-evaluation/2026-11-14/frontend-submission-regression.json`。結果見[manifest](frontend-submission-regression.json)，原始日誌留系統暫存。這不是後端真HTTP／資料庫整合。

最後Git核對發現工作期間由其他操作於01:00:56+08切回v1.0.1；兩分支都指向bb81e92且沒有分支內容差異。已保留全部未提交檔案並恢復使用者指定v1.0.2。manifest保留測試當下實際分支v1.0.1，不改寫成在另一分支執行；交付程式檔案相同。

Browser plugin未提供，使用Playwright CLI；網址`http://localhost:8092/scanner`，正常auth模式，隔離假session、所有API攔截，沒有正式帳號或資料庫呼叫。測試流程及證據：

| 流程 | 實際觀察 |
| --- | --- |
| 手動搜尋→加入→刻意503 | 每個POST前已有相同client ID／timestamp的本機快照 |
| 23:59:50失敗→翌日08:01重試 | 兩次整份body相同，timestamp仍2026-11-14T23:59:50.030+08:00、餐別晚餐；成功後queue空 |
| 背景補送成功→按仍可見加入 | POST總數仍2，提示已儲存，不新增事件 |
| 舊未綁定目標→自動／手動補送 | 均0 POST，queue原字串完全不變；中文提示保留 |
| Web檔案選擇→假OCR→首次503→再按加入 | 原內容整份body相同、POST2次、成功清相同草稿；舊未綁定queue仍保留 |
| 375／390／430／768／1440寬 | 失敗banner與頁面無水平溢位；舊目標提示另驗375／1440 |
| 390x844／1440x1000截圖 | 已目視，文字換行與關閉鈕正常，無遮蓋 |
| 頁面／非空白／overlay／console | 正確scanner與標題、非空白；最後重跑無overlay，各故意503有預期resource error、既有pointerEvents警告，無未解app error |

OCR只用假辨識回應；照片經檔案選擇但被本機攔截，沒有量測OCR或營養準確率。初次自動化重複處理file chooser觸發Expo removeChild overlay；改一次CLI upload後完整重跑通過。另一次臨時測試誤用未提供的clock.uninstall及模糊文字locator，均改用現有API／精確role後重跑。這些是測試操作問題，不掩蓋為成功。

截圖：[手機](C:/Users/botto/AppData/Local/Temp/nutrition-submit-mobile.png)、[桌面](C:/Users/botto/AppData/Local/Temp/nutrition-submit-desktop.png)。v1.0.1側欄徽章仍是release文字；本次工作分支為v1.0.2，未變更release metadata。測試瀏覽器及Expo服務於驗收後關閉。

本批修正重新審查通過：完整body／本地日期、後端目標、換帳號後畫面保護、舊保存只清相同camera／OCR草稿、OCR固定ID。saveRecord抑制過期舊session的401登出事件，當前session的401仍會通知，已加入既有帳號測試；其他API未全面改造。新版分頁共用Web Lock但不涵蓋舊lockless分頁；無Web Locks的瀏覽器會停止本機queue操作，native仍只保證單runtime。舊未綁定目標及兩key混版需後續明確調解，現階段保留並阻擋，不能稱完整遷移。

下一步是versioned／coverage-aware讀取模型、nullable每日／趨勢／洞察與編輯，再接掃描來源context、preview、v2 dispatcher、OCR小於值及推薦。automatic_web_fallback_enabled仍false；模型／Tavily付費總數不變。沒有實機相機、真登入、真Postgres／Mongo、真HTTP、真來源取回或完整拍照營養準確率驗收。
