# 個人化飲食推薦與影像辨識 App

> 健康飲食管理工具，結合 YOLO 食物影像辨識、個人化營養分析與智慧餐點推薦。

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
│   └── yolov8n.pt            # YOLOv8 預訓練模型
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
    ├── CommandList.md        # 常用指令
    ├── API_Key_Rotation.md   # API key 輪替說明
    └── Version_Comparison_TFDA.md # TFDA 資料版本比較
```

## 🔑 核心功能狀態

- **YOLO 食物辨識** — 多目標偵測 + Bounding Box + 份量估算
- **份量校正** — 掃描結果可人工調整重量並即時重算營養素
- **個人化營養追蹤** — BMR/TDEE 計算、三大營養素 + 鈉/纖維進度
- **安全過濾引擎** — 5 種疾病禁忌規則 + 過敏原比對
- **智慧餐點推薦 MVP** — 安全過濾 + TFDA/自訂食品候選 + 歷史飲食偏好加權
- **健康餐點推薦 MVP** — 預算 + 定位 + 時段 + 疾病史 + 剩餘營養素排序附近餐點
- **飲食趨勢分析** — 週熱量柱狀圖 + 營養素均值 + AI 洞察
- **未知食品備援** — TFDA 搜尋 + 自訂食品 + 營養標示 OCR
- **跨平台響應式** — 手機/平板/桌面自適應

目前仍未完成正式登入/註冊、CI 自動化測試、正式餐廳 API 串接，以及 Render + Supabase 實際部署驗證。詳細狀態請以 `docs/Project_Architecture_and_Status.md` 的 roadmap 稽核表為準。

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
| AI Model | YOLOv8 (Ultralytics) |
| Camera | expo-camera + expo-image-picker |
