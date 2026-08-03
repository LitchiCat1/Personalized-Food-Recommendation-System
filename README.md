# 個人化飲食推薦與影像辨識 App

> 健康飲食管理工具，結合 Gemini Vision 食物辨識、資料庫營養對應、個人化營養分析與智慧餐點推薦。

## 📁 專案結構

```
Personalized-Food-Recommendation-System/
├── backend/                  # Flask 後端 API
│   ├── app.py                # 主伺服器入口與 API routes
│   ├── services/             # 辨識、推薦、歷史、OCR、Profile 業務邏輯
│   ├── repositories/         # PostgreSQL/MongoDB/In-memory 資料層
│   ├── nutrition_db.json     # 手工食物營養素資料庫
│   ├── nutrition_db_tw.json  # TFDA 台灣食品營養資料庫
│   ├── requirements.txt      # Python 依賴
│   ├── test_client.py        # API 測試腳本
├── frontend/                 # Expo React Native 前端
│   ├── app/                  # Expo Router 頁面
│   │   ├── (tabs)/           # Tab 導覽頁面
│   │   │   ├── _layout.tsx   # Tab bar 佈局
│   │   │   ├── index.tsx     # 首頁 Dashboard
│   │   │   ├── scanner.tsx   # AI 食物辨識
│   │   │   ├── recommend.tsx # 智慧推薦
│   │   │   ├── history.tsx   # 飲食趨勢
│   │   │   └── profile.tsx   # 個人檔案
│   │   └── _layout.tsx       # Root layout
│   ├── components/           # 可複用元件
│   │   ├── AppContainer.tsx  # 共用頁面容器 (scroll reset + web 支援)
│   │   └── dashboard/        # Dashboard 專用元件
│   ├── lib/                  # 共用 API 與前端型別
│   ├── constants/            # 設計系統 + Mock 資料
│   │   ├── theme.ts          # 色彩/字型/陰影 Token
│   │   └── mock-data.ts      # 假資料
│   ├── hooks/                # 自訂 Hooks
│   │   └── useResponsive.ts  # 響應式 + 平台偵測
│   └── store/                # 狀態管理
│       └── useStore.ts       # Zustand 全域狀態
└── docs/                     # 文件
    ├── PRD.md                # 產品需求文件
    ├── Project_Architecture_and_Status.md # 架構、功能狀態、部署整合文件
    └── Operations_Runbook.md # 指令、部署驗收、key 輪替、工作日誌與事故經驗
```

## 🔑 核心功能狀態

- **Gemini Vision 食物辨識** — 食物名稱/份量初判 + 後端 TFDA/自訂食品資料庫營養對應
- **份量校正** — 掃描結果可人工調整重量並即時重算營養素
- **個人化營養追蹤** — BMR/TDEE 計算、三大營養素 + 鈉/纖維進度
- **安全過濾引擎** — 5 種疾病禁忌規則 + 過敏原比對
- **智慧餐點推薦 MVP** — 安全過濾 + TFDA/自訂食品候選 + 歷史飲食偏好加權
- **Google Places 店家推薦** — 預算 + 定位 + 半徑 + 店家類型搜尋，支援 Google Maps 導航與個人化 AI 店家摘要
- **飲食趨勢分析** — 週熱量柱狀圖 + 營養素均值 + AI 洞察
- **未知食品備援** — TFDA 搜尋 + 自訂食品 + 營養標示 OCR
- **Supabase Auth** — 前端登入/註冊、Bearer token 傳遞、後端 user_id 權限檢查
- **Render + Supabase 部署** — 後端已在 Render 強制 Supabase Auth，資料存於 Supabase Postgres
- **跨平台響應式** — 手機/平板/桌面自適應

目前仍未完成 iOS/Android 原生 Google Maps、完整 CI 自動化測試、session 過期提示與使用者管理 UI；Google Places 店家搜尋、Web Google Maps、個人化 AI 店家摘要、profile 編輯、登出、首次登入 onboarding、Render + Supabase 部署、Supabase Auth 登入與後端強制 user-scoped 權限檢查已完成驗證，GitHub Actions 已有基礎 CI。詳細狀態請以 `docs/Project_Architecture_and_Status.md` 的 roadmap 稽核表為準。

## 部署與驗證狀態

- Render URL：`https://personalized-food-recommendation-system-nq8t.onrender.com`
- Render service id：`srv-d7u2qhdckfvc73ei96l0`
- 部署分支：`v0.0.6`
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
