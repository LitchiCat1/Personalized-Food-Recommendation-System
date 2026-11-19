# 專案架構與功能狀態

更新：2026-11-17（第83批 Android 蘋果 preview 截圖）；工作分支 `v1.0.3`。本文件描述目前程式與已觀測部署，營養補全的逐階段規格及證據以 [企劃書](plans/2026-11-13-web-nutrition-fallback.md)為準。[舊版架構](Project_Architecture_and_Status.historical.md)僅保留歷史。

## 現行架構

| 層級 | 實作與責任 |
| --- | --- |
| 前端 | Expo 54、React Native、React 19、TypeScript、Expo Router；沿用既有五個 tabs |
| 狀態與資料 | Zustand、typed API helpers、離線紀錄佇列；v1與v2營養合約有明確能力與版本閘門 |
| 後端 | Flask／Waitress，單一 Windows 工作排程；`backend/app.py` 組裝 services 與 repositories |
| 登入 | 本機暱稱／密碼、bcrypt、隨機 Bearer token；SQLite 保留 token digest，user-scoped routes 驗證 owner |
| 持久化 | 一份 SQLite 保存帳號、session、健康檔案、飲食紀錄、菜單快取及營養流程狀態 |
| AI | 共用 OpenAI-compatible 中轉設定／金鑰池；無中轉設定時才使用既有直接 provider 路徑 |
| 食品營養 | 內附 TFDA 2,213筆及 USDA FNDDS 5,431筆；相容候選中 TFDA 優先，保留自訂食品的使用者範圍 |
| 外部服務 | Google Places／Maps；受限 USDA FDC preview；Tavily 核心已實作但正式自動補全未啟用 |
| 部署 | Expo 靜態網站與 API 同源，由本機後端提供；Tailscale Funnel 轉入 loopback5000 |
| 版本與 CI | GitHub 備份與 GitHub Actions 後端 unittest／前端 typecheck；不自動部署網站 |

## 啟動與儲存

啟動讀取 `backend/.env.local`，拒絕非空 `DATABASE_URL`，依 `DATABASE_PATH` 開啟 SQLite、檢查 schema，再建立 repository／服務與路由。檔案損毀、無寫入權限或版本不相容就停止，不改連其他資料庫。明確空路徑才使用暫存記憶體，供隔離測試／demo，正式服務不可使用。

營養 repository 保存 scan context、候選 snapshot、confirmation、新 revision、preview、來源 policy、profile、quota、lease 與 cache 狀態。來源啟動載入只接受明確的 server-owned 配置，逐項對照已安裝且 active 的 policy；不掃描候選目錄、不自動安裝、不復活撤回來源。

## 食物照片流程

1. AI 回傳照片可支持的通用食物名稱、visual_evidence、食用狀態、做法、估重與不確定性，不直接生成營養數字或無標籤推斷品種／品牌。第82批蘋果原圖一次輸出「蘋果、raw、with_skin」、估重180g／weight confidence0.5；僅是隔離單圖結果。
2. 後端檢查本機資料的食品身分與可食基準；自訂食品維持 user scope，官方相容候選先 TFDA、後 USDA。
3. 相容命中依原始基準與重量換算；未配對項與未知營養素保留，已知合計不冒充完整餐點。
4. 目前正式服務只允許真正 local miss 且精確相容171688的一般帶皮生蘋果進入系統來源選用→明確確認→固定 Detail 預覽。顯示「蘋果」，不從資料庫推斷富士品種。
5. 來源 brand、皮、生熟或範圍不明／衝突時維持排除。FDC preview 會持久化流程狀態，仍未開啟新來源 profile accept／餐點保存；既有舊版保存可用。

第82批以真蘋果照片／正常後端路由驗到 TFDA 與 USDA FNDDS local miss 後，隔離 selection 可指向已審查171688一筆。第83批使用者提供的一般HTTPS scanner Android相簿截圖顯示通用「蘋果」、USDA FDC171688參考確認及readonly營養preview；截圖不是provider request trace，未能獨立核對目前正式runtime／flags或DB寫入。畫面摘要「沒有配對營養資料」與下方已找到USDA參考來源的文字有歧義。未來Tavily只在TFDA及相容USDA/FDC來源均無結果且身分足夠明確時檢索已准入營養來源；視覺模型先提供食材身份，Tavily不辨圖，模型只抽取取回原文的固定格式數據，後端驗證後才形成待確認候選。目前Tavily正式registry仍空、automatic Web fallback關閉。

Tavily 搜尋與文字擷取、模型固定格式選格、嚴格 validator 及後端換算已有隔離測試。第82批沒有呼叫Tavily，沒有證明任何Tavily來源適用蘋果。正式registry尚空，帳戶／publisher權利與跨使用者cache尚未核可，不能把核心存在解讀為已自動搜尋所有食物。FDC Search與raw Detail HTTP仍關閉。

## 功能狀態與限制

| 項目 | 目前狀態 |
| --- | --- |
| 手機相機與辨識 | Android 使用者已驗 camera smoke；葉菜可能僅辨為泛稱，不能用 Tavily 補出物種 |
| 本機營養查找、重量修改、標示 OCR | 既有功能；食品／狀態相容與缺值語意須維持 |
|171688單一來源選用／確認／preview | 第七十八批已發布，local/public資產與旗標有核對證據 |
| 真照片觸發條件式preview | 第83批使用者截圖顯示一般HTTPS相簿蘋果到USDA FDC171688 readonly preview；未有request trace／runtime旗標核驗，不等同全流程或Tavily驗收；已有本機相容來源時不可刻意跳過 |
| 第三層自動補全與新來源保存 | 尚未開啟；依原企劃六個工作流及權利／保存門檻執行 |
| 今日／歷史／趨勢／洞察新版營養UI | 使用者已延後完整改造；不能自行擴增為本輪工作 |
| 店家搜尋、地圖與推薦 | Google Places／Maps及既有菜單快取；餐點估算不是食品實測真值 |
| 真值準確率 | 缺乏獨立標註與秤重真值，不能將配對率或模型自評當準確率 |

`v1.0.2` 已備份至GitHub。第79批清理與完整回歸、第80批進度核對均有歷史證據；第81批[真便當隔離路由驗證](food-nutrition-evaluation/2026-11-14/scanner-real-photo-local-priority-20261117.json)取得7項／本機配對4項，兩份葉菜仍未確定菜種。第83批[Android 蘋果 preview 截圖](food-nutrition-evaluation/2026-11-14/android-apple-preview-screenshots-20261117.json)支持一般scanner相簿確認／唯讀preview畫面及換算核對；沒有request trace，因此未驗證Tavily呼叫數、資料庫寫入或目前runtime flags。先前服務PID／started_at漂移及目前後端載入版本仍未重新核實，本批未部署。下一步沿既有來源准入gate，不以已有USDA來源的蘋果觸發Tavily。

## 主要檔案

- 後端：`backend/app.py`、`backend/services/`、`backend/repositories/`、`backend/config/nutrition_source_candidates/`。
- 前端：`frontend/app/(tabs)/`、`frontend/components/scanner/`、`frontend/lib/`、`frontend/store/useStore.ts`。
- 操作：[維運手冊](Operations_Runbook.md)、[Windows 部署](Local_Server_Deployment.md)。
- 驗證：[食品照片測試](food-image-evaluation/README.md)、[營養測試證據](food-nutrition-evaluation/2026-11-14/README.md)、`backend/tests/`、`frontend/scripts/test-*.mjs`。

歷史架構圖、壓力報告與舊規劃描述其各自產生版本；不可據此重啟已廢止的雲端服務或放行現有 feature flags。
