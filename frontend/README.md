# NutriLens Frontend

本目錄是 NutriLens 的 Expo React Native 前端。

## 主要結構

- `app/(tabs)/index.tsx`：首頁 Dashboard
- `app/(tabs)/scanner.tsx`：食物辨識、TFDA 搜尋、營養標示 OCR
- `app/(tabs)/history.tsx`：飲食歷史與趨勢
- `app/(tabs)/recommend.tsx`：智慧推薦
- `app/(tabs)/profile.tsx`：個人檔案與健康條件
- `store/useStore.ts`：全域使用者與本地 UI 狀態
- `lib/api.ts`：前端共用 API 呼叫與回傳型別
- `constants/theme.ts`：設計系統 token

## 啟動方式

```bash
npm install
npx expo start
```

若要用手機上的 Expo Go 測試，後端也必須另外啟動：

```bash
python ../backend/app.py
```

## Expo Go 連線說明

前端現在會依下列順序決定後端位址：

1. `EXPO_PUBLIC_API_BASE_URL`
2. `EXPO_PUBLIC_API_HOST`
3. Expo 執行環境自動推導的 host
4. web/模擬器 fallback

如果小組成員需要手動指定自己的後端位址，可在 `frontend/.env.local` 建立：

```env
EXPO_PUBLIC_API_BASE_URL=http://你的電腦IP:5000
```

如果沒有設定，系統會嘗試自動推導 Expo 開發主機的 IP。

## 開發原則

1. 新的 API 呼叫優先加到 `lib/api.ts`
2. 頁面元件盡量只處理 UI 與狀態，不要重複寫 fetch 細節
3. 掃描流程若變更，優先檢查 `scanner.tsx` 與 `backend/app.py`
4. 若要減少後續上下文成本，應優先把大型頁面繼續拆分成較小元件

## 目前與後端真實串接的頁面

1. `scanner.tsx`
2. `history.tsx`
3. `recommend.tsx`
4. `profile.tsx`

## 健康餐點推薦 MVP

`recommend.tsx` 現在除了基礎營養推薦外，也支援：

1. 使用者輸入單餐預算
2. 手機定位
3. 依時間、距離、預算、疾病史、剩餘營養素做附近健康餐點推薦

目前此功能為 **Foodpanda-like MVP**，使用專案內建的店家/餐點候選資料做排序，尚未直接串接 Foodpanda 官方 API。

## 後續優化方向

1. 補上可編輯的 profile 表單欄位：身高、體重、年齡、活動量、目標熱量、目標體重、飲食型態
2. 補上正式身份驗證與 user_id 權限隔離，目前仍使用 `demo_user` 作為測試入口
3. 補上新增餐點失敗時的重試或待同步狀態，目前 scanner 採 local-first UX
4. 將健康餐點推薦資料源改成可更新的外部資料表或正式 API
5. 把更多資料轉換邏輯從頁面搬到 `lib/` 或 hooks
6. 補上 `typecheck`、測試與 CI workflow
