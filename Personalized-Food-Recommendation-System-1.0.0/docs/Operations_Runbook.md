# NutriLens 維運手冊

更新：2026-11-17；適用 `v1.0.3`。正式環境採 Windows 單一 Waitress 程序、Tailscale Funnel HTTPS 與一份 SQLite。網站靜態檔由同一後端提供；GitHub 保存版本並執行 CI。詳細第一次架設、排程、來源安裝與回復方式以 [Windows 部署說明](Local_Server_Deployment.md)為準。

## 設定與資料

- `backend/.env.local`：`DATABASE_PATH`、`AUTH_REQUIRED=true`、註冊與伺服器金鑰設定。非空 `DATABASE_URL` 會拒絕啟動；不會改連其他資料庫。
- `frontend/.env.local`：僅公開建置參數，如 `EXPO_PUBLIC_API_BASE_URL=same-origin`、`EXPO_PUBLIC_AUTH_REQUIRED=true` 及經核可的前端功能開關。修改後須重建。
- 專案根目錄 `key.txt`：AI 中轉 Base URL、模型與金鑰池；也可用 `AI_RELAY_KEYS_FILE` 或完整三組 `AI_BASE_URL`／`AI_MODEL`／`AI_API_KEYS` 覆寫。中轉設定存在時，呼叫失敗不改用其他 provider。
- `USDA_FDC_API_KEY`、`TAVILY_API_KEY` 與 `NUTRITION_AUTHORITY_SECRET` 只放後端。根目錄的 `USDA KEY.txt`／`TavilyKey.txt` 是私下交付資料，正常 app 不會自動載入。
- SQLite 與備份放專案外；跨 Windows 啟動環境時選 AppData 外的絕對路徑。`DATABASE_PATH=` 僅供明確的暫存測試，重啟會失去資料；沒有 MongoDB 備援。

## 啟動、停止與備份

在含 `backend`／`frontend` 的專案目錄執行；啟動與停止是分開使用的指令：

```powershell
Start-ScheduledTask -TaskName "NutriLens Backend"
```

```powershell
Stop-ScheduledTask -TaskName "NutriLens Backend"
```

```powershell
python backend/scripts/backup_db.py
python backend/scripts/backup_db.py --list
```

下載目錄外層的 `start-server.bat`／`stop-server.bat` 呼叫同一排程。不要建立第二個後端指向同一份正式資料。資料庫備份用既有 SQLite backup 工具，不直接複製仍在使用的 DB／WAL。還原前須先停止後端，並確認不會覆蓋備份之後的新紀錄。

## 更新與驗證

先備份 SQLite、原設定及目前 `frontend/dist`，再驗證修改。在暫存目錄匯出前端，避免直接覆寫運行中的網站；驗證後才依部署說明切換、重啟同一排程。

```powershell
python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build:local -- --output-dir ../tmp/reviewed-web-export
```

完整後端回歸從 `backend` 目錄執行 `python -m pytest -q tests`（需開發環境的 pytest），或 CI 的 `python -m unittest discover -s tests`。單元測試使用隔離記憶體／暫存 SQLite，不讀正式 `.env.local`。不要把真實 provider 呼叫當成每次回歸的前提。

驗收本機與既有公開 `/health`：版本、`started_at`、`database=sqlite`、`auth_required=true`；公開回應不應含資料庫路徑。再比對 `/scanner` 與其 entry JS 的本機／公開／磁碟雜湊。`ai_relay_enabled` 只代表載入設定，不證明遠端可連。可選的 `NUTRILENS_DEPLOYED_BRANCH`／`NUTRILENS_DEPLOYED_COMMIT` 由管理者明確提供；缺少時顯示 `local`，不讀取已廢止平台的環境變數。

## 營養功能開關

第七十八批已發布171688一般帶皮生蘋果的系統選用、使用者明確確認與營養預覽。三個後端開關與三個前端公開開關成對配置，且需明確來源設定、已安裝 active policy 及 server-only USDA key。預設新安裝仍關閉，不能把目前服務的設定複製成全食品自動啟用。

FDC Search、raw Detail HTTP、profile accept 與自動 enrichment 仍關閉，Tavily registry 為空。既有飲食紀錄功能仍可使用；新 FDC 來源接入餐點保存尚未放行。來源撤回不會因重啟復活。具體旗標與准入矩陣見 [限定發布](Local_Server_Deployment.md#單一蘋果來源預覽已發布)與 [企劃書第19節](plans/2026-11-13-web-nutrition-fallback.md#19-實測後的放行決定)。

## 常見問題

- 連不上：確認原排程、5000 listener、後端日誌及 Tailscale Funnel；不要因重啟不順就新增服務或換資料庫。
- 手機不能開相機：使用既有 HTTPS scanner；一般區網 HTTP 不具備相機安全環境。
- 外部不能註冊：依 `SIGNUP_CODE`／`OPEN_SIGNUP` 設定處理；未明確開放時，外部預設不可註冊，本機可註冊。
- 密碼遺失：在伺服器本機執行 `python backend/scripts/reset_password.py <暱稱>`，依互動提示重設；舊 session 失效。
- 模型失敗：檢查私密的後端金鑰來源、權限與額度。禁止把金鑰、原始 provider 回應或私密日誌提交到 Git。
- 營養缺漏：保留未知值與待確認狀態，不用搜尋結果反向推斷照片菜種，不以數字是否齊全提高辨識信心。

舊雲端操作、事故與提交紀錄已移至 [歷史手冊](Operations_Runbook.historical.md)，不可當作目前部署指令。
