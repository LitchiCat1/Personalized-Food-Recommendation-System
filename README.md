# 個人化飲食推薦與影像辨識 App

> 健康飲食管理工具，結合 YOLO 食物影像辨識、個人化營養分析與智慧餐點推薦。

## 📁 專案結構

```
Personalized-Food-Recommendation-System/
├── backend/                  # Flask 後端 API
│   ├── app.py               # 主伺服器 (YOLO + 營養計算 + 推薦引擎)
│   ├── nutrition_db.json     # 食物營養素資料庫
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
│   ├── constants/            # 設計系統 + Mock 資料
│   │   ├── theme.ts          # 色彩/字型/陰影 Token
│   │   └── mock-data.ts      # 假資料
│   ├── hooks/                # 自訂 Hooks
│   │   └── useResponsive.ts  # 響應式 + 平台偵測
│   └── store/                # 狀態管理
│       └── useStore.ts       # Zustand 全域狀態
└── docs/                     # 文件
    ├── PRD.md                # 產品需求文件
    └── CommandList.md        # 常用指令
```

## 🔑 核心功能

- **YOLO 食物辨識** — 多目標偵測 + Bounding Box + 份量估算
- **個人化營養追蹤** — BMR/TDEE 計算、三大營養素 + 鈉/纖維進度
- **安全過濾引擎** — 5 種疾病禁忌規則 + 過敏原比對
- **智慧餐點推薦** — 雙軌推薦 (安全過濾 + 口味匹配)
- **飲食趨勢分析** — 週熱量柱狀圖 + 營養素均值 + AI 洞察
- **跨平台響應式** — 手機/平板/桌面自適應

## 🛠 技術棧

| Layer | Technology |
|-------|-----------|
| Frontend | Expo (React Native) + TypeScript |
| State | Zustand |
| Navigation | Expo Router (file-based) |
| Backend | Flask + MongoDB |
| AI Model | YOLOv8 (Ultralytics) |
| Camera | expo-camera + expo-image-picker |
