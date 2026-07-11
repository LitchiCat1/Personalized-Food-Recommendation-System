# 專案架構與功能狀態總整理

> 最後更新：2026-06-17
> 專案：NutriLens / Personalized Food Recommendation System

## 1. 文件目的

本文件整合 `docs/PRD.md` 與目前實際程式碼狀態，作為後續開發、交接、部署與功能補齊的主要參考。

`PRD.md` 描述的是產品願景與研究目標；本文件描述的是目前 repository 內已實作的架構、功能完成度、限制與 Render + Supabase 部署驗證狀態。

## 2. 專案定位

本專案是一套個人化飲食推薦與影像辨識系統，核心目標是降低飲食紀錄門檻，並依照使用者健康條件提供較安全的飲食建議。

目前系統已具備以下主軸：

- 使用手機相機或相簿圖片進行食物辨識。
- 以 Gemini Vision 判斷食物名稱、候選同義詞與份量描述。
- 後端使用 Gemini 候選名稱查詢 TFDA 台灣食品營養資料庫與使用者自訂食品，營養數字只來自資料庫。
- 依照估算重量換算熱量、蛋白質、碳水、脂肪、鈉與纖維。
- 依照疾病與過敏原規則產生警示或排除推薦。
- 支援手動搜尋 TFDA 食品、營養標示 OCR、自訂食品與飲食紀錄。
- 支援 Render 免費方案部署後端與 Supabase PostgreSQL 儲存資料。

## 3. PRD 與目前實作差異

| 項目 | PRD 規劃 | 目前實作 |
|------|----------|----------|
| 前端 | React Native 行動 App | Expo React Native + TypeScript + Expo Router，支援 mobile/web 開發 |
| 後端 | Flask API | Flask API，已拆分 services 與 repository |
| 影像模型 | 原規劃為本機深度學習辨識 | Gemini Vision API + 後端資料庫營養對應 |
| 營養資料 | 營養資料庫 | TFDA 台灣食品資料庫 + 手工 DB + 自訂食品 |
| 資料庫 | MongoDB | PostgreSQL/Supabase 優先，MongoDB 備援，In-memory fallback |
| 推薦 | 安全過濾 + 口味排序 + 地圖導向 | 安全過濾、候選擴展與歷史偏好加權已完成；地圖導向已接 Google Maps Web 與 Google Places 真實店家搜尋，菜單營養仍需掃描/手動確認 |
| OCR | 未明確細化 | 已使用 Gemini Vision API 做包裝食品營養標示 OCR |
| 部署 | 雲端資料儲存 | Render Web Service + Supabase Postgres 已完成首次部署驗證 |

## 4. 完整專案架構

```txt
Personalized-Food-Recommendation-System/
├── .env.local                          # 本機環境變數，已 gitignore
├── .gitignore
├── README.md                           # 專案入口說明
├── render.yaml                         # Render 後端部署設定
│
├── backend/                            # Flask 後端
│   ├── app.py                          # Flask app 入口、路由、初始化
│   ├── config/
│   │   └── disease_rules.json          # 疾病飲食限制規則設定
│   ├── requirements.txt                # Python 依賴
│   ├── test_client.py                  # 後端 API 手動測試腳本
│   ├── nutrition_db.json               # 舊版手工營養資料庫
│   ├── nutrition_db_tw.json            # TFDA 台灣食品營養資料庫，約 2,181 筆
│   │
│   ├── repositories/
│   │   └── storage.py                  # PostgreSQL/MongoDB/In-memory 資料層抽象
│   │
│   ├── services/
│   │   ├── env_service.py              # 載入 .env.local
│   │   ├── disease_rule_service.py     # 載入疾病規則設定
│   │   ├── food_service.py             # TFDA 與自訂食品搜尋、建立自訂食品
│   │   ├── healthy_food_service.py     # 附近健康餐點推薦 MVP
│   │   ├── history_service.py          # 飲食歷史彙整
│   │   ├── nutrition_label_service.py  # Gemini Vision 營養標示 OCR
│   │   ├── food_analysis_service.py    # 可信度、份量區間與健康警示共用邏輯
│   │   ├── vision_food_service.py      # Gemini Vision 食物辨識與資料庫營養對應
│   │   ├── google_places_service.py    # Google Places Nearby Search 真實店家搜尋
│   │   ├── restaurant_ai_service.py   # Gemini AI 店家摘要（餐點/價格區間/健康建議推測）
│   │   ├── profile_service.py          # 使用者 profile、BMR/TDEE/BMI
│   │   └── recommend_service.py        # 規則型雙軌推薦
│   │
│   ├── scripts/
│   │   ├── convert_tfda.py             # TFDA 原始資料轉換
│   │
│   └── tfda_data/
│       ├── 20_5.json                   # TFDA 原始完整資料
│       ├── nutrients_list.txt          # 可用營養素欄位清單
│       └── sample.txt                  # TFDA 資料格式範例
│
├── frontend/                           # Expo React Native 前端
│   ├── .env.local.example              # 前端連線 Render 後端範例
│   ├── package.json
│   ├── tsconfig.json
│   │
│   ├── app/                            # Expo Router routes
│   │   ├── _layout.tsx                 # Root layout
│   │   ├── modal.tsx                   # Modal 頁面
│   │   └── (tabs)/
│   │       ├── _layout.tsx             # Tab layout
│   │       ├── index.tsx               # 今日營養 Dashboard
│   │       ├── scanner.tsx             # AI 食物辨識、手動搜尋、OCR
│   │       ├── recommend.tsx           # 智慧推薦與附近健康餐點
│   │       ├── history.tsx             # 飲食趨勢
│   │       └── profile.tsx             # 個人檔案、疾病、過敏原
│   │
│   ├── components/
│   │   ├── AppContainer.tsx            # 共用頁面容器
│   │   ├── dashboard/                  # Dashboard 元件
│   │   ├── maps/                       # 跨平台地圖元件
│   │   │   ├── FoodMap.tsx              # Native fallback 地圖
│   │   │   └── FoodMap.web.tsx          # Web Google Maps JavaScript API
│   │   ├── scanner/                    # Scanner 元件
│   │   └── ui/                         # 通用 UI 元件
│   │
│   ├── constants/
│   │   ├── mock-data.ts                # Mock 與型別資料
│   │   └── theme.ts                    # 設計系統 token
│   │
│   ├── hooks/
│   │   └── useResponsive.ts            # 響應式與平台偵測
│   │
│   ├── lib/
│   │   ├── api.ts                      # 非 scanner 頁面 API 封裝與型別
│   │   ├── network.ts                  # API base URL 推導
│   │   └── scanner.ts                  # scanner 流程 API 封裝
│   │
│   └── store/
│       └── useStore.ts                 # Zustand 全域狀態
│
└── docs/
    ├── PRD.md                          # 產品需求與研究背景
    ├── Project_Architecture_and_Status.md
    └── Operations_Runbook.md           # 指令、部署驗收、key 輪替、工作日誌與事故經驗
```

## 5. 技術棧

| 層級 | 技術 |
|------|------|
| Frontend | Expo 54, React Native 0.81.5, React 19, TypeScript |
| Routing | Expo Router |
| State | Zustand |
| UI / Device | expo-camera, expo-image-picker, expo-location, react-native-svg, @vis.gl/react-google-maps |
| Backend | Flask, Flask-CORS |
| AI Detection | Google Gemini Vision API via REST |
| AI Summary | Google Gemini API for restaurant menu/price/budget inference |
| Nutrition Grounding | TFDA 台灣食品資料庫 + user scoped custom foods |
| Map | Google Maps JavaScript API (frontend) + Google Places API (backend) |
| OCR | Google Gemini Vision API via REST |
| Database | PostgreSQL/Supabase, MongoDB fallback, In-memory fallback |
| Deployment | Render Web Service free plan + Supabase Postgres free plan |
| CI | GitHub Actions，Backend syntax check + Frontend typecheck |

## 6. 後端架構

後端採用 Flask API，`backend/app.py` 負責初始化與路由，主要業務邏輯已拆到 `backend/services/`，資料存取集中在 `backend/repositories/storage.py`。

### 6.1 啟動流程

```txt
載入 .env.local
  -> 若有 DATABASE_URL，連線 PostgreSQL/Supabase
  -> 若無 PostgreSQL 或連線失敗，嘗試 MongoDB
  -> 若 MongoDB 也不可用，退回 In-memory
  -> 載入 Flask app + CORS
  -> 載入 nutrition_db.json 與 nutrition_db_tw.json
  -> 開放 API routes
```

### 6.2 資料層優先順序

`StorageRepository` 目前依序支援：

1. `DATABASE_URL`：PostgreSQL，建議使用 Supabase。
2. `MONGO_URI`：MongoDB。
3. In-memory fallback：本機臨時測試用，重啟後資料消失。

使用 PostgreSQL 時會自動建立：

- `users`
- `records`
- `custom_foods`

### 6.3 API 路由

| Method | Path | 功能 |
|--------|------|------|
| `GET` | `/` | 後端 API 狀態說明，避免直接打 Render URL 時出現 404 |
| `GET` | `/health` | 健康檢查，回傳 DB、模型、資料庫、疾病規則載入狀態 |
| `GET` | `/search/food?q=&limit=&user_id=` | 搜尋自訂食品與 TFDA 食品 |
| `GET` | `/food/<food_key>` | 取得單一食品完整資料 |
| `POST` | `/custom-food` | 建立或更新自訂食品 |
| `GET` | `/custom-foods?user_id=` | 列出自訂食品 |
| `POST` | `/ocr/nutrition-label` | 營養標示 OCR |
| `POST` | `/predict/vision-food` | Gemini 食物辨識與資料庫營養分析 |
| `GET` | `/user/<user_id>` | 取得使用者 profile |
| `POST` | `/user` | 建立或更新使用者 profile |
| `POST` | `/record` | 新增飲食紀錄 |
| `GET` | `/records/<user_id>?date=` | 查詢飲食紀錄 |
| `GET` | `/history/<user_id>?days=` | 飲食歷史與趨勢彙整 |
| `GET` | `/recommend/<user_id>` | 規則型食物推薦 |
| `POST` | `/recommend/<user_id>/feedback` | 推薦回饋（採納/略過/不喜歡） |
| `GET` | `/recommend/<user_id>/feedback` | 列出推薦回饋 |
| `GET` | `/healthy-food-recommend/<user_id>` | 附近健康餐點推薦（使用 restaurant_catalog.json） |
| `GET` | `/map-food-recommend/<user_id>` | 地圖推薦：Google Places 真實店家搜尋 |
| `POST` | `/map-food-recommend/<user_id>/restaurant-summary` | Gemini AI 店家摘要（餐點/價格/健康建議推測） |
| `GET` | `/disease-rules` | 疾病規則版本、審核狀態、參考來源與醫療免責摘要 |
| `GET` | `/medical-metadata` | 疾病規則與過敏原分類（allergen taxonomy）治理 metadata 合併查詢 |
| `POST` | `/calculate/bmr` | BMR/TDEE/BMI 計算 |

## 7. 前端架構

前端使用 Expo Router 的 file-based routing，主畫面由五個 tab 組成。

| Tab | 檔案 | 功能 |
|-----|------|------|
| 首頁 | `frontend/app/(tabs)/index.tsx` | 今日熱量、營養素進度、BMR/TDEE、今日餐點 |
| 辨識 | `frontend/app/(tabs)/scanner.tsx` | 相機拍攝、相簿上傳、Gemini Vision 辨識、TFDA 手動搜尋、營養標示 OCR |
| 推薦 | `frontend/app/(tabs)/recommend.tsx` | 規則型推薦、疾病過濾結果、附近健康餐點推薦 |
| 趨勢 | `frontend/app/(tabs)/history.tsx` | 7 日熱量、營養均值、鈉攝取與簡易洞察 |
| 我的 | `frontend/app/(tabs)/profile.tsx` | 使用者資料、BMR/TDEE、疾病、過敏原與後端同步 |

### 7.1 前端狀態管理

`frontend/store/useStore.ts` 使用 Zustand 管理：

- 使用者 profile。
- 今日營養與餐點狀態。
- 掃描結果。
- 相機啟用狀態。
- API base URL。

### 7.2 API 封裝

| 檔案 | 職責 |
|------|------|
| `frontend/lib/api.ts` | `history`、`recommend`、`profile`、`healthy-food-recommend` API 與型別 |
| `frontend/lib/scanner.ts` | `/predict/vision-food`、`/record`、`/search/food`、`/ocr/nutrition-label`、`/custom-food` |
| `frontend/lib/network.ts` | 解析 `EXPO_PUBLIC_API_BASE_URL`、Expo host、localhost、Android emulator fallback |

## 8. 核心資料流程

### 8.1 影像辨識與營養分析

```txt
前端拍照或上傳圖片
  -> base64 image
  -> POST /predict/vision-food
  -> Gemini Vision 判斷台灣常見食物語意、候選名稱與份量描述
  -> 後端以 Gemini 食物名稱搜尋 user scoped custom_foods 與 TFDA nutrition_db_tw.json
  -> 營養數字只由資料庫換算，不直接採用 Gemini 生成值
  -> 回傳 recognition reliability、portion_range_g、alternatives 與人工確認提示
  -> 前端可人工校正重量，並依原始每份營養比例即時重算
  -> 依每 100g 營養資料換算實際營養素
  -> check_food_safety 比對疾病規則與過敏原
  -> 回傳 detections、rejected_detections、summary
```

### 8.2 手動搜尋食品

```txt
使用者輸入中文關鍵字
  -> GET /search/food
  -> 先搜尋 user scoped custom_foods
  -> 再搜尋 TFDA nutrition_db_tw.json
  -> 前端以每 100g 顯示並可加入今日紀錄
```

### 8.3 營養標示 OCR

```txt
使用者上傳包裝營養標示圖片
  -> POST /ocr/nutrition-label
  -> Gemini Vision API 擷取 JSON
  -> normalize_ocr_result 正規化數值
  -> 回傳 suggested_custom_food
  -> 使用者可儲存為 custom_food 或直接加入紀錄
```

後端優先讀取 `GEMINI_API_KEYS`，支援以逗號分隔多組 key；若未設定，才 fallback 到 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`。當 Gemini 回傳 `401`、`403`、`429`、`500`、`502`、`503`、`504` 時，會嘗試下一組 key。

### 8.4 飲食紀錄與趨勢

```txt
前端加入掃描/手動/OCR 食品
  -> 先更新本機 Dashboard
  -> 產生 client_record_id
  -> POST /record，payload 包含 client_record_id
  -> 若同步失敗，寫入 frontend/lib/recordSyncQueue.ts 的本機待同步佇列
  -> Scanner 聚焦時自動重送未達 5 次上限的待同步紀錄
  -> 使用者可在 Scanner 頁以目前 Supabase session 重試同 user_id 的佇列
  -> 後端以 (user_id, client_record_id) 做冪等去重
  -> StorageRepository 儲存至 PostgreSQL/MongoDB/Memory
  -> GET /history/<user_id>?days=7
  -> 後端依日期聚合熱量、蛋白質、碳水、脂肪、鈉
  -> 前端呈現趨勢圖、週均值、鈉攝取與簡易洞察
```

### 8.5 推薦流程

```txt
GET /recommend/<user_id>
  -> 取得使用者疾病與過敏原
  -> 取得今日已攝取熱量
  -> 計算剩餘熱量
  -> 建立候選池：nutrition_db.json + nutrition_db_tw.json + 使用者自訂食品
  -> 排除高風險疾病與過敏食品
  -> 依熱量契合、低鈉、高蛋白、GI 分數排序

GET /healthy-food-recommend/<user_id>
  -> 取得定位與預算
  -> 載入 backend/data/restaurant_catalog.json 或 RESTAURANT_CATALOG_PATH 指定資料源
  -> 過濾距離、半徑、類型、營業時間、預算、疾病限制
  -> 依預算、距離、熱量契合、低鈉、高蛋白排序
  -> 回傳扁平餐點列表與地圖友善 restaurants 分組

GET /map-food-recommend/<user_id>
  -> 取得定位、預算、半徑、類型
  -> 後端使用 GOOGLE_PLACES_API_KEY 查 Google Places Nearby Search
  -> 回傳真實店家位置、評分、營業狀態、距離與導航資料
  -> 不產生假菜單營養；回傳 nutrition_available: false，提示到店後掃描/手動搜尋

POST /map-food-recommend/<user_id>/restaurant-summary
  -> 接收單一店家資料（Google Places 欄位）與使用者預算、健康條件
  -> Gemini 依店名、類型、價位等級、評分推測可能餐點與價格區間
  -> 不假裝知道正式菜單；回傳固定 JSON schema 與 source_note 免責
  -> 前端顯示「AI 推測」卡片，標明非店家正式菜單
```

## 9. 疾病與過敏原規則

目前疾病規則集中於 `backend/config/disease_rules.json`，由 `backend/services/disease_rule_service.py` 載入、驗證治理欄位後傳入辨識、推薦與健康餐點推薦流程。`GET /disease-rules` 會公開規則版本、審核狀態、參考來源、限制摘要與醫療免責聲明。

| 疾病 | 目前規則 |
|------|----------|
| 糖尿病 | 阻擋高 GI，單餐碳水上限 60g |
| 高血壓 | 單餐鈉上限 600mg |
| 慢性腎臟病 | 單餐蛋白質上限 40g |
| 痛風 | 阻擋高普林標籤，目前為 `hot dog` |
| 高血脂 | 單餐脂肪上限 20g |

過敏原目前由使用者 profile 的 `allergens` 陣列與食品資料中的 `allergens` 陣列比對。

疾病規則治理欄位包含：

- `rule_version`：規則版本。
- `review_status`：目前審核狀態，現階段皆為 `needs_clinical_review`。
- `last_reviewed`、`reviewed_by`：最近整理日期與整理者。
- `evidence_level`、`references`：規則依據層級與參考來源。
- `medical_disclaimer`：疾病提醒不可取代醫師或營養師建議的免責文字。

## 10. 已完成功能

> 彙整日期：2026-06-17

### 10.1 後端

- 已完成 Flask API 主服務。
- 已完成 Gemini Vision 食物影像辨識。
- 已完成 Gemini 份量估算、可信區間與營養素縮放。
- 已完成前端份量校正，掃描結果可調整重量並即時重算營養素。
- 已完成 TFDA 台灣食品營養資料庫整合，約 2,181 筆食品。
- 已完成 Gemini 候選食品名稱到 TFDA/自訂食品資料庫的查詢對應。
- 已完成 TFDA 搜尋排序，避免「蘋果」命中加工乳品/飲料。
- 已完成 Gemini model candidate rotation，`404 model not found` 視為可 fallback。
- 已完成低信心辨識拒絕、需確認標記與手動搜尋提示。
- 已完成疾病規則與過敏原警示。
- 已完成疾病規則設定化，規則已從 `backend/app.py` 移到 `backend/config/disease_rules.json`。
- 已完成疾病規則治理 metadata 與載入驗證，並新增 `/disease-rules` 查詢端點。
- 已完成 BMR/TDEE/BMI 計算。
- 已完成使用者 profile CRUD。
- 已完成飲食紀錄新增與查詢。
- 已完成 `/record` 的 `client_record_id` 冪等去重，待同步佇列重試不會重複寫入同一筆餐點。
- 已完成 7 日飲食歷史彙整。
- 已完成 TFDA 與自訂食品搜尋。
- 已完成營養標示 OCR 與自訂食品儲存。
- 已完成規則型推薦。
- 已完成推薦候選擴展，`/recommend` 會納入 TFDA 與使用者自訂食品，並回傳來源統計。
- 已完成歷史飲食偏好加權，`/recommend` 會參考近期紀錄產生 `preference_score` 與偏好原因。
- 已完成推薦回饋記錄，使用者可標記採納、略過或不喜歡，`/recommend` 會把近期回饋納入排序。
- 已完成附近健康餐點推薦 MVP（catalog-based，保留為 `/healthy-food-recommend` 相容）。
- 已完成 Google Places 真實店家搜尋，`/map-food-recommend` 改用 Places，不再讀 catalog。
- 已完成 Gemini AI 店家摘要，`POST /map-food-recommend/<user_id>/restaurant-summary` 產生餐點/價格/健康建議推測。
- 已完成 PostgreSQL/MongoDB/In-memory 三層資料儲存 fallback。
- 已完成 Render `PORT` 支援與 `render.yaml`。
- 已完成 Gemini 多 API key 輪替，Render 建議使用 `GEMINI_API_KEYS`。
- 已完成 backend health 檢查 `places_enabled` 欄位。

### 10.2 前端

- 已完成 Expo Router 五個主要 tab。
- 已完成 Dashboard 熱量環圖、營養素進度與今日餐點顯示。
- 已完成相機拍攝與相簿上傳入口。
- 已完成 scanner 頁面呼叫 `/predict/vision-food`。
- 已完成辨識結果、拒絕結果、警示與加入今日紀錄流程。
- 已完成 TFDA 手動搜尋與加入紀錄流程。
- 已完成營養標示 OCR、儲存自訂食品、直接加入紀錄流程。
- 已完成 profile 頁面讀取與同步後端使用者資料。
- 已完成疾病與過敏原切換後同步後端。
- 已完成推薦頁呼叫 `/recommend` 與 `/healthy-food-recommend`。
- 已完成定位、預算與附近健康餐點 UI。
- 已完成附近餐廳推薦地圖：
  - Web 前端使用 Google Maps JavaScript API 顯示真地圖。
  - 後端 `/map-food-recommend` 使用 Google Places 搜尋真實附近店家。
  - 提供 Google Maps 外部導航。
  - 單一 `GOOGLE_PLACES_API_KEY` 由 build script 注入前端 Maps public env。
- 已完成 AI 店家摘要：
  - 推薦頁店家卡片「AI 摘要」按鈕。
  - 呼叫 `POST /map-food-recommend/<user_id>/restaurant-summary`。
  - 顯示店家類型、可能餐點、價格區間、預算適合度、健康建議、可信度與來源提醒。
  - 明確標示「Google Places + Gemini 推測，非店家正式菜單」。
- 已完成 history 頁呼叫 `/history` 並顯示趨勢。
- 已完成 API base URL 自動推導與 Render URL 環境變數支援。
- 已完成 Expo Web static export 設定，Render 可部署 frontend static site 供同學以瀏覽器測試。
- 已完成 Supabase Auth 登入/註冊基礎整合；有 Supabase public env 時會進入 AuthGate，登入後使用 Supabase Auth user id。
- 已完成 Bearer token 傳遞，user-scoped API 會帶 `Authorization: Bearer <access_token>`。
- 已完成首次登入 onboarding；若後端無 profile，使用者必須先填基本資料，避免看到預設示範資料。
- 已完成 profile 完整可編輯表單與登出按鈕（web 用 `window.confirm`）。
- 已完成掃描/手動/OCR 新增紀錄本機持久化待同步佇列與重試入口。
- 已完成新增紀錄 `client_record_id` 產生與待同步佇列保存。
- 已完成 Scanner 聚焦時自動重送待同步紀錄，並設定自動重送最多 5 次。
- 已完成推薦卡片採納、略過、不喜歡回饋按鈕。
- 已完成健康狀況設定區塊的醫療免責提示。
- 已完成手機、平板與 web 的基本響應式顯示。
- 已完成附近餐點 fetch 失敗時自動 fallback 到 Render backend 並顯示診斷資訊。

### 10.3 部署與資料

- 已完成 `render.yaml`，可用 Render Blueprint 部署後端 Web Service 與前端 Static Site。
- 已完成 Supabase Postgres 連線支援，只要設定 `DATABASE_URL`。
- 已完成 `frontend/.env.local.example`，可指定 Render 後端 URL。
- 後端 `/health` 可檢查 PostgreSQL、MongoDB、辨識引擎與資料庫載入狀態。
- 已完成 Render Web Service + Supabase Session Pooler 實測，`/health` 已確認 `status: ok`、`postgres: true`。
- 已完成 Render 強制 Supabase Auth 實測，`SUPABASE_AUTH_REQUIRED=true` 後 user-scoped API 會驗證 token 與 `user_id`。
- 已完成 GitHub Actions CI：後端 Python syntax check 與前端 TypeScript typecheck。

## 11. 未完成功能與目前限制

> 稽核口徑：以下不是否定已完成的 MVP，而是標出距離「可長期維護、可多人使用、可部署示範」仍缺的部分。

### 11.1 帳號與資料隔離

- 已完成 Supabase Auth 基礎登入/註冊整合。
- 已完成後端 user-scoped API 的 Supabase Bearer token 驗證。
- Render 目前已設定 `SUPABASE_AUTH_REQUIRED=true`，正式遠端 API 不再允許未帶 token 存取使用者資料。
- token subject 必須等於目標 `user_id`；無 token 回 `401`，跨使用者存取回 `403`。
- 未設定 Supabase public env 的本機前端仍可進入 demo 模式，僅供開發便利，不代表正式部署權限模型。
- 已完成登出按鈕、完整 profile 編輯表單與首次登入 onboarding；尚未完成 session 過期提示與使用者管理 UI。

### 11.2 影像辨識準確度

目前 TFDA 營養資料庫約 2,181 筆，已足夠支撐 MVP 的手動搜尋、推薦候選與自訂食品流程。影像辨識已改為 Gemini Vision 判斷食物語意，後端再查資料庫取得營養值；主要限制改為 Gemini 對照片內容與份量的初判不確定性，以及 TFDA 名稱對應是否命中。

- Gemini 只提供食物名稱、候選同義詞、份量描述與估計重量，不直接提供營養數字。
- 營養數字只來自 TFDA 或使用者自訂食品資料庫。
- 若 Gemini 候選名稱找不到資料庫對應，會回到手動搜尋流程。
- 份量估算仍需人工確認；前端已可人工校正重量，但尚未形成校正回饋資料。

### 11.3 營養與醫療安全

- 疾病規則目前為簡化設定，不等同醫療建議。
- 慢性腎臟病等疾病實際還需鉀、磷、鈉、蛋白質分期限制，目前尚未完整規則化。
- TFDA 資料雖已整合，但不是所有食品都已被推薦與搜尋流程完整利用。
- 疾病規則已有版本、來源、審核狀態與醫療免責 metadata；但目前審核狀態仍是 `needs_clinical_review`，尚未建立正式臨床審核流程或疾病分期規則。

### 11.4 推薦引擎

- `/recommend` 目前是規則型與分數型排序，不是真正的個人化口味向量或協同過濾。
- PRD 提到的「餘弦相似度」目前尚未完整實作。
- 使用者採納、略過或不喜歡已會被記錄並回饋到排序；但目前仍是啟發式加權，尚未達到完整協同過濾或向量推薦。
- 推薦候選已納入 TFDA 與使用者自訂食品，排序也會參考歷史飲食紀錄與近期推薦回饋。

### 11.5 餐廳與地圖資料

- `/healthy-food-recommend` 目前使用 `backend/data/restaurant_catalog.json`，也可用 `RESTAURANT_CATALOG_PATH` 指向替代 JSON 資料源。
- `/map-food-recommend` 使用 Google Places 真實店家資料；Render backend 需設定 `GOOGLE_PLACES_API_KEY`。
- Web 地圖使用 Google Maps JavaScript API；Render frontend 同樣設定 `GOOGLE_PLACES_API_KEY`，build script 會注入前端可讀的 Maps key。因為 key 會進入 browser bundle，必須在 Google Cloud Console 限制 API 與可用網域。
- Google Places 不提供可靠菜單價格、熱量、鈉、GI 等營養資料；系統會標示 `nutrition_available: false`，到店後仍需拍照掃描或手動搜尋餐點。
- Native iOS/Android 真地圖尚未接 `react-native-maps` 或 native Google Maps SDK；目前正式真地圖以 Web Render 展示為主。

### 11.6 前端資料同步

- Dashboard 已會從 `/records` 同步今日紀錄；新帳號在完成 onboarding 前不會進入 Dashboard，避免直接看到 `constants/mock-data.ts` 的示範資料。
- 今日掃描、手動搜尋與 OCR 新增採 local-first UX，後端寫入失敗時不會阻止使用者加入本地畫面，並會把失敗紀錄保存到本機待同步佇列。
- 待同步佇列依 `userId` 顯示與重試，重啟 app 後仍會保留；重試會沿用同一個 `client_record_id`，後端會避免重複寫入。
- Scanner 聚焦時會自動重送未達 5 次上限的待同步紀錄；達上限後停止自動重送，但使用者仍可手動重試。
- 目前尚未依網路恢復事件自動重送，也尚未提供同步佇列詳情頁。
- 部分設定項如飲食目標卡片與應用程式設定仍是展示型 UI。

### 11.7 測試與品質

- 目前已有後端 service smoke tests 與部分 Flask API route tests，但尚未形成完整自動化測試矩陣。
- 後端仍保留 `backend/test_client.py` 類型的手動整合測試。
- 前端尚未建立 e2e、component test 或 API mock 測試。
- 已建立基礎 GitHub Actions CI，但目前只涵蓋後端 syntax check 與前端 typecheck。
- `frontend/package.json` 已有 `typecheck` script，但尚未建立正式 test、build script。
- 尚未建立 pytest/unit test、前端 component test 或 e2e test。

### 11.8 免費部署限制

- Render free plan 會休眠，第一次請求可能明顯變慢。
- Supabase free plan 有容量、連線數與流量限制。
- Gemini API OCR 依賴 API key 與免費額度，可能受速率或配額影響。
- 已完成 Render + Supabase + Supabase Auth 強制驗證，但仍需持續記錄後續部署、錯誤與健康檢查結果。

## 12. Render + Supabase 部署驗證狀態

目前專案已完成免費方案跨網路部署驗證，並已部署至 Google Maps/Places + AI 店家摘要版本。

- Render backend URL：`https://personalized-food-recommendation-system-nq8t.onrender.com`
- Render frontend URL：`https://personalized-food-recommendation-frontend.onrender.com`
- Render backend service id：`srv-d7u2qhdckfvc73ei96l0`
- Render frontend service id：`srv-d87fffmq1p3s73b4u590`
- 部署分支：`v0.0.3`
- 最新已驗證 commit：`dd9b6a4 add AI restaurant summaries`
- `/health` 驗證摘要：`status: ok`、`postgres: true`、`places_enabled: true`、`foods_in_tfda: 2181`、`disease_rules: 5`、`restaurants: 10`
- Auth 驗證摘要：未帶 token 回 `401`，正確 token 回 `200`，跨 `user_id` 回 `403`
- 環境變數已設定：`GEMINI_API_KEYS`、`DATABASE_URL`、`SUPABASE_AUTH_REQUIRED=true`、`SUPABASE_URL`、`SUPABASE_PUBLISHABLE_KEY`、`GOOGLE_PLACES_API_KEY`（backend 與 frontend 皆同一名稱）

### 12.1 後端 Render

`render.yaml` 目前設定：

```yaml
services:
  - type: web
    name: personalized-food-recommendation-backend
    env: python
    plan: free
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: python -u app.py
    envVars:
      - key: GEMINI_API_KEYS
        sync: false
      - key: DATABASE_URL
        sync: false
      - key: FLASK_DEBUG
        value: "false"
      - key: SUPABASE_AUTH_REQUIRED
        value: "true"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_PUBLISHABLE_KEY
        sync: false
```

Render 需要設定：

- `DATABASE_URL`：Supabase Postgres connection string，Render 上 value 必須直接以 `postgresql://` 開頭，不要包含 `DATABASE_URL=` 前綴。
- `GEMINI_API_KEYS`：營養標示 OCR 使用，可用逗號分隔多組 Gemini key。
- `FLASK_DEBUG=false`：正式測試建議關閉 debug。
- `SUPABASE_AUTH_REQUIRED=true`：Render 正式環境已啟用；user-scoped API 必須帶 Supabase access token。
- `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY`：後端 Supabase Auth token 驗證必填。

### 12.2 Supabase

Supabase 只需要提供 PostgreSQL connection string 給 Render 的 `DATABASE_URL`。Render 實測已使用 Supabase Session Pooler 成功連線；連線字串通常包含 pooler host、port、database、user 與 password。

常見錯誤：Render 的 `DATABASE_URL` value 若把環境變數名稱也一起貼進欄位，例如以 `DATABASE_URL` 前綴加上 PostgreSQL DSN，後端會將 `DATABASE_URL` 視為 connection option，可能出現 `invalid dsn: invalid connection option "DATABASE_URL"`。

後端啟動後會自動建立：

- `users`
- `records`
- `custom_foods`

### 12.3 前端連線與部署 Render

在 `frontend/.env.local` 設定：

```env
EXPO_PUBLIC_API_BASE_URL=https://your-render-service.onrender.com
EXPO_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

Render Blueprint 已包含 frontend static site：

- service name：`personalized-food-recommendation-frontend`
- rootDir：`frontend`
- build command：`npm ci && npm run build:web`
- publish path：`dist`
- SPA rewrite：`/* -> /index.html`

部署後同學應使用 frontend static site 網址操作 App；backend URL 只提供 API 與 `/health`。

部署完成後先測：

```txt
GET https://your-render-service.onrender.com/health
```

目前已驗證 URL：

```txt
GET https://personalized-food-recommendation-system-nq8t.onrender.com/health
```

建議確認：

- `status: ok`
- `postgres: true`
- `recognition_engine: gemini-vision-db-lookup`
- `foods_in_tfda` 大於 0

## 13. 未完成功能製作順序

以下順序依照「先完成本機核心功能與資料一致性，再處理 Render + Supabase 遠端部署」排序。

| 順序 | 功能 | 稽核狀態 | 已具備 | 尚未完善 / 下一步 |
|------|------|----------|--------|------------------|
| 1 | Dashboard 從後端同步今日紀錄 | MVP 可用 | `index.tsx` 會呼叫 `/records` 並重建今日統計；Scanner 新增紀錄失敗會進本機待同步佇列；Scanner 聚焦會自動重送；後端以 `client_record_id` 冪等去重 | 初始 fallback 仍用 mock data；待同步佇列尚未依網路恢復事件自動重送，也沒有詳情頁 |
| 2 | Dashboard 與 History 資料一致化 | MVP 可用 | `/history` 回傳 `record_count`、總餐數、記錄天數；前端已顯示 | streak、總餐數、今日統計尚未全部由後端統一提供 |
| 3 | 疾病規則設定化 | MVP 可用 | 規則已移至 `backend/config/disease_rules.json`，啟動時驗證治理欄位，可由 `/disease-rules` 查詢版本、來源與免責資訊；Profile 已顯示醫療免責提示 | 尚無正式臨床審核流程、疾病分期規則與管理介面 |
| 4 | 推薦候選擴展到 TFDA 與自訂食品 | MVP 可用 | `/recommend` 已納入 TFDA、自訂食品、來源統計 | 尚未針對 TFDA 類別做更精細的候選篩選與效能索引 |
| 5 | 口味偏好與推薦分數升級 | MVP 可用 | 近期飲食紀錄會產生 `preference_score` 與原因 | 仍是啟發式分數，尚無採納/略過/不喜歡回饋模型 |
| 6 | Gemini/TFDA 名稱對應 | MVP 可用 | Gemini 會產生候選中文食品名稱，後端查 TFDA/自訂食品資料庫 | 尚未建立大型評測集與同義詞命中率分析，未命中時仍依賴手動搜尋/OCR |
| 7 | 份量估算校正 | MVP 可用 | 掃描結果可調整重量並即時重算營養 | 尚未用校正資料反饋 density，也沒有參考物/深度感測自動校正 |
| 8 | 測試與 CI | 基礎 CI 已完成 | `.github/workflows/ci.yml` 會跑後端 syntax check 與前端 `npm run typecheck` | 尚無 pytest/unit test、前端 test、e2e、正式 build check |
| 9 | 使用者身份驗證 | MVP 可用 | 後端已強制驗證 Supabase Bearer token 與 `user_id` 權限；前端已支援 Supabase Auth session 與 Bearer token 傳遞 | 尚未完成登出 UI、session 過期提示、完整 profile 編輯與自動化測試 |
| 10 | Render + Supabase 實測檢查流程 | 已完成 | 已記錄 Render URL、Supabase 實測結果、遠端 `/health` 摘要與 401/200/403 權限驗收 | 尚需維護後續部署紀錄與將 smoke tests 自動化 |

## 14. 重新標註的未完成清單

以下是依照本次 roadmap 稽核後，仍應視為未完成或待完善的項目。

### 14.1 最高優先級

1. 擴充完整測試：補更多後端 route/unit tests、前端 test/e2e、正式 build check。
2. 補前端 session 過期提示、網路恢復事件自動重送與同步佇列詳情頁。
3. 將 Render/Supabase/Auth smoke test 流程自動化，但不保存 secret values。

### 14.2 中優先級

1. 同步可靠性：為待同步佇列補網路恢復事件重送、同步狀態詳情頁與失敗項目管理。
2. 推薦模型：把目前啟發式回饋加權演進為可解釋的偏好模型或向量排序。
3. 健康餐點資料來源：已用 Google Places 取得真實店家；下一步是建立真實菜單/營養資料來源，或讓使用者到店後用掃描/手動搜尋補足餐點營養。

### 14.3 低優先級 / 研究型

1. Gemini 影像辨識評測集：整理混合餐、台灣小吃、便當類照片，量測名稱命中與份量誤差。
2. 份量自動校正：參考物、餐盤尺度、深度感測或使用者校正資料回饋 density。
3. 疾病規則醫療化：建立正式臨床審核流程、疾病分期規則與更完整的前端規則來源說明 UI。

## 15. 階段完成標準

### 15.1 第一階段完成標準

完成順序 1 到 4 後，專案應達到：

- 掃描或手動新增餐點後，Dashboard 可從後端重建今日總攝取。
- History 可從後端回傳的同一批紀錄計算週趨勢、記錄天數與總餐數。
- 疾病規則開始脫離 Flask 入口檔，降低後續維護成本。
- 推薦候選資料來源開始納入 TFDA 與自訂食品。

### 15.2 第二階段完成標準

完成順序 5 到 8 後，專案應達到：

- 推薦分數開始反映使用者偏好，而不只是固定營養規則。
- 食物辨識與份量估算有更清楚的人工校正流程。
- 後端核心 API 有自動化測試。
- 前端至少可通過 lint 或 typecheck。

### 15.3 第三階段完成標準

完成順序 9 到 10 後，專案應達到：

- 正式 Supabase Auth 模式下使用者不再共用 `demo_user`。
- 手機或 Web 前端可以連線 Render 後端。
- 使用者 profile、飲食紀錄、歷史趨勢可存在 Supabase。
- 部署前有固定檢查流程，避免 Render/Supabase 設定錯誤。
- user-scoped API 在 Render 上已驗證無 token 回 `401`、正確 token 回 `200`、跨使用者回 `403`。

## 16. 後續閱讀建議

第一次接手本專案建議依序閱讀：

1. `docs/PRD.md`：產品願景、研究背景與原始需求。
2. `docs/Project_Architecture_and_Status.md`：目前實作架構、功能狀態、限制與 roadmap。
3. `docs/Operations_Runbook.md`：部署、驗收、環境變數、API key 輪替與事故經驗。

## 17. TFDA 資料庫版本歷史

本節保留 TFDA 資料庫升級脈絡，避免 docs 內散落過多狀態型文件。

### 17.1 v0.0.1：概念驗證階段

- 使用 `nutrition_db.json` 作為主要資料來源。
- 內部僅包含約 12 筆手動輸入食品資料，例如蘋果、披薩、熱狗等。
- 營養數據僅提供熱量、蛋白質、脂肪、碳水化合物、鈉、膳食纖維等基礎欄位。
- 早期影像辨識結果直接以英文 label 對應小型 JSON；找不到時回傳未知食物。
- 主要限制是資料量太少、不夠在地化、缺乏進階營養素，難以支援疾病規則。

### 17.2 v0.0.2：TFDA 官方資料升級

- 解析 TFDA 原始資料 `backend/tfda_data/20_5.json`。
- 透過 `backend/scripts/convert_tfda.py` 轉換為 `backend/nutrition_db_tw.json`。
- 目前整理出約 2,181 筆台灣常見食品。
- 營養欄位從基礎 6 項擴展到糖、飽和脂肪、反式脂肪、膽固醇、多種維生素、鉀、鈣、鐵、鎂、磷、鋅等進階欄位。
- 曾新增靜態 label 對應表，將通用影像 label 對應到 TFDA 中文食品。
- 查詢 fallback 順序為 TFDA 在地資料庫、舊版手工資料庫、未知食物預設值。
- 新增或強化 `GET /search/food` 與 `GET /food/<food_key>`，支援中文食品搜尋與單筆營養資料查詢。

### 17.3 目前狀態

TFDA 資料庫已成為手動搜尋、推薦候選與 Gemini 影像辨識營養對應的主要來源。短期瓶頸不再是營養資料筆數，而是 Gemini 候選名稱與 TFDA 食品名稱的命中率，以及照片份量估計的不確定性。
