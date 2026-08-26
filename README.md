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
│   │   ├── AuthGate.tsx      # Supabase 登入與註冊 Gate
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
- **Supabase Auth** — 前端登入/註冊、Bearer token 傳遞、後端 user_id 權限檢查
- **Render + Supabase 部署** — 後端已在 Render 強制 Supabase Auth，資料存於 Supabase Postgres
- **跨平台響應式** — 手機/平板/桌面自適應

目前 Google Places 店家搜尋、Web Google Maps、個人化 AI 店家摘要、個人檔案編輯、登出、Render + Supabase 部署、Supabase Auth 登入與後端強制 user-scoped 權限檢查均已完成驗證，GitHub Actions 已有基礎 CI。詳細狀態請以 `docs/Project_Architecture_and_Status.md` 的 roadmap 稽核表為準。

## 部署與驗證狀態

- Render URL：`https://personalized-food-recommendation-system-nq8t.onrender.com`
- Render service id：`srv-d7u2qhdckfvc73ei96l0`
- 部署分支：`v0.0.7`
- 後端儲存：Supabase Postgres Session Pooler
- 後端 Auth：`SUPABASE_AUTH_REQUIRED=true`
- 權限驗證：無 token 回 `401`，正確 token 回 `200`，跨 `user_id` 回 `403`
- CI：GitHub Actions 後端 syntax check + 前端 typecheck

部署驗收、環境變數、API key 輪替、工作日誌與避免重犯的操作守則記錄於 `docs/Operations_Runbook.md`。

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
| Backend | Flask + PostgreSQL/Supabase + MongoDB fallback |
| AI Model | Gemini Vision API + TFDA/custom food DB lookup |
| Camera | expo-camera + expo-image-picker |

## 📝 最近更新紀錄 (v0.0.7e - 拍照菜單測試版)

- **📷 實體菜單拍照上傳與 Gemini Vision AI 個人化推薦**：在「完整菜單」對話框頂部常駐上傳按鈕，支援隨時拍照上傳實體菜單，Gemini Vision 自動讀取品項價格與營養，並自動生成 3~5 項安全推薦。
- **⚖️ 卡路里與三大營養素物理公式驗算**：新增 $P \times 4 + C \times 4 + F \times 9 \approx \text{Calories}$ 校正平衡演算法，解決營養數值計算不合物理邏輯的問題。
- **🛡️ 補齊全套 11 項營養指標與移除樣板預設值**：補齊精緻糖、飽和脂肪、反式脂肪、纖維、鈣與鐵；移除前端 `fiber || 3` 及「AI 摘要」`400 kcal` 硬編碼預設值。
- **🔄 Gemini API 多金鑰動態輪替 (Key Rotation)**：解決每分鐘 15 RPM 限流與 429 錯誤，多組 API Key 自動切換不中斷。
