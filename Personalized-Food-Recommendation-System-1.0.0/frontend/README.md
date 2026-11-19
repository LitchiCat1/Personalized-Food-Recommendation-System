# NutriLens Frontend

本目錄是 NutriLens 的 Expo React Native 前端。

更新：2026-11-17；目前 `v1.0.3`。正式網站由 Windows 後端同源提供，手機經 Tailscale Funnel 的 HTTPS 網址使用。帳號與 session 存於該後端的 SQLite；已移除舊雲端備援網址與 Pages 自動發布。部署見 [本機伺服器說明](../docs/Local_Server_Deployment.md)。

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
python ../backend/app.py --lan
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

如果沒有設定，系統會嘗試自動推導 Expo 開發主機的 IP。`--lan` 僅供需要區網連入的 Expo Go 測試；正式 Funnel 仍使用預設 loopback。

正式網站使用 `npm run build:local` 或 `EXPO_PUBLIC_API_BASE_URL=same-origin`，不自動把失敗請求送到另一台伺服器。`EXPO_PUBLIC_*` 會進入公開 JS，不能放模型／Tavily／USDA server key。

## 登入

帳號存在本機後端的 SQLite 資料庫。預設就要登入；
想跳過登入、直接用 demo_user 測試時，在 `frontend/.env.local` 設：

```env
EXPO_PUBLIC_AUTH_REQUIRED=false
```

後端也要設 `AUTH_REQUIRED=false`（`backend/.env.local`），兩邊要一致。
登入後呼叫 user scoped API 時會附上 `Authorization: Bearer <access_token>`。

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

店家搜尋使用 Google Places，網頁地圖使用獨立的 Maps browser key；既有菜單快取與本地候選可作已標示的備援，未串接 Foodpanda 官方 API。店家菜單模型估算不能冒充實測營養。

## 後續優化方向

以下為一般背景方向，不是本輪新增待辦。目前先依 [營養企劃](../docs/plans/2026-11-13-web-nutrition-fallback.md)驗證一般 scanner 真照片；今日／歷史／趨勢／洞察新版營養 UI 仍延後。171688已審查來源選用／確認／preview在現有服務啟用，Search／enrichment／新來源保存仍關閉；新安裝預設 flags 為 false。

1. 補 session 過期提示、重新登入導引與使用者管理 UI
2. 讓待同步佇列支援網路恢復事件自動重送與詳情頁管理
3. 補強附近店家菜單資料來源與店家資訊品質
4. 把更多資料轉換邏輯從頁面搬到 `lib/` 或 hooks
5. 補前端 component test、e2e test 與更完整的 API mock 測試
