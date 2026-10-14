# 個人化飲食推薦與影像辨識 App

> 健康飲食管理工具，結合 Gemini Vision 食物辨識、資料庫營養對應、個人化營養分析與附近店家搜尋。

## 📁 專案結構

```
Personalized-Food-Recommendation-System/
├── backend/                  # Flask 後端 API
│   ├── app.py                # 主伺服器入口與 API routes
│   ├── data/                 # 本地靜態與快取資料
│   │   └── restaurant_catalog.json # 測試餐廳與快取菜單資料庫
│   ├── services/             # 辨識、推薦、網頁爬蟲與 AI 解析邏輯
│   │   ├── robust_restaurant_scraper_service.py # AI 菜單爬蟲與估算服務
│   │   ├── google_places_service.py # Google Places API 串接與新版 v1 相容
│   │   ├── healthy_food_service.py # 健康餐點與店家推薦整合服務
│   │   └── ...
│   ├── repositories/         # 資料庫/記憶體資料訪問層
│   │   └── storage.py        # 使用者與飲食紀錄存取 (含自動註冊 Fallback)
│   ├── nutrition_db.json     # 手工食物營養素資料庫
│   ├── nutrition_db_tw.json  # TFDA 台灣食品營養資料庫
│   ├── requirements.txt      # Python 依賴 (含 beautifulsoup4)
│   └── ...
├── frontend/                 # Expo React Native 前端
│   ├── app/                  # Expo Router 頁面
│   │   ├── (tabs)/           # Tab 導覽頁面
│   │   │   ├── index.tsx     # 首頁 Dashboard
│   │   │   ├── scanner.tsx   # AI 食物與營養標示辨識
│   │   │   ├── recommend.tsx # 附近店家搜尋與地圖
│   │   │   ├── history.tsx   # 飲食趨勢與 AI 洞察
│   │   │   └── profile.tsx   # 個人檔案設定
│   │   └── _layout.tsx       # Root layout 與驗證閘道
│   ├── components/           # 可複用 UI 元件
│   │   ├── AuthGate.tsx      # 登入與註冊 Gate（帳號存在本機資料庫）
│   │   ├── AppContainer.tsx  # 響應式佈局容器
│   │   ├── maps/             # 地圖整合元件
│   │   └── ui/               # 設計系統通用按鈕、對話框與導覽
│   ├── lib/                  # API 調用與型別定義
│   │   ├── api.ts            # 前後端 API 串接 (含 Google Places v1)
│   │   └── ...
│   ├── store/                # Zustand 狀態管理
│   │   └── useStore.ts       # 全域核心狀態
│   └── package.json          # 前端依賴與腳本 (v0.0.7)
└── docs/                     # 專案文件
    ├── PRD.md                # 產品需求文件
    ├── Project_Architecture_and_Status.md # 架構與 Roadmap 稽核表
    └── Operations_Runbook.md # 部署與維護指令手冊
```

## 🔑 核心功能狀態

- **Gemini Vision 食物辨識** — 食物名稱/份量初判 + 後端 TFDA/自訂食品資料庫營養對應
- **份量校正** — 掃描結果可人工調整重量並即時重算營養素
- **個人化營養追蹤** — BMR/TDEE 計算、三大營養素 + 鈉/纖維進度
- **安全過濾引擎** — 5 種疾病禁忌規則 + 過敏原比對
- **Google Places 店家推薦** — 預算 + 定位 + 半徑 + 店家類型搜尋，支援 Google Maps 導航與個人化 AI 店家摘要
- **飲食趨勢分析** — 週熱量柱狀圖 + 營養素均值 + AI 洞察
- **飲食紀錄管理** — 日曆區間查詢 + 手動新增今日或歷史紀錄 + 編輯與刪除
- **未知食品備援** — TFDA 搜尋 + 自訂食品 + 營養標示 OCR
- **本機登入** — 暱稱 + 密碼登入/註冊，帳號存在本機 SQLite，Bearer token 傳遞、後端 user_id 權限檢查
- **本機資料庫** — 帳號、飲食紀錄、店家菜單快取都存在一個 SQLite 檔，不需要雲端服務
- **跨平台響應式** — 手機/平板/桌面自適應

目前 Google Places 店家搜尋、Web Google Maps、個人化 AI 店家摘要、個人檔案編輯、登出、本機登入與後端強制 user-scoped 權限檢查均已完成驗證，GitHub Actions 已有基礎 CI。詳細狀態請以 `docs/Project_Architecture_and_Status.md` 的 roadmap 稽核表為準。

## 在本機執行

網站與資料庫都在自己的電腦上，不需要任何雲端服務，也不用安裝資料庫：
資料存在一個 SQLite 檔（預設 `%LOCALAPPDATA%\NutriLens\nutrilens.db`）。

第一次：

```bash
pip install -r backend/requirements.txt
cp backend/.env.local.example backend/.env.local   # 填入 GEMINI_API_KEYS、GOOGLE_PLACES_API_KEY
npm --prefix frontend install
```

### 平常使用（推薦）

先把網站打包一次（改過前端程式才需要重跑）：

```bash
npm --prefix frontend run build:local
```

之後只要開後端，網站和 API 都在同一個網址：

```bash
python backend/app.py
```

打開 http://localhost:5000 註冊帳號就能用。後端的 `/health` 會顯示資料庫檔案的位置。

### 讓其他裝置連進來

預設只有這台電腦連得到。要給別人用：

1. 在 `backend/.env.local` 設一組邀請碼，例如 `SIGNUP_CODE=nutri-2026`。其他裝置註冊時要輸入它；
   沒設的話其他裝置只能登入已經有的帳號、不能註冊（在這台電腦上永遠可以註冊）。
   要讓所有人不用邀請碼就能註冊，改設 `OPEN_SIGNUP=true`。
2. 依對方在哪裡選一種：
   - **同一個 Wi-Fi 或 VPN（例如 Radmin）**：用 `python backend/app.py --lan` 啟動，
     後端會印出「同一個網路的手機或電腦：http://192.168.x.x:5000」，在對方的瀏覽器打開即可。
   - **從外面的網路連（組員在家、老師評審）**：照常 `python backend/app.py`，另開一個終端機執行下面這行，
     把印出來的 `https://….trycloudflare.com` 網址傳給對方；關掉視窗網址就失效，每次執行網址都不同。

     ```bash
     cloudflared tunnel --url http://localhost:5000
     ```

注意：

- 手機的瀏覽器只有在 **https** 網址下才允許用相機拍照和定位。用 `http://192.168.x.x` 連時，請改用「相簿」上傳照片、
  店家頁會改用預設位置；要用相機或定位，請用 cloudflared 網址。
- 不同網址（`localhost:5000`、`192.168.x.x:5000`、cloudflared 網址、`localhost:8081`）在瀏覽器看來是不同網站，
  各自要登入一次。同一個網址開好幾個分頁時，登入、登出會自動同步。
- 只有在這台電腦上才能做的事：清除店家菜單檔案、查看金鑰診斷。
- 展示完就把 cloudflared 關掉。在咖啡店、學校這類公用 Wi-Fi 上不要加 `--lan`。

### 開發時（改前端程式）

開兩個終端機，前端改了會即時更新：

```bash
python backend/app.py                 # 後端 http://localhost:5000
npm --prefix frontend run web         # 網站 http://localhost:8081
```

其他工具：

- 忘記密碼：`python backend/scripts/reset_password.py 小明`（不帶暱稱會列出所有帳號）。
- 備份：後端關掉後，複製上面那個 `.db` 檔就是完整備份。

## Expo Go 測試注意事項

如果使用 `npx expo start --tunnel` 在手機上測試，請注意：

1. Expo tunnel 只處理前端，不會自動幫 Flask backend 建 tunnel
2. 後端必須另外啟動：`python backend/app.py`
3. 前端 API 位址目前支援：
   - `.env.local` 手動指定
   - Expo 執行環境自動推導 host
4. 若手機出現 `Network request failed`，優先檢查：
   - backend 是否啟動
   - 電腦防火牆是否開放 `5000`
   - 手機與電腦是否在可互通網路上

## 🛠 技術棧

| Layer | Technology |
|-------|-----------|
| Frontend | Expo (React Native) + TypeScript |
| State | Zustand |
| Navigation | Expo Router (file-based) |
| Backend | Flask + SQLite（本機檔案）+ MongoDB fallback |
| AI Model | Gemini Vision API + TFDA/custom food DB lookup |
| Camera | expo-camera + expo-image-picker |

## 📝 最近更新紀錄 (v0.0.7e - 拍照菜單測試版)

- **📷 實體菜單拍照上傳與 Gemini Vision AI 個人化推薦**：在「完整菜單」對話框頂部常駐上傳按鈕，支援隨時拍照上傳實體菜單，Gemini Vision 自動讀取品項價格與營養，並自動生成 3~5 項安全推薦。
- **⚖️ 卡路里與三大營養素物理公式驗算**：新增 $P \times 4 + C \times 4 + F \times 9 \approx \text{Calories}$ 校正平衡演算法，解決營養數值計算不合物理邏輯的問題。
- **🛡️ 補齊全套 11 項營養指標與移除樣板預設值**：補齊精緻糖、飽和脂肪、反式脂肪、纖維、鈣與鐵；移除前端 `fiber || 3` 及「AI 摘要」`400 kcal` 硬編碼預設值。
- **🔄 Gemini API 多金鑰動態輪替 (Key Rotation)**：解決每分鐘 15 RPM 限流與 429 錯誤，多組 API Key 自動切換不中斷。
