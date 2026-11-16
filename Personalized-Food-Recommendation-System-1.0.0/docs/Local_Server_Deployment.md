# Windows 本機伺服器：Tailscale + SQLite

本文件適用於 `v1.0.2`。每台電腦各自安裝 Tailscale、執行後端並保存 SQLite。
目前工作區及已啟動的本機伺服器使用 `v1.0.2`；2026-11-14 已完成 SQLite 備份、
`build:local`，並確認本機與既有 Tailscale 網址的首頁及健康檢查正常。
`v1.0.1` 保留為僅更換 AI 模型的基準版本，不會覆蓋。

## 網址與資料

- 本機網站：http://localhost:5000
- 公開網址：啟用 Funnel 後列出的 `https://<裝置名稱>.<tailnet>.ts.net`。
- SQLite 預設位置：`%LOCALAPPDATA%\NutriLens\nutrilens.db`。
- 自訂資料庫位置：在 `backend/.env.local` 設定 `DATABASE_PATH`，建議使用專案外的完整路徑。
- 備份與日誌：資料庫旁的 `backups`、`logs\backend.log`。
- 本機設定：`backend/.env.local`，不會提交至 Git。
- AI 設定：專案根目錄 `key.txt`，不會提交至 Git。
- USDA FoodData Central API key（選填）：在 `backend/.env.local` 設定
  `USDA_FDC_API_KEY=...`，只由後端讀取；目前僅供受限 API client／replay 使用，
  尚未啟用自動網路補全。專案根目錄的 `USDA KEY.txt` 不會被程式自動讀取，
  也不應放進前端、Expo 變數、提示詞或日誌。未設定時仍使用內附 USDA FNDDS 快照。

帳號驗證預設開啟。請先用本機網址註冊自己的帳號；`OPEN_SIGNUP=false` 且未設定
`SIGNUP_CODE` 時，外部網址只能登入既有帳號，本機仍能註冊。店家搜尋與網頁地圖需
另外設定各自的 Google 金鑰。金鑰與 `.env.local` 不包含在 GitHub 下載內容中。

## 第一次架設

1. 安裝 Python、Node.js 與 Tailscale，登入自己的 Tailscale 帳號。
2. 在包含 `backend`、`frontend` 的專案根目錄執行 `python -m pip install -r backend/requirements.txt`
   與 `npm --prefix frontend ci`。
3. 將 `backend/.env.local.example` 複製為 `backend/.env.local`，填入本機設定；將私下取得的
   完整 `key.txt` 放在專案根目錄，內容包含 Base URL、指定模型 ID 與金鑰。若要使用
   USDA FoodData Central API client，另外在 `backend/.env.local` 填入
   `USDA_FDC_API_KEY`；不要把 `USDA KEY.txt` 改名或放到前端讓它讀取。
4. 執行 `npm --prefix frontend run build:local` 打包網站。
5. 在 Windows 工作排程器建立名稱完全相同的 `NutriLens Backend` 工作，使用執行後端的
   Windows 帳號並設定登入時觸發。程式填入該電腦 `pythonw.exe` 的完整路徑，引數填入
   `"<專案完整路徑>\backend\scripts\run_in_background.py"`，起始位置填入專案完整路徑。
   取消執行時間限制，並依需求允許使用電池時執行。
6. 啟動工作，開啟 http://localhost:5000 並註冊自己的帳號。
7. 執行 `tailscale funnel --bg 5000`。若顯示尚未啟用 Funnel，開啟指令提供的網址，
   登入並完成啟用。指令成功後會列出這台裝置的公開 HTTPS 網址。

不要將 `DATABASE_PATH` 設成空字串，除非確定只要不持久的記憶體儲存。
從不同 Windows 啟動環境執行後端時，請參考 README 的 AppData 導向說明。

## PostgreSQL 歷史測試紀錄

PostgreSQL 17 曾用於隔離的 repository integration test；該測試已完成，結果保留於
`docs/food-nutrition-evaluation/2026-11-14/postgres-live-validation.json`。專案目前採 SQLite-only，
後端不再安裝 PostgreSQL driver、不提供 PostgreSQL runtime／repository 路徑，也不再執行該組測試。
現有 Windows PostgreSQL 服務與其資料目錄不屬於此清理範圍；本次沒有停用、解除安裝或修改它。
請勿把它當成正式部署依賴，也不要假設其監聽位址或防火牆狀態；這些由 Windows 服務設定決定。

## 啟動與停止

GitHub 下載內容的根目錄提供兩個批次檔；本機若多包了一層資料夾，也可放在內層專案的上一層：

- `start-server.bat`：要求啟動工作排程 `NutriLens Backend`。
- `stop-server.bat`：要求停止同一個工作排程，保留 SQLite 資料。

批次檔顯示成功只代表啟動或停止請求已送出；啟動後仍須確認工作狀態、
`http://127.0.0.1:5000/health` 與網站是否正常回應。

批次檔不包含個人的 Python、專案或 SQLite 路徑。資料庫位置沿用各台電腦
後端環境變數與 `backend/.env.local` 的 `DATABASE_PATH`；未設定時使用該帳號的預設位置。
不同人的資料庫位置不會讓批次檔失效。

換電腦使用時，仍須先建立名稱完全相同的 `NutriLens Backend` 工作排程，
並讓該排程指向那台電腦的 Python 與專案。若同學使用不同的排程名稱，
需將兩個批次檔內的名稱一起改成他的名稱。這兩個檔案只控制該後端排程；
Tailscale 沿用先前的背景設定，其他服務不會被停止。

工作排程器的 `NutriLens Backend` 會在指定帳號登入 Windows 時自動啟動後端。
Tailscale 服務隨 Windows 啟動；Funnel 使用背景持久設定。
電腦需要保持開機、連網且未睡眠。後端目前只監聽本機 5000，由 Tailscale 轉送。

手動啟動：

```powershell
Start-ScheduledTask -TaskName "NutriLens Backend"
```

停止：

```powershell
Stop-ScheduledTask -TaskName "NutriLens Backend"
```

重新啟動（先停止，確認工作排程器顯示已停止，再啟動）：

```powershell
Stop-ScheduledTask -TaskName "NutriLens Backend"
Start-ScheduledTask -TaskName "NutriLens Backend"
```

確認狀態：

```powershell
Get-ScheduledTask -TaskName "NutriLens Backend"
Invoke-RestMethod http://127.0.0.1:5000/health
& "C:\Program Files\Tailscale\tailscale.exe" funnel status
```

不要在背景排程已執行時另外啟動 `python backend/app.py`，避免佔用同一個埠。

## 更新專案

1. 停止 `NutriLens Backend` 工作，確認已停止，再切換分支或更新程式。
2. 保留原本完整路徑、`backend/.env.local`、`key.txt` 與既有 SQLite 檔案；確認目前為要測試的 `v1.0.2`。
3. 在目前專案內使用實際部署環境執行 `python backend/scripts/backup_db.py` 備份。
4. 依賴有變動時更新 Python／Node 套件。
5. 前端有變動或使用全新下載的原始碼時，執行 `npm --prefix frontend run build:local`。
6. 啟動工作，再確認本機網站與 Tailscale 網址。

排程使用該電腦 `pythonw.exe` 的完整路徑，並以本專案 `backend/scripts/run_in_background.py`
的完整路徑啟動。搬動專案或變更 Python 安裝位置後，需要修改工作排程的動作與起始位置。
排程執行的是這個路徑當下的程式，不會固定在某個 Git 分支；切換分支或修改內容後，
下次啟動就會使用更新後的檔案。沿用原路徑時，從 `v1.0.1` 改用 `v1.0.2`
不需要重新設定工作排程、Tailscale 或 SQLite。
