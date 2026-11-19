# Windows 本機伺服器：Tailscale + SQLite

本文件適用於目前的 `v1.0.3` 工作樹。每台電腦各自安裝 Tailscale、執行後端並保存 SQLite。
目前工作區及已啟動的本機伺服器沿用同一個 SQLite 部署方式；更新程式前仍須先備份資料庫、
重建前端並確認本機與既有 Tailscale 網址的健康檢查正常。

## 網址與資料

- 本機網站：http://localhost:5000
- 公開網址：啟用 Funnel 後列出的 `https://<裝置名稱>.<tailnet>.ts.net`。
- SQLite 預設位置：`%LOCALAPPDATA%\NutriLens\nutrilens.db`。
- 自訂資料庫位置：在 `backend/.env.local` 設定 `DATABASE_PATH`，建議使用專案外的完整路徑。
- 備份與日誌：資料庫旁的 `backups`、`logs\backend.log`。
- 本機設定：`backend/.env.local`，不會提交至 Git。
- AI 設定：專案根目錄 `key.txt`，不會提交至 Git。
- USDA FoodData Central API key（選填）：在 `backend/.env.local` 設定
  `USDA_FDC_API_KEY=...`，只由後端讀取；用於已審查來源的確認／預覽及隔離 API 測試，
  尚未啟用自動網路補全。現有171688限定發布見下文。根目錄 `USDA KEY.txt` 不會被程式自動讀取，
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
目前沒有 MongoDB 備援；SQLite 開啟失敗就停止。舊 Render Blueprint、Pages 自動發布與
Procfile 已移除。既有外層 BAT／排程／Funnel 是正式入口，GitHub 只作備份與 CI。
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

1. 用 `git rev-parse --verify 'refs/tags/v1.0.3^{commit}'` 取得完整 SHA，與 GitHub 發布版核對。準備符合該提交的原始碼；分支同名或 `app_version` 相同都不足以確認內容。更新依賴並將前端匯出到暫存目錄，不覆蓋仍在服務的 `frontend/dist`。
2. 使用排程工作相同的 Python、Windows 帳號及 `DATABASE_PATH` 執行 `python backend/scripts/backup_db.py`。保留通過檢查的 SQLite 備份、原設定、舊程式版本與 `frontend/dist` 副本。備份可在服務運作時做；備份失敗則不停止服務。如果更新會遷移資料庫，停機及確認無寫入後、啟動新版前再留一份備份，避免遺失第一次備份之後的新紀錄。
3. 停止 `NutriLens Backend`，確認工作已停止與 5000 埠已釋放後，再切換程式和靜態檔。保留原工作路徑、`backend/.env.local`、`key.txt` 及 SQLite 路徑。以 `git rev-parse HEAD` 和 `git status --short --untracked-files=no` 核對實際部署工作樹；不要把待提交改動當作標籤內容。核對後才在後端啟動環境設定 `NUTRILENS_DEPLOYED_BRANCH=v1.0.3` 和 `NUTRILENS_DEPLOYED_COMMIT`（已核對的完整 SHA）。同名派送環境變數或根目錄 `.env.local` 可能優先於 `backend/.env.local`；不要只在目前視窗設定後就假定排程會繼承。
4. 啟動原工作。確認本機與既有 Tailscale 公開 `/health` 都為 200，回報 `v1.0.3`、`deployed_branch=v1.0.3`、預期的七碼 `deployed_commit`、新的 `started_at`、SQLite、需登入及自動補全關閉。比對兩端 `/scanner` 的 Expo entry 與部署目錄；`deployed_commit=local` 只表示沒有版本標記，不能作為標籤部署驗證。
5. 驗證失敗時停止工作，優先回復舊程式、設定及靜態檔，再驗原服務。只有確定資料庫需要回復並處理備份後新增紀錄時，才在停止後端後使用 `backup_db.py --restore`；不要為了回復前端或程式而直接覆寫正式 SQLite。

排程使用該電腦 `pythonw.exe` 的完整路徑，並以本專案 `backend/scripts/run_in_background.py`
的完整路徑啟動。搬動專案或變更 Python 安裝位置後，需要修改工作排程的動作與起始位置。
排程執行的是這個路徑當下的程式，不會固定在某個 Git 分支；切換分支或修改內容後，
下次啟動就會使用更新後的檔案。沿用原路徑時，更新工作樹不需要重新設定工作排程、Tailscale 或 SQLite。

## FDC 預覽啟用前檢查

這是v1.0.3現有來源安裝與開關的設定審查，不會啟用功能。於內層專案執行：

```powershell
python tools/review_fdc_preview_admission.py
```

預設只檢查repository defaults及兩份本機營養資料集，不import app、不讀.env或credential，
也不開正式SQLite；blocked回傳exit code 2是預期結果，不是程式當機。
repository預設reviewed FDC tuple仍空，候選JSON不會自行安裝。第七十八批本機已用下述明確來源檔發布171688限定預覽；Tavily registry仍空。預設檢查不讀本機部署設定，因此仍可blocked，不能拿它否定已觀測的runtime。

首批最小配置只準備一般帶皮生蘋果171688，顯示名仍為蘋果；來源須精確相容且唯一、
admission通過、已明確安裝且active。開關矩陣如下，這個表不是要求立即修改本機設定：

| 範圍 | 後端 | 前端建置 |
| --- | --- | --- |
| 系統選用 | FDC_REVIEWED_SELECTION_ROUTE_ENABLED=true | EXPO_PUBLIC_FDC_REVIEWED_SELECTION_ENABLED=true |
| 使用者確認 | FDC_CONFIRMATION_ROUTE_ENABLED=true | EXPO_PUBLIC_FDC_CONFIRMATION_ENABLED=true |
| 營養預覽 | FDC_PROFILE_PREVIEW_ROUTE_ENABLED=true | EXPO_PUBLIC_FDC_PROFILE_PREVIEW_ENABLED=true |
| 維持關閉 | FDC_CANDIDATE_ROUTE_ENABLED、FDC_DETAIL_ROUTE_ENABLED、FDC_PROFILE_ACCEPT_ROUTE_ENABLED、NUTRITION_ENRICHMENT_ROUTE_ENABLED | EXPO_PUBLIC_FDC_CANDIDATE_SEARCH_ENABLED、EXPO_PUBLIC_NUTRITION_ENRICHMENT_ENABLED |

preview service會內部取固定confirmed FDC Detail，不需要打開原始Detail HTTP route；
它也不需要為此開Tavily enrichment或簽章服務。需要真正server-side USDA key及SQLite登入。
「營養唯讀預覽」仍保存scan／snapshot／confirmation／preview狀態，不能稱整個DB唯讀。
首批不接受nutrition profile、不寫meal record，也不開跨使用者cache。

進階檢查可用`--configuration <snapshot.json> --database <existing.db>`。snapshot須為明確的
server-owned非機密JSON，恰有`reviewed_sources`、`backend_flags`、`frontend_flags`、
`authentication_required`、`fdc_key_available`五欄；後兩者只填布林觀測，不放金鑰。
reviewed_sources每項沿用selection service的policy／admission_review／candidate三欄，
不能直接把候選artifact外包裝當正式配置；flags全部填布林值，不能用字串。
SQLite以mode=ro／query_only讀目前policy，缺檔不建立、缺schema不初始化、撤回不恢復。

configuration_ready／exit0只表示提供的設定快照與當下DB讀取相容，不驗證觀測真假或後續狀態，
不等於runtime flags、建置bundle、正式部署授權或影像準確率驗收。
工具不安裝政策、不寫.env、不建置／重啟；正式啟用仍須明確安裝／載入與部署時重新核對。

## FDC 來源明確安裝與啟動載入

第七十六批新增`tools/manage_reviewed_fdc_source.py`。它不讀`.env`或金鑰、不呼叫provider，
也不匯入app。必須指定既有SQLite與server-owned來源配置；缺檔不建立，安裝缺schema直接拒絕。
來源配置JSON恰有`reviewed_sources`一欄，每項為`policy`、`admission_review`、`candidate`三欄；
這是來源工具的輸入，與上節五欄的完整開關觀測snapshot不同。候選artifact不是部署配置，
不能直接拿其外包裝作輸入；所有配置來源須先通過完整審核／描述檢查且不得身分重疊。

只讀檢查（預設，mode=ro／query_only）：

```powershell
python tools/manage_reviewed_fdc_source.py --configuration <sources.json> --database <existing.db>
```

明確安裝單一來源（會寫所指定SQLite；應先依既有流程備份）：

```powershell
python tools/manage_reviewed_fdc_source.py --configuration <sources.json> --database <existing.db> --install-source usda-fdc-171688 --policy-sha256 14152c86f9f718ee7057d65b038d6b9be65d3a7197995308f29ef91f5876b85f
```

單一交易新增current與revision0歷史；相同active policy回`already_installed`，不新增revision。
撤回來源回`source_withdrawn`，內容不同回`policy_changed`，均不寫回或自動恢復；更新政策、
重新審核／重新授權不屬此安裝命令。CLI不自動修改app配置、flags、前端bundle或重啟服務。

app啟動已接`load_installed_reviewed_fdc_sources`：預設只讀明確的
`PRODUCTION_REVIEWED_FDC_SOURCES`；第七十八批另可用server-only環境變數
`FDC_REVIEWED_SOURCES_FILE`指定來源配置JSON的絕對路徑，形狀與上述安裝CLI相同。
只有空tuple時能使用檔案，兩種配置同時存在直接拒絕；不掃描候選目錄、不安裝來源、不寫來源政策。
空配置停用reviewed-selection；非空配置須全部已安裝、active、policy／policy ID一致且revision有效，
否則整組不載入並停用此route。這不是整個app啟動零寫入的宣稱：既有schema檢查／遷移照常。
載入後withdrawal仍由每次selection／preview的既有policy檢查攔截，不依賴重啟。

第七十六批僅在temp SQLite與全新子程序驗證；第七十八批已依此最小矩陣完成正式171688
安裝／啟動及本機／公開核對，現況見下一節。未開Tavily、raw Search／Detail HTTP、
accept、飲食保存或跨使用者cache，也未重做固定手機fixture。

## 單一蘋果來源預覽已發布

2026-11-16第七十八批已沿同一個`NutriLens Backend`排程完成切換，沒有新增服務或BAT。
本機／公開health均為v1.0.3，started_at=`2026-11-16T23:42:59.209397+08:00`；
SQLite、登入及兩份官方資料正常，公開health仍隱藏資料庫路徑。
171688政策revision0已安裝，明確來源設定留在資料庫旁的私密release資料夾，由上述絕對環境路徑載入。
USDA key只存在後端私密設定；既有key已用一次固定Detail實測，9營養與150g78kcal通過正式adapter。

前後端僅開選用／確認／preview各3個開關，上方excluded開關仍false；automatic fallback=false。
一般scanner顯示蘋果及server估重，仍須先通過本機miss、可見帶皮生鮮身分、active policy與使用者確認。
本機已命中的蘋果不必進此fallback；不要為展示預覽停用TFDA／USDA或修改辨識identity。
目前完成部署smoke，尚未完成本次正式真照片端到端，不能宣稱所有照片都能補全。

建置已清快取並same-origin匯出；入口為`entry-5115ba442ac55ef3887c0fae59bdaf53.js`，
本機／公開／disk SHA-256均`8c1840d3f1d52dcf85f1b26cab3d98da7e277d7f0eafda79b5981c6909695bca`。
本機`frontend/.env.local`只保留公開build flags及same-origin／登入設定，並由Git忽略；
後續一般`build:local`須保留這份設定。不要放入USDA、Tavily或relay server key，
也不要把後端環境整份複製給Expo。更改build flags後仍須清快取、重建並核對提供的entry。

私密啟動log新增`[INFO] FDC preview startup:`診斷，僅含版本／started_at、來源狀態、
實際route flags和key可用布林，不含key或設定路徑；部署檢查須與health的同一started_at綁定，
不可讀舊log或只看.env就宣稱是當前runtime。不要對外公布整份backend log。

回復副本包含原backend env、完整dist、兩次既有備份與私密`ROLLBACK.md`，均在Git外。
回復時先停止同一排程及確認5000已釋放，保留新設定後還原舊env／dist；本次新增的frontend
dotenv原本不存在，只能核對與release副本hash一致後移除，避免刪除後來的使用者修改。
來源安裝只新增policy／revision各1列；關閉路徑／flags即可停止選用，不要整庫覆寫後續使用者資料，
也不要用舊save方法或重新安裝來復活withdrawn來源。回復設定後仍用目前v1.0.3程式，
須重新核對空載入／關閉開關與local/public網站；不宣稱已還原舊版程式碼。

證據：[第七十八批發布與限定驗證](food-nutrition-evaluation/2026-11-14/fdc171688-preview-release-20261116.json)。

## 單一蘋果來源的實際上線前檢查

> 第七十七批的歷史預檢結果；缺少的設定已於上節第七十八批發布完成，不是目前待辦。

以下保留第七十七批發布前對照；其中待配置項已由第七十八批接續完成，不是目前仍缺。
第七十七批（2026-11-16）已完成本機實際核對，當時結果為尚待發布配置。證據見
[上線前檢查](food-nutrition-evaluation/2026-11-14/fdc-preview-rollout-preflight-20261116.json)。
這是一次當下觀測，不能推定後續程序、環境或來源狀態。

| 核對項目 | 本次實際結果 | 發布時處理 |
| --- | --- | --- |
| 排程／程序 | 排程指向目前checkout；5000為PID16352，health仍v1.0.2 | 更新後沿既有排程重啟，再核對v1.0.3與新的started_at |
| SQLite／登入 | health與實際路徑相符，quick_check=ok，登入必須開啟 | 保留SQLite-only與帳號資料，先以既有backup_db流程備份 |
| USDA key | 私密USDA KEY.txt存在且有一組正確格式key；現行dotenv未接USDA_FDC_API_KEY | 由既有檔案設入server-only環境；不重新申請、不放Expo或日誌；格式不是live有效性證明 |
| 明確來源／安裝 | production tuple空；正式DB無171688列 | 明確配置唯一171688的policy／admission／candidate，釘選既有digest後使用安裝CLI；不掃描候選目錄 |
| 後端開關 | 新helper＋現行dotenv的7個FDC／enrichment flags均false；舊程序FDC flags未暴露 | 僅開上方3個required flags；其餘保持false，啟動後核對實際載入與route gating |
| 前端檔案／開關 | 本機／公開scanner與entry皆200，entry hash同disk；baked flags未驗 | 明確指定3個required與2個excluded build flags，same-origin匯出，核對實際提供的新entry |

目前沒有frontend dotenv設定檔，不代表舊bundle flags已確認關閉；也不能把目前.env視為
已運行程序的環境。本批僅讀正式SQLite、設定及key格式，未寫正式SQL／.env或安裝來源，
未build／重啟。設定審查已補齊installed policy_id與policy JSON一致性檢查，避免審查通過
但啟動loader拒絕；它仍不驗證觀測真假或授權部署。

接續發布採同一個有界流程：既有備份→server-only key→明確單來源配置／安裝→
上方前後端各3個開關與same-origin建置→既有stop/start排程→本機／公開health及bundle核對。
發布前保留原設定與bundle的可回復副本；任何階段失敗即停止啟用，保留來源撤回狀態，
不要用save_source_policy或重新安裝來復活來源。準備與核對完成才進部署操作；
本表不是部署授權，不另建BAT或服務。

初次範圍仍限171688帶皮生蘋果的系統選用→明確確認→預覽；preview狀態會寫SQLite。
不開Tavily、raw Search／Detail HTTP、profile accept／meal寫入或cross-user cache，
不重做已完成Android固定fixture，也不宣稱照片重量或辨識準確率已驗證。

## 隔離手機流程驗收

> 既有固定 fixture 的歷史驗收方法與結果，不是目前一般真照片的辨識準確率證據，亦無須重複操作。

候選確認／營養預覽可使用獨立公開 HTTPS 8443 測試，不要求手機安裝 Tailscale。
它與正常443網站不同，僅使用固定蘋果資料、暫存 SQLite及獨立frontend匯出；
任選照片均回固定測試結果，不評估辨識準確率，也不能保存profile或飲食紀錄。

在專案根目錄啟動（需既有Node依賴、Python環境及伺服器端Tailscale Funnel）：

```powershell
python backend/scripts/scanner_phone_e2e_server.py --origin https://<device>.<tailnet>.ts.net:8443 --minutes 60 --funnel
```

以實際裝置網域替換範例。程式將先清快取匯出獨立網站，再列出短效手機網址；
同一網址另存在專用系統暫存目錄的 `phone-run.json`。不要將含token的網址提交到Git。
在Windows背景啟動時，`Start-Process` 使用 `-WindowStyle Hidden`。

手機操作：開始測試 → 相簿選圖或拍照 → 選蘋果候選 → 送出逐項決定 → 預覽固定資料營養 → 核對150g／78kcal。
每次scan reference仍只有120秒，過期請重新選圖或拍照。測試session可設1–60分鐘；
到期程式會停止測試gateway／backend並嘗試清除自己的8443 Funnel。
若強制終止程序，請另查Funnel狀態，確認8443是否仍指向已停止的測試gateway。

8443已有配置時程式會拒絕覆蓋；正常443、5000後端、正式SQLite及production flags不需更動。
不要將 `scanner_browser_e2e_server.py` 直接接到Funnel；其固定token和可控制時鐘／provider的端點
只能在loopback測試使用。公開入口僅能使用上述受限gateway。
