# Operations Runbook

> 最後更新：2026-05-07

本文件整合原本分散的操作指令、部署驗收、API key 輪替與事故經驗。後續維運與部署流程以本文件為準。

## 1. 安全原則

- 不要把 Render API key、Supabase database password、Supabase `service_role` key、Gemini API key 寫入 git tracked 檔案。
- 不要把 secrets 貼到聊天、issue、PR、README、docs 或 commit message。
- 只要 key/password/token 曾貼到聊天或日誌，就視為 compromised，應立即撤銷或輪替。
- public publishable key 可用於前端 public env，但仍避免不必要地重複散佈。
- 驗收時不要輸出 access token；只輸出狀態碼、必要 user id 與非敏感摘要。

## 2. 常用開發指令

### 2.1 安裝依賴

```powershell
cd frontend
npm install
```

### 2.2 Git

```powershell
git pull
git branch
git switch <branch-name>
git switch -c <new-branch-name>
```

提交前先確認狀態與 diff：

```powershell
git status --short
git diff --check
```

### 2.3 前端開發

```powershell
cd frontend
npm run typecheck
npm run web -- --port 8083
```

Expo tunnel 測試：

```powershell
cd frontend
npx expo start --tunnel
```

清除快取：

```powershell
cd frontend
npx expo start -c
```

### 2.4 後端輕量檢查

避免一次啟動耗時模型或長時間無輸出，優先跑短檢查：

```powershell
python -m py_compile "backend/app.py" "backend/services/auth_service.py" "backend/repositories/storage.py" "backend/services/disease_rule_service.py" "backend/services/history_service.py" "backend/services/food_analysis_service.py" "backend/services/vision_food_service.py" "backend/services/healthy_food_service.py"
```

食物辨識目前採 Gemini Vision 初判，再由後端查 TFDA/自訂食品資料庫取得營養值；不再部署本機影像模型。

### 2.5 一週飲食測試資料

不必真的記錄一星期，`backend/scripts/seed_week_test_data.py` 會一次灌入 7 天飲食紀錄，
再依 `calculate_pdf_daily_targets` 的疾病別條件逐日檢查是否達標。營養值全部取自
`nutrition_db_tw.json` (TFDA) 依克數換算，和 App 自己查到的數字一致。

```powershell
python backend/scripts/seed_week_test_data.py --scenario mixed
```

常用參數：

- `--source curated|recommend` — `curated` 用內建台灣家常菜單（營養值查 TFDA）；`recommend` 直接抓 `/healthy-food-recommend` 的推薦餐點，依 match_score 輪流分攤到七天三餐，用來測「整週照推薦吃能不能達標」
- `--budget` / `--lat` / `--lng` / `--radius-km` / `--category` — `--source recommend` 查詢推薦時的參數
- `--scenario mixed|compliant|over` — `--source curated` 專用：混合週（5 天達標 + 2 天破戒）、全達標、全超標
- `--profile healthy|diabetes|hypertension|kidney_disease|gout|hyperlipidemia` — 一併設定使用者健康條件
- `--skip-profile` — 沿用後端既有 profile，不覆蓋
- `--dry-run` — 不寫入後端，直接在本機算出每日達標結果（調菜單份量時用）
- `--clear` — 刪除同情境先前灌入的紀錄
- `--report out.json` — 輸出完整逐日結果
- `--api-url` / `--user-id` / `--token` — 打雲端後端時使用（`--token` 為 Supabase access token）

`client_record_id` 是 `seed_<情境或 recommend>_<日期>_<餐別>`，重跑只會補上新的一天，不會產生重複紀錄。
沒有設定 `DATABASE_URL` 時後端使用記憶體儲存，重啟 Flask 資料就會消失，需要重跑腳本。

`--source recommend` 的兩個已知限制：推薦 API 每道餐點只回傳熱量、蛋白質、碳水、脂肪、鈉，膳食纖維／精緻糖／飽和脂肪／反式脂肪不在 payload 裡，只能記 0，所以纖維一定不達標；另外當半徑內沒有營業中的店家時，`build_healthy_food_recommendations` 會啟用開發用 fallback，把全部店家搬到使用者附近並一律視為營業中，此時推薦清單不代表真實可買到的餐點。


### 2.6 在 Render 上跑一週測試

Render 後端 `SUPABASE_AUTH_REQUIRED=true`，每個請求都要帶 Supabase access token，
而且 `require_user_access` 只允許存取 token 擁有者自己的資料。token 一律走環境變數，
不要寫在指令列（會留在 shell 歷史）。

```powershell
$env:NUTRILENS_API_URL = "https://<backend>.onrender.com"
$env:NUTRILENS_ACCESS_TOKEN = "<在 App 登入後取得的 access token>"
python backend/scripts/seed_week_test_data.py --source recommend --skip-profile
```

沒給 `--user-id` 時，腳本會依序取 `NUTRILENS_TEST_USER`、access token 的 `sub`、`demo_user`；
在 Render 上請讓它自動用 token 的 `sub`，否則會被 403 擋掉。
已經在 App 完成 onboarding 的帳號建議加 `--skip-profile`，避免測試腳本覆寫真實的身高體重與疾病設定。

與本機環境的差異：

- Render 跑在 UTC。`APP_UTC_OFFSET_HOURS=8` 已寫進 `render.yaml`，「今天」與店家營業時間才會用台灣時間判斷。
- Render 有 `DATABASE_URL`，資料寫進 Postgres 會**永久保留**（本機是記憶體，重啟就沒了）。
  測完請務必用同樣參數加 `--clear` 清掉，否則測試資料會混進真實飲食紀錄。
- 反式脂肪單位、腎臟病蛋白質方向、UTC 時區三項修正都在 v0.0.8d；
  Render 服務要切到該分支並重新部署後才會生效。


## 3. 本機環境變數

### 3.1 後端

後端啟動時會讀取：

- `./.env.local`
- `backend/.env.local`

建議統一使用專案根目錄 `.env.local`。

常用 key：

```env
DATABASE_URL=postgresql://...
GEMINI_API_KEYS=key1,key2,key3
GEMINI_API_KEY=single-key-fallback
GEMINI_MODELS=gemini-2.5-flash,gemini-2.0-flash
DISEASE_RULES_PATH=backend/config/disease_rules.json
RESTAURANT_CATALOG_PATH=backend/data/restaurant_catalog.json
SUPABASE_AUTH_REQUIRED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
GOOGLE_PLACES_API_KEY=your-google-maps-and-places-key
APP_UTC_OFFSET_HOURS=8
```

`RESTAURANT_CATALOG_PATH` 可省略；未設定時後端會使用 `backend/data/restaurant_catalog.json`。若要測試替代餐廳資料源，請指定 JSON 檔路徑，不要把 API token 或私有商家資料寫入 repo。

`APP_UTC_OFFSET_HOURS` 可省略；未設定時預設 8（台灣 UTC+8，無日光節約時間）。伺服器（Render）跑在 UTC，但飲食紀錄的 timestamp、店家 `open_hours` 都是本地時間，因此「今天吃了多少」「店家現在有沒有開」一律以這個偏移量換算。換地區部署時改這個值即可，不需要 tz database。

`DISEASE_RULES_PATH` 可省略；未設定時後端會使用 `backend/config/disease_rules.json`。替代規則檔必須包含 `rule_version`、`review_status`、`last_reviewed`、`reviewed_by`、`evidence_level`、`references` 與 `medical_disclaimer`，否則啟動時會失敗。

### 3.2 前端

前端使用 `frontend/.env.local`，此檔已被 git ignore。

```env
EXPO_PUBLIC_API_BASE_URL=https://personalized-food-recommendation-system-nq8t.onrender.com
EXPO_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
GOOGLE_PLACES_API_KEY=your-google-maps-and-places-key
```

未設定 Supabase public env 時，前端會維持 demo 模式；正式 Render 驗收應設定 Supabase public env。

本專案目前使用單一 `GOOGLE_PLACES_API_KEY`。Frontend build script 會把它注入成 Expo 可讀的 Google Maps public env，因此該 key 會出現在前端 bundle；必須在 Google Cloud Console 限制 Maps JavaScript API 與 Places API 使用範圍，不要寫入 repo 或聊天。

## 4. Gemini API Key 輪替

本專案使用 Gemini API 進行食物影像辨識與營養標示 OCR。Render 部署環境建議使用 `GEMINI_API_KEYS` 放多組 key 做輪替；本機可使用單一 `GEMINI_API_KEY` 或同樣使用 `GEMINI_API_KEYS`。模型可用 `GEMINI_MODELS` 以逗號分隔設定候選順序；未設定時會依序嘗試 `gemini-2.5-flash`、`gemini-2.0-flash`、`gemini-1.5-flash`。

單一 key：

```env
GEMINI_API_KEY=your-key
```

多 key 輪替：

```env
GEMINI_API_KEYS=key1,key2,key3
```

如果兩者同時存在，後端會優先使用 `GEMINI_API_KEYS`，並保留 `GEMINI_API_KEY` / `GOOGLE_API_KEY` 作為 fallback。輪替會在 Gemini 回傳 `401`、`403`、`429`、`500`、`502`、`503`、`504` 時嘗試下一組 key。

輪替步驟：

1. 到 Google AI Studio 產生新的 Gemini API key。
2. 本機開發：更新專案根目錄 `.env.local`。
3. Render 部署：更新 Web Service 的 `GEMINI_API_KEYS` environment variable。
4. 儲存環境變數並重新部署後端。
5. 測試 `POST /ocr/nutrition-label` 或至少確認後端啟動無 env 錯誤。

## 5. Render + Supabase 部署設定

- Backend Render URL：由 Blueprint 建立 `personalized-food-recommendation-backend` 後由 Render 指派，每次部署各自不同
- Frontend Render Static Site：由 Blueprint 建立 `personalized-food-recommendation-frontend`，部署後使用 Render 指派網址
- Render service id：以部署者自己的 Render Dashboard 顯示為準
- 部署分支：`v0.0.8d`
- 後端儲存：Supabase Postgres Session Pooler
- 後端 Auth：`SUPABASE_AUTH_REQUIRED=true`

Backend Render URL 是後端 API，不是前端網頁。瀏覽器打開根路徑 `/` 只會看到 API 狀態 JSON；正式操作畫面請使用 frontend static site 網址。

Render 需要設定：

```env
DATABASE_URL=postgresql://...
GEMINI_API_KEYS=key1,key2,key3
FLASK_DEBUG=false
SUPABASE_AUTH_REQUIRED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
GOOGLE_PLACES_API_KEY=your-google-maps-and-places-key
```

`DATABASE_URL` value 必須直接以 `postgresql://` 開頭，不要包含 `DATABASE_URL=` 前綴。

Blueprint 首次建立時，`DATABASE_URL`、`GEMINI_API_KEYS`、`SUPABASE_URL`、`SUPABASE_PUBLISHABLE_KEY` 與 `GOOGLE_PLACES_API_KEY` 都只需在 Backend Web Service 輸入一次。Frontend 會透過 Blueprint service reference 取得可公開的 build-time 值，不需要重複輸入。Frontend API 位址也會自動引用同次部署建立的 backend 公開 hostname，不可再固定填入原專案網址。

`render.yaml` 已設定 frontend build：`npm ci && npm run build:web`，publish path：`dist`，並加上 SPA rewrite `/* -> /index.html`。
Blueprint 會把 `SUPABASE_URL`、`SUPABASE_PUBLISHABLE_KEY` 與 `GOOGLE_PLACES_API_KEY` 引用到 Frontend Static Site，並把前後端 Auth flag 固定為 `true`。若缺少 Supabase URL 或 publishable key，正式 Render 前端會顯示設定錯誤並停止載入 demo profile。

## 6. 部署後驗收流程

### 6.1 Render deploy 狀態

```powershell
render deploys list srv-d7u2qhdckfvc73ei96l0 --output json
```

latest deploy 應為 `live`。

### 6.2 Health check

根路徑可讀性檢查：

```powershell
curl https://personalized-food-recommendation-system-nq8t.onrender.com/
```

應回傳 API 狀態 JSON。若 `/` 回 `404`，通常代表後端仍在舊版部署；不代表 `/health` 或 API 壞掉。

健康檢查：

```powershell
curl https://personalized-food-recommendation-system-nq8t.onrender.com/health
```

應確認：

- `status: ok`
- `postgres: true`
- `foods_in_tfda` 大於 0
- `disease_rules` 大於 0
- `restaurants` 大於 0

### 6.3 Auth 權限驗收

驗收標準：

- `GET /user/<user_id>` 不帶 Authorization 應回 `401`。
- `GET /user/<user_id>` 帶正確 Supabase Bearer token 應回 `200`。
- `GET /user/demo_user` 帶其他使用者 token 應回 `403`。

已驗證結果：

- `/health`：`200`
- 未帶 token：`401`
- 正確 token + 自己的 `user_id`：`200`
- 正確 token + 其他 `user_id`：`403`

自動化 smoke script：

```powershell
$env:SMOKE_API_BASE_URL="https://personalized-food-recommendation-system-nq8t.onrender.com"
$env:SMOKE_USER_ID="<supabase-auth-user-id>"
$env:SMOKE_ACCESS_TOKEN="<supabase-access-token>"
$env:SMOKE_FORBIDDEN_USER_ID="demo_user"
python backend/scripts/smoke_render_auth.py
```

注意：

- 不要把 `SMOKE_ACCESS_TOKEN` 寫入 repo、docs、CI logs 或聊天內容。
- CI 若要跑此腳本，使用 GitHub Actions secrets 注入環境變數，且只輸出狀態碼與非敏感摘要。
- 缺少必要環境變數時腳本會以 exit code `2` 跳過，不會使用任何硬編碼 token。

### 6.4 前端回歸驗收

Render Static Site 驗收：

```powershell
curl https://<frontend-static-site>.onrender.com
```

瀏覽器打開 frontend 網址後，應看到 NutriLens App 畫面。若登入頁沒有出現，確認 `EXPO_PUBLIC_SUPABASE_URL` 與 `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 是否已在 frontend static site 設定。

本機驗收：

```powershell
cd frontend
npm run typecheck
npm run build:web
npm run web -- --port 8083
```

確認：

- AuthGate 顯示登入/註冊。
- 測試帳號可登入。
- 登入後進入首頁。
- 首頁可同步後端今日紀錄。
- 推薦、趨勢、Profile 頁不因 401/403 卡死。

## 7. 2026-05-07 工作日誌摘要

本次完成 Render + Supabase 部署收斂，讓後端 user-scoped API 改為強制 Supabase Auth Bearer token 驗證，並確認前端登入後仍可正常使用。

### 7.1 已完成

- Supabase Postgres 已透過 Session Pooler 供後端使用。
- 後端已支援 Gemini 多 API key 輪替。
- GitHub Actions CI 已建立。
- 後端 Supabase Auth 驗證已在 Render 強制啟用。
- 前端 Supabase Auth 已完成基本登入/註冊與 token 傳遞。
- 首次登入若後端無 profile，前端會導向 onboarding，要求使用者先填基本資料，不再自動建立預設 profile。
- Expo Web SSR 的 Supabase storage 初始化錯誤已修正。

### 7.2 重要提交

- `48fe93e support Gemini API key rotation`
- `428d9db add GitHub Actions CI`
- `efc4595 update CI to Node 24`
- `260f18f document deployment status`
- `fc8c8c4 add optional Supabase auth checks`
- `54aec9a add frontend Supabase auth`
- `0423dab fix Supabase auth storage on web`
- `58e2f04 create profile on first auth login`
- `24442df require Supabase auth on Render`
- `24bf2c4 document auth deployment lessons`

## 8. 經驗總結與避免重犯

### 8.1 Render `DATABASE_URL` 格式

Render env value 只填 value，不要包含 `KEY=` 前綴。錯誤示例是把 value 填成 `DATABASE_URL=postgresql://...`，這會導致 invalid dsn。

### 8.2 Render env 更新方式

Render CLI v2.16.0 可查服務、deploy、logs，但沒有可用的 env var update 子命令。自動化 env var 更新應優先使用 Render API/MCP；若用 Dashboard，人工確認比瀏覽器工具自動化可靠。

### 8.3 不用不穩定 UI 自動化 secrets

Dashboard env 表格是動態 UI，button/input index 不穩定，且刪除按鈕可能缺少明確文字或 aria label。若 UI 操作出現空白列或不可辨識刪除按鈕，應立即取消/重新載入，不要硬存。

### 8.4 Expo Web SSR 與 browser-only API

Web server render 階段沒有 `window`。Supabase Web storage 必須使用 `typeof window !== 'undefined'` guard；Native 平台才使用 AsyncStorage。

### 8.5 Auth user id 與 profile provisioning

正式 Auth 後不可依賴 `demo_user`。登入成功後應以 token subject 作為唯一 `user_id`；若 profile 不存在，前端會導向 onboarding，完成基本資料後才建立後端 profile 並進入 App。

### 8.6 Supabase email rate limit

Supabase Auth 測試註冊可能遇到 `email rate limit exceeded`。遠端驗收優先使用既有測試帳號；若要測註冊，先調整 Auth 設定或準備可收信測試帳號。

### 8.7 Secrets 外洩處理

即使沒有寫入檔案，只要 secret 出現在聊天內容，就視為外洩。曾貼出的 Render API key、Gemini API keys、Supabase database password 應立即輪替或撤銷。
