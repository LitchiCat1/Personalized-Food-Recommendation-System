# Windows 本機伺服器：Tailscale + SQLite

本文件適用於 v1.0.1。每台電腦各自安裝 Tailscale、執行後端並保存 SQLite。

## 網址與資料

- 本機網站：http://localhost:5000
- 公開網址：啟用 Funnel 後列出的 `https://<裝置名稱>.<tailnet>.ts.net`。
- SQLite 預設位置：`%LOCALAPPDATA%\NutriLens\nutrilens.db`。
- 自訂資料庫位置：在 `backend/.env.local` 設定 `DATABASE_PATH`，建議使用專案外的完整路徑。
- 備份與日誌：資料庫旁的 `backups`、`logs\backend.log`。
- 本機設定：`backend/.env.local`，不會提交至 Git。
- AI 設定：專案根目錄 `key.txt`，不會提交至 Git。

帳號驗證預設開啟。請先用本機網址註冊自己的帳號；`OPEN_SIGNUP=false` 且未設定
`SIGNUP_CODE` 時，外部網址只能登入既有帳號，本機仍能註冊。店家搜尋與網頁地圖需
另外設定各自的 Google 金鑰。金鑰與 `.env.local` 不包含在 GitHub 下載內容中。

## 第一次架設

1. 安裝 Python、Node.js 與 Tailscale，登入自己的 Tailscale 帳號。
2. 在包含 `backend`、`frontend` 的專案根目錄執行 `python -m pip install -r backend/requirements.txt`
   與 `npm --prefix frontend ci`。
3. 將 `backend/.env.local.example` 複製為 `backend/.env.local`，填入本機設定；將私下取得的
   完整 `key.txt` 放在專案根目錄，內容包含 Base URL、指定模型 ID 與金鑰。
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

## 啟動與停止

GitHub 下載內容的根目錄提供兩個批次檔；本機若多包了一層資料夾，也可放在內層專案的上一層：

- `start-server.bat`：要求啟動工作排程 `NutriLens Backend`。
- `stop-server.bat`：要求停止同一個工作排程，保留 SQLite 資料。

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

1. 在目前專案內執行 `python backend/scripts/backup_db.py` 備份。
2. 停止 `NutriLens Backend` 工作。
3. 更新程式，保留原本完整路徑、`backend/.env.local`、`key.txt` 與外部資料庫。
4. 依賴有變動時更新 Python／Node 套件。
5. 前端有變動或使用全新下載的原始碼時，執行 `npm --prefix frontend run build:local`。
6. 啟動工作，再確認本機網站與 Tailscale 網址。

排程使用該電腦 `pythonw.exe` 的完整路徑，並以本專案 `backend/scripts/run_in_background.py`
的完整路徑啟動。搬動專案或變更 Python 安裝位置後，需要修改工作排程的動作與起始位置。
單純更新程式內容、沿用原路徑時，不需要重新設定 Tailscale 或 SQLite。
