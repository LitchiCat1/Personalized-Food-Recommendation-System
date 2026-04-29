# 專案架構與功能狀態總整理

> 最後更新：2026-04-28  
> 專案：NutriLens / Personalized Food Recommendation System

## 1. 文件目的

本文件整合 `docs/PRD.md` 與目前實際程式碼狀態，作為後續開發、交接、部署與功能補齊的主要參考。

`PRD.md` 描述的是產品願景與研究目標；本文件描述的是目前 repository 內已實作的架構、功能完成度、限制與 Render + Supabase 異地連線準備狀態。

## 2. 專案定位

本專案是一套個人化飲食推薦與影像辨識系統，核心目標是降低飲食紀錄門檻，並依照使用者健康條件提供較安全的飲食建議。

目前系統已具備以下主軸：

- 使用手機相機或相簿圖片進行食物辨識。
- 以 YOLOv8 偵測食物類別與 Bounding Box。
- 將 YOLO label 對應到 TFDA 台灣食品營養資料庫。
- 依照估算重量換算熱量、蛋白質、碳水、脂肪、鈉與纖維。
- 依照疾病與過敏原規則產生警示或排除推薦。
- 支援手動搜尋 TFDA 食品、營養標示 OCR、自訂食品與飲食紀錄。
- 支援 Render 免費方案部署後端與 Supabase PostgreSQL 儲存資料。

## 3. PRD 與目前實作差異

| 項目 | PRD 規劃 | 目前實作 |
|------|----------|----------|
| 前端 | React Native 行動 App | Expo React Native + TypeScript + Expo Router，支援 mobile/web 開發 |
| 後端 | Flask API | Flask API，已拆分 services 與 repository |
| 影像模型 | YOLO 深度學習辨識 | YOLOv8 Nano (`yolov8n.pt`) |
| 營養資料 | 營養資料庫 | TFDA 台灣食品資料庫 + 手工 DB + 自訂食品 |
| 資料庫 | MongoDB | PostgreSQL/Supabase 優先，MongoDB 備援，In-memory fallback |
| 推薦 | 安全過濾 + 口味排序 + 地圖導向 | 安全過濾、候選擴展與歷史偏好加權已完成；真實地圖/餐廳 API 尚未完成 |
| OCR | 未明確細化 | 已使用 Gemini Vision API 做包裝食品營養標示 OCR |
| 部署 | 雲端資料儲存 | 已有 `render.yaml` 與 Supabase `DATABASE_URL` 支援 |

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
│   ├── yolov8n.pt                      # YOLOv8 Nano 預訓練模型
│   ├── nutrition_db.json               # 舊版手工營養資料庫
│   ├── nutrition_db_tw.json            # TFDA 台灣食品營養資料庫，約 2,181 筆
│   ├── yolo_tfda_mapping.py            # YOLO COCO label 到 TFDA 食品映射與手動搜尋建議
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
│   │   ├── predict_service.py          # YOLO 辨識、營養換算、安全檢查
│   │   ├── profile_service.py          # 使用者 profile、BMR/TDEE/BMI
│   │   └── recommend_service.py        # 規則型雙軌推薦
│   │
│   ├── scripts/
│   │   ├── convert_tfda.py             # TFDA 原始資料轉換
│   │   └── verify_mapping.py           # 驗證 YOLO 到 TFDA 映射
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
    ├── CommandList.md                  # 常用指令
    ├── API_Key_Rotation.md             # Gemini API key 輪替
    └── Version_Comparison_TFDA.md      # TFDA 資料版本差異
```

## 5. 技術棧

| 層級 | 技術 |
|------|------|
| Frontend | Expo 54, React Native 0.81.5, React 19, TypeScript |
| Routing | Expo Router |
| State | Zustand |
| UI / Device | expo-camera, expo-image-picker, expo-location, react-native-svg |
| Backend | Flask, Flask-CORS |
| AI Detection | Ultralytics YOLOv8 Nano |
| Image Processing | OpenCV headless, Pillow, NumPy |
| OCR | Google Gemini Vision API via REST |
| Database | PostgreSQL/Supabase, MongoDB fallback, In-memory fallback |
| Deployment | Render Web Service free plan + Supabase Postgres free plan |

## 6. 後端架構

後端採用 Flask API，`backend/app.py` 負責初始化與路由，主要業務邏輯已拆到 `backend/services/`，資料存取集中在 `backend/repositories/storage.py`。

### 6.1 啟動流程

```txt
載入 .env.local
  -> 若有 DATABASE_URL，連線 PostgreSQL/Supabase
  -> 若無 PostgreSQL 或連線失敗，嘗試 MongoDB
  -> 若 MongoDB 也不可用，退回 In-memory
  -> 載入 Flask app + CORS
  -> 載入 YOLOv8 模型
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
| `GET` | `/health` | 健康檢查，回傳 DB、模型、資料庫、疾病規則載入狀態 |
| `GET` | `/search/food?q=&limit=&user_id=` | 搜尋自訂食品與 TFDA 食品 |
| `GET` | `/food/<food_key>` | 取得單一食品完整資料 |
| `POST` | `/custom-food` | 建立或更新自訂食品 |
| `GET` | `/custom-foods?user_id=` | 列出自訂食品 |
| `POST` | `/ocr/nutrition-label` | 營養標示 OCR |
| `POST` | `/predict` | 影像辨識與營養分析 |
| `GET` | `/user/<user_id>` | 取得使用者 profile |
| `POST` | `/user` | 建立或更新使用者 profile |
| `POST` | `/record` | 新增飲食紀錄 |
| `GET` | `/records/<user_id>?date=` | 查詢飲食紀錄 |
| `GET` | `/history/<user_id>?days=` | 飲食歷史與趨勢彙整 |
| `GET` | `/recommend/<user_id>` | 規則型食物推薦 |
| `GET` | `/healthy-food-recommend/<user_id>` | 附近健康餐點推薦 MVP |
| `POST` | `/calculate/bmr` | BMR/TDEE/BMI 計算 |

## 7. 前端架構

前端使用 Expo Router 的 file-based routing，主畫面由五個 tab 組成。

| Tab | 檔案 | 功能 |
|-----|------|------|
| 首頁 | `frontend/app/(tabs)/index.tsx` | 今日熱量、營養素進度、BMR/TDEE、今日餐點 |
| 辨識 | `frontend/app/(tabs)/scanner.tsx` | 相機拍攝、相簿上傳、YOLO 辨識、TFDA 手動搜尋、營養標示 OCR |
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
| `frontend/lib/scanner.ts` | `/predict`、`/record`、`/search/food`、`/ocr/nutrition-label`、`/custom-food` |
| `frontend/lib/network.ts` | 解析 `EXPO_PUBLIC_API_BASE_URL`、Expo host、localhost、Android emulator fallback |

## 8. 核心資料流程

### 8.1 影像辨識與營養分析

```txt
前端拍照或上傳圖片
  -> base64 image
  -> POST /predict
  -> Flask 解碼圖片
  -> YOLOv8 偵測 label、confidence、bounding box
  -> assess_detection 做信心與泛標籤檢查，容器/餐具類別回傳手動搜尋建議
  -> get_nutrients 三層 fallback
     1. YOLO_TO_TFDA -> nutrition_db_tw.json
     2. nutrition_db.json
     3. UNKNOWN_NUTRIENTS
  -> estimate_weight 依 Bounding Box 面積與 density 估算重量
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

### 8.4 飲食紀錄與趨勢

```txt
前端加入掃描/手動/OCR 食品
  -> POST /record
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
  -> 掃描內建 RESTAURANT_CATALOG
  -> 過濾距離、營業時間、預算、疾病限制
  -> 依預算、距離、熱量契合、低鈉、高蛋白排序
```

## 9. 疾病與過敏原規則

目前疾病規則集中於 `backend/config/disease_rules.json`，由 `backend/services/disease_rule_service.py` 載入後傳入辨識、推薦與健康餐點推薦流程。

| 疾病 | 目前規則 |
|------|----------|
| 糖尿病 | 阻擋高 GI，單餐碳水上限 60g |
| 高血壓 | 單餐鈉上限 600mg |
| 慢性腎臟病 | 單餐蛋白質上限 40g |
| 痛風 | 阻擋高普林標籤，目前為 `hot dog` |
| 高血脂 | 單餐脂肪上限 20g |

過敏原目前由使用者 profile 的 `allergens` 陣列與食品資料中的 `allergens` 陣列比對。

## 10. 已完成功能

### 10.1 後端

- 已完成 Flask API 主服務。
- 已完成 YOLOv8 Nano 模型載入與圖片辨識。
- 已完成 Bounding Box 份量估算與營養素縮放。
- 已完成前端份量校正，掃描結果可調整重量並即時重算營養素。
- 已完成 TFDA 台灣食品營養資料庫整合，約 2,181 筆食品。
- 已完成 YOLO label 到 TFDA 食品的靜態映射。
- 已完成手工營養 DB fallback 與未知食品 fallback。
- 已完成低信心辨識拒絕、需確認標記、泛標籤手動搜尋提示。
- 已完成容器/餐具類 YOLO 標籤的保守拒絕策略與 TFDA 搜尋建議詞。
- 已完成疾病規則與過敏原警示。
- 已完成疾病規則設定化，規則已從 `backend/app.py` 移到 `backend/config/disease_rules.json`。
- 已完成 BMR/TDEE/BMI 計算。
- 已完成使用者 profile CRUD。
- 已完成飲食紀錄新增與查詢。
- 已完成 7 日飲食歷史彙整。
- 已完成 TFDA 與自訂食品搜尋。
- 已完成營養標示 OCR 與自訂食品儲存。
- 已完成規則型推薦。
- 已完成推薦候選擴展，`/recommend` 會納入 TFDA 與使用者自訂食品，並回傳來源統計。
- 已完成歷史飲食偏好加權，`/recommend` 會參考近期紀錄產生 `preference_score` 與偏好原因。
- 已完成附近健康餐點推薦 MVP。
- 已完成 PostgreSQL/MongoDB/In-memory 三層資料儲存 fallback。
- 已完成 Render `PORT` 支援與 `render.yaml`。

### 10.2 前端

- 已完成 Expo Router 五個主要 tab。
- 已完成 Dashboard 熱量環圖、營養素進度與今日餐點顯示。
- 已完成相機拍攝與相簿上傳入口。
- 已完成 scanner 頁面呼叫 `/predict`。
- 已完成辨識結果、拒絕結果、警示與加入今日紀錄流程。
- 已完成 TFDA 手動搜尋與加入紀錄流程。
- 已完成營養標示 OCR、儲存自訂食品、直接加入紀錄流程。
- 已完成 profile 頁面讀取與同步後端使用者資料。
- 已完成疾病與過敏原切換後同步後端。
- 已完成推薦頁呼叫 `/recommend` 與 `/healthy-food-recommend`。
- 已完成定位、預算與附近健康餐點 UI。
- 已完成 history 頁呼叫 `/history` 並顯示趨勢。
- 已完成 API base URL 自動推導與 Render URL 環境變數支援。
- 已完成手機、平板與 web 的基本響應式顯示。

### 10.3 部署與資料

- 已完成 `render.yaml`，可用 Render Blueprint 或 Web Service 部署後端。
- 已完成 Supabase Postgres 連線支援，只要設定 `DATABASE_URL`。
- 已完成 `frontend/.env.local.example`，可指定 Render 後端 URL。
- 後端 `/health` 可檢查 PostgreSQL、MongoDB、模型與資料庫載入狀態。

## 11. 未完成功能與目前限制

> 稽核口徑：以下不是否定已完成的 MVP，而是標出距離「可長期維護、可多人使用、可部署示範」仍缺的部分。

### 11.1 帳號與資料隔離

- 尚未完成正式登入、註冊或身份驗證。
- 目前前端預設使用 `demo_user`，只適合測試，不適合正式多人上線。
- 尚未整合 Supabase Auth。
- 後端 API 目前信任前端傳入的 `user_id`，沒有驗證 requester 是否有權讀寫該使用者資料。

### 11.2 影像辨識準確度

目前 TFDA 營養資料庫約 2,181 筆，已足夠支撐 MVP 的手動搜尋、推薦候選與自訂食品流程；短期不需要再新增大型營養資料庫。主要瓶頸是 YOLOv8 Nano 的 COCO 類別與台灣食物名稱之間的映射，而不是營養資料筆數。

- 目前使用 `yolov8n.pt`，這是 COCO 通用模型，不是專門訓練的台灣食物模型。
- `yolo_tfda_mapping.py` 目前只映射 COCO 原生食物標籤，容器與餐具類別會保守拒絕並提示 TFDA 搜尋詞。
- 混合餐、便當、湯品、台灣小吃的辨識能力有限。
- 份量估算是 2D Bounding Box 面積乘上 density，前端已可人工校正重量；但尚未加入深度感測、參考物或餐盤大小自動校正。
- 份量校正目前只在前端即時重算並隨紀錄保存，尚未形成可回饋模型或校正 density 的學習資料。

### 11.3 營養與醫療安全

- 疾病規則目前為簡化設定，不等同醫療建議。
- 慢性腎臟病等疾病實際還需鉀、磷、鈉、蛋白質分期限制，目前尚未完整規則化。
- TFDA 資料雖已整合，但不是所有食品都已被推薦與搜尋流程完整利用。
- 疾病規則尚未有版本、來源、審核者與醫療免責顯示機制。

### 11.4 推薦引擎

- `/recommend` 目前是規則型與分數型排序，不是真正的個人化口味向量或協同過濾。
- PRD 提到的「餘弦相似度」目前尚未完整實作。
- 使用者點擊、喜好、拒絕尚未形成可學習的推薦模型。
- 推薦候選已納入 TFDA 與使用者自訂食品，排序也會參考歷史飲食紀錄；但目前仍是啟發式加權，尚未達到完整協同過濾或向量推薦。
- 推薦結果尚未記錄使用者是否採納、略過或不喜歡，因此偏好分數只能從飲食紀錄間接推估。

### 11.5 餐廳與地圖資料

- `/healthy-food-recommend` 目前使用 `healthy_food_service.py` 的內建 `RESTAURANT_CATALOG`。
- 尚未串接 Google Maps、外送平台、餐廳公開 API 或正式商家資料源。
- 營業時間與距離計算只是 MVP 邏輯。

### 11.6 前端資料同步

- Dashboard 已會從 `/records` 同步今日紀錄，但初始載入與後端失敗時仍會保留 `constants/mock-data.ts` 的本地預設資料。
- 今日掃描新增採 local-first UX，後端寫入失敗時不會阻止使用者加入本地畫面，也尚未提供重試佇列或同步失敗提示。
- 部分設定項如飲食目標卡片與應用程式設定仍是展示型 UI。
- Profile 頁面目前主要可切換疾病與過敏原；身高、體重、年齡、活動量、目標熱量等尚未提供完整可編輯表單。

### 11.7 測試與品質

- 目前沒有完整自動化測試。
- 後端只有 `backend/test_client.py` 類型的手動整合測試。
- 前端尚未建立 e2e、component test 或 API mock 測試。
- 尚未建立 CI/CD pipeline。
- `frontend/package.json` 只有 `lint` script，沒有正式 `typecheck`、`test`、`build` script。
- repository 目前沒有 `.github/workflows`。

### 11.8 免費部署限制

- Render free plan 會休眠，第一次請求可能明顯變慢。
- Supabase free plan 有容量、連線數與流量限制。
- Gemini API OCR 依賴 API key 與免費額度，可能受速率或配額影響。
- `render.yaml` 與 `DATABASE_URL` 支援已存在，但尚未在文件中記錄實際部署 URL、部署日期與 `/health` 驗證結果。

## 12. Render + Supabase 異地連線準備狀態

目前專案已具備用免費方案做跨網路測試的基本條件。

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
    startCommand: python app.py
    envVars:
      - key: GEMINI_API_KEY
        sync: false
      - key: DATABASE_URL
        sync: false
```

Render 需要設定：

- `DATABASE_URL`：Supabase Postgres connection string。
- `GEMINI_API_KEY`：營養標示 OCR 使用。
- `FLASK_DEBUG=false`：可選，正式測試建議關閉 debug。

### 12.2 Supabase

Supabase 只需要提供 PostgreSQL connection string 給 Render 的 `DATABASE_URL`。

後端啟動後會自動建立：

- `users`
- `records`
- `custom_foods`

### 12.3 前端連線 Render

在 `frontend/.env.local` 設定：

```env
EXPO_PUBLIC_API_BASE_URL=https://your-render-service.onrender.com
```

部署完成後先測：

```txt
GET https://your-render-service.onrender.com/health
```

建議確認：

- `status: ok`
- `postgres: true`
- `model: yolov8n`
- `foods_in_tfda` 大於 0

## 13. 未完成功能製作順序

以下順序依照「先完成本機核心功能與資料一致性，再處理 Render + Supabase 遠端部署」排序。

| 順序 | 功能 | 稽核狀態 | 已具備 | 尚未完善 / 下一步 |
|------|------|----------|--------|------------------|
| 1 | Dashboard 從後端同步今日紀錄 | MVP 可用 | `index.tsx` 會呼叫 `/records` 並重建今日統計 | 後端寫入失敗沒有重試佇列；初始 fallback 仍用 mock data |
| 2 | Dashboard 與 History 資料一致化 | MVP 可用 | `/history` 回傳 `record_count`、總餐數、記錄天數；前端已顯示 | streak、總餐數、今日統計尚未全部由後端統一提供 |
| 3 | 疾病規則設定化 | MVP 可用 | 規則已移至 `backend/config/disease_rules.json`，啟動時載入 | 尚無規則版本、來源、審核流程與管理介面 |
| 4 | 推薦候選擴展到 TFDA 與自訂食品 | MVP 可用 | `/recommend` 已納入 TFDA、自訂食品、來源統計 | 尚未針對 TFDA 類別做更精細的候選篩選與效能索引 |
| 5 | 口味偏好與推薦分數升級 | MVP 可用 | 近期飲食紀錄會產生 `preference_score` 與原因 | 仍是啟發式分數，尚無採納/略過/不喜歡回饋模型 |
| 6 | YOLO/TFDA 映射擴充 | MVP 可用 | 食物 label 已映射；容器/餐具會回傳搜尋建議 | 尚未訓練食物專用模型，混合餐與台灣小吃仍依賴手動搜尋/OCR |
| 7 | 份量估算校正 | MVP 可用 | 掃描結果可調整重量並即時重算營養 | 尚未用校正資料反饋 density，也沒有參考物/深度感測自動校正 |
| 8 | 測試與 CI | 未完成 | 有 `backend/test_client.py` 手動測試；可跑 `npx tsc --noEmit` 與 `npx eslint .` | 尚無 pytest/unit test、前端 test、CI workflow、正式 typecheck script |
| 9 | 使用者身份驗證 | 未完成 | 有 user profile CRUD 與 `user_id` 欄位 | 尚無登入/註冊/token 驗證/資料權限隔離 |
| 10 | Render + Supabase 實測檢查流程 | 未完成 | 有 `render.yaml`、`DATABASE_URL`、`.env.local.example` | 尚未記錄實際部署 URL、Supabase 實測結果與遠端 `/health` 截圖/輸出 |

## 14. 重新標註的未完成清單

以下是依照本次 roadmap 稽核後，仍應視為未完成或待完善的項目。

### 14.1 最高優先級

1. 建立測試與 CI 基礎：新增後端可自動執行的 smoke/unit tests、前端 `typecheck` script、GitHub Actions。
2. 補身份驗證與資料隔離：至少導入登入狀態、token 驗證與 user_id 權限檢查。
3. 完成 Render + Supabase 實測紀錄：部署 URL、環境變數、`/health` 結果、前端連線設定與常見錯誤排除。

### 14.2 中優先級

1. Profile 完整可編輯：身高、體重、年齡、活動量、目標熱量、目標體重、飲食型態。
2. 同步可靠性：掃描/手動/OCR 新增紀錄失敗時要有提示、重試或待同步狀態。
3. 推薦回饋資料：記錄使用者採納、略過、不喜歡，用於後續偏好模型。
4. 健康餐點資料來源：把內建 `RESTAURANT_CATALOG` 移到資料檔或資料庫，未來才方便替換正式 API。

### 14.3 低優先級 / 研究型

1. 食物專用模型或 fine-tuning：改善混合餐、台灣小吃、便當類辨識。
2. 份量自動校正：參考物、餐盤尺度、深度感測或使用者校正資料回饋 density。
3. 疾病規則醫療化：補規則來源、版本、審核者、疾病分期與醫療免責 UI。

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

- 使用者不再共用 `demo_user`。
- 手機或 Web 前端可以連線 Render 後端。
- 使用者 profile、飲食紀錄、歷史趨勢可存在 Supabase。
- 部署前有固定檢查流程，避免 Render/Supabase 設定錯誤。

## 16. 後續閱讀建議

第一次接手本專案建議依序閱讀：

1. `docs/PRD.md`
2. `docs/Project_Architecture_and_Status.md`
3. `README.md`
4. `backend/app.py`
5. `backend/repositories/storage.py`
6. `backend/services/predict_service.py`
7. `frontend/lib/api.ts`
8. `frontend/lib/scanner.ts`
9. `frontend/store/useStore.ts`
10. 目標頁面，例如 `frontend/app/(tabs)/scanner.tsx`
