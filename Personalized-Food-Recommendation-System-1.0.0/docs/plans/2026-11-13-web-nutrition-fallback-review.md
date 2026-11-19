# 第三層營養補全：第二至四輪自行審查紀錄

第102–103批於2026-11-19驗證後端 USDA 優先檢查與 Scanner 請求順序；第101批公開真照留作前兩層證據。目前分支為 `v1.0.3`。各批敘述保留當時的版本狀態。現行判斷見下方收尾複核及主計畫首頁、第2、13、15、19節。[流程計畫書](2026-11-13-web-nutrition-fallback.md)。
方式：第二輪先完成初稿，再從第 1 至 16 節重讀，將承諾、資料流與現有程式逐一對照。
限制：第二輪為同一代理自行審查，當時未實測；第三輪依授權實測但尚未實作。後續修復已修改後端，Phase2a另由儲存、風險及API代理獨立交叉檢查；仍不等於外部安全或營養專業審核。第五十六批fake vision/FDC瀏覽器E2E、第五十七批條款查核均屬當時限定結果；其後Android相機smoke及固定preview已有使用者驗收，171688也已由第七十八批正式限定發布，不能再概括為完全未測手機或沒有任何正式來源。Tavily Web來源仍未准入，正式真照片條件式preview及準確率未驗證。第97批Detail覆蓋未保存數值或逐欄source metadata，不能作營養來源品質結論；第98批雖完成metadata比較，仍未選定來源或energy method。

## v1.0.3 發布後核對（2026-11-19）

[GitHub Release](https://github.com/LitchiCat1/Personalized-Food-Recommendation-System/releases/tag/v1.0.3) 的標籤與 GitHub 分支 `v1.0.3` 核對到相同提交 `ecceed6c40f49a5f7491e577d1b51e19a17500c2`，本機已在該分支且提交一致。原本未追蹤的照片、截圖及本機測試檔未改動。

本機與既有 Tailscale Funnel 的 `/health` 均回 200：`app_version=v1.0.3`、`database=sqlite`、`auth_required=true`、`automatic_web_fallback_enabled=false`，啟動時間均為 `2026-11-19T17:51:44.495154+08:00`。兩端 `/scanner` 與 Expo entry 均回 200，entry SHA-256 `82028ba5cd38adc19b488a9ed53bb113658614e1347c09bccca42a68e55d4418` 與現行 `frontend/dist` 相同。`deployed_branch` 和 `deployed_commit` 均回 `local`，只能確認服務回報的版本與實際提供的靜態資產，不能證明已部署 GitHub 標籤，也未驗證 Scanner 互動。

本次未部署、重啟、讀寫正式 SQLite、改旗標或呼叫模型／USDA／Tavily。沒有新案例符合第19節，第三層仍停在等待證據，不新增查圖、擴搜或手機重測批次。日後若安排正式更新，再依[維運手冊](../Operations_Runbook.md)備份 SQLite，記錄部署的分支與提交，並於重啟後核對服務及前端資產。

### Windows／SQLite 更新演練

從 `refs/tags/v1.0.3` 的 `ecceed6c` 匯出後端到暫存目錄，以正式排程同版 Python 在不同 loopback 埠執行既有背景啟動程式，用全新 SQLite 且略過本機設定。首次隔離環境缺少 Python 使用者套件路徑而停止；保留 `APPDATA` 讓同版 Python 讀取已安裝的依賴後通過，沒有傳入金鑰或正式連線設定。

兩次隔離啟動均由 `/health` 回報 `v1.0.3`、`ecceed6c`、SQLite、需登入、本機資料可用及自動補全關閉；`started_at` 更新。使用既有 CLI 備份和還原，兩份檔案 `quick_check=ok`；還原後只含備份時的測試列，備份後寫入的測試列仍由原檔改名保留。第二次啟動後還原資料仍在，測試埠已關閉。未測部署後的 Scanner 互動，未動正式排程、資料庫、前端或 Tailscale。已更新 [Windows 部署說明](../Local_Server_Deployment.md#更新專案)；部署準備至此完成，只有安排正式更新時才執行備份與重啟。不影響第19節的 Tavily 停點。

## 第三層收尾複核（2026-11-19）

以[主計畫第19節](2026-11-13-web-nutrition-fallback.md#19-實測後的放行決定)的現行條件核對既有案例，不重做照片或供應商測試：

| 案例 | 不進第三層的原因 |
| --- | --- |
| [一般帶皮生蘋果](../food-nutrition-evaluation/2026-11-14/scanner-apple-identity-20261117.json) | 已有相容的 USDA FDC 171688，不能繞過第二層。 |
| [青江菜](../food-nutrition-evaluation/2026-11-14/bok-choy-bounded-source-close-batch99-20261119.json) | 已知候選無法選出適用的食材本體原列，FDC 也有非空候選；維持未配對，不以生鮮或蒸熟資料換算熟炒份量。 |
| [香菇赤肉羹](../food-nutrition-evaluation/2026-11-14/web-nutrition-candidate-preflight-batch100-20261119.json) | 固定商品頁擷取不是真實掃描；缺食用範圍確認、正式查詢流程的零筆證據與試驗用途的權利依據。 |
| [糯米腸](../food-nutrition-evaluation/2026-11-14/scanner-public-nuomichang-batch101-20261119.json) | FDC 查詢回非空候選，即使沒有相容項也不是明確零筆；另缺已確認的食用範圍與可核對的一手營養來源。 |

**結論：分層順序已隔離驗證；真來源正向驗收未執行。**無合格案例，不擴搜或另開測試批次。待同一案例補齊確認身分／食用範圍、前兩層證據及可使用來源，再以原始FDC Search模式做一次隔離驗收。通過不等於放行公開使用。本次只更新文件，沒有真供應商呼叫、應用程式重測、正式資料寫入、旗標變更或部署。

## 第一百零三批 Scanner 分層順序（2026-11-19）

在原始 FDC Search 模式，Scanner 先發布本機結果，等有效掃描的 FDC 回應才可能發出補全；伺服器仍須驗證零筆證據。審核來源路徑優先且不接補全，避免共用快照被當成兩次獨立查詢。同品項的既有營養及份量不覆寫；新增品項才從待確認區移除。失效回應不更新畫面，補全過程的舊 401 不觸發目前登入的登出。顯式清除同時移除待確認品項。

Scanner 34 項、營養 150 項測試及 typecheck、lint、隔離 Expo web export 通過。Playwright 以固定 API 回應操作相簿，檢查 390 與 1440px；成功序列為 vision→FDC→enrichment，原 TFDA 份量校正至110g後仍保留。FDC 502 時沒有補全，手動重試後的空回應由模擬後端回 409、仍保留本機結果。清除後才收到的成功回應未恢復資料。無水平溢出、無頁面 runtime 錯誤；僅兩個預期注入的 HTTP 錯誤。使用已安裝的 Chromium，未對外送圖或呼叫真模型、USDA、Tavily。

這驗證客戶端順序，沒有證明實際 FDC 整庫查無、Tavily 真來源擷取、份量正確率或 Android 實機行為。後端的真實 SQLite 證據檢查沿用第102批。正式環境未部署、未改旗標或 SQLite，第三層只在第19節重開條件齊備時做一次隔離正向驗收。

## 第一百零二批 第三層後端順序檢查（2026-11-19）

複核發現 Scanner 會先對本機未命中品項請求網路補全，之後才查 FDC；後端原先也沒有驗證 FDC 是否已查過。新增同一品項所有受控 FDC Search 明確零筆的伺服器證據，與候選快照在同一 SQLite 交易寫入。補全路由先檢查本機查無配對、官方資料健康、無相容已配置審核來源及同帳號／同掃描版本／同品項的未過期 Search 證據，才可讀 Web 快取或建立 provider。舊或跳過搜尋的空快照、相容已審核來源、含候選或上游缺少明確零筆的結果均不能放行。

隔離 HTTP 以假 FDC 和網路 provider 測試：先請求補全回 409，正式資料源不可用回 503；FDC Search 成功、有證據且無已審核相容來源後才進入假 provider，同冪等請求可重播。SQLite 另驗證證據過期、跨帳號／品項／版本拒絕，以及寫入失敗的交易回滾。不呼叫真模型、USDA 或 Tavily；未部署、未開旗標，未修改正式 SQLite 或來源清單。不是 Scanner 串接或真來源第三層驗收。糯米腸仍未配對，不反覆擴搜。開啟自動補全前須解決 Scanner 呼叫順序，並有合格來源才重開隔離試驗。

完整後端回歸：1176 項測試、1293 個子測試通過，77.95 秒。未執行前端或實機測試，本批未修改前端。

## 第一百零一批 公開糯米腸真照自動辨識（2026-11-19）

依使用者要求，直接以有署名的公開糯米腸照片呼叫現行辨識路由，未提示食品名稱。影像辨識回「糯米腸」，與來源標示相符，分數0.92；烤製狀態是模型從影像判斷。估重1800g是多個食物的加總，信心0.30，無秤重或實際食用範圍，不能拿來換算攝取量。未配對品項未納入合計，API的已配對合計0不表示該食物營養為0。

TFDA與USDA FNDDS都成功載入，本機結果是 `no_local_mapping`。正常FDC路由確實發出三次搜尋，去重後五筆只涵蓋糯米、糯米粉或米糕，無相容整品。候選 `available` 不是資料來源已採用；不能由此推論整個USDA資料庫均不存在糯米腸。未找出符合此品項且用途有據的營養來源，公開照片授權也不能代替它，因此未呼叫Tavily、Detail或擷取模型。這只是單張照片的後端實測，不是Android相機、整體準確率或第三層驗收。[第101批證據](../food-nutrition-evaluation/2026-11-14/scanner-public-nuomichang-batch101-20261119.json)。

## 第一百批 第三層單一候選前置查核（2026-11-19）

只查既有 GREEN&SAFE「香菇赤肉羹」`MEG0028ABCS`。官方商品頁有每份與每100g標示，但適用的是含羹湯與肉羹的冷凍調理包，不是泛稱肉羹、肉羹米粉或僅固形物。早期 `exact_soup` 固定控制曾成功擷取，同一頁亦曾漏表；不等於現行正常掃描或全流程正向採用。第27批地瓜球PDF的HTTP驗證另已留存，表格被壓平而回 `no_evidence`，不重跑也不計作正向驗收。

真實掃描品項與食用範圍確認、正常TFDA／USDA及限定FDC無相容配對紀錄、來源使用條件的可稽核依據，三項未齊。公開商品頁不等於准入依據；站方交易安全頁的搜尋摘要未能在原頁重現，不據此判定禁止，也不聯絡站方。結案為「前置查核完成；正向驗收未啟動」。沒有合格新案例不重開，不委派其他來源搜尋。未呼叫Tavily／模型／USDA API，未複製營養數值或改正式設定、SQLite、部署。[第100批證據](../food-nutrition-evaluation/2026-11-14/web-nutrition-candidate-preflight-batch100-20261119.json)。

## 第九十九批 青江菜來源評估收尾（2026-11-19）

上一批的「另找一筆來源」缺少結束條件。本批把查核限於既有MEXT與CoFID候選。MEXT生鮮及水煮列標示為葉，油炒列含添加油。CoFID官方主表的名稱篩選只命中蒸熟 `13-516`，舊食品表無命中。連同第98批FDC血緣結果、CNF與USDA的資料重疊及AFCD排除決策，青江菜生鮮參考與熟炒均以未配對結案。

再次複核六項工作流時，以蘋果實機截圖更新原先仍寫缺原照的摘要。已完成的隔離與實機驗收限於各自的測試情境。第三層正向試驗已有明確進入條件和停止規則。正式網路補全仍關閉。

以隔離設定跑過後端身分保護、官方來源選用、補全路由及來源准入等相關回歸，83項及105個子測試通過。前端掃描器26項通過。MEXT檢索輸出顯示原頁營養數字，專案證據只留來源範圍與判定。CoFID工作簿位於系統暫存區。[第99批證據](../food-nutrition-evaluation/2026-11-14/bok-choy-bounded-source-close-batch99-20261119.json)。

## 第九十八批：青江菜FDC來源血緣審查（2026-11-19）

以server-side USDA key對Foundation `2685572`做2次、SR Legacy `170390`做4次固定Detail唯讀查詢，均未重試；沒有保存營養amount、完整payload或資料庫內容。第一次整理Foundation分析明細時，輸出欄位選擇過寬，命令輸出包含嵌套分析明細內的amount；未寫入證據檔、SQLite或profile。後續查詢改為metadata-only投影，該範圍錯誤已列入機器紀錄。無Tavily／模型呼叫，未改程式、測試、flags或部署。

Foundation記錄發佈日2024-04-18、NDB 11116。水分、脂肪、纖維與鈉列有8個data points及分析細節，方法分別包括vacuum oven、acid hydrolysis、enzymatic-gravimetric與ICP；蛋白質、碳水及Atwater General／Specific energy均標示calculated／calculated-or-imputed，沒有分析細節；糖、飽和脂肪、反式脂肪未提供。SR Legacy記錄發佈日2019-04-01、同為NDB 11116；蛋白質／脂肪各1點、鈉2點、纖維0點且沒有逐項分析方法；碳水、糖、飽和脂肪及kcal/kJ energy有計算／imputed derivation，反式脂肪標為assumed zero。所查欄位沒有footnote。共同NDB code不足以證明兩列互換，data points／推導差異亦無法決定哪列更代表台灣青江菜。

**結論：**兩列source quality都未足以支持青江菜raw每100g顯示；不選來源、不選energy number、不拼欄、不建policy/profile。熟炒掃描仍no-match。下一步另找一筆來源權利可審、食品範圍及營養欄位血緣充分的權威原列；若找不到，維持no-match。來源gate通過後才實作獨立reference-only唯讀API/UI，與熟菜portion、掃描合計、風險、profile及餐點保存完全隔離。[機器紀錄](../food-nutrition-evaluation/2026-11-14/fdc-bok-choy-lineage-review-batch98-20261119.json)。

## 第九十七批：青江菜固定 FDC Detail 與 raw reference-only 可行性（2026-11-18）

對固定FDC Detail ID `2685572`、`170390`、`170391`各發一次唯讀請求。先前使用DEMO_KEY各查一次均為403；隨後經server-only key完成三次Detail，未重試，未輸出或保存credential。成功response有營養數值，但本次審查只保留欄位覆蓋／來源差異，不將數值寫入證據JSON、SQLite或profile；Tavily／模型呼叫0。

Foundation raw `2685572` 對應六個schema欄位，缺糖、飽和脂肪及反式脂肪，並列兩種kcal算法。SR Legacy raw `170390` 映射九項欄位，反式脂肪原格為零。兩筆raw的重疊營養欄位數值有差異；不能合併資料、不能以欄位較完整直接推定較可信，也不能將固定FDC名稱視為台灣青江菜特定栽培品種。SR Legacy `170391` 為無鹽水煮瀝乾，資料完整度不能消除其與熟炒的烹調差異。

**結論與破綻：**建立單獨標示的raw reference-only路徑在技術上可行，但目前FDC preview需要source/scan identity全相容及正重量，並計算portion；若直接沿用，將把raw資料誤作照片熟菜營養。另兩筆raw候選的數值差異與Foundation雙energy method尚未以逐欄來源、分析方法、樣本數及footnote解釋，故此刻選source會是假精確。保持熟炒item no-match，不建立source policy/profile，不顯示任一候選數字。下一步先比對兩筆raw記錄的分析／sample／nutrient lineage／energy method；若差異無法解釋，保留no-match。若選定且審查通過，才實作明確標示每100g、生熟估重不互乘、排除合計／風險／儲存的獨立API/UI並加隔離正反測試。[機器紀錄](../food-nutrition-evaluation/2026-11-14/fdc-bok-choy-detail-review-batch97-20261118.json)。

## 第九十六批：青江菜FDC alias與生熟相容性複核（2026-11-18）

已在query normalizer加入唯一server-owned alias `青江菜` → `bok choy`；原中文名稱保留，其他蔬菜、品牌字串及模型自供alias不會因此擴張。只有exact name通過身份資格及真local miss後，現有候選搜尋才使用原名與一個alias。泛稱葉菜仍於lookup/provider前阻擋；候選仍不是identity confirmation、來源准入或營養profile。

用公開DEMO_KEY實際查USDA FDC：exact Chinese `青江菜` 0結果，英文查詢回傳兩筆raw、兩筆boiled (with／without salt)及一筆標成`Cabbage, Chinese, raw`的FNDDS泛稱列。固定Detail僅確認四個具體ID的描述、型態與分類，未保存營養值。候選命中不表示營養匹配。service regression確認raw→stir-fried及boiled→stir-fried均於Detail API前拒絕；聚焦suite 41項及22項subtests、完整後端suite 1179項及1282項subtests均通過。

**發現的流程破綻與處置：**目前FDC profile preview必須source/scan狀態、做法、scope及variant精確匹配，並且一定要有重量後計算portion。現有程式沒有「只顯示raw每100g、不計算熟菜portion」的獨立reference-only預覽契約，因此青江菜raw FDC結果不能拿來代替熟炒營養，也尚不能安全呈現成照片營養。煮菜的鹽選項與使用者只排除添加油的範圍亦不相同。先唯讀審查固定Detail九項核心/可選營養格及準備狀態，再決定要加raw reference-only呈現或繼續no-match；不因為已有alias便准入FDC record。Tavily自動補全和營養保存維持未啟用。[第96批機器證據](../food-nutrition-evaluation/2026-11-14/fdc-bok-choy-alias-compatibility-batch96-20261118.json)。

## 第九十五批：食材名稱更正及本機優先複核（2026-11-18）

名稱更正與營養來源確認分開。名稱更正由後端驗證登入者、當前掃描與品項版本，新增確認紀錄及版本。一般影像掃描不會帶入使用者確認來源。保留影像分數、估重與食用狀態；後續候選須綁定新版本，不能沿用舊品項的確認。重查先走既有本機比對，未找到相容營養不計入合計。

隔離瀏覽器以固定影像輸出驗到泛稱422、具體品名重送202及實際本機查無相容配對。只驗到使用者明確更正「炒菜葉」為「青江菜」，不能據此推論模型會辨識青江菜，或正式服務已啟用。畫面逐項已區分身分確認和營養未匹配，整體摘要仍寫「待確認」。後續FDC候選驗收時一併確認摘要能否清楚表達未配對原因。

本階段驗收已完成。青江菜英文別名已加入；生鮮不能套用熟菜估重，煮菜也不能替代熟炒。下一步需審查固定FDC Detail與九項營養覆蓋，判斷是否存在獨立raw per-100g參考呈現，而非沿用會計算portion的preview。真Tavily正向採用、來源准入與正式旗標及配額核對仍是後續工作。[第95批證據](../food-nutrition-evaluation/2026-11-14/identity-correction-batch95-20261118.json)。

## 第九十四批：server-owned身分資格與provider零呼叫修補（2026-11-18，歷史）

依第93批決議，實作身分專用`identity_confirmation_required`，不直接沿用混合份量、候選營養及缺值狀態的UI `needs_confirmation`。vision端server derivation要求confidence至少max(0.75,既有`VISION_FOOD_MIN_CONFIDENCE`)、名稱非泛稱／不確定、validation issues為空，且food_state、preparation_method、components_scope皆為有效已知enum。alternatives依現有prompt為同食物同義名稱，不能只因不同字串判定不同物種。`weight_confidence`及estimated weight不參與身分資格：明確食材但低估重信心仍可取得每100g參考profile；缺重量時portion保持null，既有scanner merge不把它轉成可記錄項目。

確認狀態從vision server response一路進scan-context adapter、SQLite持久JSON及item-set hash、HMAC scan-authority claims、enrichment request fingerprint與前端scanner context。server route先跑既有local lookup；local miss且身分不合格時，在web cache read之前拒絕，故不建立provider、reserve/consume quota或consume JTI。改client flag會造成durable hash mismatch；legacy context缺欄位不取得web資格；SQL reopen後狀態/hash一致。核心web service亦共用eligibility gate。FDC來源確認不改vision identity，故不能作名稱確認捷徑。

聚焦回歸117 passed／397 subtests；HTTP integration包含在內。完整後端1161 passed／1273 subtests。前端nutrition 145 passed、scanner 25 passed、typecheck、lint及web export通過。真Tavily／模型／USDA API呼叫0，未讀key或production DB，未改runtime flags、部署、commit/push。注意：此修補建立fail-closed gate，沒有提供通用user food-name confirmation endpoint/UI，也沒有建立可解鎖的identity correction revision；在該流程完成前，只有scan本身server-derived清楚身分可進eligibility，既有FDC candidate confirmation不會解除身份flag。機器可讀證據：[第九十四批閘門證據](../food-nutrition-evaluation/2026-11-14/identity-enrichment-gate-batch94-20261118.json)。

## 第九十三批：整體流程複核與待確認身分閘門（2026-11-18）

本次重讀主計畫首頁、第2／5／7／13／15／19／22節，並核對`nutrition_scan_context_adapter.py`、`nutrition_enrichment_route_service.py`、`web_nutrition_service.py`、`fdc_candidate_search_service.py`、`food_query_normalization_service.py`及`app.py`的authority、eligibility、FDC查詢與HTTP接線。三層主架構合理，沒有需要重做；主要發現是現行計畫漏寫一項會影響錯配營養的實作缺口。

**P1 身分未確認可能進入第三層：**vision結果依`needs_confirmation`標示低於0.75、候選衝突等情況；營養scan-context adapter白名單未保存此欄位，`_web_enrichment_eligible`目前以0.45最低辨識門檻、無validation issue及非泛稱作主要篩選。兩種門檻語意不同：最低辨識門檻只讓候選保留，不代表食品名稱可供自動營養套用。下一步應將server-owned身分確認狀態／確認來源與revision納入authority contract；待確認項目在確認並重查TFDA／USDA前，provider Search／Extract呼叫數必須為0。不得信任client自行提交的`confirmed=true`。

**P1 現行待辦摘要含過時陳述：**第15節曾稱尚無簽署token、enrichment coordinator、跨程序配額及cache；但程式已有server-signed authority、authenticated `/nutrition/enrichment`、scanner條件式呼叫、SQLite durable request/quota/cache及lease/replay路徑，且相關隔離驗證記錄在先前批次。應把未完成項改為「缺真Tavily正向採用與權利已核可來源的端到端驗收」，不把已實作的HTTP／authority／quota重新列為待設計，也不把程式接線當成production runtime已開啟。

**P1 FDC與第三層次序需一致：**第92批的alias gate仍有效，但在任何第三層live extraction前，先完成待確認身分阻擋；之後才加青江菜server-owned英文alias，測試真正local miss、候選人工選擇及raw／boiled／stir-fried相容性。FDC是USDA第二層，CNF 2026資料與USDA血緣重疊，不是獨立第三來源。`炒菜葉`仍不得搜尋。

**P1 生熟與portion語意：**使用者只明確排除添加油；這不表示raw青江菜營養可視為熟炒青江菜。若只找到raw FDC資料，顯示時必須標示「生鮮每100g參考」且不乘熟菜影像估重；若UI無法清楚區分reference-only與已匹配portion，則維持未配對，不顯示熟菜精確營養。無添加油煮菜紀錄也不能假定等於一般炒菜。

**P2 授權與部署gate分開：**Gemini所稱checkbox時點、API無參數即自動同意及只需署名均未被FSANZ條文支持。依使用者指示不聯絡FSANZ，AFCD保持排除；CNF不作獨立來源。Tavily技術隔離測試、來源profile准入、正式公開服務是不同gate。正式啟用前仍需記錄Tavily plan/Terms適用依據及各publisher的搜尋、擷取、呈現、保存和重用權；沒有信件不等於獲授權。

**P2 可信度措辭：**0.45與0.75是程式門檻／待確認規則，不是經校準的正確機率。現有蘋果、便當截圖及單次真模型不能證明高辨識率、估重準確率或營養準確率。至少需以人工標註的食材名稱、食用狀態／範圍與秤重真值分別量測identity、compatibility、portion error、coverage及拒答率；30張只可作探索性試跑，不應作高信心宣稱。

**P2 UI驗收文案：**第83批截圖顯示摘要「目前沒有配對營養資料」與項目已找到USDA參考來源但尚未確認同時出現，語意矛盾仍待修正文案。這不阻擋後端alias測試，但使用者正式看到來源候選前須明確區分「有候選、未確認、未計入」與「沒有來源」。

**現行順序：**(1) authority context納入server-owned `needs_confirmation`／confirmed revision並加provider-call-zero測試；(2) 明確確認「青江菜」後加入受控英文FDC alias，保留泛稱拒絕及使用者候選確認；(3)驗raw／熟製相容與reference-only呈現；(4)挑選權利條件可記錄的真eligible miss，做隔離Tavily＋模型正向抽取；(5)只有正式啟用gate都通過後才審production flags與SQLite寫入。不得強迫local miss，不用已匹配蘋果測Tavily，也不聯絡FSANZ。

本批只做文件與程式靜態查核，未改程式、執行測試、呼叫Tavily／模型／USDA API、讀取私密runtime flags、操作SQLite、部署、提交或聯絡FSANZ。機器可讀摘要見[第九十三批證據](../food-nutrition-evaluation/2026-11-14/plan-flow-review-batch93-20261118.json)。

### 第八十五批：Researcher 免費方案範圍與青江菜來源候選（2026-11-17）

使用者回報 Tavily Researcher 免費方案，沒有 Order Form 或書面確認，專案為非商業大學畢業專題。官方 Help Center 明確說個人專案、免費 Researcher 以及由後端代理的客戶端搜尋可用；API key須留在伺服器，不可直接提供給終端使用者或轉售API。官方 Governing Terms 說API受Platform Terms治理，Terms又保留 internal-business-purpose 範圍文字，因此有限隔離技術試驗與公開／production開放需分開判斷：前者可依 Help Center 明確說明繼續評估，後者須保留適用條款依據或取得書面釐清。不能錯誤地說「免費方案一律不能用」，也不能宣稱此處已完成法律核准。

青江菜來源逐層審查結果不支持直接補值。MEXT 06338是「チンゲンサイ／葉／油いため」，葉片範圍不含整株可見莖。FSANZ AFCD F001300列有完整青梗菜外觀，但範圍是「fried, no added fat」且profile為recipe-derived，不能等同照片中未知油量的一般炒菜；其Data User Licence基於CC BY-SA 3.0 AU，分發需署名、ShareAlike及限制聲明，下載資料檔前須閱讀接受條款，本批未下載或代為接受。AUSNUT 2023第三方索引顯示一個含油、多種烹調法合併的候選代碼，但官方原始列、來源推算方法與授權尚未核實。搜尋結果和官方來源排序不會把通用「炒菜葉」變成已辨識青江菜，也不會補出照片看不到的油鹽配方。

目前通用Markdown adapter限定一個連續表格且最多64列，AFCD/AUSNUT資料的多區塊、零值/缺值語意及kJ能量映射均未測；可能需來源專用adapter。只有先核實原列及再使用權，才做一次隔離source-format抽取，並將其明確標成解析能力測試而非照片營養驗收。正式Web registry仍0、自動fallback關閉；本批未呼叫Tavily／模型、未讀key或帳戶頁、未操作SQLite、未部署。證據：[機器可讀候選審查](../food-nutrition-evaluation/2026-11-14/source-rights-candidate-review-batch85-20261117.json)。

**使用者範圍補充：**使用者接受不把添加油算入，目標是青江菜食材本體的參考營養，不是完整炒菜營養。第85批先將AFCD F001301 raw每100g列為主要候選、F001300無添加脂肪熟製列作比較候選；該批尚未核對F001301實際分析portion。第86批確認F001301為80% leaf & stem分析、20% end of stem未分析。raw每100g不能直接乘熟菜估計克數而宣稱精確。下一步由第86批更新為先核實資料權利與欄位來源型態，再決定是否做有界schema／adapter測試；任何解析測試都不代表圖片上的菜名或portion營養已驗收。

自我挑戰：這次瀏覽已找到更完整且更近似的官方候選，但仍存在把「名稱相同」誤當「烹調等價」的風險；不應因AFCD的正式程度就放寬 prepared/stir_fried/whole-plant 相容條件。下一個證據應同時回答準備方法、可食部、原始值/缺值、授權和實際抽取格式；任一不合就保留未知值。

### 第八十六批：青江菜官方來源原列與使用者範圍複核（2026-11-17）

使用者澄清可以不計添加油，直接取得青江菜食材本體營養。這僅明確排除添加油；沒有擴寫為使用者已確認鹽或醬料政策，也不計算完整炒菜營養。

查閱FSANZ AFCD官方 F001301 與 F001300 詳細頁及Data User Licence。F001301為raw、每100g；其說明為白至淡綠色莖與深綠葉，Analysed Portion=80% leaf & stem，20% end of stem標示unanalysed。營養來源跨1997／2001／2005／2021採樣與文獻，tryptophan imputed from savoy cabbage，並有列為imputed zero的欄位；因此固定抽取schema必須區分測量／來源推算／imputed zero／缺值，不能把所有零值當成同一語意。F001300是fried, no added fat，Derivation=Recipe，作熟製比較而非已辨識照片配方。來源每100g行不自動等於照片熟菜實際portion。

AFCD Data User Licence基於CC BY-SA 3.0 Australia；使用包括正確署名、公開衍生作品遵循同授權，以及隨散布附上data limitation與澳洲資料可能不適用其他國家的聲明。官方頁明示下載前須讀並接受條款。本批只有讀取條款與官方food-detail網頁，沒有接受條款、下載檔案、把營養值複製進公開證據、呼叫Tavily／模型或准入source。分發授權與第三方材料例外仍需具體評估，不能僅憑CC標籤推定app和持久化營養profile均已獲准。

結論：使用F001301作生鮮每100g的待審候選；清楚標示生鮮基準，不按熟菜估重換算精確份量，不稱為整道炒菜。下一步先審查CC BY-SA對本專題app、資料庫持久化及模型抽取結果分發的適用性，並落實營養欄位來源型態／imputed-zero映射；只有授權足以支持後才進行單來源Tavily／模型adapter測試。完整證據：[機器可讀來源審查](../food-nutrition-evaluation/2026-11-14/source-rights-candidate-review-batch86-20261117.json)。

### 第八十七批：FSANZ AFCD公開使用與持久化授權範圍（2026-11-17）

核對[FSANZ Data User Licence Agreement](https://www.foodstandards.gov.au/science-data/monitoringnutrients/afcd/datauserlicenceagreement)及[CC BY-SA 3.0 AU legal code](https://creativecommons.org/licenses/by-sa/3.0/au/legalcode.en)。條款將數位保存列為reproduction、公開電子傳輸列為distribution；散布Work需隨每份副本提供授權URI、limitation statement、澳洲資料不一定適用其他國家的聲明及合理署名／免責資訊；散布Derivative Work需使用相同授權，但條款說明Collection整體不必因此一併採相同授權。條款亦指明AFCD含第三方資料，FSANZ不保證重用不侵害第三方權利。

工程解讀：若SQLite保存的是受保護Work，持久保存落入條款所稱reproduction；若API／UI傳送內容屬Work或Derivative Work，可能落入distribution。但官方條文沒有直接判定一筆F001301資料、所選營養欄位或模型轉成固定JSON profile是否構成substantial part／Derivative Work，也未說明這種profile和整個app的授權邊界。條款沒有明列非商業畢業專題豁免，故不能用非營利身分推定已豁免；也不能從條文直接斷言app整體必須改採CC BY-SA。上述是條款閱讀與風險辨識，不是法律意見。

**決定：**暫不接受授權、下載AFCD檔案、複製真實營養格、執行Tavily／模型來源抽取或將F001301准入。下一步需取得FSANZ針對此實際流程的書面答覆：免費公開非營利app能否將單筆選定營養值／provenance保存於SQLite及user-specific snapshots／備份，並以API、畫面及匯出提供給使用者；欄位映射後的profile是否為衍生作品、ShareAlike只適用資料profile還是應用程式其他部分；每個API／UI／匯出／保存副本需如何附授權、署名、限制聲明及澳洲適用性警語；F001301是否有須另行清理的第三方來源。完整問題、條款摘錄與未決事項見[機器可讀審查](../food-nutrition-evaluation/2026-11-14/source-rights-candidate-review-batch87-20261117.json)。本批未接受條款、未下載資料、沒有Tavily／模型／資料庫／程式／部署操作。

### 第八十九批：FSANZ 權利釐清詢問草稿（2026-11-17）

查閱[FSANZ聯絡頁](https://www.foodstandards.gov.au/contact)及[官方詢問表單](https://www.foodstandards.gov.au/contact/enquiry-form)。頁面將一般問題導至詢問表單，且註明只能提供一般資訊。已準備[英文詢問草稿](fsanz-afcd-clarification-request-2026-11-17.md)，說明台灣大學非商業畢業專題與free public app，請求就AFCD F001301單列值的SQLite持久保存（含user-specific profile／meal snapshots與備份）、authenticated API/UI/匯出、Tavily與AI模型協助定位來源及選取欄位後由server驗證、notice／attribution落點、固定JSON是否為Derivative Work／substantial part、ShareAlike邊界與third-party lineage提供一般資訊。草稿請FSANZ若超出表單範圍，指引或轉介適當AFCD licensing contact。

草稿未提交，沒有替使用者填姓名／學校／email或送出表單。沒有接受授權、下載AFCD資料、附上照片／key／數值或寫入證據真值。下一步由專案負責人自行審閱、補聯絡資訊並提交；保留提問文本和回覆，逐項檢查回覆是否覆蓋實際資料流。送出詢問本身不等於取得使用權或法律核准。完整操作界線見[機器可讀紀錄](../food-nutrition-evaluation/2026-11-14/fsanz-afcd-clarification-draft-batch89-20261117.json)。

### 第九十一批：MEXT／CoFID／Health Canada CNF 替代來源初篩（2026-11-17）

為依使用者指示停止聯絡FSANZ並繼續找合適來源，查核MEXT、CoFID與Health Canada CNF的官方reuse說明及青江菜原列。MEXT表示資料可自由使用並要求二次利用註明標準成分表來源；但官方06160是「Green bok choy/leaves, raw」，葉片範圍不能當成整株青江菜。CoFID官方GOV.UK頁面最後更新為2021-03-19，並指出部分舊食品未在後續版本重新審核；這批沒有下載Excel或從官方原始workbook確認精確bok choy列，故先不採用。

Health Canada CNF官方指南有明確較可操作的條件：CNF 2015允許商業／非商業使用、要求標示Health Canada為來源、營養值不得修改但可表達不同份量，並要求免責／非背書／參考用途說明。官方API指南說明JSON／XML供自有應用使用，nutrient amount提供可食部每100g均值、sample/standard error與source id。以唯讀food-description endpoint查詢code 2038，回傳`Bok choy, pak-choi, raw`；未呼叫nutrient endpoint。Health Canada現行頁明示線上可查的是CNF 2015，2026版目前提供資料檔；Open Government Portal metadata將CNF 2026列為Open Government Licence - Canada，但本批未下載2026資料，也未確認2026 code 2038或第三方source lineage。2015 API條款和2026下載資料授權不能混為同一路徑。

**決定：**CNF是目前最有希望的替代候選，不是已核准source。需先核對2026版code與source IDs、比較是否只是USDA/FDC既有資料的重複來源、確認本地TFDA／USDA miss條件，並決定直接API應位於第三層的source registry或是否仍使用Tavily／模型一般搜尋。portion仍需尊重資料基準；raw每100g不能直接當照片熟重的精確營養。production registry仍0、自動fallback關閉。完整資料及請求範圍見[機器可讀證據](../food-nutrition-evaluation/2026-11-14/alternative-nutrition-source-screening-batch91-20261117.json)。

### 第九十批：Gemini AFCD 授權說法核對與下一步調整（2026-11-17）

使用者提供Gemini對「下載勾選／直接API／署名即可」的說法作參考，並指示不需寫信給官方。重新查閱[FSANZ Data User Licence Agreement](https://www.foodstandards.gov.au/science-data/monitoringnutrients/afcd/datauserlicenceagreement)及[AFCD Data files頁](https://www.foodstandards.gov.au/science-data/food-nutrient-databases/afcd/data-files)。官方授權明文寫出「行使Work授予的任何權利，即接受並受條款約束」，因此「只有下載當下按checkbox才發生接受」不是條文所支持的限定；也不能因第三方API沒有接受參數，就推論資料用途不受原授權約束。官方Data files頁目前描述Excel工作簿供載入自有軟體與操作，沒有據此確認有官方AFCD API。若來源是第三方API，仍須另外識別該API的供應者、來源與使用條款，不能假設它繞過資料權利。

Gemini提到署名、不得暗示FSANZ背書及資料無擔保，方向部分正確但不完整。條文的散布條件還包括授權URI、limitation statement、澳洲資料可能不適用其他國家的聲明、保留版權／免責通知；衍生作品另需按同一授權散布並合理標示修改。對固定JSON profile究竟是Work、Derivative Work、Collection中的作品，或僅是未受著作權保護的事實／數值摘錄，頁面未直接判定；第三方資料風險也明列保留。故本輪不將Gemini結論採為法律判定或來源准入依據。

**使用者決定與流程更新：**使用者指示不需聯絡FSANZ，不寄出第89批草稿。該草稿只保留為未提交歷史參考，不再列作下一步；這不代表授權問題已解決。AFCD F001301繼續排除於source registry及production fallback之外，沒有接受授權、下載檔案、複製營養值、呼叫Tavily／模型或改動SQLite／程式。下一步改為檢查可用替代來源的官方授權、精確食品列及營養欄位涵蓋；只有來源授權及資料範圍都清楚後，才做隔離adapter/schema測試。證據：[第九十批機器可讀紀錄](../food-nutrition-evaluation/2026-11-14/source-rights-gemini-claim-review-batch90-20261117.json)。

### 第八十八批：AFCD欄位來源與缺值語意設計（2026-11-17）

比對目前 `NutritionProfileV1`、`NutritionExtractionV1`、Markdown adapter 與 relay selector。Profile V1保留原始數字、單位、exact／less_than、cell evidence、缺值null及upper bound；adapter將dash、em dash、N/A折成null，未保留缺值理由或value origin。Evidence contract由模型選 server-issued row ID；模型不回填數字或來源狀態。V1 `nutrition_status`依可用point值決定，因此若資料列含imputed zero，現合約無法在profile／coverage中區分它與分析零，且增加未授權欄位會被嚴格校驗拒絕。

提出但未實作的版本化語意：profile層記錄食品列derivation（analysed／recipe／calculated／mixed／unknown）；欄位層區分analytical、source-derived、imputed、imputed-zero與missing reason（not-reported／not-analysed／not-applicable／unknown）；exact／less-than仍是獨立比較維度。imputed-zero必須有官方文字依據且原值正好為0；只有dash而無明確註記時採unknown null。分類由server-owned來源adapter依官方metadata賦值，模型只做欄列選擇。未來coverage需把「有數字」與「實測品質」分開，且不要將numeric complete標作all-analytical complete。

這是契約設計草案，需專案schema review並受第87批來源權利gate約束；現階段不得把該提案當成已支援AFCD、不得把status塞進V1、不得抽取真數值或寫入SQLite。詳細實作邊界與檢查結果見[機器可讀設計證據](../food-nutrition-evaluation/2026-11-14/nutrition-field-semantics-design-batch88-20261117.json)。本批只讀五份服務程式檔，未做web/model/provider/DB操作、未改程式或部署。

### 第八十三批：Android 蘋果相簿確認與營養 preview 畫面複核（2026-11-17）

檢視使用者提供的四張 Android 一般 HTTPS scanner 截圖。畫面依序顯示「蘋果（98%）」待確認、通用蘋果估重180g及`USDA FDC 171688 · SR Legacy`參考來源、名稱／份量已確認、唯讀preview。預覽中每100g九項值乘1.8後與180g畫面值一致（依顯示精度捨入）；畫面明示估重來自影像而非秤重，且preview未寫入掃描結果或飲食紀錄。這是使用者操作後的畫面證據，不含network trace或後端DB觀測；不能獨立證明provider呼叫數、目前runtime flags、profile／meal寫入或營養準確率。沒有代替使用者操作或保存資料。

發現首頁摘要「目前沒有配對營養資料」和同一畫面「已找到相容的 USDA 參考營養」語意不一致；實際狀態應表述為尚無已確認並計入的營養、項目等待確認。截圖沒有提供克數編輯控制，僅能重申份量是低信心影像估算，不推定其他畫面不存在調整功能。

這組截圖使用USDA FDC 171688，不是Tavily第三層驗收；local-first下既有相容來源應短路Web fallback。惟無request trace，截圖本身也不能確認實際Tavily request count。Tavily registry仍空、自動fallback關閉，來源／publisher准入及真頁正向採用仍是後續gate。逐圖hash及證據界線見[機器可讀證據](../food-nutrition-evaluation/2026-11-14/android-apple-preview-screenshots-20261117.json)。本輪只檢視畫面和更新文件，未修改程式、部署或呼叫模型／USDA／Tavily。

下一步沿既有來源准入工作：先明確核可可檢索與展示／保存的Web來源，再用真正eligible local miss驗證Tavily→固定schema抽取→後端檢查→使用者確認；不強制讓已命中USDA的蘋果走Tavily。

### 第八十二批：蘋果照片與影像身分／營養檢索分界（2026-11-17）

蘋果原圖實際是WebP（副檔名jpg），現有decoder按內容signature正確傳`image/webp`；原始位元組未改。以現行prompt／真relay單次經正常Flask vision及reviewed-selection路由，臨時SQLite、test-only authentication、TFDA／USDA實際資料集及明確安裝的171688政策。輸出蘋果、raw、with_skin、brand=null、confidence0.98、180g／weight confidence0.5；TFDA與USDA FNDDS均無相容命中。隔離selection產生唯一reviewed_match，要求明確user confirmation；沒有Detail、confirm、preview、model nutrition extraction或Tavily。reported tokens3252、8.9秒、0重試、費用未知；沒有正式DB／部署改動。

此次回應支持現行提示詞能在這張圖回通用名與可見皮膚狀態，但不證明image ground truth、品種、校準confidence或估重準確。Logo位於背景而非食品包裝，模型沒有將它當食品品牌，品牌欄null。171688的結果是相容的generic source候選，不是模型認出品種，也未代表網頁營養流程已實測。

修訂第三層計畫：視覺辨識已在現有第一模型回合完成；不需先多呼叫一個模型「猜品種」。TFDA→相容USDA/FDC均查無後，才把保存的通用品名及可見狀態／範圍交由Tavily找准入來源。模型僅能按既有固定schema擷取檢索原文欄位、份量基準、單位及來源；後端獨立核對相容性、來源格、缺值及算術。Tavily不辨圖，relevance score不是身份信心；營養頁不能反推照片身份或提高vision confidence。歧義時停止，保留未確認而不生成數字。此為企劃修訂而非啟用；Tavily registry仍空／fallback off。[機器可讀證據](../food-nutrition-evaluation/2026-11-14/scanner-apple-identity-20261117.json)。

下一步仍在既有照片驗收範圍：由使用者在正常HTTPS scanner檢查此圖的「蘋果」、估重及171688參考/確認畫面；隔離test_client不是手機端到端。確認與保存須由使用者操作；目前後端正式執行版本及私密旗標未重新核實。

## 範圍凍結結論（2026-11-15）

### 第八十一批：真便當照片與本機優先限定核對（2026-11-17）

未改程式，使用原便當JPEG、現行prompt／真relay、正常Flask vision及reviewed-selection路由與臨時SQLite；測試登入驗證為隔離owner，不是正式密碼登入／Android相機驗收。已審171688只安裝於臨時DB；保留真本機資料與lookup，不強迫miss。取得vision200／selection200、7項strict validation無issues，TFDA配白飯／豆干、USDA配滷雞腿／茄子，後兩項的TFDA無相容命中；沒有同一項兩層皆相容的競爭例，不能稱全域排序已由單張證明。4項核心原格換算與已配對合計713kcal／570mg鈉吻合；仍有3項未計，optional缺值與legacy數字placeholder限制保留，不能當九項完整營養或整餐真值。

兩份葉菜各有不同ID，confidence0.72／0.75仍屬泛稱，selection為identity_required；先前使用者回報的大陸妹／青江菜未由本次模型確認，不能用Tavily搜尋反推菜種。熟毛豆與本機候選狀態不相容而拒配，selection的local_priority在此表示阻擋不相容本機結果向外升級，不是已成功配對。7項皆無FDC候選；scan／snapshot各1、confirmation／preview／profile均0，沒有呼叫餐點保存。臨時DB已關閉且目錄移除。

留存真模型請求1次／0重試，reported total_tokens7311、elapsed33.061秒；先前inline執行未回輸出且沒落證據，0–3次實際呼叫不可恢復，不納入驗收，本批只可聲明總呼叫1–4次、費用未知。Tavily／USDA呼叫0。本次正常路由以test_client執行，沒有瀏覽器／正式掃描操作；缺少一般帶皮生蘋果原照，原定正式真照片及條件式171688確認→preview仍未通過，不重做固定手機fixture或放寬身分。

自行核對發現服務已在測試前重啟：5000／PID14912、started_at=2026-11-17T17:24:35.717018+08:00；本機／公開health仍v1.0.3／SQLite／auth true／automatic fallback false，scanner及entry200且hash同第78批。9份第79批程式hash未變，但本批沒查正式啟動事件／私密flags／policy／key，不能推定第79批程式已載入或尚未載入。初次唯讀核對因沿用第80批started_at斷言失敗，後續保留新觀測並修正最新摘要；沒有嘗試回復舊服務。本批無程式修改／部署／正式資料寫入／完整回歸／commit／push。[機器可讀證據](../food-nutrition-evaluation/2026-11-14/scanner-real-photo-local-priority-20261117.json)。

### 第八十批：企劃進度一致性核對（2026-11-17）

依使用者要求，比對現行程式、第70至79批證據、主企劃各摘要及運行服務。發現首頁狀態仍提第一批、第13節沿用沒有真來源adapter／HTTP接線的早期說法、第22節缺第69至73及75至79批且第74批順序錯置，六個工作流未清楚標出已完成Detail與手機子項，驗收索引另有第71批舊段落標為「最新」。現已修正相關正文與表格，補上歷史閱讀界線、空Tavily registry與已安裝FDC171688的區別，並同步交接。原始每批證據、失敗結果、授權與未完成門檻不改寫。

唯讀核對排程Running／5000 PID32084、本機與公開health ok／v1.0.3／SQLite／auth true／automatic fallback false，started_at及本機／公開／磁碟entry仍與第78批相同；第79批9份程式／測試hash吻合。未直接讀私密flags／key檔或正式policy列，細項維持第78批發布證據的範圍。health會經既有repository讀取筆數並檢查relay設定，已修正初稿「完全未存取DB」的不精確說法；本輪沒有直接連DB、正式資料寫入、重跑完整測試、真模型／USDA／Tavily呼叫、設定變更、重啟／部署或commit／push。第79批清理仍未部署。

結論：修正後現行摘要一致，已實作／隔離驗證／正式限定發布／尚未驗收分開標示；不將本次文件核對算成新功能、真照片或營養準確率通過。唯一接續項仍為一般scanner真照片的本機優先、可見身分與條件式171688確認→preview，無新增工作流，不重做固定手機fixture。Tavily准入／真頁正向採用、新來源正式保存與跨使用者cache門檻保留。詳細觀測、修訂與檢查見[進度核對證據](../food-nutrition-evaluation/2026-11-14/plan-progress-reconciliation-20261117.json)。

以下依批次保留歷史複核；其中「下一步／關閉／未部署」描述各批當時狀態，不覆蓋上述結論。

### 第七十九批：現行文件與廢止部署路徑清理（2026-11-17）

已先將使用者插入的清理工作寫進主企劃，再逐項核對引用與行為。Render Blueprint、Pages自動發布、Procfile及Render專用signup／bind／health環境分支已移除；可選Mongo初始化、pymongo依賴、儲存分支及假Mongo測試均清除。SQLite／明確暫存記憶體介面保留；22處呼叫全部對齊。DATABASE_URL拒絕、health.mongo=false、遷移與舊飲食合約及仍被引用的直接模型路徑有現行用途，未因名稱舊而刪除。

實際發現前端推薦失敗後會用原auth headers轉送其他後端的舊fallback，已移除環境變數消費與重送，以3項行為測試核對同一伺服器目標與診斷。主README／PRD／部署／架構／維運／env範例及註解已對齊Windows排程＋Tailscale Funnel＋SQLite；舊架構與維運全文另外保存，過時雲端計畫、多Agent指令及交接文件標為歷史。新增文件索引與架構快照索引。既有Word／Excel與測試原始證據不改寫；開發Docker範例僅修正port binding，未宣稱建置或正式採用。

完整後端1143 passed／1273subtests，0failed／skipped、69.89秒；前端營養145、scanner25、設定／連線目標11、typecheck／lint及暫存same-origin匯出通過。最終20份Markdown連結／fence、191份Python AST／22處constructor引用及git diff空白檢查通過；44份公開／來源／建置文字對7組已知私密值掃描0命中，9份來源hash一致。首輪測試sys.modules回復造成bcrypt重載問題及缺key訊息斷言均已修正，最後完整回歸通過；urllib初次信任鏈失敗改用正常驗證TLS的requests完成核對，未繞過憑證。詳見[清理證據](../food-nutrition-evaluation/2026-11-14/deployment-legacy-cleanup-20261117.json)。

同一代理自行複核，未另開代理；已核對範圍未發現新增阻擋缺陷，不宣稱所有歷史內容已改寫或全域無廢碼。本機／公開health及scanner entry保留第七十八批started_at與雜湊，正式env／dist／SQLite／flags均未改、未重啟／部署。真模型／USDA／Tavily呼叫0，未commit／push。既有下一步仍為正式一般scanner真照片的本機優先、通用名稱／可見身分與條件式171688預覽驗收；本批整理與暫存建置不能代替該證據，也不重做固定手機fixture或放寬相容性。Tavily／accept／新來源飲食保存及cross-user cache仍排除。

### 第七十八批：單一來源預覽發布與回復準備（2026-11-16）

已完成既定受控發布，不再以另一輪規劃替代部署。發現並補齊唯一接線缺口：正式app原本只讀Python tuple，現在可用server-only `FDC_REVIEWED_SOURCES_FILE`明確指定與安裝CLI相同的一欄JSON。沒有路徑時仍空預設；相對路徑、混用tuple／檔案、缺檔、重複key、無效UTF-8、超限、額外欄位及未安裝／withdrawn均拒絕。兩個新增測試驗證讀檔不安裝／不復活、DB bytes不變及診斷不洩漏路徑；既有四次新app程序測試改走真環境設定接線，保留active重啟／withdrawn／empty檢查。

舊env、完整dist與資料庫備份留在Git外，隔離副本先安裝／審查／啟動通過；原USDA key以一次固定Detail實測有效，正式adapter完整驗9營養及150g78kcal。之後依既有排程停止→正式digest安裝→env與same-origin建置切換→重啟。運行v1.0.3的私密啟動診斷以started_at綁定health，確認恰一來源、3個required旗標true、4個excluded旗標false及key可用。公開／本機／磁碟entry雜湊一致，公開不洩漏DB路徑，7條匿名POST均401；SQLite quick_check=ok，來源政策／歷史各新增1列，其餘檢查的列數不變。回復只還原設定與dist，不以整庫覆寫後續使用者資料，也不復活撤回來源。

完整後端1142／1282subtests通過，149.76秒，發生在最後加入不含機密的啟動診斷之前；最終focused38／72subtests、11.09秒及build-config8通過，均0failed／skipped。清快取匯出已成功；14個文字輸出掃描7組已知機密值皆0命中。前端公開旗標另保留於ignored frontend/.env.local，避免下次一般build遺失開關，沒有放server key。無UI原始碼更動、無重做Expo／Android固定fixture；模型／Tavily／Search0，僅真USDA fixed Detail1。

自行複核未發現本批範圍新增阻擋缺陷；不等於正式真照片辨識／估重／prompt遵循率通過。本機已命中不得強迫fallback；171688只限可見帶皮生蘋果，不推斷富士。正式Tavily仍空／automatic fallback=false，accept／飲食保存與cross-user cache仍排除。下一步是一般scanner真照片的本機優先與條件式preview驗收，未通過時記錄原因，不降相容性門檻或新增工作流。未commit／push。詳見[發布證據](../food-nutrition-evaluation/2026-11-14/fdc171688-preview-release-20261116.json)。

### 第七十七批：實際上線前檢查與policy ID落差修復（2026-11-16）

已讀取實際scheduled task／PID、本機health、現行.env必要欄位及正式SQLite，只輸出非機密觀測。排程指向目前checkout，但既有程序health仍v1.0.2；不能因git branch是v1.0.3就宣稱已更新服務。SQLite路徑與health相符、不受AppData導向阻擋，mode=ro／query_only的quick_check=ok、來源表存在但171688無安裝列。登入health確認開啟，本機及既有公開Funnel的scanner／entry皆200，entry hash一致且等於disk。未新增Funnel、server或手機fixture。

部署仍須配置：原USDA KEY.txt存在且恰有一個正確格式key，但目前dotenv未提供USDA_FDC_API_KEY；不能把檔案存在當成server client已可用，也不能把正確格式當live有效性。production明確tuple仍空，現行dotenv的required／excluded後端開關均false。這是新helper加目前檔案的觀測，不是舊程序環境；health只證明auth與automatic_web_fallback=false。五個frontend baked flags仍未觀測，缺少frontend dotenv或entry hash一致都不能代替建置證據。實際repo及prospective171688＋正式只讀DB兩份審查均blocked；無需再請使用者申請或重交已有key。

本輪重現一個設定審查假陽性：安裝列policy_id錯誤而policy JSON完整相同，review先前回configuration_ready，但batch76 loader會blocked。已補policy_id精確一致判斷，更新fixtures及真temp SQLite regression，review／startup皆blocked且DB bytes不變；缺欄位／null也拒絕。既有negative revision本來就拒絕，不列本輪新修復。focused36 passed／64subtests，0failed／skipped、13.14秒；未重跑full backend，無UI變更，沒有新Expo／Android或真照片準確率證據。

同一代理自行複核，未另開代理。本批讀了正式DB及私密設定／key檔，但無正式application SQL寫入、credential輸出、provider請求、設定／flags／registry修改、build、重啟、部署或commit。5000／PID16352保留，8090無listener。下一步沿既有備份→server-only key→明確單來源配置／安裝→最小開關／same-origin建置→受控重啟及local/public smoke的發布流程；不重做本次檢查輪或固定手機fixture，不開未核可Tavily、accept／meal／跨使用者cache。所有觀測與限制見[公開證據](../food-nutrition-evaluation/2026-11-14/fdc-preview-rollout-preflight-20261116.json)。

### 第七十六批：明確安裝與啟動載入（2026-11-16）

本批完成上一批已列出的實作子項。新增來源lifecycle service、明確安裝／只讀檢查CLI及專用SQLite install-if-absent方法，正常app啟動接唯讀來源載入。候選檔不自動被發現或准入；production tuple仍空。CLI恰一欄reviewed_sources的來源配置與上批五欄開關觀測snapshot用途不同，操作手冊已分開說明，不能直接套候選artifact外包裝。

審查找出舊save_source_policy在CAS更新時會設回active，不能用於啟動。新安裝單一BEGIN IMMEDIATE內只新增current／revision0歷史；完全相同active來源回already_installed，沒有timestamp／revision漂移。withdrawn與不同政策不更新，即使新政策另有有效admission也不能用安裝命令取代舊政策。明確digest與完整admission／candidate驗證位於lifecycle service，並非宣稱底層通用repository的所有呼叫均受新准入閘門控制。

啟動整組檢查明確配置：缺少、inactive、identity／policy ID／policy不符、revision無效、配置重疊或讀取錯誤，都不載入並停用reviewed-selection；空配置亦停用。source loader本身無寫入，app既有schema初始化／遷移仍可能寫DB，不把整個啟動說成唯讀。已載入後撤回仍由每次selection／preview的既有current-policy檢查攔截，載入不是跨時間鎖或撤回豁免。

15項新測試涵蓋真temp SQLite兩次reopen、readonly bytes不變與寫入拒絕、未配置Fuji不被發現、撤回不復活、內容漂移、history寫入失敗全回滾、兩連線安裝及安裝／CAS撤回競爭、CLI缺檔／schema／digest。另啟動4個全新app程序：前兩次active載入成功，撤回後blocked且route停用，空配置時empty且route停用；這是實際app import／SQLite接線，不是HTTP服務或真照片辨識驗收。最終focused51／71subtests，完整後端1139／1272subtests，0failed／skipped，143.11秒。

同一代理自行複核，未另開代理；本批限定測試範圍未發現新增阻擋缺陷，不宣稱零缺陷、影像準確率或模型新prompt遵循率。無UI變更或重複Expo／Android驗收；無真provider、金鑰檔、正式DB讀寫、flags／tuple變更、服務重啟／部署或commit。正常5000仍PID16352，8090無listener。正式Tavily來源仍未准入。下一步只接既定171688單一來源受控部署核對，沿用上一批最小開關矩陣與現有備份流程，不新增工作流。[機器可讀證據](../food-nutrition-evaluation/2026-11-14/fdc-reviewed-source-lifecycle-20261116.json)。

### 第七十五批：來源安裝與最小開關准入（2026-11-16）

本輪完成既有最後設定審查，結論不是全面上線。首批最小範圍為171688一般帶皮生蘋果的系統選用、使用者明確確認及營養預覽；Fuji1750340仍限其身分，暫不列首批配置。原始Search／Detail對外route、accept／飲食保存、Tavily與跨使用者cache均排除。fixed Detail由preview service內部取用，不需要因此打開原始Detail HTTP route；FDC preview也不依賴Tavily enrichment signer。辨識模型仍只負責影像，不產生營養數字或代做數值計算。

新增`fdc_preview_admission_service.py`與`tools/review_fdc_preview_admission.py`，重用真selection的admission／descriptor／policy檢查，逐一核對SQLite/auth/server key的明確布林觀測、兩份本機資料健康、前後端各3個required flags與全部excluded flags、installed policy active／完整相等／revision型別。配置內重複ID及多來源相同identity也拒絕。不能把字串false、整數1、未觀測值當作已通過；policy loader錯誤不回傳路徑、SQL或secret。

工具預設只讀repository defaults與實際本機dataset，不import app、不載dotenv或金鑰。顯式指定SQLite時以mode=ro／query_only及同一讀transaction取目前政策，不建立schema、不安裝或復活撤回來源。即使完整明確配置與暫存SQLite通過，結果也只為configuration_ready、deployment_authorized=false；它不是正式loader、權利新授權、執行期強制閘門或跨時點交易保證。部署時仍須重新核對安裝／runtime／已建置frontend一致性。

預設實跑為blocked：reviewed FDC設定空，required repo flags全false，正式DB／auth／server key未觀測。這不是宣稱正式DB沒有政策或金鑰缺失；也沒有把checkout預設冒充運行中後端或前端bundle。預覽是營養讀取範圍，仍寫scan／snapshot／confirmation／preview狀態，不能稱整個資料庫無寫入。SQLite-only與既有六工作流維持。

重新查核官方USDA API Guide：資料CC0／public domain，保留來源標示與server-only key要求。Tavily Platform Terms顯示2026-05-04更新，本次未找到可一概允許保存與跨使用者cache的條款；未查帳戶Order Form或取得publisher核准，維持排除。不能把服務端API可用、公開網站或既有程式布林值當權利證據。這是技術准入審查，非法律意見。

測試結果、發現與限制統一記於[本批證據](../food-nutrition-evaluation/2026-11-14/fdc-preview-admission-review-20261116.json)。首次重複來源斷言失敗是registry較早拒絕，刪除重複診斷後改驗原嚴格拒絕，未降低條件。無UI修改、正式DB讀寫、來源安裝、provider呼叫、重啟／部署或commit／push。同一代理自行複核，非獨立審查。下一步只實作既有明確安裝／重啟載入與撤回不復活的隔離驗證，之後依本矩陣受控部署；不再將本次設定審查當作下一個未完成項。

### 第七十四批：系統選用與使用者確認分開（2026-11-16）

正常scanner新增預設關閉的已審查來源選用路徑。伺服器只接受scan ID／revision，不接client重量、品名、來源ID或營養數值；必須先確認兩份官方本機資料健康，且lookup明確為no_local_mapping。來源必須通過完整admission digest、精確identity相容及已安裝active policy一致性；多筆相容、撤回、未安裝、政策漂移、低信心、泛稱、未知skin／做法、錯owner及過期均不能取得可選來源。本機hit、conflict、partial或incompatible不被當成可外查的miss，原始Search快照也不能被改寫成已審核選用。

這條路徑只建立唯一參考快照，不等於使用者確認，不取Detail、不建profile。使用者看到「蘋果・估計150g」，來源原文可展開；明確選取並確認後，仍由既有confirmation簽發revision1，再取fixed Detail並核對server重量。主名稱與來源身分分離，且photo confidence不變。首次互動發現確認後radio因choices清空而失去選取，已改讀server completed item；Web又未從accessibilityState輸出aria-checked，已補明確屬性並驗為true。殘留「候選」及預覽成功後仍寫等待Detail的文字一併修正。

Expo dev server再次於執行前被自動審查拒絕，未重試等價dev命令；允許的隔離靜態export／原test harness成功完成真hydration及HTTP互動。乾淨session用單一CLI選檔，vision200→reviewed-selection200→confirmation202→preview200；每100g52kcal、150g78kcal及九個值來自既有真171688capture離線回放。合成vision回蘋果150g、強制local miss、icon當上傳fixture，不能用來聲稱真照片辨識或本機沒有蘋果。AuthGate使用預置測試session，非帳密登入驗收；未攔截營養／vision API。

首次把run-code filechooser listener和CLI upload混用造成重複change／removeChild錯誤，已改單一路徑；最終新session全程console error／warning均0。375／390／430／768／1440寬度無水平溢出，390與1440截圖已檢視、文字及來源換行正常。最終確認／preview段隔離SQLite confirmations2→3、previews2→3、scan contexts7→8，profiles與meal records均0；累計offline Detail3次，本輪真模型／USDA／Tavily均0。

本批前段完整後端1120／1224subtests、180.49秒通過，後續只改UI／recovery；接續focused backend17／27subtests、nutrition145、scanner25及typecheck／lint通過。enabled測試export與disabled flags的`npm run build:web`都輸出到系統暫存資料夾，後者確認不含8090測試origin或test token，沒有替換正式dist。機器可讀證據：[fdc-reviewed-selection-browser-e2e-20261116.json](../food-nutrition-evaluation/2026-11-14/fdc-reviewed-selection-browser-e2e-20261116.json)。

同一代理自行複核，未另開代理；未發現本批限定流程新增阻擋缺陷，仍非零缺陷或正式啟用許可。正式Web registry／reviewed FDC配置為空，未安裝policy、改flags、寫正式DB、重啟／部署或commit／push。下一步只回既有來源安裝與registry／flags最後准入，不再重做已完成的固定手機fixture；Tavily未核可來源維持排除。

### 第七十三批：通用來源與影像身分傳遞（2026-11-16）

使用者已補充授權後續需要的完整Expo互動測試，已寫入主計畫；既有環境拒絕保留為歷史限制，本批沒有UI改動或Expo啟動，不能宣稱互動缺口已消失。仍沿用六工作流，沒有新資料庫或功能。

單次真USDA固定Detail回傳171688完整原名（含Food Distribution Program）、SR Legacy／NDB9003、110列營養及原始擷取envelope。新增通用來源候選與hash-bound review，與1750340富士限定候選分開；未知品種的蘋果不需改名。`with_skin`是既有variant欄位中的帶皮狀態，不是品種；若skin未知、去皮／熟製／果汁／brand／scope不相容仍拒絕。raw+mixed僅作明確未加熱蘋果的舊enum約定，沒有把unknown當wildcard。這項做法有明確限制：新的prompt是否能穩定提供正確skin／method仍需真照片測試，不能由合成identity的通過推論。

實測修正兩個具體缺口：vision response producer原本遺失brand／variant，現在加入optional型別／長度／控制字檢查並完整傳至scan adapter／SQLite，原name／confidence／weight confidence保留；candidate未列真source原文時，preview可成功但accept會source_conflict，已增加完整審查原名與新digest，沒有放寬底層profile驗證。反式脂肪0由真605列取得；缺值仍不補0。generic／Fuji policy順序互換時匹配結果不變。

來源證據與驗收分開：[真capture來源](../food-nutrition-evaluation/2026-11-14/fdc-generic-apple-source-20261116.json)、[離線保存回放](../food-nutrition-evaluation/2026-11-14/fdc-generic-apple-acceptance-20261116.json)。temp SQLite preview不寫profile、accept一筆、兩次reopen、冪等／owner／撤回及歷史留存通過；原Fuji回放亦成功，兩null不變。這不是手機飲食保存、process crash或真影像品種驗收。先前簡化171688 fixture即使數值相同仍是synthetic，不能回溯改稱真source測試。

新增測試5項、focused60／104subtests通過；最終完整後端1110／1210subtests、0failed／skipped、141.94秒。Python編譯通過。provider實際USDA Detail1、Search0、Tavily0、模型0、重試0；來源權利沿用既有官方證據，並非新Tavily方案／publisher核准。同一代理自行複核，未另開代理；未發現本批範圍新增阻擋缺陷，但已知正常scanner免選原始資料列的系統接線尚未完成。下一步在既有工作流4設計並實作server-owned來源選用與使用者份量確認的明確邊界，再用已授權隔離Expo驗證。正式policy repository／Web registry／flags／服務未操作，無commit／push。

第七十二批歷史補充（通用來源由第七十三批接續）：使用者不應理解資料庫品種才能完成一般食材辨識。已將通用名稱、來源身分、系統配對責任與未知品種不等於未知食材寫入主計畫，修改prompt及候選／preview來源標示；原候選面板仍是受限核對，未宣稱日常自動配對完成。未知蘋果不能透過改名或選取富士候選繞過name／variant匹配。

既有真USDA capture的canonical hash與前次公開replay證據一致，無新API呼叫；新增離線驗證工具在temp SQLite完成preview、accept、兩次close/reopen、same-key replay與撤回邊界，僅一筆owner-bound profile、零飲食紀錄。原每100g七值及150g換算一致，兩脂肪缺值保持null；來源原文與辨識名各自保存。使用合成明確富士identity驗後端，不能稱為照片品種辨識或手機保存驗收。

後端focused90／138subtests通過，前端nutrition／scanner測試、typecheck、lint及清快取web export通過。Expo測試伺服器命令被環境自動審查以`blocked by policy`拒絕，未改寫同類命令繞過；改用本機靜態離線元件render（icon／button stub、無hydration／API），Playwright驗375／390／430／768／1440寬度無水平溢出、標題及來源標籤分開，手機／桌面截圖已檢視。唯一console error是靜態預覽favicon404，非應用錯誤；此結果不替代完整Expo互動或真機驗收。初次pytest從錯誤工作目錄導致import失敗，改由backend及明確PYTHONPATH後90項通過；未重跑完整backend或新真模型。正式registry／flags／DB／服務不變，測試程序已收起。

本次同一代理自行複核，未發現本範圍新增阻擋；剩餘缺口是本FDC路徑通用來源准入與使用者不必選原始資料列的系統接線，不能以Fuji-only成功解除。主計畫下一個有界子項已修正；來源與flags的既有最終門檻仍在。證據：[fdc-reviewed-source-acceptance-20261116.json](../food-nutrition-evaluation/2026-11-14/fdc-reviewed-source-acceptance-20261116.json)。

### 第七十一批：來源准入與刪除需求排除（2026-11-16）

自行重讀source registry、source/profile/cache及FDC preview路徑後，確認舊rights合約的retention／withdrawal只是敘述文字，無法保證實際方案已批准、完整刪除可行或來源policy未漂移。本輪以server-owned admission review補上完整policy digest、publisher／provider分離核准、刪除及cross-user cache範圍。production Web registry現在必須經嚴格builder建立，仍空；FDC JSON不能誤進Tavily Markdown路徑。低階SQLite policy repository仍是server-only primitive，沒有被誤稱為每次保存都強制執行新准入。

依凍結範圍直接排除需刪除或刪除條件不明的來源，不擴建purge系統。withdrawal仍只撤回未來使用，歷史列／WAL／backup不宣稱已刪。Tavily帳戶實際應用範圍及原publisher權利仍缺證，不能用Tavily輸出保存許可替代；本輪也沒有新增正式Tavily來源。hash綁定僅防設定漂移，不證明review的法律正確性或取代供應商授權。

既有真FDC1750340 replay支持建立「生鮮帶皮富士蘋果」候選policy，明列variant、能量編號957、兩項脂肪未知、owner-bound保存與真實retention範圍。不得由一般蘋果／未知品種推定富士帶皮；raw+mixed是既有enum約定，未新增辨識或更名規則。候選檔無自動載入，未安裝正式SQLite或registry；手機synthetic171688不作它的食品／營養證據。

新增14項admission測試及focused74／69subtests通過；完整隔離後端1098／1185subtests，0失敗／略過。temp SQLite驗真close/reopen、policy digest及withdrawal current拒絕／historical仍在，profiles=0；新測試禁止socket。此次為同一代理自行複核，非獨立審查。未見本次邊界新增阻擋，但不代表權利證據永不變動、完整real-source photo flow或保存已驗收。無真provider呼叫、credential讀取、正式DB操作、重啟／部署、commit／push。下一項是既有隔離preview／accept／保存驗收，再做最終flags；不重做完成的手機fixture或增加工作流。證據：[source-admission-boundary-20261116.json](../food-nutrition-evaluation/2026-11-14/source-admission-boundary-20261116.json)。

### 第七十批：Android 流程完成與臨時入口清理（2026-11-16）

使用者確認已完成前批三項操作且結果皆正確；測試state及日誌亦新增一組vision200／candidate200／confirmation202／preview200，fake Search／Detail各增加1，profiles／meal records保持0。故完成的是固定蘋果150g／78kcal候選確認與唯讀preview的Android流程子項；裝置及畫面核對依使用者回報，服務端增量沒有獨立device識別。本次未取得新截圖或response，也未區分相簿／拍照，不擴大成真營養、辨識準確率、accept或保存驗收。

依驗收結果結束臨時synthetic child，觀察gateway自行退出、測試listener及8443 Funnel移除；正常443／5000與原started_at保留，automatic fallback=false。這是真正退出清理的證據，但未實際等待到期觸發。原手機待驗條目已解除，不應再列為下一個必做項。下一步回到原有來源rights／policy／撤回刪除及registry、保存交易與最後flags門檻；不增加工作流，不因固定資料流程通過就開正式Tavily。證據：[android-candidate-preview-acceptance-20261116.json](../food-nutrition-evaluation/2026-11-14/android-candidate-preview-acceptance-20261116.json)。

### 第六十九批：公開手機 gateway 的邊界複核（2026-11-16）

使用者不需要私人測試網址；新增公開 HTTPS 8443 的短效 gateway，未直接公開原固定 token 的 harness。重新讀碼及反例驗證確認：gateway 白名單只含必要 session／profile／scan／candidate／confirmation／preview，原控制端點與 accept／飲食保存／enrichment 不轉送；token、Host／Origin、期限及回應大小都在轉送前後受限。frontend／backend 只繼承 OS 工具鏈環境，禁讀 dotenv，使用暫存 export／SQLite 與 synthetic providers。8443 已有配置時拒絕覆蓋，結束只刪仍精確吻合自己的 proxy，443 維持原站。

真瀏覽器經公開 Funnel 完成 confirmation 202／revision1／preview200，150g蘋果為78kcal；沒有 application route mock。公開越權反例403／未登入401後，DB counts及fake provider次數保持不變，profile／meal均0。phone／browser unittest16通過，focused pytest36通過／34 subtests、scanner24通過，typecheck／lint／清快取匯出與390／1440渲染檢查通過。這是同機瀏覽器走公開HTTPS的證據，不能改稱Android、tailnet peer、真provider或準確率驗收。

session 到期／Funnel精確清理有單元契約；尚未實際等待本次60分鐘結束，故不記為已完成自動清理驗收。已載入preview仍是唯讀快照，沒有自動消失合約。固定資料入口也不能證明任意食品營養已可補全；下一步為使用者Android實機操作後回填結果。工作樹識別升v1.0.3，正常443服務仍v1.0.2且未重啟；來源registry空，正式設定未開啟，runtime只重查automatic fallback=false。此複核未發現本輪入口的阻擋缺陷；來源准入與正式啟用門檻依舊。證據：[scanner-phone-preview-gateway-20261116.json](../food-nutrition-evaluation/2026-11-14/scanner-phone-preview-gateway-20261116.json)。

### 第六十三批：兩次同圖模型回放與局部修正

在使用者持續模型呼叫授權下，使用原照片及正式 recognition prompt 做兩次串行、零重試的隔離 live relay 呼叫；strict parser 均成功。模型兩次均輸出七項且將兩個綠色菜區保守標為泛稱，明示照片不足以確認菜種；所有 self-rated confidence 均高於0.45，因此本兩次輸出的待確認主要來自營養未配對／相容性，不是低信心 gate。兩次卻在名稱、排序、估重、重量信心與做法 enum 上不一致；本測試沒有重量真值，不能量化準確率或校準信心。原 Android 封包、品質0.7處理後的 bytes 及原始手機 response 仍不可得。

原始輸出發現 `葉菜（左上格）`／`葉菜（右下）` 用區域字尾繞過有限泛稱 gate；修正只識別列出的視覺方位字尾，特定菜名附同一字尾仍通過既有檢查。白飯被高分標示為蒸熟，卻因 TFDA `A0550601` 未明列 preparation_method 而拒配；僅依 exact source/key/code/name/description 加受限 `steamed` enum 對應，其他做法仍拒。這不是 TFDA 原有 enum 或普遍放寬。毛豆仍只找到生的 TFDA profile，熟食結果維持不配；不得用生品值補熟食。兩次 replay 本機重算後營養仍 incomplete，合計只含成功配對項。

完整後端 `1082 passed / 1141 subtests`。獨立複核兩處程式修正未見廣泛放行漏洞。共真模型呼叫2次、回報 tokens 12,428、重試0、Tavily／USDA API 0；relay 未提供可用價格，故不報成本估算。未讀出／列出 credential，未呼叫正式 app route、未存取正式 DB、未寫 profile／meal record、未改 flag／registry、未部署或 commit。完整原始輸出留在 ignored 本機 `tmp/`，勿公開；精簡 evidence 不包含憑證或照片位元組：[photo-model-replay-20261115.json](../food-nutrition-evaluation/2026-11-14/photo-model-replay-20261115.json)。

第六十二批完成既有身分門檻的 bounded repair：三個 fallback helper 與直接 query plan 共用已知泛稱判定；舊 FDC snapshot 的 suggested／confirm、issued confirmation 的 Detail authority，以及 direct-SQL preview accept 寫入前均加同一檢查。defer／reject、immutable evidence 及過去已 accepted 的同鍵重播保留；本批不清除或重寫歷史 profile。完整後端 `1074 passed / 1090 subtests`、0 failed／skipped、`146.98s`。其中真 Flask route＋隔離 SQLite 驗得泛稱 `409 confirmation_required` 且零 cache/provider/quota/request/JTI 消耗；同名候選維持獨立 ID 與合成重量。

獨立審查找到三類缺口並已修正：明確未知標記漏擋、「熟食材」最長修飾詞剝除錯誤、舊 preview 直接 SQL 接受繞過；最終交叉複核未發現本 bounded 範圍新增的重大回歸或同類新授權繞過，不是整體零缺陷保證。有限詞彙 gate 不證明菜種，local hit 優先權不改；candidate confirm 複製原 scan identity，不等於身分已更正。本批無真 provider、key、正式 DB、flags 或服務操作，未部署，來源准入／手機營養 E2E 及原照片模型對照仍待驗。證據：[food-identity-gate-regression-20261115.json](../food-nutrition-evaluation/2026-11-14/food-identity-gate-regression-20261115.json)。

第六十一批新增使用者本人 Android 回報及補充：相機成功、辨識完成、主觀大致正確，且確認使用先前提供的 HTTPS scanner 網址。附圖左上「大陸妹」、右下「青江菜」為使用者提供的菜種標註，兩項均在待確認區顯示為「炒菜葉」。證據：[android-camera-smoke-20261115.json](../food-nutrition-evaluation/2026-11-14/android-camera-smoke-20261115.json)。這補上外部 Android 使用既定公開 HTTPS 入口的使用者 smoke 回報；瀏覽器、原始 response／分數／拒絕理由／item ID、來源 metadata、保存動作或營養真值仍未知，故不代表私有 Tailscale peer、完整手機營養 E2E 或第三層已通過。下文各批的「未驗真相機」保留為當時歷史邊界。

本批獨立唯讀審查及離線 helper probe 發現：辨識 prompt 容許不確定時使用「葉菜」，而 FDC Search、enrichment 與 web 的信心／validation gate 對高分泛稱尚無明確阻擋；原四個合成 case 及補充「炒菜葉／大陸妹／青江菜」三個 case 均通過資格 helper，未執行 provider。後續 policy／registry 仍會約束是否取回與接受來源，不能把此 probe 解讀為 production 已誤填或具體名稱已能匹配營養。待確認區含低信心和營養未匹配兩種情況，程式將它們排除合計，但本次原始回應／數值未核對；同名項目在程式上可保有不同 ID，實機 ID 未驗。下一步在既定身分確認工作內修正共用 gate，涵蓋帶做法泛稱、同名多項、cache 與確認後 revision；不強迫模型猜菜種，不靠 Tavily 回填影像身分。本批未修應用程式，也未重新驗證服務 runtime flags。

第六十批唯讀部署預檢證據：[phone-tailscale-preflight-20261115.json](../food-nutrition-evaluation/2026-11-14/phone-tailscale-preflight-20261115.json)。此證據不包含 Android 真相機或第二裝置操作。

目前不需再擴增規劃範圍；原有六個收尾工作流仍是封閉清單。FDC Detail replay 已完成有限真 API 驗收；來源條款已再查核但 production admission 仍被 publisher rights／實際方案範圍阻擋；scanner/UI 已接線，且完成隔離 SQLite browser → HTTP preview bounded E2E；第五十八批完成跨程序 reservation，第五十九批完成 expiry/restart UI 與同 DB 真程序重啟重播，均使用 fake providers／暫存SQLite。第六十八批有 Android「拍照」結果截圖及使用者拍照回報，僅將 camera smoke 記為 user-attested 完成；舊 badge／計數文案與修正後部署不一致原因待查。來源呈現、另一裝置的確切部署路徑、profile accept／飲食紀錄實機寫入仍未驗。四個讀取畫面維持延後選配；最後 production flag 審查仍須待 gate 通過後才決定開或維持關閉。這些都是既有工作流的收尾驗收，不是新增功能，且不保證最終會開啟第三層。

### 第六十八批：Android 拍照辨識使用者回報

使用者明確回報已以 Android 相機拍照辨識，並提供5張結果截圖；首張選中「拍照」模式及顯示辨識結果，故本次 bounded camera smoke 按 user-attested 完成記錄。截圖本身沒有快門預覽／來源照片，結果頁又顯示「啟動相機」，因此沒有可獨立核對的快門—結果關聯或原始 request trace。此紀錄不升格為完整 authenticated nutrition E2E。

8個候選中2項配對、6項待確認；白飯 TFDA 180g 和茄子 USDA 參考55g合計357 kcal、蛋白質6.2g、鈉77mg，算術吻合。比較第六十七批可見結果時，配對食品由白飯／雞腿變為白飯／茄子，白飯估重200g變180g；但原始照片 bytes、取景及實際來源真值未綁定，不視為受控同圖模型穩定性測試。熟肉塊35%被標低信心；其餘待確認可能是營養不相容，截圖未顯示原始 rejection metadata。

截圖仍有「Gemini + TFDA」與「已辨識 2 項食物」文案，與可見 USDA 來源及6項待確認不一致。本批唯讀 GET 公開 `/scanner` 與 JS bundle 各一次，均 HTTP 200；bundle `entry-a14ad6f15a5616c7c0db5aed6c916e85.js` SHA-256 `65a1c6ad6ae466bdcfa76aaea307201e36e9b96cd15f00da2896d1b1bebd24d9` 與本機匯出相同，且不含兩個舊文案字串。手機 capture time、cache 或實際 asset trace 未取得，仍不能確定舊文案原因。加入今日紀錄按鈕沒有操作結果，保存未知；模型供應商、USDA／Tavily實際呼叫、usage、成本與 DB writes均未知。下一個窄驗收是使用者下次開啟頁面時完整重新載入並確認修正文案；在此之前不改正式 flags 或保存資料。證據：[android-camera-results-20261116.json](../food-nutrition-evaluation/2026-11-14/android-camera-results-20261116.json)。

第六十批僅完成部署預檢：排程指向目前 v1.0.2 checkout、local/Funnel health 同程序、scanner bundle 與匯出檔雜湊相同、SQLite 唯讀 integrity check 通過。使用者有 Android 手機，故下一步可由本人手機加真相機；原 server 同學缺席不阻擋。本批明確發出的 HTTP requests 僅有 health、scanner HTML 與 JS，沒有由預檢動作觸發 live model/provider call；未檢視服務背景日誌。Funnel 從伺服器本機打通不等同第二裝置或 Tailscale peer；其他 FDC/enrichment backend flags 未由 `/health` 暴露，不能稱為 runtime 全部已驗 false。必須保持測試 harness loopback-only，不寫 profile／dietary records，維持來源權利與 production admission gate。證據：[phone-tailscale-preflight-20261115.json](../food-nutrition-evaluation/2026-11-14/phone-tailscale-preflight-20261115.json)。

長尾驗收（人工標註／秤重照片、HEIC／EXIF、來源表格覆蓋、p50／p95、成本、斷線、重試、過期、重啟與配額）只能歸入上述工作流的子測試，不得自然衍生成新功能。若測試發現問題，只能修正既有門檻、標記阻擋並保持旗標關閉，或列為 post-release 品質觀測；Tavily／原網站權利不成立時排除該來源，不無限尋找替代來源。新需求才需要另開變更審查與新版本。SQLite-only、PostgreSQL／Mongo 不作正式路徑、不得用近似食品代填、不得藉營養結果提高影像信心，均維持固定邊界。

## 第四十六批複核：前端 preview／accept contract（2026-11-15）

新增的前端 helper 只傳送 server-owned references，並在停用旗標時於網路前 fail closed。它阻擋客戶端注入 FDC ID、重量、Detail document、profile 與 source policy；success response 需要符合明確欄位與 digest／狀態約束，錯誤保留 typed code 與 `Retry-After`。定向 helper 測試由初始 `5` 項補至 `6` 項，新增確認停用旗標優先於 malformed request；前端 nutrition regression 為 `124 passed`，TypeScript／ESLint 通過。

後端真 Flask route＋隔離 SQLite preview→accept→同 key replay 為 `2 passed`，FDC preview focused 為 `30 passed`，完整後端為 `1010 passed`，`compileall` 通過。這些數字只證明 contract、認證邊界、SQLite 持久化與 replay；仍沒有 scanner/UI、真 USDA Detail、正式 rights／production registry 或手機／Tailscale bounded 測試。正式旗標及 automatic fallback 必須維持關閉，SQLite-only 決策不變。

本批新發現的設定缺口已補入 `backend/.env.local.example`：`FDC_PROFILE_PREVIEW_ROUTE_ENABLED=false` 與 `FDC_PROFILE_ACCEPT_ROUTE_ENABLED=false`。下一步應先做真來源固定 Detail replay 與 rights/provider review，再做 disabled-by-default 的手機 preview→accept 流程；不能因前端 helper 測試通過而直接開啟自動補全。

## 第四十七批複核：真 USDA FDC 固定 Detail replay（2026-11-15）

本批已完成第一階段真來源驗證，但結論要分層解讀。固定 `fdcId=1750340` 的兩次 server-side replay 均成功取得相同食品身份、Foundation 類型、35 列營養資料；經 server-reviewed nutrient mapping 後，真 payload 通過 FDC adapter、`NutritionProfileV1` 及 150g portion 換算。focused client／adapter/profile suite 為 `28 passed`、`7 subtests passed`。證據：[usda-fdc-detail-replay-20261115.json](../food-nutrition-evaluation/2026-11-14/usda-fdc-detail-replay-20261115.json)。

複核時發現完整 response hash 會因可選描述性 metadata 漂移；這不是核心食品／營養值漂移。故 hash 只作單次 provenance，不能硬編碼成永久相等條件；核心 FDC ID、description、data type、營養列數、選定 nutrient number 與數值才是 fail-closed 審查欄位。`tools/verify_fooddata_central.py` 已改用正式 adapter retrieval version，修正原先舊 demo 版本造成真 client 輸出無法重播的工具契約破綻。

這一批沒有解除來源 rights／production registry、糯米腸同物匹配、確認後 scanner/UI、手機／Tailscale bounded E2E 或自動補全開關。所有 `FDC_*`、`NUTRITION_ENRICHMENT_ROUTE_ENABLED` 與 `automatic_web_fallback_enabled` 仍為 `false`；SQLite-only 決策不變。下一步是來源 rights／policy／production registry 審核，不是把 Apple 固定 ID 擴大成一般食品自動補全。

## 第二輪當時的主要結論

架構可行，但首版應從少量可核對來源開始。檢索不會自行修復辨識錯誤或照片估重不確定性。
目前中轉站聯網能力、第三層來源涵蓋率與真實速度仍未確認，不能在設計階段宣稱通過。
兩層既有資料與第三層參考值需分開追溯；補全成功不得自動提高視覺辨識信心。

## 已發現並修訂的設計破綻

| 優先度 | 初稿問題／對照證據 | 可能後果 | 已納入計畫的修正 |
| --- | --- | --- | --- |
| P1 | 只規劃保存食品profile，沒有保存未配對項目 | 重讀歷史時部分餐點變成「完整」 | 新增 records.nutrition_context，保存 unresolved、scope 與分母；更新SQL／其他後端及離線路徑 |
| P1 | 「新版前端就緒」過於籠統 | 舊前端仍把缺鈉看成0，關閉開關後已有資料仍會失真 | 明確 contract_version=2 與受影響讀取 upgrade_required；既存部分資料讀取支援不能隨開關撤回 |
| P1 | 改重只重算營養，忽略現有警告不更新 | 食物加量後仍顯示原本未超標結論 | 納入不呼叫AI的後端preview，改重／補全後重新評估，revision防亂序；存檔再驗算 |
| P1 | 只談餐點unknown，未明列每日剩餘額度與推薦 | 缺鈉餐點可能導出「還能吃更多鈉」 | remaining、短缺、推薦與趨勢共同消費coverage，保留已知值、不下完整結論 |
| P1 | signed token 被誤當完整防濫用措施 | 重放或改名可不斷觸發付費搜尋 | 每次認證與配額、查詢上限、有界冪等／single-flight；校正模式由後端簽新revision |
| P1 | 首次DNS檢查可能與實際連線不同 | 網頁取回可能被重導或重綁至內網 | 指定安全取回器／egress，檢查實際目的IP、TLS及每次redirect，涵蓋IPv6 |
| P2 | 「請求結束後不繼續付費」承諾過強 | 已送出模型呼叫無法撤銷，成本估算不真實 | 改成到期不新增呼叫，已送出可能計費並納入尾端成本 |
| P2 | 全域2個作業但其餘HTTP請求等待 | 8個Waitress執行緒仍可能全部卡住 | 容量滿即busy，限制等待及重試，不以semaphore無限排隊 |
| P2 | 保留小於符號但未定義如何合計 | `<0.1g` 可能被當精確0或0.1 | 點值null、保留upper_bound；核心僅有界限先不自動納入，不能宣稱未知餐點有完整上界 |
| P2 | 誤寫「foods_json欄位」 | 實作可能對不存在欄位設計migration | 對照RECORD_COLUMNS，改為實際records.foods；紀錄層context需真正新增欄位 |
| P2 | 推測提示詞有重量數字範例 | 把未存在原因寫成不穩定來源 | 查核現行prompt後改成菜名／拆分範例及結構預設值，明列錨定影響仍待A/B測試 |
| P2 | 「模型可沿用」容易被讀成擷取能力已測 | 選了同模型卻處理不了長表格或schema | 改為優先沿用，但必須通過獨立擷取與格式驗證 |
| P2 | 「重試不重複付費」忽略跨服務失敗 | 遠端已處理但回應遺失時重送仍可能計費 | 明列本機冪等與供應商冪等差別，僅承諾有界重試、合併已知重複工作與不重複記錄 |
| P2 | 每項驗證隔離未說明整份批次JSON損壞 | 可能以不完整片段當成功結果 | 整份無法解析時第三層invalid_output，保留本機官方結果，不做正則補救 |

## 現有程式的穩定性查核

以下是目前程式與實驗資料的發現；僅寫入規劃，沒有在本輪改程式。

1. `vision_food_service.py:178` 將辨識、份量、來源參考、候選數與缺值合成needs_confirmation。它不是模型辨識品質的單一指標；拆開原因才能知道何處要改善。
2. `vision_food_service.py` 的normalize_confidence對缺值給0.5，可能超過0.45接受門檻；大於1又直接除100，新合約必須明確0至1並拒絕布林／無效值。
3. `food_analysis_service.py` 的reliability score直接取模型自評；沒有校準資料可證明這是正確率。不能用上網查到資料替它加分。
4. `scanner.tsx:270/323` 相機／相簿都請求quality=0.7；但相簿不像相機使用resolveImageBase64，部分web blob/data URI可能讀取失敗。這是輸入可用性缺口，不等於模型看不懂食物。
5. `nutrition_label_service.py:152/164` 檢查magic bytes與大小，未完整驗證影像尺寸與方向；是否導致實際辨識問題仍需以裝置照片實測。
6. 原生辨識未配置嚴格schema，也沒有像relay分支檢查finish_reason；原生輪替可能切不同模型、各次60秒而缺整體deadline。影響需要與目前實際走relay的流量分開評估。
7. `store/useStore.ts:451` 改重量不更新原始food warnings或route mealWarnings。第三輪真實store重播未觀察到累積四捨五入漂移，因保留originalNutrition；撤回先前對反覆縮放累積誤差的推論。仍以已取位的原份量數值而非原始每100g計算，計畫改為標準profile重算與權威preview。
8. 既有13圖的兩次辨識實驗沒有找到更多可確認項目，且增加延遲。首版不啟用自動整張重辨識；改用分離因素的測試與必要時使用者校正。
9. `build_placeholder_bbox` 是位置占位資料，不能拿來裁切特定食物做第二次辨識或評估定位準確率。局部補拍由使用者提供；若未來做自動裁切，必須另驗證真實定位能力。

## 仍未消除的不確定性

- 缺資料的小吃是否在允許來源中有「正確食用狀態＋可食熟重＋足夠營養欄位」，目前沒有可用比例的實測。
- 25秒與4項／6頁等限制只是起始預算；目前模型延遲可能讓未快取補全很常逾時，Phase 0應提早量測再決定首版範圍。
- 中轉站工具支援、真實模型版本、取樣參數、來源憑證與保存權限均未定案。首頁403不等於不支援，也不能當作支援證據。
- 信心校準需要人工辨識真值；重量誤差需要秤重真值；營養誤差需要標示／配方或其他可靠參考。現有照片不能獨自提供全部真值。
- 低光、遮擋、堆疊與相似菜色的辨識限制可能仍在；不能承諾第三層消除所有待確認項目。

## 第二輪之後的驗收要求

- 每個新增結果追溯到實際取回的表格與食品狀態；錯食品、錯狀態、錯範圍反例不得通過。
- 保存、離線補送、編輯、重讀與每日／歷史聚合後，缺值、界限與未計入項目皆保留。
- 新增／改重／補全的警告使用同一後端規則；已知量超標與資料不足可以同時成立。
- 預算與排程滿載時本機結果可用，不把「busy／timeout」算成「資料庫沒有」；重試不無限重複付費。
- 報告將辨識精度、項目配對覆蓋率、來源配對精度、重量誤差、格式成功率、延遲及成本分開呈現。
- 「計畫已審查」僅指本文與主計畫已對照修訂；功能缺口尚未修復、真實模型與上線成效尚未驗證。

## 第三輪：實測後重新審查

依使用者「先實測、再審查」指示，實測完成後重讀主計畫，並持續將Tavily指南、參數對照、品名簡化與階段更新要求回寫正文。證據見[完整報告](../food-nutrition-evaluation/2026-11-13/README.md)與[摘要JSON](../food-nutrition-evaluation/2026-11-13/summary.json)。

### 新證據造成的修訂

| 優先度 | 實測反例／審查問題 | 主計畫已修訂 | 尚未完成 |
| --- | --- | --- | --- |
| P1 | 複雜strict schema僅回12/39項，null常變0 | 目前relay採JSON-object＋提示格式＋本地嚴格驗證，完整唯一ID集合不可缺 | 正式validator與回歸fixture |
| P1 | memory／SQLite把null鈉存0，context丟棄；前端亦丟來源及缺值 | Phase1／2先做合約與全保存鏈，部分營養啟用前驗舊版相容 | 現行資料流程修復及migration |
| P1 | 官方來源能量互斥、宏量總克數大於食品重 | 補能量／質量／子集合／比例檢查，矛盾進source_conflict | 含容忍量的實作及營養專業規則核對 |
| P1 | 不存在商品路徑回首頁也被Extract列成功 | 驗主商品、scope、表格及最終來源身分，不只驗域名／HTTP | 來源adapter、重導及故障測試 |
| P1 | 「吉林糯米腸」若刪修飾就套表，可能掩蓋地域或配方差異 | 名稱分類與顯示分開；保留原名、brand／region／state；相容才reference_only | 該來源配方審查、正規化器及反例集 |
| P2 | 單次擷取40秒、五頁Extract18.6秒 | 撤回25秒冷查詢成功承諾，只作部分結果deadline | 完整冷／熱路徑p95與容量 |
| P2 | 無任務佇列首版卻暗示慢任務可背景完成 | 首版請求結束就終止套用；後續持久化作業另列範圍 | 若選背景功能須另設durable job設施 |
| P2 | 128項份量信心全低；只有2項名稱信心低 | 拆needs_confirmation原因，不靠調分／外搜提高視覺信心 | 秤重與辨識獨立標註校準 |
| P2 | 「滷牛肉」查無而相近熟牛肉名稱可配 | 外搜前先處理經審核且受狀態限制的別名 | 別名審核與假陽性控制 |
| P2 | evidence用省略號拼接，不能證明值屬同欄 | table／row／column ID及後端讀原格，自由引文不作唯一證據 | 表格身分與數值綁定 |
| P2 | 同頁初輪缺表、後輪各模式都有表且同雜湊 | Markdown／advanced只是候選設定，逐次驗完整性，不宣稱升級必改善 | 固定因素、順序及多來源A/B |
| P2 | country=taiwan仍回吉林；精確假品名仍回近似頁 | 區分文件參數與實測，後端重驗身分，搜尋score不當信心 | 泛化檢索精度、語言／depth對照 |
| P3 | 正向原始純JSON2/3，完整外層code fence導致嚴格解析失敗 | 僅允許去除完整外圍欄，禁止搶救截斷／混文 | 與正式validator整合驗證 |

### 測量及工具的自行校正

- 128項中48項排除包含46項無營養配對、2項低辨識信心。彙整欄位改為excluded_items並新增原因分布，不把全部當資料庫缺資料。
- 正向測試舊harness對不存在item的null檢查誤通過3項，原43/60不作成效依據。修工具後不重送付費；保留原回應，離線raw parser修正40/60，production parser去完整外圍欄後60/60。這只驗有限數值／null／ID，不等於完整驗收。
- 反覆重量編輯未見累積漂移，撤回未經證實的因果敘述；警告不更新已由實際store重播確認。
- q70只測2張照片，不能和13張混合涵蓋率做改善比較，也不等於手機Expo處理。
- 後輪商品表格恢復可能涉及快取／來源／服務變動，未隔離原因；不能以單輪差異評估advanced效果。

### 當前放行判斷

可行性通過：Tavily實際Search／Extract可用，現有模型可擷取提供的文字，程式可做確定性換算。有真實醫院參考與精確產品對照案例。

正式自動補全不放行：尚未完成資料合約／保存／風險、表格與身分驗證、授權、限額、客戶端相容及端到端整合。模型原生搜尋未確認不再阻擋獨立Tavily方案；其他未驗證事項仍列待辦。

本輪正式功能未改、未部署、未提交。已增加診斷腳本／證據及忽略Tavily金鑰檔，分支保留v1.0.1。後續每階段完成依主計畫第22節同步修正企劃書、審查與受影響實測結論。

## 第四輪：前兩層路由、第三層入口與未測門檻

依使用者再次審查要求，重讀主計畫及所有既有試驗的範圍，再對照實際本機匹配。新增 [routing-offline.json](../food-nutrition-evaluation/2026-11-13/routing-offline.json)，由 [probe_nutrition_routing.py](../../tools/probe_nutrition_routing.py)重現；socket連線被阻擋，無模型／Tavily新呼叫，未碰使用者資料。

### 按嚴重度排列的發現

| 優先度 | 發現與程式證據 | 本輪證據及後果 | 已回寫的規格／未完成工作 |
| --- | --- | --- | --- |
| P1 | 名稱移除所有括號，丟失已知內餡；vision_nutrition_service.py:45 | 水餃(韭菜)自動選熟高麗菜水餃。一般參考警告無法使已知不同內餡變相容 | 第4、14、21節要求先保留修飾並驗內餡，現行前兩層matcher仍待修 |
| P1 | state檢查主要是排除熟食配乾品，未驗反向矛盾與components_scope；同檔:54 | raw白飯仍配熟飯；僅USDA時dry泡麵仍配含湯66kcal；prepared泡麵本體／含湯兩種scope回同一表。這些是可重現缺少防護，不是實際照片錯誤率 | 第4、5、8、14節規定跨層共用相容性檢查；新增正反向狀態及scope回歸 |
| P1 | 原態TFDA排名先於熟USDA，且返回值截為5筆；同檔:118 | 炒高麗菜先選生甘藍23kcal；相容熟USDA被壓後，在完整庫甚至不出現在前5。既有test_tfda_precedes_usda_even_if_usda_name_is_exact固定這行為 | 第1、4、13–15節明確變更政策細節：相容候選中保留TFDA優先；ingredient_reference不可終止熟食查詢；需改舊測試，歷史不回算 |
| P1 | 自訂資料選nutrition_per_100g但unit沿用原輸入；nutrition_label_service.py:88、food_service.py:118及matcher:110 | 經公開builder：200g每份400kcal，先得200kcal/100g，保留per serving後matcher又變100kcal/100g。一般自訂優先控制正常；此案例不是所有自訂品都錯 | 第8、14節以選定數值組的basis為準，矛盾拒絕；builder、搜尋結果及自訂／OCR路徑待修測 |
| P1 | 未配對回應捨棄原辨識重量、state、item_id；vision_food_service.py:154 | 既有地瓜球／糯米腸原始結果有重量，rejected無重量與ID；同一便當兩筆葉菜同名。若直接以舊回應接enrich，無法正確綁定重量或區分項目 | 第5、6、14節在篩除前產生ID及完整簽署上下文；profile共用但item不得合併；正式跨段尚未實作 |
| P1 | 核心值僅用isinstance，份重只驗truthiness；vision_nutrition_service.py:103 | 合成Boolean／負數／NaN可入候選；負份重產負營養、True份重放大100倍、字串份重拋TypeError。現有7,644筆快照未發現這三類異常核心值 | 第8、14節將數值validator擴至前兩層／自訂；不把合成反例說成官方資料已污染 |
| P2 | USDA是本機FNDDS子集，中文映射少且忽略item.name_en；同檔:79及convert_usda_fndds.py:22 | 5,431筆中12筆有中文名／別名。隔離全脂牛奶控制：name_zh中文＋name_en精確英文不命中，直接英文名稱可命中。不能由本機no match推論USDA全庫查無 | 第2、5、14、15節區分no_local_mapping；先審核雙語候選，不盲信翻譯或提高外搜量 |
| P2 | USDA檔不存在靜默回{}；nutrition_database_service.py:9 | 臨時空目錄重現。現行尚無Tavily正式入口，因此未觀察到失敗後付費暴增；但舊計畫沒禁止此退化路由 | 第5、14、15節分unavailable／not_found；監測版本及檔案完整性，禁自動付費放大與負快取 |
| P2 | 嚴格解析與視覺涵蓋仍可能被既有成功數字掩蓋；nutrition_label_service.py:115、vision_food_service.py:295 | 共用parser仍會從混文正則取JSON；60/60有限檢查不是嚴格schema驗收。nutrition_complete只看已辨識項目，不涵蓋照片漏項或實際吃下比例 | 第7節另定嚴格入口；第10、14、15節保存辨識限制，分辨欄位coverage、視覺完整與食用份量；尚未完成validator／真值評估 |

### 未測項與判斷

主計畫第15節已由6項概括待辦，改成12個環節的證據／缺口／門檻表。仍沒有完整正式路由的「照片 → TFDA → USDA → Tavily → 模型 → 驗證 → 保存／編輯／每日風險」端到端測試。positive-pipeline名稱不能當此證明，它使用選定來源測文字擷取。

尚未通過的必要測試：本輪反例修復、來源表格欄列validator、完整保存與各後端migration、舊版／開關、正式並發與斷線重啟、手機／HEIC／EXIF、獨立標註與秤重、來源保存授權。Tavily參數進一步A/B及模型原生搜尋是優化／替代路徑，不應拖延前述必要修正。

### 本輪驗證與後續順序

現有影像匹配與匯入測試24/24通過。它們驗的是既有行為，沒有覆蓋新反例；某些既有測試預期本身需要按新版相容性政策修改。新增診斷用於重現現況，未把問題修成通過，也未新增功能測試冒充實作完成。

先完成Phase1的本機相容性／基準／ID及嚴格合約，再完成Phase2保存／風險，接著用實際協調器離線重播，才進少量已審核來源與有界真實端到端。保持正式自動補全不放行；可行性結論維持成立，但完整營養可靠度仍未量測。

## 第一批實作後複查

使用者已授權依序實測及修復；本節取代前輪「正式程式未改」作為目前狀態。已修改本機後端流程，未部署、未啟用第三層、未新增付費請求。第四輪原始證據保留，修後新增[routing-repaired.json](../food-nutrition-evaluation/2026-11-13/routing-repaired.json)及[13圖離線重播](../food-nutrition-evaluation/2026-11-13/local-repaired-replay.json)。

| 問題 | 已完成修復及驗證 | 仍需後續工作 |
| --- | --- | --- |
| 生TFDA阻擋熟USDA、top5遮蔽 | 先相容性再來源排序；大量生TFDA反例只留下熟USDA，相容TFDA及使用者自訂優先控制正常 | 擴大逐食品、烹調及配方審核；未提供原態參考獨立UI |
| 內餡／狀態／範圍消失 | 保留非中繼括號；已知韭菜不配高麗菜；raw飯、dry泡麵、本體vs含湯拒錯配 | 任意品牌／地域正規化尚未實作，現有規則不是全食品本體論 |
| 自訂二次換算及無效數值 | builder與adapter依實際nutrition dict決定basis；200g400kcal回200/100g；矛盾舊表不自動配；嚴格數字及單位驗證 | OCR界限值、部分營養合約與全保存鏈仍待處理 |
| 未配對ID／份量流失 | server產生scan/item ID、revision=0；matched/rejected共用完整context，重名項與總重count控制通過 | 簽章、跨請求revision、保存與前端映射未完成 |
| 缺檔當查無 | 分層loader與API健康；缺失／壞JSON／schema／數字／hash控制，單層故障保留其他結果 | 目前預期轉換輸出雜湊未配置；第三層協調器不存在，不能宣稱故障外搜全流程已驗 |
| 寬鬆parser及無效信心 | vision專用嚴格完整JSON／外圍欄解析，拒重複鍵／非有限／混文／截斷；信心與重量不做字串或bool強轉 | 舊OCR／其他共用parser維持原路徑；營養欄列／ID集合validator尚未完成 |
| USDA中文缺口 | 一筆特定全脂牛奶對應固定USDA row且重驗英文名；未知中文即使模型英文正確亦不盲配 | 本機英文資料大多仍無審核中文映射，不能聲稱全庫覆蓋改善 |

獨立複查在首版修復後再找出並修正：清燙高麗菜套用含油熟菜、炒水餃套水煮資料、荷包蛋因蛋類被誤判生食、缺狀態與unknown不一致、巨大整數使math.isfinite溢位，以及壞item被捨棄後完整性與確認旗標不一致。提示詞同步固定method／scope enum，避免模型自由中文與後端enum互斥。上述都有聚焦回歸；新提示詞尚未透過真模型照片測成效。

後端全套測試退出0，未配置真Postgres的整合測試略過；其餘為memory／臨時SQLite／mock。舊13圖41項重播修前27配對、修後18配對；增加待處理主要是拒絕不相容原態或方法候選，不是新增照片真值驗證。第一批只完成Phase1一部分，九項可空profile、界限值、coverage、Phase2持久化／風險及Phase3正式協調器仍需依序進行。

## 第二批離線合約實作後複查

九項nullable profile、原始基準換算、排他上界、逐營養coverage及adapter限定表格驗證已完成離線服務。正式掃描／保存／風險尚未接線；本節更新前輪的未實作狀態，不把單元測試當作正式第三層或真實食品準確率。

模型合約收斂為選source/table/column/row ID，數字、單位、份重與證據由可信server adapter取出。強制掃描同表可用欄列並交叉驗kJ/kcal、每份/每100g；切換選取欄不能掩蓋來源矛盾。schema／prompt、完整唯一ID、九欄null、有資料／缺鈉／無重量／錯狀態／惡意文字／不存在食品等fixture俱備。沒有HTML/PDF真adapter，eligible_item_ids及audited/reusable只是可信server前提，不能由client自填旗標建立信任。

獨立審查找出並修正：部分宏量總質量超重未驗、點值／上界跨欄矛盾未驗、Python True==1使canonical型別替換通過、非字串unit拋TypeError、負零重建失敗、單欄與整份metadata大小上限不同。另加稀疏雙表間的子集合矛盾檢查，僅作一致性驗證、不拼表補缺。原始十進位字串／基準保存，計算不取已四捨五入顯示值；相同JSON可重新換算。

[profile-contracts.json](../food-nutrition-evaluation/2026-11-13/profile-contracts.json)盤點現有快照：TFDA330完整、1870部分、13來源一致性待審；USDA5431皆只缺反式脂肪，其他八欄有值。後續呈現需逐營養欄區分，不將這種partial誤說成全部營養不可信。13筆均是糖高於碳水，例如鮮奶布丁17.9g／13.1g；轉換器未見單位或欄位錯配，本機舊原始ZIP也相同。但分析方法／批次未知，不能斷言官方資料錯誤；舊ZIP與snapshot manifest的列數／hash不同，更不能宣稱完整來源鏈驗證。原快照與正式matcher未因本次盤點改寫。

剩餘限制：固定rounding容忍尚未按來源精度校準；小份量雙表疑義保守待審。新版表格原格只接受一般十進位格式與g/mg，體積列拒絕；其他格式需具體adapter。candidate與profile不授權自動納入，核心點值／來源權限仍是協調器門檻。下一步優先Phase2保存／風險／版本協商，包含legacy_unknown與OCR小於語意；之後才是真來源取回／授權、安全及正式Tavily協調器。

第二次審查補齊來源／目標身分enum及型別、HTTPS來源URL、帶時區抓取時間、adapter／retrieval版本與server prompt_version；限制dict／字串payload、catalog及prompt的大小／深度，typed拒循環／非法JSON。食品原名／狀態亦進profile快照。這些格式控制不等於來源授權或SSRF驗收。新增74項中33項profile、41項evidence通過，含舊dataset health合計86項nutrition聚焦測試通過；沒有新增付費請求。

最後完整隔離回歸653項中630通過、23項真Postgres整合略過，退出0；編譯、diff、三份文件與21份JSON查核通過。沒有真Postgres、真來源adapter、正式保存鏈或手機端到端驗收；本批達成離線合約門檻，第三層持續停用。

## 第三批交付審查：Phase2a後端保存與風險

本批限定record／preview／history後端v2；未改前端，不能標整個Phase2完成。三位分工代理分別處理儲存／schema、風險／進度與獨立API測試，主代理實作紀錄合約及路由後再次交叉檢查。

| 發現 | 實測或檢查 | 修正／限制 |
| --- | --- | --- |
| null在重讀變0，SQL丟context | memory／臨時SQLite／fakeMongo往返 | 新增v2context／version欄與canonical重算，legacy_unknown保留舊值 |
| 分頁可掩蓋其他頁v2 | 舊版limit=1取得legacy、同範圍另有v2 | 按完整查詢範圍保護，不只查當頁；不隱藏紀錄 |
| 菜單兩條漏擋下游 | mock付費函式曾被呼叫 | 五條個人化路徑統一在外部呼叫前攔截；推薦整合仍未完成 |
| 手動改鈉清掉已知過敏原／油炸 | 純紀錄fixture | 保留原始profile及食品風險身分，不讓改營養解除已知風險 |
| 原始profile fallback遇null | 手動改營養回歸曾失敗 | 保留最初可用快照，重複修改不抹除來源 |
| 有限值合計仍溢位 | exact與less_than各為有限極大值、巨大legacy整數／百分比 | 檢查整體上界與加總／百分比；typed numeric_range，不輸出非有限JSON |
| 只先查revision仍有競態 | 同時更新測試 | SQLite／memory只有一方成功；Mongo條件query僅fake驗證 |
| 舊版改／刪先查後寫可碰到新v2 | 儲存層直接繞過HTTP檢查 | SQL／Mongo條件與memory鎖內再次保護，舊版回upgrade_required |
| 全未知／全排除無疾病仍safe | 風險服務fixture | 改unknown；完整欄位也只為reference_nutrition_only，不代表過敏原安全 |

預覽與保存共用同一營養重算／風險路徑；未解項保留分母，省略既有項目拒絕，明確未食用才排除。新紀錄不接任意客戶端官方／web profile，只接受server本機來源或user_modified手動值。辨識context目前client_supplied且visual_completeness固定not_verified，未實作scan簽署／持久化，不能宣稱防止最初漏項。

最終測試明細見[record-backend-regression.json](../food-nutrition-evaluation/2026-11-13/record-backend-regression.json)。第一次全套在DELETE介面尚未整合完成時發生簽章TypeError；完成整合後全套通過，最終再次加入舊PATCH原子保護回歸。保留此執行問題，不當成正式功能缺陷或付費重試。

仍待驗：前端nullable型別／顯示、掃描／OCR與小於值、queue migration及跨日離線、歷史／趨勢／洞察、個人化推薦恢復、真Postgres／Mongo、部署migration。Mongo先查再insert的既有路徑尚無並行唯一索引保證。第三層來源repository／授權／安全取回／協調器及真值評估仍未做；下一步Phase2b，不重跑既有付費實驗。

## 第四批交付審查：Phase2b1前端基礎（2026-11-14）

已依指示建立v1.0.2，保留工作樹未提交修改。主代理做型別與transport，兩位代理分別做原格換算與queue，另有唯讀獨立合約審查。先建立獨立v2模組，尚未改既有營養顯示為nullable；只轉接queue、固定舊重送metadata及既有錯誤banner。

| 發現／風險 | 修正及證據 |
| --- | --- |
| 淺層回應檢查接受假complete／空未解ID | 重新核對原格intake與coverage狀態／分母／合計／IDs，加入反例 |
| 必要portion／風險身分遺失、point和upper同時存在 | 拒不完整或互相矛盾回應，避免下游格式化與風險誤判 |
| 原格嚴格檢查誤拒未解項 | 對齊fiber／sodium順序，Python真服務fixture比較所有項目 |
| POST同ID可能回既有legacy | 型別與runtime保留v1／v2聯集；不假稱已轉版 |
| queue可被舊retry降級 | 舊load只回v1，舊mutation保留v2；v2存原create payload，不重送server snapshot |
| 必填時間／來源／餐別在型別中可省略 | Queue專用輸入型別明列必填，不默默補當下時間 |
| 同runtime並行enqueue覆蓋 | mutex及immutable snapshot；mock並行測試通過 |
| 遷移或future schema會丟資料 | 新key寫入成功才清舊；損壞／未知／混版key保留且停下，focus catch顯示未同步 |
| retry忽略保存的原時間／餐別 | 改用getPendingRecordReplayMetadata，跨日fixture與呼叫點已核對 |

45項新測試及114項完整前端回歸通過；typecheck／lint／build:web通過。[驗收與範圍](../food-nutrition-evaluation/2026-11-14/README.md)明列五寬錯誤banner、互動與資料保留檢查。這不構成真手機或v2掃描全鏈驗收。console無error，保留既有pointerEvents警告。

未解門檻：跨tab原子鎖、混版queue合併、live submit按下時凍結時間、新版dispatcher、scanner及所有nullable顯示消費端、OCR小於語意、推薦／真DB。未接線的功能繼續禁止第三層；沒有新增付費呼叫或部署。

## 第五批交付審查：Phase2b2a送出完整性（2026-11-14）

本批依依賴順序先修舊scanner送出／重送，再進nullable全鏈；前述第四批未解項中，live submit與新版web分頁鎖已在限定範圍完成。完整記錄見主企劃第27節及[本批驗收](../food-nutrition-evaluation/2026-11-14/README.md#phase2b2a-送出與重試完整性)。

| 重現問題 | 修正與驗證 |
| --- | --- |
| 首次失敗跨日後才取queue時間／餐別 | 按下時固定完整事件，write-ahead後才POST，跨午夜整份body比對 |
| UTC字串把台灣凌晨算前一天 | 注入既有formatLocalTimestamp；獨立Asia/Taipei程序測00:03仍當日+08 |
| 改稿沿用client ID，後端回舊紀錄卻顯示新內容 | 不可變輸入、改稿拒絕；移除scanner optimistic append，成功後讀後端 |
| 遠端已存而remove失敗／背景成功後再點 | saved標記先於清理；同草稿再點不發POST |
| 換帳號後舊請求寫新畫面／401登出新session／舊保存清新辨識 | 核對user／token／API及草稿identity；saveRecord僅當前session發401事件，舊請求不發、新session401仍發已測；新camera／OCR結果保留 |
| OCR每次建新food ID使未改稿重試被擋 | 固定food ID為OCR草稿key；web檔案輸入＋假OCR重試body相同 |
| 分頁read-modify-write互相覆蓋 | 新版同名Web Lock包讀取／遷移／修改，無鎖停止；兩store mock並行驗證 |
| 改API後queue補送到另一個後端 | 保存原apiBaseUrl，整批POST前驗；舊缺目標／不符不送不刪，瀏覽器原字串不變 |

新增25項、全前端139通過且typecheck／lint／build:web通過。正常auth假session，所有API攔截，無實際登入／DB／付費呼叫；刻意503的resource error與既有pointerEvents警告有明確原因。測試曾重複處理file chooser產生Expo removeChild overlay，單次upload重跑後無overlay。camera／OCR新草稿identity保護另經呼叫點審查，未冒稱native相機驗收。

重新審查調整順序：既有trends以Number(null)成0、insights作假短缺結論、editor重建foods丟profile，不能直接把v2型別混入。下批先獨立versioned讀取模型／coverage-aware聚合，再接顯示與編輯。舊queue目標綁定／混版調解、舊lockless分頁、native多runtime、v2 dispatcher、OCR小於值、推薦／真DB與來源協調器仍是門檻；未啟用第三層。

## 第六批交付審查：Phase2b2b讀取模型（2026-11-14）

已完成前批指定的獨立讀取／彙總，尚未接畫面。主計畫第2、15、19、22節已同步更新，詳細範圍見第28節與[本批驗收](../food-nutrition-evaluation/2026-11-14/README.md#phase2b2b-讀取模型與本機架設沿用)。

| 審查發現 | 修正與證據 |
| --- | --- |
| legacy已知合計包含無法驗證的舊0／總數 | reported_value與驗證known_value分開；legacy_unknown不能作可信下界／剩餘／不足結論，缺欄位null |
| 只載一頁卻作整日結論、沒載到的天被當無紀錄 | 明列complete／page範圍；page不產生完整值／平均／目標結論，未載入日not_loaded |
| 未解項或全排除日讓摘要誤變完整 | 留原分母／快照，not_consumed明確排除；全排除日保留unknown，重新彙總不恢復被抑制的完整／上界 |
| 跨日／跨帳號或重複stable ID混入 | 使用當地日期前綴，拒越界／不同user／同ID重複；transport核對請求user／日期／天數 |
| 回應逐日皆合法但summary被竄改 | 驗證逐日數字、筆數、summary合併／coverage／avg_known_sum；actual Python fixture與反例測試 |
| 將legacy avg_*等同Decimal平均，合法回應被拒 | 0.1與0.2日均反例；Python3.14補償求和另與JS不同。未使用相容avg_*僅查格式，權威avg_known_sum仍嚴格比對與ties-to-even |
| 嚴格驗證unused refined_sugar別名擋舊資料 | 僅驗canonical九欄；保留原別名不作營養依據，新增相容反例 |
| 拿修改過的投影取得完整宣告 | 彙總重驗原server snapshot，保留profile／context／original identity而非重建foods |

新40項／完整179項前端測試、typecheck／lint／build:web及build:local通過。獨立審查未發現本限定helper範圍的新阻斷問題，不代表來源、照片或醫療專業驗收。本批沒有UI改動，未重跑手機渲染；未重跑既有733項後端。APP_VERSION與Expo／package根版本改1.0.2，編譯與啟動health驗證。

使用者另指定沿用已停止的Tailscale／SQLite架設供v1.0.2測試。保留原排程／腳本／env／模型／key，先備份DB，再同源export並啟動；本機及Funnel首頁／health確認正常，使用SQLite且驗證開啟。這是使用實際DB的啟動，與manifest內純測試的零使用者DB存取分開，沒有登入或飲食紀錄API操作。保護branch ref v1.0.1仍bb81e92；同名tag的存在不當成分支被改動。

待辦仍是nullable畫面／request guard／載入全量策略、掃描context／preview／revision、紀錄編輯、v2 dispatcher、舊queue調解、OCR界限、推薦與真DB／原生裝置／來源協調器。history沒有range anchor不能證明回應新鮮度；complete只描述已記錄項目，不能證明全天食物全數已記。第三層未啟用。

## 第七批交付審查：Phase3a Tavily核心（2026-11-14）

依使用者新優先序，今日／歷史／趨勢／洞察完整接線延後；先完成可隔離測試的Tavily後端核心。這是既有企劃的實作，並非等此步結束才開始。正式registry為0、沒有enrich公開route或profile保存權威，尚未啟用自動補全。見[主企劃第29節](2026-11-13-web-nutrition-fallback.md#29-第七批phase-3a-tavily-後端補全核心)及[驗收](../food-nutrition-evaluation/2026-11-14/README.md#phase3a-tavily後端補全核心)。

| 審查發現 | 修正與證據 |
| --- | --- |
| 表格合法不代表與食品相同；validator本身不比較名字 | registry先驗精確審核name／brand／variant／state／method／scope，才核發eligible_item_ids；不能只刪吉林兩字 |
| 權限旗標不能自己產生真來源授權 | 明列搜尋／擷取／快照／重用與review參照；只有synthetic fixture授權，production registry保持空 |
| 模型可挑不同來源、缺核心卻把熱量計入 | 多compatible policy回ambiguous_source；四核心必須是點值，否則incomplete_core、保持未解分母 |
| Energy(kJ)等變體被當unknown略過，可藏反證 | adapter拒未審營養列變體與空測量表；全欄及原格參與既有同源矛盾驗證 |
| 已換算custom serving丟原基準 | 既有matcher只選身分／優先，profile改讀server原始local表與custom builder原始選中基準 |
| 模型輸入帶整個item可能混入健康史 | 明列欄位白名單；無帳號／疾病／照片傳到Tavily或模型擷取 |
| web份量或多項合計溢位讓整餐raise | 加入份量預驗及罕見aggregate numeric_range隔離，保留其他點值與全分母 |
| 模型invalid_output／供應商額度被統稱upstream_error | 保留invalid_output、budget_exceeded、timeout終態；不足／逾時不冒充not_found |
| hardcoded confidence與正式設定漂移 | 重用既有VISION_FOOD_MIN_CONFIDENCE，低信心或validation issues不外搜 |
| socket阻擋及舊日期fixture使測試失敗 | socket改拒建子類以容許PySocks繼承；SQLite API fixture用帶時區時間，正式日期驗證不改 |

105個新增socket禁止測試通過（23 client／35 adapter／14 model／33 coordinator），涵蓋有界失敗、缺值、0、界限、錯品牌、錯來源及份量原格。完整後端838項，815通過、23未配置真Postgres略過、0失敗／錯誤。實際relay橋接只准一次attempt，未改既有辨識的預設輪替。這些是假transport／合成來源／模型選格的離線測試，沒有新付費、正式DB、來源使用權或真照片精度證據。

尚未處理：真來源與Tavily保存條款核可／具體真頁adapter、簽署scan/profile repository、per-user quota／冪等／跨請求single-flight／合法快取、影像金鑰池容量預留、HTTP與掃描保存接線及原生／部署端到端。只透過固定Tavily API，沒有直接fetch，不可宣稱DNS／redirect／任意URL SSRF門檻已驗。完整統計畫面可延後；未知不變0、來源快照、重量preview與舊版保護仍是正式試用必要條件。

## 第八批來源權限審查

官方文件查核後，USDA FoodData Central的資料權利可列為首批候選：API指南與首頁均標示資料為公有領域／CC0 1.0，並要求伺服器保護API key及遵守速率限制。這只回答資料權利，不回答固定食品頁是否能被Tavily Extract取得、頁面是否含完整營養表，亦不證明照片辨識出的食品相容。TFDA資料集在政府資料開放平台標示政府資料開放授權，但TFDA網站宣告仍要求註明出處並保留個別特殊聲明；在來源頁／資料類型／保存範圍逐項核對前列review-only。

Tavily的官方說明將Search／Extract輸出保存與出版者權利分開；可保存輸出不代表取得第三方內容授權，跨客戶共享快取需向Tavily確認方案適用性。故本批只補registry的權利證據欄位與拒絕條件，沒有把任何來源寫入production registry。證據見[source-rights-audit.json](../food-nutrition-evaluation/2026-11-14/source-rights-audit.json)。對FDC網域的一次受限Tavily Search只找到首頁／更新頁，未找到穩定food-details頁；以伺服器端USDA API key取得一筆Foundation API JSON後，新增的FDC adapter成功通過既有profile/evidence validator，並對Atwater energy及重複nutrient number要求server選擇。這確認API JSON格式可做第一個重播基礎，但沒有證明Tavily Extract能取到該JSON，也沒有建立正式policy。證據見[usda-fdc-api-replay.json](../food-nutrition-evaluation/2026-11-14/usda-fdc-api-replay.json)。bounded FDC client現只接受server-side `USDA_FDC_API_KEY`，不自動讀`USDA KEY.txt`；完整隔離回歸為855項（832通過、23項未配置PostgreSQL略過），且沒有新增USDA／Tavily請求。下一步是把FDC API key／rate limit納入server authority與有界HTTP流程，不以Markdown格式猜測。

## 第九批交付審查：USDA client、authority與冪等配額（2026-11-14）

本批新增的FDC client固定單筆API endpoint，只接受server-side `USDA_FDC_API_KEY`，禁止proxy／redirect／retry，通過共用期限、回應大小、strict JSON與`fdcId`比對；設定文件明確指出`USDA KEY.txt`不會被服務自動讀取。真實key只做受限FDC replay／client probe，未把秘密或完整回應寫入公開產物。

另完成獨立`NutritionAuthorityService`與`NutritionEnrichmentGuard`合約：前者簽署短效server-owned scan/profile identity，後者綁定fingerprint、single-flight、idempotency conflict與user/global quota；retryable provider failure釋放額度，`not_found`不作成功快取。authority 10項、guard 11項、FDC client 15項、adapter 6項通過；完整後端876項中853通過、23項因未配置PostgreSQL略過，詳[phase3b-backend-regression.json](../food-nutrition-evaluation/2026-11-14/phase3b-backend-regression.json)。

獨立複核的阻擋條件仍成立：兩個新服務是process-local，未接`app.py`、scanner、profile repository、HTTP route或production registry；跨程序／跨重啟的token consume、idempotency結果、quota與cache仍需共享資料庫原子操作及撤回／TTL政策。尚未進行真HTTP、真PostgreSQL／Mongo併發、照片準確率或自動補全啟用驗收，`automatic_web_fallback_enabled`保持false。

## 第十批交付審查：durable profile/source repository（2026-11-14）

本批先完成SQLite/Postgres的server-owned營養來源與profile持久化，不接正式路由。repository以現有reviewed registry作policy gate，保存不可變source policy revision history，profile hash由canonical profile計算，並以transaction + CAS避免並行靜默覆蓋。額外複核後已補上撤回／換版對owner讀取的失效、snapshot/reuse權利旗標、source URL/content hash/adapter version provenance比對，以及跨帳號reuse條件；10項測試全數通過，證據見`nutrition-profile-repository.json`。

仍有明確阻擋：Mongo atomic repository尚未實作；scan context、authority replay、idempotency/single-flight result、quota、cache TTL/withdrawal及HTTP route都尚未持久化或接線。repository不會自行讓production registry有內容，也不會改變`automatic_web_fallback_enabled=false`。下一批應先補durable request/quota/replay，再進行route的401/403、stale revision、profile mismatch、並行provider call及重啟驗收。

## 第十一批交付審查：durable scan context／authority replay（2026-11-14）

本批新增`scan_context_repository.py`，補上正式補全路由前的scan持久化與重播邊界。SQLite/Postgres保存使用者、scan ID/revision、完整辨識項目集合、canonical item-set hash、期限及active／expired／consumed／superseded／revoked狀態；不同帳號不能讀寫同一context，revision不可跳號，建立新revision會使舊版本失效，item遺漏／重複／改版不會被當成同一請求。authority JTI以unique表持久化，與consume在同一transaction中寫入，兩連線並行只能一個成功。8項離線測試全數通過，證據見[scan-context-repository.json](../food-nutrition-evaluation/2026-11-14/scan-context-repository.json)。

另外確認scanner展示用`recognition_context`不可直接成為authority input；正式route必須先由server映射至白名單欄位，再保存與簽署。

阻擋條件縮小但仍存在：enrichment request結果、idempotency／pending lease、跨程序single-flight、per-user/global quota及TTL／withdrawal cache尚未完成；Mongo仍不支援。repository尚未接`app.py`、scanner或provider，`automatic_web_fallback_enabled`維持`false`，不得據此宣稱已能自動補全。

## 第十二批交付審查：durable request／quota repositories（2026-11-14）

本批在上一批的scan context基礎上完成兩個SQL持久化邊界，仍未接正式路由。`nutrition_enrichment_repository.py`保存idempotency／fingerprint唯一性、server payload hash、pending lease、到期接管與結果；`nutrition_quota_repository.py`以同一transaction原子保存user/global window reservation，retryable失敗釋放，`not_found`消耗額度但不成為成功營養快取。

| 審查項目 | 結果 |
| --- | --- |
| request identity與重播 | 通過；同請求重啟後回結果，body／revision變更及跨使用者fingerprint明確拒絕 |
| lease與single-flight | 通過；pending逾時可由相同server-owned body接管，舊owner不能完成 |
| quota邊界 | 通過；user/global atomic reserve、retryable release、terminal／not_found consume、跨連線最後slot只允許一方 |
| 完整回歸 | 908項，885通過、23項因未配置真Postgres略過，0失敗／錯誤；證據見`durable-enrichment-repositories-regression.json` |

仍未驗證／未完成：live PostgreSQL與Mongo併發、HTTP authentication、authority route consume、request與quota跨repository作業協調、cache TTL／source withdrawal、scanner保存接線、真provider並行只一次及Tavily production policy。這些repository未修改`automatic_web_fallback_enabled`，production registry仍為空，不能視為自動補全上線。

## 第十三批交付審查：合法快取與可恢復協調器（2026-11-14）

本批補上前一輪審查指出的TTL／撤回及跨repository作業缺口，但仍刻意不接公開路由。正向cache repository只保存已驗證成功profile，key綁食品完整身分、來源與policy revision、URL、adapter／retrieval版本；預設TTL 7日、上限90日。讀取重新檢查source active／revision／rights，撤回或換版立即miss；`not_found`、429、timeout及其他provider failure沒有負快取寫入路徑。server-internal cache綁owner，cross-user必須有明確provider核准。8項cache測試通過，含重啟、過期、撤回、權利、provenance與scope。

可恢復協調器以durable request lease、per-user/global quota reservation及server-owned scan/profile revision為邊界；provider只呼叫一次，結果先保存再結算quota。retryable結果釋放額度，terminal／`not_found`消耗額度；quota結算例外可由重播reconcile，避免重新付費。provider返回後會再次檢查來源撤回／scan期限，拒絕TOCTOU下的stale結果。6項協調器測試與35項既有repository測試通過；完整925項後端回歸為902通過、23項未配置真PostgreSQL略過、0失敗／錯誤，證據見[phase3c回歸](../food-nutrition-evaluation/2026-11-14/phase3c-durable-orchestration-regression.json)。

審查結論：資料邊界與恢復語意已足以進入獨立authenticated enrichment route的測試設計，但尚未達啟用條件。Mongo atomic路徑、真PostgreSQL併發、authority token consume、scanner保存／preview、真provider closure、production source registry與HTTP 401／403及重啟端到端仍未驗。legacy `/predict/vision-food`不可直接包成第三層provider，否則本機TFDA／USDA命中會誤扣web quota；`automatic_web_fallback_enabled`維持`false`。

## 第十五批複核：scanner／authority／HTTP整合（2026-11-14）

前一批列出的兩個接線阻擋已完成限定驗證。scanner現在把伺服器辨識結果縮減成白名單item snapshot後保存；authority secret未配置或路由旗標關閉時不回傳token。啟用測試中，短效token的user、scan revision與完整item-set hash會被驗證，JTI與scan consumed狀態在同一個durable repository操作中寫入；同一idempotency key可重播，換key不能重用已消費scan。

本批新增scanner→route、authority replay、profile/source mismatch及Flask HTTP fixtures，沒有真Tavily／模型呼叫。仍需注意低信心／被拒項目為了維持完整item set會保存並可進入後續請求；正式開啟前應決定是否加入明確使用者確認門檻。真PostgreSQL／Mongo併發、真provider HTTP、429／timeout、跨重啟HTTP及positive cache write仍是未完成阻擋，production registry與自動fallback旗標維持關閉。

## 第十六批複核：provider resilience與正向快取（2026-11-14）

第十五批列出的 fake-provider 作業風險已完成限定驗證。兩執行緒同 key 的 single-flight 只發一個 provider call；timeout／429 的 retryable outcome 釋放 reservation，下一次重試使用新 reservation；quota 結算回應遺失時，重播會以 durable request 結果 reconciliation；SQLite 關閉重開後已完成 request 只回放，不再次付費呼叫。完整隔離回歸為 `955` 項，`932` 通過、`23` 項真 PostgreSQL 未配置跳過、`0` 失敗／錯誤，證據見`phase3f-provider-resilience.json`。

另外確認 positive cache 已由 route 接線：僅完整且有核心點值的 web profile，在 source policy／provenance／TTL／scope 通過時寫入；partial、not_found、timeout、429、invalid output 及非 web profile 不寫入。這修正前一節「尚未接線」的描述，但只代表離線 SQLite／fake provider 合約成立。真 PostgreSQL／Mongo、多程序 HTTP、真 Tavily／模型、首批來源權利與低信心使用者確認仍未驗；`PRODUCTION_SOURCE_REGISTRY`、`automatic_web_fallback_enabled`與route flag 持續關閉。

## 第十七批複核：低信心與 validation flags 的 fail-closed（2026-11-14）

複核發現低信心／帶 `validation_issues` 的 item 即使有 web cache，也不應被快取讀取提高可信度。route 現在先完成 TFDA／USDA local lookup；local miss 後立即檢查既有 `VISION_FOOD_MIN_CONFIDENCE` 與 validation flags，失敗即回 `confirmation_required`（HTTP 409），不讀 web cache、不建 provider、不 consume authority、不 reserve quota。新增 route 與 HTTP regression；完整隔離後端為`959`項，`936`通過、`23`項真 PostgreSQL 未配置跳過、`0`失敗／錯誤，證據見`phase3i-confidence-http.json`。

這個門檻維持證據分離：營養資料不能反向提高照片辨識信心。官方 TFDA／USDA 命中仍可回傳；要繼續第三層，必須先由使用者確認並建立新的 server-owned scan revision。真來源、真 DB、多程序 HTTP、frontend enrichment 接線與四畫面 v2 消費仍未驗，所有自動補全旗標持續關閉。

## 第十八批複核：provider contract、混合來源與未知 item 防護（2026-11-14）

| 審查發現 | 修正與證據 |
| --- | --- |
| known TFDA／USDA／cache 與 web 合併後 coverage 仍可能沿用 web 的部分統計 | provider factory 依完整 server-owned item set 重建 `NutritionCoverageV1`；mixed local+web test 驗證兩項都在分母與 known count |
| web 結果可能覆蓋較高權威的 local item | 合併時保留 known item；web 只補 missing item IDs |
| provider 宣稱 complete 但只回 `item_id` | route canonical item contract 要求 revision、status、origin、recognition context、profile、portion；malformed output 回 `invalid_output` |
| coordinator 可持久化不屬於本次 scan 的 item | complete／accepted 結果的 item IDs 必須與 request 完全相同；新增 unknown-ID regression |
| 測試 fixture 只表達舊的寬鬆 coordinator 結果 | 所有成功 fixture 改為 `NutritionEnrichmentRouteV1`，保留專門 malformed fixture 以確認 fail-closed |

本批 enrichment focused tests 34項通過；完整隔離後端 `962` 項（`939` passed、`23` skipped、0 failures/errors），前端營養回歸 `117` 項通過。這些是 SQLite／fake provider／mock transport 證據，不是 live PostgreSQL、Mongo、真來源或真 provider HTTP 驗收。production registry 與自動補全旗標仍關閉。

## 第十四批交付審查：authenticated enrichment route（2026-11-14）

新增的`POST /nutrition/enrichment`已與舊影像辨識路由隔離。審查確認請求先驗證Bearer登入與user binding，再用server-owned scan context拒絕過期、撤回、superseded、缺漏／重複／變更item set；本地TFDA→USDA命中不建立request lease、不占web quota。正向cache只在官方本地miss後檢查，source/profile authority在provider factory前重新驗證，避免 stale revision先觸發第三層。

離線route service 9項及完整後端936項（913通過、23項真PostgreSQL未配置略過）通過；手動Flask client確認401／403。這批沒有真Tavily／模型呼叫，production registry與`automatic_web_fallback_enabled`仍關閉。新的實作不等於正式開啟：尚缺scanner adapter與authority JTI consume、真HTTP provider／source policy、真PostgreSQL／Mongo併發、429／timeout與跨重啟驗收，且web成功profile的cache write尚待接線。

## 第十九批複核：本機 fail-closed 與 scanner transport 接線（2026-11-14）

目前執行中的 v1.0.2 服務已以 `/health` 驗證 SQLite、認證及官方資料層正常，兩個自動補全旗標仍關閉，沒有 provider 呼叫或使用者資料寫入；證據見`local-enrichment-route-disabled.json`。這是部署安全邊界驗證，不是 enabled route 的端到端驗收。

前端 scanner 已接上可關閉的 transport：保留 server-owned context／authority／item ID，只有顯式 Expo capability flag、authority token 與外部注入 source policy metadata 齊全才發 enrichment request；失敗時保留原 TFDA／USDA 結果。前端 189 項測試、typecheck、lint、web export 及後端 962 項隔離回歸均通過，證據見`phase3k-frontend-regression.json`與`phase3k-backend-regression.json`。

重新審查後，未解除的阻擋是：正式 source policy／保存權利、真 Tavily／模型 HTTP replay、真 PostgreSQL／Mongo 多程序與跨重啟、四個統計畫面的 nullable v2 消費，以及低信心項目的使用者確認／新 scan revision 流程。前端接線不會自行開啟 production registry，`automatic_web_fallback_enabled`與`NUTRITION_ENRICHMENT_ROUTE_ENABLED`繼續維持關閉。

## 第二十二批複核：PostgreSQL 驗證環境缺口（2026-11-14）

本輪按下一步順序先執行真 PostgreSQL 前置檢查。結果不是「PostgreSQL 通過」：本機沒有 PostgreSQL service／CLI／容器，`NUTRILENS_TEST_DATABASE_URL` 未配置，所以 52 項 PostgreSQL 測試中只有 29 項 offline driver／SQL contract 通過，23 項 live integration 被正確略過。另有 database selection 14 項與營養 repository offline 35 項通過。證據見[postgres-validation-blocked.json](../food-nutrition-evaluation/2026-11-14/postgres-validation-blocked.json)。

已補充專用`test_nutrition_postgres_integration.py`，準備在測試 URL 提供後驗證隨機schema、JTI replay、跨連線 request replay及quota last-slot；目前3項均因同一環境條件略過，不能列為通過。

隔離後端完整回歸重跑為965項（939通過、26略過、0失敗／錯誤），其中新增fixture的3項也只是環境略過；詳見[phase3l-backend-regression.json](../food-nutrition-evaluation/2026-11-14/phase3l-backend-regression.json)。

這次沒有 provider、Tavily、USDA、金鑰檔或使用者資料副作用。真 PostgreSQL 的 nutrition schema、row lock、跨程序 idempotency／lease、quota last-slot、重啟 HTTP 尚未驗；Mongo 新營養路徑也仍明確不支援，不能以既有舊 StorageRepository 的 fake Mongo 測試替代。下一個可執行條件是提供一次性隔離 PostgreSQL／Supabase 測試 URL，再重跑並補上五個 nutrition repository 的 live integration；在此之前不得開啟任何自動補全旗標。

## 第二十三批複核：SQLite 重啟、JTI replay 與 lease recovery（2026-11-14）

在等待隔離 PostgreSQL 測試庫期間，先補上不依賴外部服務的三個持久化邊界。第一，pending enrichment lease 過期後重新開啟 SQLite 檔案只能由新 worker reclaim，`request_id` 不變、`attempts` 增加，完成結果可再讀取。第二，retryable outcome（例如 timeout）寫入後重啟，原 idempotency key 重新取得 owner lease，清除舊 error 且不產生第二筆 request。第三，已消費的 scan authority JTI 在重啟後若嘗試綁定另一個 scan，回傳 `replay_conflict`，且另一個 scan 不會被誤消費。

新增 `test_nutrition_enrichment_repository.py` 兩項與 `test_scan_context_repository.py` 一項；兩個 targeted suite 共18項全通過。完整隔離後端回歸為968項（942通過、26略過、0失敗／錯誤），證據見[sqlite-restart-replay-regression.json](../food-nutrition-evaluation/2026-11-14/sqlite-restart-replay-regression.json)。

這批只證明 SQLite 的檔案重啟與跨連線語意，不能替代 PostgreSQL 的真 row lock、跨程序 last-slot／lease 競態，也沒有解除 Mongo atomic、真 provider HTTP、來源權利或自動補全旗標的阻擋。`automatic_web_fallback_enabled`、`NUTRITION_ENRICHMENT_ROUTE_ENABLED`與 production source registry 持續關閉。

## 第二十四批複核：source policy ID 與 source ID 正規化（2026-11-14）

複核發現請求欄位雖稱 `source_policy_id`，既有 route、coordinator 與 cache 實際上把它當成 `source_id` 使用；政策格式則允許兩者不同。若直接採用不同 ID，可能導致 authority／cache 找不到來源，或讓同一政策的兩種別名產生兩筆 request。現在 `NutritionProfileSourceRepository` 提供明確的 `get_source_policy_by_policy_id` 與 `resolve_source_policy_reference`：輸入可保持既有 source-id 相容，也可使用 policy-id；多個來源共用同一 policy ID 時直接回 `source_conflict`。resolver 只接受目前 active/current policy，再比對要求的 revision，不能以歷史 revision 授權新補全。

route 會把 alias 解析成 canonical `source_id` 後查 cache，profile reference 也必須綁定同一來源；coordinator 在 fingerprint 前把 alias canonicalize 成 policy ID，讓 source-id／policy-id 重試共用同一 durable request。cache repository 亦在直接 API 呼叫時正規化 source ID，並保留換版／撤回失效語意。證據見[source-policy-alias-regression.json](../food-nutrition-evaluation/2026-11-14/source-policy-alias-regression.json)：四個 targeted suite 共53項全數通過。

本批未呼叫 Tavily、USDA 或模型，未讀取金鑰，未變更 production source registry 或自動補全旗標。live PostgreSQL 的 policy-id 查詢／併發、Mongo atomic repository、真 provider HTTP 仍未驗證；`automatic_web_fallback_enabled`、`NUTRITION_ENRICHMENT_ROUTE_ENABLED`持續關閉。

## 第二十五批複核：本機 PostgreSQL 安裝後的 live persistence 驗收（2026-11-14）

本機 PostgreSQL 17 已安裝並以 `postgresql-x64-17` 服務自動啟動；`127.0.0.1:5432`
可連線，SCRAM 驗證規則已恢復。使用專用非 production 測試角色，所有測試在隨機 schema
內執行並於 teardown 清理，測試 URL／密碼未寫入 repo。既有 PostgreSQL storage/auth/
transaction/concurrency/reconnect 套件 23/23 通過；營養 persistence 的 JTI replay、
request replay 與 quota contention 3/3 通過，合計 26/26，且測試後沒有殘留 schema。

這只解除真 PostgreSQL persistence 的環境阻擋；Mongo atomic、真 provider HTTP、來源權利與
production registry、跨重啟 authenticated route 及四個統計畫面的 v2 消費仍是開啟第三層前置
條件。前置阻塞證據 `postgres-validation-blocked.json` 保留不覆蓋，新結果見
`postgres-live-validation.json`；所有自動補全旗標繼續關閉。

## 第二十六批複核：SQLite-only SQL 清理後重審（2026-11-14）

SQLite-only SQL 清理與完整後端回歸完成。`DATABASE_URL` 現在會明確拒絕，PostgreSQL adapter／driver／舊 tests 已移出目前 v1.0.2；SQLite database selection、driver 缺席時 import、JTI replay／revoke／跨重啟和 route targeted tests 通過，完整後端為906 tests + 682 subtests 通過。第45批 PostgreSQL live tests 是真實但隔離的歷史驗收，不是正式環境要求；本機 PostgreSQL 服務沒有在本批停用，現有 SQLite 資料也沒有被測試接觸或搬動。舊 `render.yaml` 分支仍是 `v1.0.1` 且設定 Postgres，README 已明確標示不得用於 `v1.0.2`。

此輪重新閱讀來源准入證據後，仍不適合開啟第三層：USDA FDC CC0 僅能確認資料可用條件，現有固定 ID client／adapter 只 replay 一筆蘋果資料，未實測候選搜尋、中文 alias、熟度／料理相容與 photo identity；Tavily 的地瓜球 PDF Extract 對線性化表格缺乏可驗證的 row/cell 對齊，adapter 正確拒絕，來源權利亦未獲 production approval。所以下一步限定為 FDC candidate-search/identity 合約及負例審查；不是 production wiring。證據：[SQLite-only cleanup regression](../food-nutrition-evaluation/2026-11-14/sqlite-only-cleanup-regression.json)、[USDA FDC 單筆 replay](../food-nutrition-evaluation/2026-11-14/usda-fdc-api-replay.json)、[Tavily/model replay](../food-nutrition-evaluation/2026-11-14/live-tavily-model-replay.json)。

## 第二十七批複核：FDC 候選搜尋與身分 validator（2026-11-14）

本批完成 FDC bounded Search client 及 `FdcCandidateSelectionV1` 離線 prompt／validator，定向 suite `31 passed`、`12 subtests passed`；完整隔離後端 `922/922 passed`、0 failed／skipped。獨立複核先發現 prompt／validator 的 FDC ID 限制不一致、候選 metadata 缺少重驗及未知身分仍能 suggestion，均已補正：僅允許 canonical 1–18位正整數 ID、白名單資料類型與格式化 metadata；核心身分欄位未知／缺漏時，validator 拒絕 suggestion。所有模型 suggestion 都仍是 `confirmation_required`。詳[主企劃第49節](2026-11-13-web-nutrition-fallback.md#49-第二十九批usda-fdc-候選搜尋與身分選擇離線合約)與[本批證據](../food-nutrition-evaluation/2026-11-14/fdc-candidate-selection-regression.json)。

尚有一項 route wiring 前置：目前 builder 與 validator 各自收候選 mapping；後續要使用同一份 server-owned normalized immutable snapshot，並綁定 scan revision/item-set/candidate digest，確保模型看到的候選正是被驗證及呈現給使用者的候選。本批沒有使用 USDA key、live Search、Tavily、模型或使用者 DB，也沒有 route、UI、nutrition profile 或 production source policy 接線。下一個受限步驟是 live FDC Search query replay，先測中文 alias 與英文名稱的真實候選品質，再決定是否進固定 ID detail replay；不能把 API 可呼叫視為食品匹配可用。

## 第二十八批複核：糯米腸 FDC live Search（2026-11-14）

用本機 USDA key 共發出3次 Search 請求，沒有取固定 ID Detail、營養資料或模型輸出。第一次中文輸入被 Windows native pipe 轉碼，明確排除為有效語意測試；`rice sausage` 回10筆，結果涵蓋異國香腸飯、一般 sausage 及 sausage rice links，無台式糯米腸等價證據；Unicode 正確的「糯米腸」query 回0筆。key 沒有輸出或寫入 evidence，正式 DB、route、Tavily 及模型未觸碰。完整證據：[fdc-live-search-replay.json](../food-nutrition-evaluation/2026-11-14/fdc-live-search-replay.json)。

結論是 Search API 的 bounded client 可呼叫，但目前 query 對此食品不具可用召回／精確度：中文直查 miss，寬泛英文有高誤配風險。這不是 FDC 全庫不存在該食品的證明。不得讓模型依排名挑近似 sausage，也不得把營養相近當作身份相同。下一批先設計受控 query normalization／少量英文別名並離線驗證；仍找不到可靠同物候選時，要保留 not_found 並轉至其他經准入來源，不接 FDC detail 或 production route。另維持之前發現的 prompt／validator candidate snapshot drift 為 route 前阻擋。

## 第二十九批複核：受控 query normalization（2026-11-14）

交接檢查發現 `food_query_normalization_service.py` 原本會對超量／重複 alias 靜默截斷或去重，與測試預期的可稽核 fail-closed 不一致；已改成 alias 超過兩個、case-insensitive 重複或非 allowlist 直接 `invalid_request`。目前糯米腸只允許原名、`glutinous rice sausage`、`Taiwanese glutinous rice sausage`，不接受 `rice sausage`、品牌拼接或模型自產同義詞。

另外補上 plan 的 `item_id`、`scan_revision` 與 identity digest。名稱、品牌、variant 或食用狀態改變時，`validate_fdc_search_query_plan()` 回 `plan_mismatch`；核心狀態未知時只保留原始中文 query。定向 query suite `6 passed`、`6 subtests passed`；FDC 相關 suites `31 passed`、`18 subtests passed`。證據與限制見[主企劃第51節](2026-11-13-web-nutrition-fallback.md#51-第三十一批受控-fdc-query-normalization-與計畫綁定)。

這仍不是候選品質或營養正確率驗收：沒有新增 live Search、Detail、Tavily、模型或使用者資料操作。正式接線前仍須將 query plan、候選結果、prompt、validator 綁在同一份 server-owned immutable snapshot；品牌／地區／括號內容不做通用字串刪除，避免把不同食品誤正規化成相同名稱。

## 第三十批複核：受控 alias live Search（2026-11-14）

第二輪 FDC Search 依 query plan 發出3次請求：原始「糯米腸」0筆；兩個 allowlist alias 各10筆，但結果主要是糯米粉、熟糯米、米糕，並混入異國 sausage-and-rice，沒有台式糯米腸同物候選。alias 只改善部分文字召回，沒有達到可安全配對的身份精度；因此安全狀態維持 `not_found`，不取 detail、不建 profile。完整逐筆證據：[fdc-alias-live-search-replay.json](../food-nutrition-evaluation/2026-11-14/fdc-alias-live-search-replay.json)。

交接結論：不要再用更寬泛的英文 alias 追求召回，否則會放大誤配。下一步應優先完成 immutable candidate snapshot／人工確認契約，或另找已核准且能保留食品組成與每100g原始表格的來源；FDC 對此 item 不能直接成為第三層營養值來源。

## 第三十一批複核：FDC snapshot 防止候選漂移（2026-11-14）

前一批指出 builder 與 validator 分別接收候選 mapping，可能讓模型看到的候選與 validator 使用的候選不一致。本批已改為 `FdcCandidateSnapshotV1`：建構時完成 server-owned identity／metadata projection、固定候選排序與 canonical digest；prompt 使用同一 snapshot，validator 重算並驗證 `snapshot_digest`、`item_set_digest`、`identity_digest`、`scan_revision` 及模型回傳 digest。候選內容變更、scan revision／item identity 變更、快照或模型 digest 不符、快照外 FDC ID、item 重複／缺漏、未知欄位均拒絕。成功 suggestion 仍只會是 `confirmation_required`。

定向回歸為 `38 passed`、`18 subtests passed`；完整隔離後端回歸為 `929/929 passed`，0 failed／skipped。證據：[fdc-candidate-snapshot-regression.json](../food-nutrition-evaluation/2026-11-14/fdc-candidate-snapshot-regression.json)。本批沒有 USDA Search／Detail、Tavily、模型、API key、使用者 DB 或 profile 操作，也沒有接正式 route。SQLite-only 仍是正式部署 SQL，PostgreSQL 不作正式部署。

複核結論：候選 prompt→validator 的資料漂移阻擋已解除，但 pipeline 仍未因此具備可自動補全能力。正式接線前仍缺使用者確認 UI、固定 FDC ID detail／nutrition adapter、來源 policy 與 route-level authority；糯米腸的 live FDC 結果仍不可安全配對，不能由相似食品代填。

## 第三十二批複核：FDC 使用者確認與 Detail replay 前置條件（2026-11-14）

新增確認 validator 後，模型 suggestion 與使用者確認已形成兩個不同狀態：模型 suggestion 永遠是 `confirmation_required`；只有使用者在同一 immutable snapshot 內明確選取的候選才可產生 `confirmed_pending_revision`。`reject`／`defer` 不得帶 FDC ID，任何確認結果都綁定 snapshot、revision 與 identity digest，並要求後續建立新的 server-owned scan revision，避免把低信心照片原地升權。

這仍不是已接線的使用者流程：沒有 HTTP endpoint、前端 UI、Detail provider 或營養寫入。下一個阻擋是固定 `/fdc/v1/food/{id}` endpoint、canonical FDC ID、payload ID、adapter version 與 retrieval version 的一致性驗證；正式 route 還必須使用伺服器持久化且綁定 authenticated user／scan_id 的 snapshot，不能信任客戶端重送的 snapshot。

## 第三十三批複核：FDC Detail → profile → portion 離線換算（2026-11-14）

補跑並確認固定 Detail adapter 的離線整合回歸：由受控 fake Detail payload 建立 `NutritionProfileV1`，再以 150g `vision_estimate` 份量計算，確認每100g基準只換算一次，原始 energy／nutrient evidence、單位、adapter version 與 retrieval version 維持可追溯。定向 FDC suite 現為 `40 passed`、0 failed；其中 fixed-detail adapter 為 `8` 項。證據見 [fdc-candidate-confirmation-regression.json](../food-nutrition-evaluation/2026-11-14/fdc-candidate-confirmation-regression.json)。

此批仍沒有 live USDA Detail、Tavily、模型、API key、HTTP route、前端確認 UI 或使用者資料庫副作用；不能把 fake transport 的換算通過解讀成 FDC 候選身分或真來源營養正確率。正式接線前仍必須由伺服器依 authenticated user、`scan_id`、`scan_revision`、`item_revision` 與 snapshot digest 取回持久化快照，記錄確認 actor／時間／idempotency／expiry，並在確認後建立新的 server-owned scan revision；不可接受客戶端自帶 snapshot 或 digest。

## 第三十四批複核：server-owned FDC snapshot persistence（2026-11-14）

本批補上前一批指出的持久化邊界，但沒有把它誤當成確認流程完成。`FdcCandidateSnapshotRepository` 只允許以 authenticated user 的 server-owned scan context 加上伺服器取得的候選 mapping 建立快照；它不接受 client snapshot／digest 作為 production input。資料表綁定 user、scan、revision、item-set digest、snapshot digest、expiry 與 status，並在新 revision、過期、撤回、重啟或候選 mapping 漂移時拒絕舊內容。

定向 snapshot／scan／selection／adapter suite 為 `39 passed`、`21 subtests passed`。這解除的是「快照可以安全落盤並在重啟後重新取回」的前置條件，不解除 confirmation endpoint、確認 actor／時間／idempotency、Detail HTTP、前端 UI、來源權利或自動補全旗標。下一步應在這個 repository 之上實作 authenticated confirmation contract，且成功確認後必須建立新的 server-owned scan revision，不能原地提升影像信心。

## 第三十五批複核：FDC confirmation durable contract（2026-11-15）

確認持久化已補上，但仍刻意停在 HTTP 之前。repository 不保存或信任 client snapshot；它從 server-owned snapshot repository 讀取快照，以嚴格 validator 驗證決策，並保存 actor、request hash、idempotency、expiry 與 digest 綁定。`confirm` 仍只是待新 revision 的授權，`reject`／`defer` 沒有 FDC ID 權限。

聚焦 confirmation／snapshot／selection suite 為 `28 passed`、`16 subtests passed`。剩餘風險是 endpoint 的 authenticated actor binding、確認後新 scan revision 的原子建立、前端確認畫面與 Detail route 尚未驗證；不能把 repository 測試解讀成使用者流程已上線。

## 第三十六批複核：authenticated confirmation HTTP boundary（2026-11-15）

新增 route 後，authenticated actor binding 與 client snapshot boundary 已有 HTTP regression：未登入在 feature gate 前回401；旗標關閉回503；user mismatch、未知欄位及 forged snapshot 不會進 repository；成功 confirm 只回 `202` pending-new-revision，不回營養值或信心升級。聚焦 route／repository／snapshot／selection 共 `33 passed`、`16 subtests passed`。

尚未解除的破綻是「確認記錄已保存，但新 revision 尚未原子建立」。因此 route 不能被當作 Detail provider 的授權入口，也不能在目前 revision 直接查 FDC Detail。下一步必須設計 server-owned revision issuance／transaction，確保同一 confirmation idempotency 重試不會產生兩個新 revision，之後才可接固定 Detail route 與前端 UI。

## 第四十六批複核：來源 rights／保存／撤回與 registry（2026-11-15）

官方條款複核結果與目前 registry 決策一致：USDA FDC 明示 public domain／CC0、需要 server-side API key 與 attribution，且 API 有速率限制；Tavily 允許 Search／Extract 輸出長期保存，但原始出版者權利與跨多使用者共用 cache plan 仍須另外確認。這些條款解除的是「服務層保存條件未知」，不是「任何搜尋到的食品頁都可自動重用」。因此 `PRODUCTION_SOURCE_REGISTRY` 維持空集合是正確的 fail-closed 結果。

複核另重現一個撤回後跨使用者歷史讀取的 500 風險：`nutrition_profile_repository.py` 在來源 policy 已撤回時，非 owner 的 `include_withdrawn=True` 會因 `source=None` 進入 rights lookup。現在已改為直接回 `source_unavailable`，並新增 regression；owner 的明確歷史讀取仍保留嵌入快照。完整 backend regression 為 `1011/1011 passed`，證據見 [source-rights-withdrawal-regression-20261115.json](../food-nutrition-evaluation/2026-11-14/source-rights-withdrawal-regression-20261115.json)。

剩餘阻擋沒有被掩蓋：`retention_policy`／`withdrawal_policy` 尚是文字審查欄位，撤回只使未來 authority／cache miss，不會依條款自動 purge 已存 profile、cache 或 raw snapshot。若來源要求刪除，必須先補明確 purge contract，否則不得登錄。下一個工作流可進入手機／Tailscale／SQLite disabled-by-default bounded E2E，但所有自動補全與 FDC／Tavily registry 旗標仍關閉。

## 第四十七批複核：SQLite／排程／Tailscale disabled-by-default smoke（2026-11-15）

停止並重新啟動既有 `NutriLens Backend` 工作排程後，確認目前 v1.0.2 程式確實被載入；本機與 Tailscale Funnel 的 `/health` 都是 `200`，且回報 SQLite、auth required、`automatic_web_fallback_enabled=false`、`nutrition_v2_scanner_enabled=false`。未登入呼叫 `/nutrition/enrichment` 及四條 FDC 路徑，在兩個 endpoint 都回 `401`。證據：[phase4-disabled-e2e-20261115.json](../food-nutrition-evaluation/2026-11-14/phase4-disabled-e2e-20261115.json)。

另用臨時 SQLite／臨時帳號啟動隔離服務，四條 FDC 路徑在 flags false 時回 `503 feature_disabled`；沒有 provider／Tavily／USDA／正式 DB 副作用。這次實測也確認一個部署操作風險：工作排程不會 hot-reload，若更新程式後只執行 `start-server.bat` 而沒有先停止，可能仍服務舊 route。現有部署文件已有先停、更新、再啟動與 health 檢查要求，本批依該順序完成。

這不是 native camera、相簿或 Tailscale authenticated write 驗收，也不代表完整 FDC confirmation→issued revision→preview→accept 已經開啟；仍維持所有 production flags 與 registry 關閉。下一步可做 scanner/UI 的 server-reference 接線審查，並把任何真機缺口維持為阻擋而非以測試替代。

## 第四十批複核：FDC Detail 與 profile／份量合約的離線接續（2026-11-15）

複核確認 `NutritionProfileV1` 的正規入口仍是 `build_nutrition_profile()`，`calculate_portion()` 會從 `source_nutrients` 與 `source_basis` 重建原始值。因此新增的 `fdc_detail_profile_service.py` 不把 FDC raw JSON 直接當 profile，也不把 per-portion 或已四捨五入欄位再次縮放；未知重量不會默認 100g。

本輪另修正容易造成錯誤配對的假設：scan 辨識名稱（如 `蘋果`）與 FDC source description（如 `Apples, raw, with skin`）不是同一欄。服務分開保存兩者，只對 state、preparation、components scope、brand、variant 做嚴格相容檢查；`unknown` 與 `None` 不可繞過檢查。輸出不攜帶 photo confidence，故營養補全不會升高影像可信度。

聚焦 FDC detail/profile/adapter/repository suite 為 `59 passed`、`7 subtests passed`。這是離線資料契約，不是 route 已上線；沒有 profile 寫入、真 USDA/Tavily/model 呼叫、來源權利核准、跨重啟 HTTP 或手機驗收。下一個必要檢查是 source policy／provenance 與 profile preview/write transaction 的整合，所有自動補全旗標維持關閉。

## 第四十一批複核：FDC 專用 source policy 邊界（2026-11-15）

獨立 validator 現在要求 FDC API 的固定 provider kind、canonical FDC ID／URL、per-100g table ID、adapter/retrieval version、來源身份與 server-approved review record；裸 Search candidate 不具備升格來源 policy 的資格。這避免把 USDA FDC API 與 Tavily Markdown page 混用同一份未分辨的 policy。這批只有離線 policy contract（7 passed），尚未將 policy 接到 durable profile repository，也沒有正式 rights approval、profile write、route 或自動補全。下一步先補 FDC provenance 的 retrieval/table/ID/identity 重驗與 policy withdrawal/restart/CAS 負例。

## 第四十二批複核：FDC policy 與 profile provenance durable binding（2026-11-15）

本輪已把前一節列出的 provenance 缺口補到 SQLite profile repository，但範圍仍保持在 server-owned offline contract。FDC-shaped policy 不再能透過改寫 provider kind 走一般 Web/Tavily policy；專用 validator 會固定 provider、numeric ID、Detail URL/source ID、per-100g table、adapter/retrieval version、source identity 與 server review。profile 寫入 transaction 重新驗證 FDC ID/provider kind、table/retrieval version 和完整 source identity；Detail continuation 會輸出這些 provenance 欄位。candidate Search 結果仍沒有 policy promotion 資格。

定向 policy／repository／Detail suite 為 `26 passed`、`9 subtests passed`；完整 backend 為 `985 passed`、`719 subtests passed`、0 failed。既有 Web/Tavily fixture 仍通過。負例涵蓋 ID／URL／table／版本／identity drift、provider downgrade、缺 review／rights 與候選升格；沒有 live provider、key、route、production profile write 或 confidence 變更。

## 第四十三批複核：server-owned FDC profile preview（2026-11-15）

本輪補上 FDC policy 的 durable withdrawal／CAS／restart 負例，並建立獨立的唯讀 preview coordinator。它把 authenticated confirmation、active issued scan context、canonical current FDC policy 與固定 Detail replay 綁在一起，重量與身份只取自 server-owned scan item；provider I/O 前後都重驗授權狀態，故 policy 撤回、revision／weight／confirmation 漂移、未確認 item、回應 ID 不符或 malformed document 都不會產生 preview。preview 仍不寫 profile、不改影像信心，也不接現有 raw Detail route。

Focused preview suite 為 `10 passed`；policy／repository／preview 合計 `32 passed`、`9 subtests passed`；完整 backend regression 為 `997 passed`、`721 subtests passed`、0 failed。這解除的是「可安全產生 server-owned nutrition preview」的離線前置條件，不解除來源 rights 正式核准、production registry、HTTP/UI、profile accept/write、飲食紀錄或自動補全。下一個阻擋是獨立 preview persistence 與單一 SQLite transaction 的 accept/write primitive，需避免巢狀 transaction 並驗證 rollback、restart、idempotency、CAS 與跨連線競態。

破綻尚未全部解除：這些測試證明 policy/provenance 邊界，不代表 USDA 對糯米腸有可用同物資料，不代表 rights 已取得正式核准，也不代表確認後 profile 寫入已具備跨 repository 原子性。下一步先補 FDC policy withdrawal／CAS／restart durable regression，再以 private preview/write transaction 綁定 confirmation-issued revision；所有自動補全旗標與 production registry 仍關閉。

## 第三十八批複核：FDC confirmation 原子 revision（2026-11-15）

前一批的 atomic issuance 缺口已解除：SQLite 交易先查 idempotency，再驗證 active server-owned snapshot，並在同一 transaction 保存 confirmation 與簽發下一個 revision；舊 revision 標為 `superseded`。相同 payload 重播原 issued revision，不會重複建版；rollback、restart、reject/defer 與 mixed confirm/defer 已回歸。

聚焦 confirmation／HTTP／scan-context suite 為 `23 passed`；完整後端 `970 passed`、`710 subtests passed`、0 skipped／failed。另以兩個 SQLite 連線並發提交同一 idempotency key，確認只保存一筆 confirmation 與一個 issued revision。server-owned lookup 另外檢查 owner、expiry、issued revision 及 active 狀態，未確認 item 不回傳候選 ID。未呼叫 USDA、Tavily、模型或 Detail，也未寫 profile／使用者飲食紀錄。固定-ID Detail route 已另增 disabled-by-default contract，見企劃書第59節；前端確認 UI、profile／portion接續與來源權利／政策仍待完成。

## 第四十四批複核：FDC preview accept/write 原子持久化（2026-11-15）

本批已完成前一批要求的高風險寫入邊界。`FdcProfilePreviewRepository` 將 preview 的 confirmation、issued scan/item revision、完整辨識 identity、server-owned weight、snapshot digest、FDC policy/source provenance、Detail hash、profile hash 與 portion 一起保存；`accept_preview()` 在單一 SQLite `BEGIN IMMEDIATE` transaction 中重新驗證所有綁定，再寫入 profile 並 consume preview。現有 public `save_profile()` 沒有被巢狀呼叫，避免 transaction primitive 互相嵌套。

rollback（profile insert 或 preview consume 失敗）、重啟後 replay、同／異冪等鍵、兩個 SQLite connection 競態、過期／撤回／policy revision／份量／identity drift、儲存 hash tamper 及 duplicate preview ID 綁定漂移均已測試。FDC focused suite `60 passed`，完整 backend `1000 passed`；沒有真 provider、Tavily、模型或 API key 呼叫。accept 仍是 server-side primitive，沒有接飲食紀錄，也不改 photo confidence。

## 第四十五批複核：preview/accept authenticated HTTP boundary（2026-11-15）

新增兩個預設關閉的 route：`POST /nutrition/fdc/profile-preview` 與 `POST /nutrition/fdc/profile-accept`。route 先驗證 authenticated user，再檢查 feature flag；preview 只接受 confirmation／scan／issued revision／item references，preview ID 由 server 產生；accept 只接受 server-owned preview ID 與 idempotency key。client profile、FDC ID、weight、Detail document、source policy 與未知欄位均在 repository／provider 前拒絕。

route focused suite `7 passed`，另有真 Flask route＋隔離 SQLite 的 `2 passed` integration tests，與既有 FDC confirmation／Detail 合約合計 FDC focused `69 passed`。integration 只使用 fake Detail provider，沒有 live USDA、Tavily、模型或 key。這只證明 disabled-by-default HTTP 邊界與資料注入防護，不代表功能已開啟。`FDC_PROFILE_PREVIEW_ROUTE_ENABLED`、`FDC_PROFILE_ACCEPT_ROUTE_ENABLED`、`FDC_CONFIRMATION_ROUTE_ENABLED`、`FDC_DETAIL_ROUTE_ENABLED`、`NUTRITION_ENRICHMENT_ROUTE_ENABLED`、`automatic_web_fallback_enabled` 與 production source registry 仍關閉；下一步仍是 Detail→profile/portion 線上接續、真來源 rights／provider 驗收及 scanner/UI／手機端 bounded test。

## 第四十八批複核：scanner／UI reference flow 前置條件（2026-11-15）

本輪把 scanner 實際程式與既有 FDC route contract 對照。`scanner.tsx` 只有一般 nutrition enrichment helper；`nutrition-fdc-preview-api.ts` 雖已具備 reference-only preview／accept transport，沒有任何 scanner／畫面呼叫。影像辨識回應中的 `scan_context` 只在同一次函式內供 enrichment 使用，未保存供後續使用者確認。更重要的是，後端 snapshot repository 只有 server-side `save_candidates()` primitive，沒有接入 `/predict/vision-food`，也沒有 authenticated snapshot／selection read route；因此 UI 沒有合法來源取得候選清單、snapshot digest 或 confirmation reference。

前端 `124` 項 nutrition regression、typecheck、lint，以及後端 FDC snapshot／confirmation／Detail／preview focused `35` 項均通過。這些結果證明目前停用旗標下不會誤呼叫 provider，也不能被解讀為 UI 已可操作。若現在直接做 UI，必須把候選或 FDC ID 從 client 傳回，違反 server-owned boundary；所以本輪不修改 UI、不開旗標。

下一步應先完成 server-owned candidate snapshot 的建立／保存／authenticated reference-only read contract，再將 `scan_id`、revision、snapshot digest 以不可偽造的伺服器回應傳給 scanner，最後才接 confirmation → issued revision → preview → accept UI。native camera／相簿與真機寫入仍另列 bounded E2E；來源 rights／registry 仍是 production admission hard gate。

另外修正 scanner 的資料完整性反例：新增 enrichment item 若沒有 server-owned 正重量，原先可能以 `100g` 建立可記錄食物；現在直接保留 unresolved，既有 item 也不在缺重量時被覆蓋。scanner records `12 passed`，整組 nutrition `124 passed`，typecheck／lint 通過。

## 第四十九批複核：FDC candidate Search server boundary（2026-11-15）

已新增 `FDC_CANDIDATE_ROUTE_ENABLED=false` 的 authenticated POST/GET route。POST 不接 client item/candidate/FDC ID，只從 owner-bound persisted scan context 重查本地營養資料；TFDA 或 USDA FNDDS dataset health 不可用時拒絕搜尋，且僅對高信心、validation clean 的 `no_local_mapping` 查詢 USDA。Matched、source conflict、incomplete、incompatible 與低信心項目不觸發 FDC Search。每掃描最多 4 個 eligible miss、12 requests、每 request 5 candidates、25 秒 deadline；candidate snapshot 綁定完整 scan/revision/identity digest，GET 只回 owner 的 active snapshot，route response 僅含候選 metadata，不含營養數字或 Detail payload。

定向 service/HTTP tests `13 passed`，另以真 Flask route＋隔離 SQLite＋fake FDC Search 完成 snapshot POST、GET、同 digest replay 與 owner denial integration；FDC snapshot/query/client/vision local routing/enrichment HTTP regression `66 passed`、`68 subtests passed`。完整隔離 backend pytest `1032 passed`、`721 subtests passed`、0 failed/skipped。live provider、API key、Tavily/model、production SQLite、profile/record 均未觸發；所有旗標仍關閉，registry 為空。

新發現的操作限制：同一 scan/revision 的 duplicate Search 在單一後端程序內序列化並從持久快照 replay；SQLite snapshot unique constraint 可保護重複寫入，但跨 process Search single-flight 尚無持久 lease，若未來改多 worker 需先補 durable reservation 或共享鎖。目前 Windows/Tailscale 單程序服務可保留此限制，但不得宣稱跨程序只呼叫一次。下一步才可接 scanner reference state 與 item-by-item confirmation UI；未通過手機 bounded E2E 前維持 candidate/confirmation 等 flags false。

## 第五十批複核：scanner candidate reference transport（2026-11-15）

新增預設關閉的前端 candidate Search helper，POST 僅傳 scan ID/revision，GET 僅傳同一 reference；response validator 精確允許 server projection，不接受營養值、FDC Detail 或未知欄位。它會檢查 owner scan、revision、digest、身份欄位、候選項目上限與 `available`/`empty` 狀態一致性。空候選 snapshot 是成功讀取，不代表 provider error，也不會自動挑選食材。

scanner 只保存 scan ID/revision、snapshot 與候選 metadata，不保存 authority token。Zustand 以 reference object identity、owner 與 API host 防止延遲 response 寫入過期狀態；新掃描、清除、登出、帳號切換或 API host 變更會清除 reference。候選 request 是不改變 vision detections 的背景附加流程，且需前端明確旗標與 access token；本次沒有實際開啟 flag 或發出候選 Search。

| 驗收 | 結果 |
| --- | --- |
| frontend nutrition tests | `131 passed` |
| scanner and store lifecycle tests | `15 passed` |
| TypeScript／ESLint | 通過 |
| backend candidate contract/integration | `8 passed`，隔離 SQLite + fake provider |
| side effects | 0 live USDA/Tavily/model/key；0 production SQLite/profile/record writes；flags false |

結果與限制記錄於 [fdc-candidate-scanner-reference-20261115.json](../food-nutrition-evaluation/2026-11-14/fdc-candidate-scanner-reference-20261115.json)。下一個可實作項目是以 candidate snapshot 建立逐食材確認 UI 並呼叫既有 confirmation route；但現有份量調整只存在 client state，而 preview 讀取 server-owned weight，UI 必須先顯示伺服器原重量或先建立安全的 weight revision contract，不能送 client weight 覆蓋。仍須維持使用者確認，不可把 Search 候選視為 AI 已認定或營養來源。手機實機、camera/gallery、Tailscale enabled bounded flow、來源 rights admission 與跨程序 Search reservation 均未驗證；所有 production flags 與 registry 繼續關閉。

## 第五十三批複核：重量契約與逐項候選確認（2026-11-15）

重量調整沒有後端 route，revision primitive 也只允許同一 item set；本批沒有讓 client weight 覆寫 server-owned scan。確認面板只呈現 USDA 候選 metadata，要求每項明確 `confirm`／`reject`／`defer`，不顯示營養、不提高 photo confidence、不建立 profile，也不寫 dietary record。未來 preview 固定使用伺服器掃描重量，面板已明示 local portion correction 與 server preview 是不同狀態。HTTP helper 只傳 digest-bound choices/reference，server response 以 scan revision、snapshot digest、item identity 和 unchanged confidence 驗證；issued revision 前進後清空舊 snapshot，transport retry 沿用完全相同的 idempotency key/body。

frontend nutrition `138 passed`、scanner lifecycle `16 passed`、backend confirmation＋preview route `12 passed`、typecheck／ESLint 通過。Expo Web 390×844 僅完成未登入登入頁 smoke，無 console errors/warnings；沒有實際確認 route 或 provider 呼叫。尚未解除的風險是沒有數字版 server weight preview、沒有重量修改 revision route、沒有手機 camera/gallery＋Tailscale enabled E2E，也未把確認接上 Detail/profile preview/accept。fake provider／隔離 SQLite bounded E2E 應先涵蓋上述流程，但仍不得接 profile accept 或飲食紀錄寫入；rights admission、production registry、跨 process Search reservation 仍是 production gate。

## 第五十六批複核：scanner → 隔離 SQLite HTTP → FDC preview browser E2E（2026-11-15）

本輪把真實瀏覽器操作接到獨立 Flask 子程序與臨時 SQLite：gallery 選圖後，真 `/predict/vision-food` 回傳高信心 unmatched 食物，前端保留 server scan reference，接續真 candidate Search、使用者 confirmation（revision `0 → 1`）及 server-owned profile preview。Vision、FDC Search 與 Detail provider 均為固定 fake；Playwright 未攔截 vision／營養 routes。此流程未呼叫 profile accept 或飲食紀錄寫入。

實測修正一個實際接線缺口：沒有 local nutrition detection 的高信心 recognized/unmatched 項目原先會令 scanner 丟棄 scan reference；現在只對 ID 相符且無 validation issue 的 server-owned 項目保留候選流程。低信心及 validation-invalid 項目仍不進入確認。preview 驗得 server weight 與 portion weight 同為 `150g`，每100g `52 kcal` 計算為 `78 kcal`；SQLite 留存 2 個 scan contexts、1 snapshot、1 confirmation、1 active preview，profile／meal record 都為 0。慢速操作因既有 120 秒 expiry 回 `409`，快速重跑成功，未放寬 TTL。

scanner tests `18 passed`、preview HTTP integration `3 passed`，typecheck、ESLint 與 Expo web export 通過。390×844 與 1440×1000 均無水平溢出，切換 viewport 後 preview 保留，瀏覽器無 runtime error；僅有既有 `pointerEvents` deprecation warning。詳細證據見 [fdc-profile-preview-sqlite-browser-e2e-20261115.json](../food-nutrition-evaluation/2026-11-14/fdc-profile-preview-sqlite-browser-e2e-20261115.json)。

此為 bounded test，不是上線許可：未驗真 USDA/Tavily/model、相機、Tailscale 外部裝置、production registry/來源權利、跨程序 Search reservation、accept 或飲食紀錄。production flags 維持 false，registry 維持空集合，SQLite-only 不變。下一 gate 為來源權利／production registry 審查及跨程序 reservation；真相機與另一裝置驗收仍列為部署前界限，不可由本輪 browser 測試代替。

## 第五十七批複核：來源權利、publisher rights 與 purge 邊界（2026-11-15）

本輪核對 USDA FDC API Guide 與 Tavily 當前 Terms/Help Center。FDC 表示其資料屬 public domain／CC0 1.0，並請使用者標示 FDC；API key 須 server-side，預設限額為每 IP 每小時 1,000 次。這支持 FDC 資料本身的使用候選資格，但不替代食品 identity、nutrient adapter、FDC ID 與 profile provenance 審核，也沒有在本輪建立 policy 或 registry entry。

Tavily 官方 Help 表示 Search／Extract／Crawl output 可長期保存且無 Tavily 層級的 delete requirement，也允許應用程式對 end users 顯示 output。相同文件明確保留 original publisher rights 責任，Tavily 不授予 third-party content 權利；跨多客戶快取須先聯絡確認方案。現行 Platform Terms 的 API grant 為 internal business purposes；使用者實際 order form／account plan 未檢視，所以不能據此認定目前 app 的所有部署型態均已涵蓋。個別營養頁的內容條款／license／attribution 未 review 前，Tavily source 不進 registry。

程式盤點顯示 withdrawal 是 future access revocation，不是 purge：profiles、cache、preview、scan context、candidate snapshot、confirmation 及 enrichment request/result rows 仍會保留；cache 唯有 TTL `purge_expired()`。source result row evidence / normalized profiles 可能持久化，雖未發現獨立 raw Tavily page table；不得把「未存全文」推論為 publisher restrictions automatically satisfied。若來源要求刪除，需有 source-scoped、可冪等的 SQLite purge，並涵蓋 WAL／journal、backup 及依賴資料；否則排除該來源。此為 repository code review，不是法律意見或真 DB purge 測試。

證據及官方連結見 [source-rights-recheck-20261115.json](../food-nutrition-evaluation/2026-11-14/source-rights-recheck-20261115.json)。本輪沒有 provider call、key read、production DB write 或 flags change；registry `0`，所有正式 flags 仍關閉。下個技術 gate 可進 SQLite cross-process Search reservation；這不解除逐網站 rights admission、Tavily plan scope、真相機或 Tailscale external-device 驗收。

## 第九十二批複核：CNF／FDC血緣及青江菜搜尋邊界（2026-11-17）

本批對照CNF 2026與USDA FDC的官方回應，並檢查現有local USDA來源及查詢服務。CNF food code 2038明確標記來源為未修改USDA資料、USDA NDB 11116；選取的七個核心營養欄與FDC SR Legacy 170390相同。CNF 2026並非獨立fallback候選。CNF source code 12代表假設為零；若未來要建立source adapter，缺值／估算零語意必須先映射，不能填成真實零。沒有保留營養數字。

FDC官方API以`bok choy`找到raw Foundation與raw SR Legacy，也找到cooked boiled列；精確中文`青江菜`無結果。現有候選search已把泛稱身分和非local miss fail closed，但查詢alias registry只有糯米腸英文名，無青江菜映射。這是可重現、範圍狹窄的檢索可達性缺口，不構成放寬generic identity gate或以模型記憶判定營養的理由。青江菜別名應是server-owned retrieval alias，必須只在模型已回傳具體身份之後使用，且不應改變辨識結果或confidence。

架構上，online FDC Search/Detail仍屬USDA第二層，不是Tavily第三層。推薦順序為local TFDA → local USDA FNDDS → gated/user-confirmed USDA FDC → 權利與食物相容條件均通過後才是Tavily受控檢索＋模型抽取。青江菜raw source不能直接乘熟菜照片估重；若無prepared-compatible row，應呈現明確限定的raw per-100-g食材參考或維持未配對，不能聲稱精確熟菜份量。添加油仍排除。詳細紀錄：[alternative-nutrition-source-screening-batch92-20261117.json](../food-nutrition-evaluation/2026-11-14/alternative-nutrition-source-screening-batch92-20261117.json)。

未發現需要聯絡FSANZ的技術缺口，也沒有寄信。這是資料血緣與程式路由檢查，不是法律意見、照片識別準確率或端到端provider acceptance。CNF未准入、production registry仍空、automatic fallback仍關閉。下一gate為青江菜英文候選query的限域實作／測試，先不接Tavily／模型營養抽取。

## 第五十八批複核：跨程序 reservation 與鎖順序（2026-11-15）

原本 snapshot PK 和 Python lock 不保證跨 worker 不重複 Search。本批加入短 SQLite lease transaction，provider 期間不持 writer lock；snapshot insert、owner／expiry／active scan 驗證及 lease 清除同交易。真 Windows spawn 驗證兩程序共用一份 3-query plan，第三程序重啟後直接 replay。provider 失敗與 follower 共用一個 error，不由等待者自動排隊重查；後續新請求可成功重試。真 terminate owner 後，透過注入時鐘越過 lease expiry，由新程序接手成功；這個測試沒有等待正式 60 秒。

獨立審查提出並已修正三類問題：頻繁 writer polling 改為唯讀、失敗刪 lease 可能放大重試改為保存 failed outcome，以及 scan／snapshot Python lock 與 SQL writer lock 順序反轉改為 durable path 僅靠 SQLite lock、transaction-local direct SQL 驗證。regression 直接禁止 writer transaction 取得 scan Python lock，以及 durable snapshot 取得 snapshot Python lock，並涵蓋外層 confirmation transaction 讀取。

最終完整 pytest 在上述修正後為 `1044 passed`、`721 subtests passed`、0 failed／skipped；candidate focused collection 共 `40` 項包含其中。另驗 wrong user、stale owner、immutable replay、先提交快照的競態與 snapshot／lease 原子 rollback。證據：[fdc-candidate-search-reservation-20261115.json](../food-nutrition-evaluation/2026-11-14/fdc-candidate-search-reservation-20261115.json)。獨立最終複核未發現此 reservation／snapshot 範圍內剩餘阻擋，不能據此宣稱整個 pipeline 零缺陷。

限制不隱藏：lease 無法保證上游費用 exactly-once；provider 已回應但本機未 commit 就中斷仍可能重查。failed／abandoned reservation metadata 只在啟動或後續 claim 到 scan expiry 時清理，沒有定時 purge；這也不取代第五十七批來源撤回刪除契約。未開正式 flags、未讀 key、未呼叫真 provider、未動正式 SQLite 或保護分支。該批交接的 expiry/restart UI 已由第五十九批完成限定驗收；真相機／Tailscale 另一裝置、來源 admission 及最後 flag review 仍保留，六工作流範圍不變。

## 第五十九批複核：過期／斷線／同 DB 重啟恢復（2026-11-15）

獨立讀碼確認原本 candidate catch 靜默、expired confirmation 反覆沿用舊 request、preview 英文錯誤及裝置時間判斷 snapshot 等缺口。本批以共用 recovery helper 修正；current-reference 與 session guard 防止舊失敗清除新 scan，store 只清除相符 authority／snapshot，保留 detections／timestamp。暫時錯誤沿用完整原決定／冪等鍵，terminal 失效退出確認並提示重掃。獨立複核後未發現本次修改的阻擋缺陷，31項前端相關測試通過。

真瀏覽器透過真 Flask HTTP 及 temp SQLite 驗過：candidate失敗／成功重試；candidate失敗後過期再重試 `409` 且零額外Search；snapshot過期後確認無新revision；confirmation過期後預覽無Detail；fake Detail返回時越過期限則 `409`，不保存／顯示晚到preview。實際停止測試程序並以同 DB `--resume`，既有candidate、confirmation、preview及policy revision保持；重啟期間網路失敗保留原決定，再送body與key完全相同，只簽一次revision。另對已保存confirmation再真重啟，replay為同ID／revision的`202`，preview續作`200`；到期後兩者均`409`，不多呼叫Detail。

最終新browser session以單一CLI click/upload排除初期重複處理filechooser造成的測試錯誤，沒有runtime exception／framework overlay；resource errors全為刻意注入的502／409。error與preview在375／390／430／768／1440寬度無水平溢出，390／1440截圖已檢視。完整前端224通過、後端1051通過／734 subtests、0失敗／略過；typecheck、lint及web export通過。Metro曾沿用測試環境transform，最終清快取匯出並檢查same-origin／flags=false及不含測試8090／token；這項部署驗證必須保留。

限制仍清楚：UI已載入的preview沒有expires_at／自動移除合約，只有唯讀核對用途；清除／重掃會移除，後續授權仍由server重驗，不得當成可寫入憑證。confirmation繼承原snapshot期限，新issued scan不延長它。資料列status尚active也不能略過expires_at，沒有定時purge或來源撤回刪除驗收。本批只完成expiry/restart子項，沒有真相機、另一裝置Tailscale、來源正式准入、accept／飲食紀錄實機寫入或真provider。所有正式flags／registry維持關閉，SQLite-only及六工作流不變。證據：[fdc-expiry-restart-browser-e2e-20261115.json](../food-nutrition-evaluation/2026-11-14/fdc-expiry-restart-browser-e2e-20261115.json)。

## 第八十四批複核：Tavily 使用範圍與公開營養來源候選（2026-11-17）

本輪使用官方來源查閱 Tavily Help Center／Platform Terms、MEXT 食品成分資料與 GOV.UK CoFID。Help Center 表示客戶面向應用及免費 Researcher 方案可用，但 Platform Terms 的 API grant 仍寫限客戶 internal business purposes；Help Center另指另行簽署協議控制。實際方案、Order Form及書面support答覆均未取得，故不能確認此專案部署型態已被涵蓋，也不推定禁止。Tavily 不授權第三方內容，publisher權利仍須獨立審核。

MEXT官方頁明示食品成分資料可自由使用、應用二次使用需標示《日本食品標準成分表（八訂）増補2023年》，標準值以可食部每100g表示，且2023資料頁列有2026-03-27正誤更新。CoFID官方資料頁提供Excel、適用GOV.UK OGL v3.0（第三方內容例外），但最後更新為2021-03-19，並指出部分舊食品未在後續版本review／validated。這些是官方資料候選，不證明指定食物列含完整九項營養、不證明特定照片身份或台灣菜餚相容，也未測Tavily是否能抽取其來源頁／表格。

維持 production Web registry 為空、automatic fallback 關閉。下一個必要輸入是適用的 Tavily plan／Order Form 或其書面確認；釐清後才選擇一個真實、身份已確定且健康TFDA／USDA皆無相容記錄的食品，做限域來源擷取。不得以已有USDA match的蘋果強制觸發，也不得以身份未定的葉菜測營養檢索。完整來源、結論及副作用見[第84批機器可讀證據](../food-nutrition-evaluation/2026-11-14/source-rights-candidate-review-20261117.json)。本批沒有Tavily API／模型呼叫、credential／account頁讀取、DB操作、設定／程式變更、部署或測試執行。
