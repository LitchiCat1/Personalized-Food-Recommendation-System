# NutriLens Frontend

本目錄是 NutriLens 的 Expo React Native 前端。

## 主要結構

- `app/(tabs)/index.tsx`：首頁 Dashboard
- `app/(tabs)/scanner.tsx`：食物辨識、TFDA 搜尋、營養標示 OCR
- `app/(tabs)/history.tsx`：飲食歷史與趨勢
- `app/(tabs)/recommend.tsx`：附近店家搜尋與地圖
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

## Supabase Auth

若要啟用正式登入/註冊與後端 `user_id` 權限隔離，需在 `frontend/.env.local` 設定：

```env
EXPO_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key
EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED=true
```

三項皆設定後，前端會顯示 Supabase Auth 登入/註冊畫面，並在呼叫 user scoped API 時附上 `Authorization: Bearer <access_token>`。若 `EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED` 不是 `true`，前端會維持 demo 模式；正式環境應與後端 `SUPABASE_AUTH_REQUIRED` 使用相同值。

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

## 附近店家搜尋

`recommend.tsx` 支援：

1. 使用者輸入單餐預算
2. 手機定位
3. 依距離、預算與店家類型搜尋附近店家

目前此功能為 **Foodpanda-like MVP**，使用專案內建的店家/餐點候選資料做排序，尚未直接串接 Foodpanda 官方 API。

## 後續優化方向

1. 補 session 過期提示、重新登入導引與使用者管理 UI
2. 讓待同步佇列支援網路恢復事件自動重送與詳情頁管理
3. 補強附近店家菜單資料來源與店家資訊品質
4. 把更多資料轉換邏輯從頁面搬到 `lib/` 或 hooks
5. 補前端 component test、e2e test 與更完整的 API mock 測試
