# 營養流程分階段驗收

最新：第六十八批收到使用者 Android 拍照辨識結果回報。使用者表示以相機拍照並取得結果；截圖選中「拍照」，但無法單獨證明快門與結果的請求對應，故記為 user-attested camera smoke。畫面共8個候選，白飯與茄子2項配對、6項待確認，合計357 kcal／77mg鈉；截圖仍出現舊 badge／標題。唯讀 GET 確認目前公開 scanner HTML／bundle HTTP 200，bundle SHA-256 `65a1c6ad6ae466bdcfa76aaea307201e36e9b96cd15f00da2896d1b1bebd24d9` 與本機修正版一致，且未見舊文案字串；手機當時載入的資產仍未知。證據：[android-camera-results-20261116.json](android-camera-results-20261116.json)。正式 automatic fallback 與 v2 scanner 仍關閉。

## 第六十八批：Android 拍照辨識結果（2026-11-16）

使用者回報已用 Android 相機拍照辨識，並提供五張結果截圖。第一張顯示「拍照」模式選中、Android 公開 HTTPS scanner 網域及辨識完成結果；依使用者直接回報，將相機辨識 smoke 記為完成。截圖本身沒有快門預覽或來源照片，結果頁仍顯示「啟動相機」，因此不能獨立重播或證明該結果與特定快門事件相連；這不是原始 request／response trace。

畫面共8個候選：白飯（97%，估重180g，TFDA）329 kcal、蛋白質5.6g、鈉4mg；茄子（88%，估重55g，USDA參考）28 kcal、蛋白質0.6g、鈉73mg。可見合計為357 kcal、蛋白質6.2g、鈉77mg，逐項相加吻合。其餘6項待確認為菜菜75%、熟肉塊35%（明示信心過低）、豆干丁90%、毛豆仁88%、雞腿95%、青江菜72%。營養參考值依影像估重換算；未有秤重、配方或營養真值，故不評估正確率。

相較第六十七批截圖，配對由白飯／雞腿變為白飯／茄子，茄子由待確認變成配對、雞腿改為營養未匹配待確認，白飯估重由200g變180g；候選數由7變8。兩批未證明來源影像 bytes、取景與拍攝條件完全相同，故只記錄可見輸出差異，不宣稱模型同圖重跑不穩定或哪次比較準確。

頁首仍顯示舊「Gemini + TFDA」和「已辨識 2 項食物」，但下方有USDA參考來源且另列6項待確認。事後唯讀 GET 公開 `/scanner` 與其 bundle 均 HTTP 200；server bundle `entry-a14ad6f15a5616c7c0db5aed6c916e85.js` 的 SHA-256 為 `65a1c6ad6ae466bdcfa76aaea307201e36e9b96cd15f00da2896d1b1bebd24d9`，與本機 `frontend/dist` 相同，且 bundle bytes 不含截圖裡舊 badge／標題字串。這使舊瀏覽器資產或較早截圖成為合理解釋，但沒有手機 cache、HTML/JS 載入記錄，不能確認確切原因。「加入今日紀錄」按鈕可見，但是否操作／寫入未知。截圖也不能證明實際模型、USDA／Tavily呼叫、usage、費用、登入或資料庫寫入。

本批 agent 檢視五張圖片與既有文件，另只 GET 公開 scanner HTML／JS 各一次；未呼叫模型／USDA／Tavily或 application API，未接觸資料庫，未改程式、旗標或 registry。完整欄位、逐張 SHA-256 及限制見 [android-camera-results-20261116.json](android-camera-results-20261116.json)。相機 smoke 子項已完成；下一次手機 UI 檢查前應完整重新載入頁面，較大的 Tailscale／SQLite preview/accept 驗收與來源權利 gate 仍未因此通過。

## 第六十七批：Android 相簿結果追測與 bundle 對照（2026-11-16）

使用者提供五張新截圖。第1張明確選中「相簿」，主要操作為「選擇餐點照片」，所以是另一輪相簿辨識，不是相機快門測試。共7個候選：白飯（97%，200g，TFDA）366 kcal、鈉4mg；滷雞腿（96%，110g，USDA參考）232 kcal、鈉436mg。畫面合計598 kcal、鈉440mg、蛋白質30.8g，算術吻合。另五項待確認：綠色葉菜78%、茄子92%、豆干92%、毛豆仁90%、綠色葉菜80%，未計入合計。

與第65批相簿結果相比，雞腿估重由105g變110g，顯示熱量由222升至232 kcal、鈉由416升至436mg；這是估重／模型結果差異，不是準確度測量。葉菜仍以泛稱呈現，分數高低不構成菜種真值，也不應因此觸發營養檢索。

截圖1仍顯示舊「Gemini + TFDA」與「已辨識2項食物」字樣。唯讀 GET 檢查時，公開 scanner HTML與 JS bundle 均 HTTP 200；bundle SHA-256 `65a1c6ad6ae466bdcfa76aaea307201e36e9b96cd15f00da2896d1b1bebd24d9` 與前次修正後部署版本相符。截圖可能早於部署或使用舊瀏覽器資產，現有證據無法區分。下一輪先重新載入當前頁面，再獨立跑 Android「拍照」模式；需截到相機模式／快門結果，辨識後停在結果頁，不確認候選、不接受 profile、不保存飲食紀錄。

截圖上的「加入今日紀錄」按鈕沒有成功或失敗狀態，保存狀態維持未知。模型供應商、app 執行時模型／USDA／Tavily請求、usage、費用及資料寫入也無法由截圖判定。本批 agent 僅 GET scanner HTML／JS，未呼叫模型／USDA／Tavily或正式 application API，未接觸資料庫、未改旗標。完整截圖雜湊與限制見 [android-gallery-followup-20261116.json](android-gallery-followup-20261116.json)。

## 第六十六批：目前 relay 原模型聯網能力重測（2026-11-16）

依使用者授權，以現有受限診斷工具發出最多4次模型請求，全部0重試。requested alias 為 `[AN]gemini-4-hydrogen-high`，回應 `model` 欄位為 `gemini-4-hydrogen`。一般 payload 與加上 `web_search_options` 的固定網頁讀取探測均 HTTP 200，但模型明確回覆沒有網路搜尋／讀取工具；回應沒有 `tool_calls`、`annotations` 或 `grounding_metadata`。簡單 strict-schema 控制成功；required function-tool 控制回傳1個 function call，表示一般工具呼叫可用，不是網路搜尋證據。總回報 usage 為2,948 tokens、0重試；relay沒有價格資料，不推估費用。完整診斷摘要：[model-capability-recheck-20261116.json](model-capability-recheck-20261116.json)。

本批0 Tavily／USDA請求，未傳照片、未登入、未寫正式 SQLite／profile／飲食紀錄，未改正式 flags／source registry，未部署。本結果只驗證目前 relay 請求路徑，不表示供應商原生 API 加入專用 Google Search grounding 不可能。第三層當前建議維持「受控搜尋／來源取回 → 模型只抽取來源明確列出的每100g營養欄位 → 後端驗證來源、食品狀態、單位、缺值與份量換算」；Tavily 是檢索工具而非營養資料庫，正式 source registry 仍空、自動補全仍關閉。模型不得憑記憶補營養數字，泛稱「菜葉」不得搜尋。

下一個手機驗收仍需使用者以 Android 相機快門拍攝同一張便當，辨識後停在結果頁，不確認候選、不接受 profile、不保存飲食紀錄。

前批：第六十四批備份 SQLite、`build:local` 成功，重啟既有 `NutriLens Backend` 排程部署目前 v1.0.2。local／Funnel health 均200，scanner HTML／bundle200，遠端與本機 bundle SHA-256 相同，外部 `database_path` 為 null；automatic fallback=false、v2 scanner=false。當時的 Android 掃描待辦已由第六十五批的相簿辨識結果接續，但相機快門仍待驗。模型／USDA／Tavily呼叫0，未登入、未寫profile或飲食紀錄。證據：[deployment-phone-smoke-preflight-20261116.json](deployment-phone-smoke-preflight-20261116.json)。

前批：第六十三批以同一張便當照片呼叫真實 relay 模型兩次（0重試），strict parsing 成功；同圖重跑有菜名、重量及做法差異。兩次均將葉菜保守標泛稱，且每項辨識信心高於0.45，所以這兩份結果進待確認區主因是沒有相容營養配對，不是低信心。局部修正位置字尾泛稱 gate 和精確 TFDA 電鍋白飯做法 enum 對應後，完整後端 `1082 passed / 1141 subtests`，當時尚未部署。未做原手機封包、菜種獨立真值或秤重驗收；Tavily／USDA API呼叫為0。證據：[photo-model-replay-20261115.json](photo-model-replay-20261115.json)。持續模型呼叫授權已記入主企劃書；該批使用量12,428 tokens，relay未提供價格，因此不推估費用。

前批：第六十二批完成已知泛稱的共用 fallback 身分門檻及舊 confirmation／preview 新授權阻擋，完整後端 `1074 passed / 1090 subtests`。程式尚未重啟／部署，真模型與手機營養實測未因此完成。證據：[food-identity-gate-regression-20261115.json](food-identity-gate-regression-20261115.json)。

前批證據：第六十一批取得使用者本人 Android 相機／辨識完成及使用既定 HTTPS scanner 的回報；附圖左上大陸妹、右下青江菜（使用者標註）均在待確認區顯示「炒菜葉」，見 [android-camera-smoke-20261115.json](android-camera-smoke-20261115.json)。第六十批部署預檢保留於 [phone-tailscale-preflight-20261115.json](phone-tailscale-preflight-20261115.json)。第五十九批 expiry/restart browser UI 與同 SQLite 真程序重啟隔離驗收見 [fdc-expiry-restart-browser-e2e-20261115.json](fdc-expiry-restart-browser-e2e-20261115.json)。正式 source rights 與 production flags 閘門未解除，統計完整畫面仍依使用者要求延後。

## 第六十五批：Android 相簿辨識結果與來源摘要文案（2026-11-16）

使用者提供四張 Android 行動瀏覽器結果截圖及一張便當照片。首張顯示「相簿」模式選中，故這是相簿上傳辨識結果，不是相機快門流程證據。截圖顯示共7個候選：2項成功配對營養、5項待確認／未計入。

| 狀態 | 項目 | 信心 | 份量 | 可見營養／來源 |
| --- | --- | ---: | ---: | --- |
| 已配對 | 白飯 | 97% | 200g | TFDA；366 kcal、蛋白質6.2g、碳水82g、脂肪0.6g、飽和脂肪0.2g、纖維1.2g、鈉4mg；總糖及反式脂肪未提供 |
| 已配對 | 滷雞腿 | 93% | 105g | USDA參考資料；222 kcal、蛋白質23.5g、碳水0g、總糖0g、脂肪14.1g、飽和脂肪3.9g、纖維0g、鈉416mg；反式脂肪未提供 |
| 待確認 | 菜葉 | 82% | 未顯示 | 缺少相同食品與狀態的可信營養資料；建議搜尋葉菜、青菜、綠色葉菜 |
| 待確認 | 茄子 | 88% | 未顯示 | 未配對；建議搜尋茄子 |
| 待確認 | 豆干 | 87% | 未顯示 | 未配對；建議搜尋豆干、豆乾 |
| 待確認 | 毛豆 | 84% | 未顯示 | 未配對；建議搜尋毛豆、枝豆 |
| 待確認 | 菜葉 | 83% | 未顯示 | 缺少相同食品與狀態的可信營養資料；建議搜尋葉菜、青菜、綠色葉菜 |

可見合計 `366 + 222 = 588 kcal`、`4 + 416 = 420mg sodium`，與畫面一致；五項待確認不在該總數中。雞腿卡片標示 USDA 一般參考值，並提示實際配方、含水量、油鹽及品牌可能不同，估重排除骨頭但包含雞皮。圖中文字另指出整體影像估重與營養不是實測值，營養合計不完整。兩個葉菜項目維持「菜葉」泛稱；高 confidence 僅是模型輸出分數，不能證明菜種或校準準確。此結果支持保守不猜種、不拿相似來源代填；不能從截圖推斷植物種類、重量真值或營養準確率。

截圖也暴露 UI 問題：固定頁首「Gemini + TFDA」不能描述當次結果，因為雞腿卡顯示 USDA，且設定 relay 可用、實際模型供應商／回應沒有 request trace；摘要「已辨識2項食物」只數有配對營養項，卻與五項已辨識但待配對項矛盾。已修改前端：頁首 badge 依 matched detections 顯示 TFDA／USDA／自訂等來源，不再猜模型；辨識標題改為「已配對 N 項營養資料」，總候選 pill 會計入 pending，部分待確認時用警示 icon。純 helper 測試涵蓋來源摘要及零配對／部分配對標題。

| 驗收 | 結果 |
| --- | --- |
| Android flow | 公開 HTTPS 行動瀏覽器相簿選圖後辨識完成；不是相機快門驗收 |
| visible result | 7項候選：2 matched、5 pending；588 kcal／420mg 鈉算術吻合 |
| model/provider evidence | 實際供應商、請求／重試次數、tokens／費用未能從截圖判定 |
| record persistence | 截圖未顯示成功保存或失敗；是否有資料寫入未知 |
| live USDA/Tavily | per-item USDA reference label 不是 live API call 證據；請求紀錄未取得 |
| frontend regression | scanner 24 passed、typecheck、lint、build通過；390×844及1440×1000 rendered QA無水平溢出、0應用程式錯誤 |

五個附件的 SHA-256、輸入／資訊限制和未證項見 [android-gallery-recognition-20261116.json](android-gallery-recognition-20261116.json)。之後已完成 `build:local`、SQLite 備份、既有排程 stop/start 與 public bundle 驗證：390×844／1440×1000 rendered QA 無水平溢出、0應用程式錯誤；遠端 bundle SHA-256 `65a1c6ad6ae466bdcfa76aaea307201e36e9b96cd15f00da2896d1b1bebd24d9` 與本機一致，health200且 automatic fallback／v2 scanner仍關閉。保存／模型使用狀態不猜測；`refs/heads/v1.0.1`、SQLite-only、空 production source registry 及正式 fallback 關閉決策不變。下一步可由使用者在 Android 相機模式重做同一張照片驗收；相簿不代表相機權限／快門已通過。

## 第六十四批：部署 v1.0.2 與 Android 掃描前置（2026-11-16）

先完成 SQLite 備份與 `npm --prefix frontend run build:local`，再停止原排程、確認 5000 listener 釋放並啟動同一個 `NutriLens Backend`。local／Funnel health 均 HTTP 200，回報 v1.0.2、SQLite、auth required、automatic web fallback=false、nutrition v2 scanner=false、AI relay=true。Funnel scanner頁 HTTP 200；本機與遠端 bundle SHA-256 相同（`15c433c5bba7bcf8b478c240c51425246e7c858dc8b05fd954d49b667728e462`）。外部 health 的 `database_path` 欄位值為 null，本機 health 有值；資料庫路徑未由外部回應洩漏。

本次僅發 health、scanner HTML 和 bundle GET，沒有登入／相機辨識／profile accept／飲食紀錄操作，沒有觸發模型、USDA或Tavily。服務啟動會照常存取 SQLite schema／維護，因此不宣稱零正式 DB 存取；沒有使用者 profile 或 meal-record 寫入。FDC/enrichment flags 未由公開 health 暴露，沒有改動且未在本批獨立驗證。`v1.0.1` branch 保持基準 commit，SQLite-only 不變。證據：[deployment-phone-smoke-preflight-20261116.json](deployment-phone-smoke-preflight-20261116.json)。

**待完成的手機驗收：**請使用者以 Android Chrome 開啟既有 HTTPS scanner、登入並用相機拍攝同一張便當，辨識後停在結果頁，不確認候選、不接受 profile、不保存飲食紀錄。只記菜名、待確認區與錯誤。此部署不會強迫模型猜菜種；若仍顯示「炒菜葉」等泛稱，保持泛稱不進資料檢索，不視為程式失敗或辨識準確率改善。未取得實機結果前，不宣稱手機驗收通過。

## 第六十三批：原照片模型回放與局部修正（2026-11-15）

原圖位元組 `1ba154...70ea`（516x387 JPEG，47,567 bytes）與 production prompt 相同，串行呼叫兩次、皆HTTP 200／stop／strict JSON通過，零重試。設定識別 `[AN]gemini-4-hydrogen-high`，回報模型 `gemini-4-hydrogen`；relay provider 身分未獨立驗證。回報 prompt 1,934 tokens／次、completion 1,051／1,063、reasoning 4,615／1,831，所報總量共12,428 tokens；無 relay 價格，未估費用。

兩次皆輸出7項，白飯、滷雞腿及兩個葉菜大致可見；第一次綠菜名為「綠色葉菜」×2、做法 unknown，第二次為「葉菜（左上格）／葉菜（右下）」、做法 stir_fried。兩次明確表示無法由照片確定菜種，沒有把使用者標註送入 prompt。confidence各在0.75以上，但重量信心僅0.35–0.60；同圖兩次估重、項目順序與部分配對欄位改變，沒有 ground truth 因此不作準確率聲稱。全部項目均高於0.45門檻；在這兩次重播中，待確認來自本機營養未配對／相容性，而非低信心。

發現並修補兩處狹窄問題：位置後綴不能讓泛稱取得 fallback 身分；TFDA A0550601 白飯資料證實電鍋烹煮熟白米但無 method enum，僅對此精確紀錄將最近 enum `steamed` 作相容映射，不放寬其他食物／做法。修正後離線重播：第一次4項有本機配對、3項未配；第二次2項有配對、5項未配，兩餐均不完整。熟毛豆對應來源仍為生品，故正確拒絕；葉菜未搜尋、不以網路推斷菜種。獨立審查未發現兩項修補有廣泛放行漏洞。全後端1082項與1141 subtests通過。未呼叫Tavily／USDA API，未碰 production DB／route、未存檔、未改 registry／flag、未重啟或部署；完整模型 raw report 僅留 ignored `tmp/`，精簡可核對證據：[photo-model-replay-20261115.json](photo-model-replay-20261115.json)。原Android request bytes與先前raw response仍未知。

## 第六十二批：泛稱 fallback 身分門檻（2026-11-15）

三個 helper 及 FDC query plan 共用已知泛稱／不確定名稱判定；「炒菜葉」即使高分，也不能進新 FDC Search、web cache 或 Tavily 補全。小白菜／大陸妹／青江菜等具體名稱仍需通過既有狀態、來源與營養檢查，不能據此認定已有營養或照片菜種正確。正規化僅供比較，不改原名、分數、ID、重量與 revision；同名兩項用合成 40／70g 驗證分開保留，非本次照片的測量重量。

舊 snapshot 可讀，但不能將泛稱 suggested／confirm；舊 issued confirmation 不再授權 Detail，舊 active preview 不得再接受寫 profile。defer／reject 和已 accepted 的原鍵 evidence replay 保留，不新增 profile。獨立複核修正未知標記、熟食材剝除及 direct-SQL preview bypass，最後未發現本範圍新增重大回歸。完整後端 `1074 passed / 1090 subtests`、`146.98s`；真 Flask route＋隔離 SQLite 的 focused 7 項及 preview repository 13 項包含在總數內，不能再相加。

此為有限詞彙 fallback guard，official/custom local hit 優先路徑不改；沒有新增菜名更正 UI／route，不把 candidate confirm 視為具體身分已補足。本批沒有真 provider、key、正式 DB、flag、重啟、commit 或 push。SQLite-only、空 production registry 及來源准入邊界不變；手機服務尚未套用本輪程式。下一個既定驗收是原照片受限模型對照與 raw response／rejection diagnostics，未新增第七個工作流。完整證據：[food-identity-gate-regression-20261115.json](food-identity-gate-regression-20261115.json)。

## 第六十一批：Android 相機回報與葉菜身分門檻（2026-11-15）

使用者實機回報：相機正常、辨識完成、主觀結果大致正確；補充確認使用既定 HTTPS scanner，並提供 `food_picture/多種菜色的便當.jpg`，標註左上大陸妹、右下青江菜，兩者在待確認區顯示「炒菜葉」。一張照片與兩項使用者標註不構成辨識準確率；原始 JSON、實際分數／拒絕理由／item ID、來源 metadata、總測試數、份量與營養真值、瀏覽器及是否保存仍未知。這是外部 Android 使用公開 HTTPS 入口的使用者 smoke 回報，不代表私有 Tailscale peer、FDC／Tavily 補全或正式 SQLite 寫入通過。

目前 prompt 要求不確定菜種時使用「葉菜」等保守名，沒有查到後處理把具體菜名一律改為「菜葉」的規則。已檢視附圖，但菜種仍以使用者標註為依據，沒有原始回應不足以定位退回原因。待確認區同時接收低信心及營養未匹配，依程式不進合計，非本次數值核算證據；程式允許同名不同 ID，未驗本次 ID／照片位置對應。原四個離線合成 case 外，再補測「炒菜葉／大陸妹／青江菜」；合成 confidence=0.95、validation_issues=[] 及合法狀態下，七個 case 均通過三個資格 helper 及 FDC query plan。這證明泛稱資格 gate 缺口，未呼叫 provider、未驗整條 route或營養涵蓋；web 後續仍須通過 registry／policy 等條件。

下一個既定門檻為修正共用食品身分判定，涵蓋「炒菜葉」等帶做法泛稱，防止高分或 web cache 繞過確認；保留原辨識名稱、分數與各自 item ID，具體菜種經確認建立新 revision，本次使用者標註不等於確認 UI 已完成。Tavily 僅補已知身分的營養來源，不反推照片菜種。本批含補充仍只更新文件／證據，未改程式、旗標、正式 DB 或服務，未新增模型／Tavily／USDA 呼叫。完整輸入與結果：[android-camera-smoke-20261115.json](android-camera-smoke-20261115.json)。

## 第六十批：Windows／SQLite／Tailscale Android 驗收前預檢（2026-11-15）

唯讀預檢確認排程工作與目前 v1.0.2 checkout 相同、服務健康、本機及 Funnel HTTPS 使用同一 SQLite 後端，scanner 頁與 bundle `200` 且 asset hash 完全相同；SQLite `integrity_check=ok`。本批明確發出的 HTTP requests 僅有 health、scanner HTML 與 JS，沒有由預檢動作觸發 live provider call；未檢視服務背景日誌、key/secret 內容，亦沒有手機照片、資料列寫入、restart 或 flag 變更。這是相機 E2E 的前置條件，不是手機或第二裝置通過證據。

健康 API 只有回報 automatic web fallback 關閉；FDC route flags 未暴露，scheduled task process environment 未被檢查，故其他 runtime flags 明記未證。測試用 browser server 含固定 token 與 test controls，只准 loopback，禁止公開。下一項限定為 Android Chrome 上未保存的真相機辨識 smoke test；不呼叫 FDC preview/accept，也不寫 profile／meal record。完整欄位見 [phone-tailscale-preflight-20261115.json](phone-tailscale-preflight-20261115.json)。

## 第五十九批：expiry/restart UI（2026-11-15）

修正candidate靜默失敗、terminal失效反覆重試、裝置時鐘否決server snapshot等問題。真browser／HTTP／temp SQLite驗過candidate失敗重試、expired candidate／confirmation／preview拒絕、Detail進行中到期、真服務停止／同DB重啟、原決定／冪等鍵相同重試及已保存confirmation跨重啟同ID／revision重播；profile／meal writes均0。120秒TTL未放寬，所有provider均fake。

完整前端224通過；後端1051通過／734 subtests、0失敗／略過（151.23秒）；typecheck／lint／清快取web export通過。error／preview在375／390／430／768／1440寬度無水平溢出，最終browser無runtime exception。一般匯出採same-origin及四個功能flags=false，已驗不含測試8090位址／token。完整證據與限制：[fdc-expiry-restart-browser-e2e-20261115.json](fdc-expiry-restart-browser-e2e-20261115.json)。已顯示preview仍是唯讀歷史快照，不宣稱自動到期移除；真相機、另一裝置Tailscale、來源admission及accept／飲食紀錄實機寫入仍待驗。

## SQLite Cross-process Search Reservation（2026-11-15）

兩個 Windows spawn worker 各自開同一暫存 SQLite 檔；fake provider 等到確認 follower 已加入 reservation 才放行。結果為一份 query plan、3 次 Search、相同 digest；第三個新程序重播增加 `0` 次呼叫。失敗併發只呼叫 `1` 次，兩程序回相同 `upstream_error`；下一個新程序重試成功後累計 `4` 次。另真正中止 blocked owner，以 repository clock `1000 → 1006` 越過 `1005` lease expiry，驗證新程序恢復；沒有等待真實 60 秒。

補上短 claim transaction、唯讀 follower polling、共享失敗結果、stale-owner 防護及 snapshot／reservation 原子 commit／rollback。獨立審查修正 scan／snapshot Python lock 與 SQL writer lock 的順序反轉；durable path 只依 SQLite lock，交易內直接查同連線的 scan state。等待 regression 確認只有初次 claim 的 1 個 writer transaction。

最後程式修正後完整後端 pytest：`1044 passed`、`721 subtests passed`、0 failed／skipped，`141.07s`；40 項 candidate focused collection 包含其中。這是至少一次恢復，不保證外部 API exactly-once；中斷前已完成但尚未提交的上游回應可能需重查。過期 reservation metadata 在啟動或未來 claim 清理，沒有背景定時 purge。完整證據：[fdc-candidate-search-reservation-20261115.json](fdc-candidate-search-reservation-20261115.json)。

本批沒有 live USDA／Tavily／model、key read、正式 DB/profile/meal-record write、正式服務重啟或旗標變更；registry 仍空、SQLite-only 不變。下一步為既定 expiry/restart bounded UI，真相機／另一裝置 Tailscale、來源 rights admission 與最終 flags review 仍待完成。

版本保護：使用者明定v1.0.1只更換AI模型，保留原branch基準bb81e92；本企劃其餘改動在v1.0.2隔離，無push。最近依指示以既有Tailscale／SQLite啟動v1.0.2；下文「未部署／未commit」描述各批當下狀態。模型／金鑰設定、本機DB、使用者新增照片及無關外層規劃不加入提交。

## Phase3a.1 來源權限與首批候選審查

日期2026-11-14；本批只查核官方授權／保存範圍並補registry合約，未啟用production policy；已完成1次受限FDC網域Search，沒有擷取使用者資料。完整狀態見[source-rights-audit.json](source-rights-audit.json)。

| 來源 | 結論 | 下一個阻擋條件 |
| --- | --- | --- |
| USDA FoodData Central | CC0 1.0，列為第一個真頁重播候選；API key與速率限制需伺服器控管 | 固定food-details頁的Tavily Extract重播、食品身分／版本／表格adapter審查 |
| TFDA open data／網站 | 資料集授權與網站／個別頁權利需分開核對，暫列review-only | 來源特定權利、保存範圍及adapter重播 |
| Tavily輸出 | API保存條款不取代原出版者權利；跨使用者快取需確認方案 | 方案／跨使用者重用核可，且不得送出健康史或照片 |

registry現在要求license、attribution、reuse／cache scope、retention／withdrawal、reviewer及evidence URLs；cross-user reuse沒有provider明確核可時會被排除。production registry仍為0，沒有正式自動補全。

## Phase3b.0 USDA FDC API replay

本批對`fdc.nal.usda.gov`做一次受限Tavily Search，結果只有首頁／更新頁，沒有穩定的固定food-details營養頁；沒有再用Tavily Extract猜測動態頁。改用伺服器端USDA API key取得一筆Foundation資料（FDC 1750340），保存於本機忽略目錄後離線重播，金鑰未寫入報告。新增`fooddata_central_adapter.py`只接受受審canonical API URL、有限JSON、Foundation／SR Legacy／FNDDS、每100g語意、payload hash及固定食品身分；Foundation的Atwater General／Specific與重複營養編號必須由server policy指定，不能由模型選擇。既有evidence/profile validator驗證成功，證據見[usda-fdc-api-replay.json](usda-fdc-api-replay.json)，6項adapter測試及FDC重播通過。

這是API格式及單筆資料重播，不是Tavily頁面能力、食品相容性、照片準確率或正式保存授權驗收。FDC API key仍須server-side authority／配額／速率限制；production registry保持0，automatic_web_fallback_enabled保持false。

## Phase3b.0a 真 USDA FDC 固定 Detail replay（2026-11-15）

本批以 process-only 的 `USDA_FDC_API_KEY` 對固定 `1750340` 做兩次 server-side Detail replay；金鑰未寫入產物。兩次均為 HTTP 200、`Apples, fuji, with skin, raw`、`Foundation`、35 nutrient rows；指定 server-reviewed nutrient numbers 後，adapter、profile 與 150g portion 通過，證據見 [usda-fdc-detail-replay-20261115.json](usda-fdc-detail-replay-20261115.json)。

觀察到完整 payload hash 會因可選 metadata 欄位變動；兩次的核心 ID／描述／類型／列數／選定營養編號與數值一致。因此 hash 僅保存為每次 retrieval provenance，不作永久 byte-for-byte gate；核心內容漂移仍需 fail-closed。此批沒有 profile／飲食紀錄／route／UI／production registry 寫入，沒有改動任何 feature flag，也不代表糯米腸已有可用 FDC 同物資料或正式來源權利批准。

## Phase3b.1 USDA FDC bounded client

新增`fooddata_central_client.py`，固定呼叫單筆`https://api.nal.usda.gov/fdc/v1/food/{fdcId}`，只接受後端環境變數`USDA_FDC_API_KEY`；不讀`USDA KEY.txt`、不接受前端環境變數、不允許redirect／proxy／自動retry，並以共用deadline、512KB串流上限、strict JSON、回應FDC ID比對及credential-free hash文件保護取回結果。設定說明見[Windows伺服器操作說明](../../Local_Server_Deployment.md)。

本批完整隔離後端回歸為855項，832通過、23項因未配置專用PostgreSQL略過，0失敗／錯誤；證據見[usda-client-backend-regression.json](usda-client-backend-regression.json)。回歸清除Tavily、relay與本機env，沒有新增USDA／Tavily請求，也沒有接入正式route、production registry或使用者資料。這仍不是API配額、真PostgreSQL／Mongo併發、真照片準確率或自動補全上線驗收。

## Phase3b.2 authority 與冪等／配額邊界

`nutrition_authority_service.py` 以HMAC-SHA256簽署短效scan/profile authority，綁定user、scan revision、item identity、profile hash與source ID；拒絕篡改、過期、future clock、unknown kid、跨user及未支援欄位。`nutrition_enrichment_guard_service.py` 以server-owned欄位建立fingerprint，提供process-local single-flight、idempotency conflict、per-user／global quota reserve；timeout／429／upstream error／busy釋放額度，`not_found`消耗額度但不建立成功快取，舊完成項按window清理而pending保留。

authority 10項、guard 11項通過；加入本批後完整隔離後端回歸為876項（853通過、23項未配置PostgreSQL略過、0失敗／錯誤），證據見[phase3b-backend-regression.json](phase3b-backend-regression.json)。服務未接`app.py`、scanner、正式repository或production registry。跨程序／跨重啟的consume、idempotency結果、quota與profile cache仍未持久化，正式啟用前必須改用共享資料庫原子操作並驗收HTTP授權、舊revision、profile hash/source mismatch、並行只一次provider call、429／timeout重試及重啟行為。automatic_web_fallback_enabled仍false。

## Phase3a Tavily後端補全核心

日期2026-11-14；工作分支v1.0.2。新增固定Tavily client、伺服器來源registry、限定Markdown表adapter、單次relay橋接與自動補全協調器。沒有改正式route或開關；production source policy數為0。詳[企劃書第29節](../../plans/2026-11-13-web-nutrition-fallback.md#29-第七批phase-3a-tavily-後端補全核心)。

| 檢查 | 結果 |
| --- | --- |
| 新Tavily client | 23項；固定參數／精確URL／完整JSON／大小／共用deadline／去敏錯誤，fake streaming session |
| 新限定表adapter | 35項；真原格validator、0／null／小於值、kJ／雙基準矛盾、身分／份重／多表／列名變動拒絕 |
| 新模型橋接 | 14項；一次attempt、不輪替重試、共用deadline、拒非stop／超大／截斷輸出；既有relay測試亦通過 |
| 新協調器 | 33項；真本機matcher優先、原始custom serving、官方命中零付費、失敗隔離、全部未知分母、品牌／權限／核心點值、食品去重、溢位 |
| 新測試整合 | 105通過，0失敗／略過，socket建立／DNS／connection均阻擋 |
| 完整後端 | 838項，815通過、23真Postgres未配置略過、0失敗／錯誤，106.538秒 |

重建新測試：`python tools/verify_web_nutrition.py --output docs/food-nutrition-evaluation/2026-11-14/tavily-core-offline.json`。見[manifest](tavily-core-offline.json)。完整後端回歸：`python tools/verify_nutrition_backend.py --output docs/food-nutrition-evaluation/2026-11-14/tavily-backend-regression.json`，見[結果](tavily-backend-regression.json)。外部DB／relay／Tavily環境清除，跳過local env；memory／暫存SQLite與fake Mongo，不碰使用者DB。

初次完整回歸836項有1項既有SQLite API fixture失敗：台灣凌晨用無時區本地日期，後端將其當UTC未來日。改該測試payload為帶時區app_now、增加錯誤body診斷；正式日期政策未變。初次socket封鎖使用函式而破壞PySocks類別繼承，改拒建socket的子類後105項全過。這些執行問題保留說明，不隱藏成一次通過。

本批0新模型呼叫、1次受限Tavily Search（0 Extract）、0使用者紀錄操作、0金鑰設定修改；Search未納入production route，且使用的金鑰未寫入報告。先前67模型嘗試、11 Search＋6 Extract／13 reported credits為歷史批次數字，不與本次Search混同。服務未重啟、前端未改，未新增手機／桌面渲染或真照片正確率驗證。v1.0.1 branch ref保持原基準，無commit／push。

尚未完成：Tavily／真來源保存及重用條款、首批真頁policy／格式重播、signed scan/profile repository、user quota／冪等／跨請求single-flight／cache、影像容量預留、HTTP／掃描preview與v2保存／重送。直接來源fetch未實作，不宣稱DNS／redirect SSRF已驗；假來源review不能授權真網站。今日／歷史／趨勢／洞察完整改造延後，但來源／null／revision及舊客戶端保護仍須完成後才能正式試用。

## Phase2b2b 讀取模型與本機架設沿用

日期2026-11-14，工作分支v1.0.2。完成純record／history read model、跨紀錄coverage彙總、保守目標比較與歷史scope驗證；尚未接入今日／歷史／scanner／編輯等畫面。[主計畫第28節](../../plans/2026-11-13-web-nutrition-fallback.md#28-第六批phase-2b2b-讀取模型與本機架設沿用)記錄已驗及未驗範圍。

| 檢查 | 結果 |
| --- | --- |
| 新record投影 | 11項；真Python純服務快照，當地日期／零與null／排他上限／legacy報告值／來源context保存與拒假合計 |
| 新每日／範圍彙總 | 17項；缺紀錄日與not_loaded、未解分母、mixed legacy、分頁、全排除日、可信部分超量與重複／越界／溢位 |
| 新history一致性 | 12項；真server空／mixed／全排除日／小數平均fixture、summary竄改、跨帳號／日期／天數、Python捨入及API typed error |
| 全前端 | 179通過，0失敗／略過 |
| typecheck／lint／build:web | 通過 |
| build:local | 通過，最後export用於既有本機服務 |
| 後端 | 只有版本常數變更，py_compile及啟動health通過；未重跑先前733項 |

[frontend-read-model-regression.json](frontend-read-model-regression.json)由`node tools/verify_nutrition_frontend.mjs --output docs/food-nutrition-evaluation/2026-11-14/frontend-read-model-regression.json`產生。純測試socket禁用、fetch mock，沒有真DB或付費呼叫；私密日誌只在系統暫存。這些數字不含下述實際部署步驟。

獨立審查找出並補正：legacy known_sum不能當可信下界；all-excluded日之後再次彙總不得恢復complete／bound；相容avg_*與Decimal avg_known_sum合法不同，Python3.14浮點求和也不能以JS順序相加冒充。權威coverage／avg_known_sum仍驗證；相容avg_*僅格式驗證且不被讀取模型使用。本機計算平均不捨入，server平均維持一位小數。完整只描述該查詢已記錄食品，並非全天完整或醫療安全。

另依使用者指定把已停止的v1.0.1架設供目前v1.0.2使用：原task／Tailscale／SQLite位置沿用，先備份，再build:local及使用start-server.bat啟動。health確認v1.0.2／sqlite／auth_required=true／v2 scanner=false；loopback監聽、本機首頁與JS200、Funnel首頁／health200且與本機頁面相同，外部DB路徑隱藏。見[不含密鑰與個人路徑的啟動證據](local-server-v1.0.2.json)。正式DB僅由備份及正常啟動migration／維護存取，沒有登入、飲食紀錄讀寫或付費API。服務保持執行；Git保護分支未動。

尚未驗收：nullable UI／原生相機／真照片營養準確率、v2掃描／OCR／dispatcher、來源授權與抓取協調器、真Postgres／Mongo併發。history沒有range anchor／新鮮度證據，之後還需全量載入與session／request guard。本批無可視UI改動，不新增渲染驗收或宣稱已改善照片辨識；automatic_web_fallback_enabled仍false。

## Phase2b1 前端基礎

日期：2026-11-14；工作分支v1.0.2，原基準bb81e92。依使用者要求建立分支並保留未提交修改，沒有新commit或部署。現行流程見[企劃書第26節](../../plans/2026-11-13-web-nutrition-fallback.md)。

本批完成獨立nullable型別、原格計算／coverage、顯式v2 API，以及版本化queue、舊retry固定時間／餐別和queue錯誤提示。既有scanner、OCR、今日、編輯、趨勢與推薦仍未轉成v2，不能宣稱全鏈完成。

| 自動檢查 | 結果 |
| --- | --- |
| 新原格換算／coverage | 15項通過，含null／0／排他上界、單位、未知重量、原格往返、極值 |
| 新API transport | 14項通過，Python純服務產snapshot、socket禁用、mock fetch；非真HTTP整合 |
| 新queue／metadata | 16項通過，mock storage遷移／失敗保留／版本／並行／跨日／衝突 |
| 全部前端Node測試 | 114通過，0失敗／略過，985ms |
| typecheck／lint／build:web | 均退出0 |

結果見[frontend-foundations-regression.json](frontend-foundations-regression.json)。重建：`node tools/verify_nutrition_frontend.mjs --output docs/food-nutrition-evaluation/2026-11-14/frontend-foundations-regression.json`。原始執行日誌留系統暫存，不把環境／原始日誌寫入公開manifest。Node module-type提示及Expo既有套件版本提示不代表本批產品例外。

渲染流程：`http://localhost:8092/scanner` → future queue schema使讀取失敗 → 顯示資料保留提示 → 關閉提示 → 切手動搜尋並輸入白飯 → 原queue仍在 → 重載恢復提示。Browser plugin未提供，使用Playwright CLI；假session及所有API回應僅在隔離瀏覽器攔截，未連正式DB或付費服務。

| UI檢查 | 結果 |
| --- | --- |
| 頁面／標題 | scanner／NutriLens 個人化飲食推薦 |
| 非空白／無framework overlay | 通過 |
| Console | 0 errors；1項既有pointerEvents deprecation warning |
| 375／390／430／768／1440寬 | 無頁面或alert水平溢位，alert未超出視窗 |
| 截圖 | 390x844與1440x1000已目視確認換行與關閉鈕 |
| 互動與資料保留 | 關閉、輸入及重載通過，future queue原值仍在 |

截圖位於測試機暫存，未加入repo：[手機](C:/Users/botto/AppData/Local/Temp/nutrition-v2-mobile.png)、[桌面](C:/Users/botto/AppData/Local/Temp/nutrition-v2-desktop.png)。畫面既有v1.0.1徽章是應用release文字，本次只建立v1.0.2工作分支，未改release metadata。

獨立審查發現並修正：假完整coverage、未解IDs遺失、point／bound矛盾、必要metadata遺失、POST去重混版、queue必填型別及舊retry忽略固定時間。嚴格回應檢查亦發現營養欄位陣列順序差異，已對齊後端並補未解項跨語言比對。

限制：queue mutex只保護單runtime，跨tab原子性與混版衝突合併未完成；目前偵測兩key並存就停下保留。v2尚無UI dispatcher；live legacy submit未在按下時固定時間，首次跨午夜失敗仍可能採較晚日期。重送後optimistic今日、preview revision／警告與全部nullable顯示、OCR小於值與推薦尚待接線。沒有真手機、真登入、照片／秤重準確率、真Postgres／Mongo或完整後端HTTP驗收。本輪未改後端，未重跑先前733項。

automatic_web_fallback_enabled仍false；本批0模型呼叫、1次受限Tavily Search（0 Extract）、0實際使用者資料庫修改。先前67模型嘗試及17 Tavily請求為歷史實測總量，另加本次Search後應以各批證據分開解讀。

## Phase2b2a 送出與重試完整性

日期2026-11-14；v1.0.2，未commit／部署，既有修改及使用者照片保留。完成範圍是舊scanner／manual／OCR送出與queue完整性；nullable v2 UI及dispatcher仍未接線。詳[企劃書第27節](../../plans/2026-11-13-web-nutrition-fallback.md#27-第五批phase-2b2a-送出與重試完整性)。

| 檢查 | 結果 |
| --- | --- |
| 新submission流程 | 13項；真helper／queue／serializer＋mock fetch，含臺灣00:03日期／跨午夜、固定body、write-ahead、改稿攔截、saved標記及帳號／API隔離 |
| 新lock／target | 12項；mock共用鎖兩store、並行修改／遷移、無鎖不讀寫、原後端綁定與舊未綁定阻擋 |
| 全部前端Node測試 | 139通過，0失敗／略過 |
| typecheck／lint／build:web | 均退出0，最後一次包含新草稿identity、OCR固定ID及舊401事件session guard |
| 後端測試 | 後端未改，本批未重跑既有733項 |

重建：`node tools/verify_nutrition_frontend.mjs --output docs/food-nutrition-evaluation/2026-11-14/frontend-submission-regression.json`。結果見[manifest](frontend-submission-regression.json)，原始日誌留系統暫存。這不是後端真HTTP／資料庫整合。

最後Git核對發現工作期間由其他操作於01:00:56+08切回v1.0.1；兩分支都指向bb81e92且沒有分支內容差異。已保留全部未提交檔案並恢復使用者指定v1.0.2。manifest保留測試當下實際分支v1.0.1，不改寫成在另一分支執行；交付程式檔案相同。

Browser plugin未提供，使用Playwright CLI；網址`http://localhost:8092/scanner`，正常auth模式，隔離假session、所有API攔截，沒有正式帳號或資料庫呼叫。測試流程及證據：

| 流程 | 實際觀察 |
| --- | --- |
| 手動搜尋→加入→刻意503 | 每個POST前已有相同client ID／timestamp的本機快照 |
| 23:59:50失敗→翌日08:01重試 | 兩次整份body相同，timestamp仍2026-11-14T23:59:50.030+08:00、餐別晚餐；成功後queue空 |
| 背景補送成功→按仍可見加入 | POST總數仍2，提示已儲存，不新增事件 |
| 舊未綁定目標→自動／手動補送 | 均0 POST，queue原字串完全不變；中文提示保留 |
| Web檔案選擇→假OCR→首次503→再按加入 | 原內容整份body相同、POST2次、成功清相同草稿；舊未綁定queue仍保留 |
| 375／390／430／768／1440寬 | 失敗banner與頁面無水平溢位；舊目標提示另驗375／1440 |
| 390x844／1440x1000截圖 | 已目視，文字換行與關閉鈕正常，無遮蓋 |
| 頁面／非空白／overlay／console | 正確scanner與標題、非空白；最後重跑無overlay，各故意503有預期resource error、既有pointerEvents警告，無未解app error |

OCR只用假辨識回應；照片經檔案選擇但被本機攔截，沒有量測OCR或營養準確率。初次自動化重複處理file chooser觸發Expo removeChild overlay；改一次CLI upload後完整重跑通過。另一次臨時測試誤用未提供的clock.uninstall及模糊文字locator，均改用現有API／精確role後重跑。這些是測試操作問題，不掩蓋為成功。

截圖：[手機](C:/Users/botto/AppData/Local/Temp/nutrition-submit-mobile.png)、[桌面](C:/Users/botto/AppData/Local/Temp/nutrition-submit-desktop.png)。v1.0.1側欄徽章仍是release文字；本次工作分支為v1.0.2，未變更release metadata。測試瀏覽器及Expo服務於驗收後關閉。

本批修正重新審查通過：完整body／本地日期、後端目標、換帳號後畫面保護、舊保存只清相同camera／OCR草稿、OCR固定ID。saveRecord抑制過期舊session的401登出事件，當前session的401仍會通知，已加入既有帳號測試；其他API未全面改造。新版分頁共用Web Lock但不涵蓋舊lockless分頁；無Web Locks的瀏覽器會停止本機queue操作，native仍只保證單runtime。舊未綁定目標及兩key混版需後續明確調解，現階段保留並阻擋，不能稱完整遷移。

下一步是versioned／coverage-aware讀取模型、nullable每日／趨勢／洞察與編輯，再接掃描來源context、preview、v2 dispatcher、OCR小於值及推薦。automatic_web_fallback_enabled仍false；本批未呼叫模型，僅有1次受限Tavily Search且未做Extract。沒有實機相機、真登入、真Postgres／Mongo、真HTTP、真來源取回或完整拍照營養準確率驗收。

## 第十批：SQLite/Postgres profile/source repository（2026-11-14）

本批完成下一個必要基礎，但仍未接正式 route。新增`backend/repositories/nutrition_profile_repository.py`，以SQL transaction/CAS保存伺服器擁有的營養來源 policy與profile snapshot。來源 policy另有不可變的revision history；profile hash由canonical profile在server計算，並重新驗證食品身分、來源URL、content hash、adapter version、snapshot/reuse權利及owner／cross-user scope。來源撤回或policy換版後，新的profile authority讀取會被拒絕；歷史飲食紀錄仍使用`records.foods`內的不可變snapshot，不重新解析live profile。

10項repository測試全數通過，涵蓋SQLite檔案重啟、兩連線CAS、來源歷史、撤回、provenance mismatch、權限拒絕、跨帳號reuse與Postgres JSONB/RLS/FOR UPDATE contract，證據見[nutrition-profile-repository.json](nutrition-profile-repository.json)。repository目前只支援SQLite/Postgres；Mongo尚未實作atomic unique-index路徑，因此Mongo部署仍不得啟用付費補全。

這一批仍沒有HTTP enrichment route、durable idempotency／quota/result repository、真Postgres/Mongo併發或模型/Tavily呼叫；`automatic_web_fallback_enabled`仍為`false`，production registry仍為空。

## 第十一批：durable scan context／authority replay repository（2026-11-14）

新增`backend/repositories/scan_context_repository.py`，把scanner產生的`user_id`、`scan_id`、`scan_revision`、完整辨識項目集合及短效期限保存於SQLite/Postgres。item set以server canonical hash驗證，項目遺漏、重複、未知或revision不符都會拒絕；同一scan revision只接受同一使用者與同一集合，revision必須依序前進，舊revision建立新版本後會標成`superseded`而不能再授權。過期、consumed、superseded與revoked是持久化狀態，不能靠重啟清除。

authority JTI另以unique durable replay table記錄，消費scan context與JTI寫入同一transaction；兩個SQLite連線並行消費只會有一個成功，重啟後仍拒絕同一JTI。8項repository測試全數通過，證據見[scan-context-repository.json](scan-context-repository.json)。這個repository仍不接`app.py`或scanner，也不會啟用自動Tavily fallback；後續已另完成request／quota持久化，下一個門檻是TTL／撤回與作業協調後的HTTP route驗收。

## Durable enrichment request與quota repositories（2026-11-14）

本批在v1.0.2完成正式HTTP route前的兩個SQL持久化邊界。enrichment request repository保存idempotency key、fingerprint、request hash、pending lease、結果與錯誤；quota repository原子保存per-user與global reservation，retryable失敗釋放，`not_found`消耗額度但不成為成功快取。

| 檢查 | 結果 |
| --- | --- |
| enrichment request | 6項通過；同請求重播、body／revision conflict、fingerprint唯一、lease reclaim、retryable／not_found、重啟結果 |
| quota | 9項通過；user/global atomic reserve、retryable release、not_found consume、ownership、window rollover、重啟與並發最後slot |
| 完整後端 | 908項，885通過、23項因未配置真Postgres略過，0失敗／錯誤；[回歸證據](durable-enrichment-repositories-regression.json) |

聚焦scan證據：[scan-context-repository.json](scan-context-repository.json)。Mongo、live PostgreSQL、HTTP route、scanner接線、合法快取TTL／撤回及真provider並行尚未驗證；沒有新的付費模型／Tavily呼叫或使用者資料寫入。`automatic_web_fallback_enabled`仍為`false`，production registry仍為空。

## Phase3c Durable orchestration與正向快取

日期2026-11-14；工作分支v1.0.2。新增`nutrition_cache_repository.py`與`nutrition_enrichment_coordinator.py`，但沒有接`app.py`、scanner、production registry或自動fallback。

| 檢查 | 結果 |
| --- | --- |
| durable repositories | 35項通過；含scan context、enrichment request、quota、profile/source，PostgreSQL首次競態使用`ON CONFLICT DO NOTHING`後重讀驗證 |
| positive cache | 8項通過；成功profile only、7日預設／90日上限TTL、owner/cross-user rights、source revision／撤回、provenance、重啟 |
| coordinator | 6項通過；single provider call、retry lease、quota release/commit、result-first crash recovery、TOCTOU withdrawal recheck |
| 完整後端 | 925項，902通過、23項因未配置真PostgreSQL略過，0失敗／錯誤 |

完整隔離回歸結果見[phase3c-durable-orchestration-regression.json](phase3c-durable-orchestration-regression.json)。本批沒有新的付費模型／Tavily請求、使用者飲食紀錄寫入或服務重啟；Mongo與真PostgreSQL仍未實測。cache不提供negative-cache寫入，`not_found`／timeout／429不會變成成功命中。下一步是獨立authenticated enrichment route與server-owned scan adapter，完成401／403、revision／profile mismatch、並行、重啟與真provider測試後，才可評估開啟`automatic_web_fallback_enabled`。

## Phase3d authenticated enrichment route

本批新增獨立`POST /nutrition/enrichment`及`nutrition_enrichment_route_service.py`。route先驗證登入、user binding與server-owned scan context，再依TFDA→USDA本地結果、正向cache、來源／profile authority順序處理；沒有直接包裝`/predict/vision-food`，也沒有讀取或暴露`TavilyKey.txt`／USDA key檔案。`NUTRITION_ENRICHMENT_ROUTE_ENABLED`預設為false，Mongo或非SQLite/Postgres也會保持關閉；production registry與`automatic_web_fallback_enabled`仍未開啟。

| 檢查 | 結果 |
| --- | --- |
| route service | 9項；item set mismatch、expired／revoked／superseded scan、local hit零provider／零quota、provider replay、feature fail-closed、source revision先於provider factory拒絕、profile hash mismatch、user quota exhaustion |
| Flask smoke | 缺少Authorization回401；user mismatch回403 |
| 完整後端 | 936項，913通過、23項真PostgreSQL未配置略過、0失敗／錯誤；見[phase3d-route-regression.json](phase3d-route-regression.json) |

本批未呼叫真Tavily／模型、未改使用者飲食紀錄、未重啟正式服務。仍未驗scanner adapter與authority JTI consume、真source policy／provider HTTP、真PostgreSQL／Mongo併發、429／timeout與跨重啟流程；web成功profile的cache write仍待接線。這些是正式開啟前置條件，不能把本批離線測試描述成第三層已上線。

## Phase3e scanner／authority／HTTP整合（2026-11-14）

本批完成scanner到server-owned scan context的接線：只保存authority白名單欄位，並在SQL context中固定scan revision、完整item-set hash與期限。配置合法的`NUTRITION_AUTHORITY_SECRET`且route flag開啟時，scanner回傳短效authority token；enrichment route驗證user／revision／item set後，以durable JTI consume防止同一scan被不同idempotency key重用。同一idempotency key的重播仍可讀取已保存結果。

| 檢查 | 結果 |
| --- | --- |
| scanner／route integration | 通過；完整item set、presentation-only欄位排除、scanner retry冪等 |
| authority／HTTP replay | 通過；首次consume、同key replay、新key拒絕、token mismatch |
| 完整後端回歸 | 949項，926通過、23項因未配置真PostgreSQL略過，0失敗／錯誤；見[phase3e-scanner-authority-regression.json](phase3e-scanner-authority-regression.json) |

本批仍未呼叫真Tavily／模型，未啟用production source registry或自動fallback，未實測真PostgreSQL／Mongo併發、跨重啟HTTP、429／timeout及positive cache write。低信心／被拒項目仍保存以維持完整item set，正式開啟前需另定使用者確認門檻。

## Phase3f provider resilience與正向快取（2026-11-14）

本批以隔離 fake provider 驗證正式開啟前的作業恢復語意，並修正文件中「positive cache 尚未接線」的過時描述。coordinator 在兩執行緒同一 idempotency key 下只呼叫一次 provider；timeout／429 釋放配額並可用同 key 重試；release／commit 回應遺失後，重播會 reconciliation；SQLite 關閉重開後已完成 request 不會再次呼叫 provider。route 已呼叫 `_cache_successful_web_profiles()`，只快取完整 web profile，partial／失敗／not_found 不寫入。

| 檢查 | 結果 |
| --- | --- |
| coordinator resilience | 10項通過：single-flight、timeout／429、quota release／reconciliation、SQLite restart replay |
| route／cache regression | 22項通過；完整 web cache write 與 partial 不寫入均通過 |
| 完整後端隔離回歸 | 955項，932通過、23項真PostgreSQL未配置略過、0失敗／錯誤 |

證據見[phase3f-provider-resilience.json](phase3f-provider-resilience.json)。本批沒有真 Tavily／模型呼叫、沒有讀取或暴露 `TavilyKey.txt`／`USDA KEY.txt`，沒有使用者資料寫入。仍未驗真 PostgreSQL／Mongo 多程序併發、跨重啟 HTTP、首批真來源 policy／權利與低信心使用者確認；production registry、`automatic_web_fallback_enabled`及 route flag 持續關閉。

## Phase3g／3h 低信心 fail-closed（2026-11-14）

複核發現低信心或帶 `validation_issues` 的 item 原本可能在 local miss 後先讀 web cache，或建立 provider 直到 web core 才拒絕；這會浪費 quota，也可能讓營養結果反向提高影像辨識可信度。現在 route 保留 TFDA／USDA 官方命中，但在 local miss 後、cache lookup／provider／authority consume／quota 前即回 `confirmation_required`，HTTP status 為409。低信心 item 不讀 web cache、不進 Tavily／模型；後續需使用者確認並建立新的 server-owned scan revision。

| 檢查 | 結果 |
| --- | --- |
| route confidence／validation gate | 17項通過；provider、cache、authority、quota 均未被不合格 item 觸發 |
| 完整後端隔離回歸 | 959項，936通過、23項真PostgreSQL未配置略過、0失敗／錯誤 |

另以 Flask HTTP fixture 驗證同一門檻回傳409，authority 不提前消費、provider與quota皆未觸發。證據見[phase3i-confidence-http.json](phase3i-confidence-http.json)。這只驗證 SQLite／fake provider 的安全邊界，未驗真 PostgreSQL／Mongo、多程序 HTTP、真來源 policy／權利或 frontend enrichment 接線；production registry、`automatic_web_fallback_enabled`及 route flag 持續關閉。

## Phase3j 結果合約與混合來源 coverage（2026-11-14）

本批針對 provider 結果的最後一個已知邊界補強：factory 拒絕非 dict、缺少 items／item_id 或無法重建 coverage 的輸出；known TFDA／USDA／cache item 不會被 web 覆蓋，合併後重新計算完整 coverage。route 對新增 item 要求 canonical `NutritionEnrichmentRouteV1` 欄位，item_id-only 的 complete payload 轉為 `invalid_output`。coordinator 再核對結果 item IDs 必須與 request 完全一致，避免未知食品進入 durable result。

| 檢查 | 結果 |
| --- | --- |
| enrichment focused route／coordinator／HTTP | 34項通過 |
| frontend nutrition regression | 117項通過 |
| 完整後端隔離回歸 | 962項，939通過、23項因未配置真PostgreSQL略過、0失敗／錯誤 |

證據見[phase3j-contract-regression.json](phase3j-contract-regression.json)。本批沒有真 Tavily／模型請求、沒有讀取或暴露 `TavilyKey.txt`／`USDA KEY.txt`，沒有寫入正式使用者飲食紀錄。真來源權利、live PostgreSQL／Mongo 多程序與跨重啟 HTTP、frontend scanner 接線仍未完成；`PRODUCTION_SOURCE_REGISTRY`、`automatic_web_fallback_enabled`及`NUTRITION_ENRICHMENT_ROUTE_ENABLED`保持關閉。

## 本機服務 fail-closed smoke（2026-11-14）

目前執行中的 v1.0.2 Windows 服務 `/health` 回傳 HTTP 200，確認 SQLite、認證與官方資料層正常；自動 web fallback 與 enrichment route 仍關閉。此次檢查沒有 provider 呼叫、金鑰讀取或使用者紀錄寫入。詳見[local-enrichment-route-disabled.json](local-enrichment-route-disabled.json)。

## Phase3k scanner transport 與完整回歸（2026-11-14）

scanner 現在可保留 server-owned scan context，並在明確的 Expo capability flag、authority token 與外部注入 source policy metadata 同時存在時，才呼叫 enrichment route；預設設定仍為關閉。provider 或 policy 失敗會保留既有 TFDA／USDA 結果，缺少必要 point values 不會寫成 `undefined` 或虛構零值。

| 檢查 | 結果 |
| --- | --- |
| 前端完整測試 | 189 項通過 |
| typecheck／lint／web export | 全數通過 |
| 後端隔離回歸 | 962 項，939 通過、23 項因未配置真 PostgreSQL 略過，0 失敗／錯誤 |

證據見[phase3k-frontend-regression.json](phase3k-frontend-regression.json)與[phase3k-backend-regression.json](phase3k-backend-regression.json)。本批沒有真 Tavily／模型呼叫或正式使用者資料寫入；四個統計畫面的 nullable v2 UI、真 PostgreSQL／Mongo 多程序、來源權利與 production auto-enrichment 仍未驗收。

## PostgreSQL 驗證前置（2026-11-14）

本機沒有可用的 PostgreSQL 測試服務，且未配置 `NUTRILENS_TEST_DATABASE_URL`。`test_postgres*.py` 的 29 項 offline contract／driver 測試通過，23 項 live integration 略過；database selection 14 項與營養 repository offline 35 項通過。這不是 live PostgreSQL 驗收。詳見[postgres-validation-blocked.json](postgres-validation-blocked.json)。

另有專用 `test_nutrition_postgres_integration.py`，預備驗證隨機schema、scan JTI replay、request跨連線 replay及quota global last-slot；目前3項因沒有測試 URL 略過，沒有建立連線。

隔離後端完整回歸：965 項，939 通過、26 項略過、0 失敗／錯誤；詳見[phase3l-backend-regression.json](phase3l-backend-regression.json)。

## SQLite restart／replay／lease regression（2026-11-14）

本批先在不需要外部資料庫的條件下補強可重啟安全邊界：逾期 pending lease 在重新開啟 SQLite 檔案後只能由新 owner reclaim，`request_id` 不變且 `attempts` 遞增；retryable 結果重啟後可用同一 idempotency key 重新取得 lease，不會建立第二筆 request；已消費的 authority JTI 在重啟後不能綁定另一個 scan，衝突會拒絕且目標 scan 維持 active。

| 檢查 | 結果 |
| --- | --- |
| enrichment repository targeted tests | 9項通過 |
| scan context targeted tests | 9項通過 |
| 完整後端隔離回歸 | 968項，942通過、26項略過、0失敗／錯誤 |

證據見[sqlite-restart-replay-regression.json](sqlite-restart-replay-regression.json)。這批仍不是 live PostgreSQL 的 row lock／多程序驗收；Mongo、真 provider、Tavily、USDA 與模型 HTTP 仍未呼叫，所有自動補全旗標維持關閉。

## PostgreSQL 本機服務與 live persistence 驗收（2026-11-14）

本機已完成 PostgreSQL 17 服務安裝與設定：Windows service `postgresql-x64-17` 為
Running／Automatic，`127.0.0.1:5432` 可接受連線，`pg_hba.conf` 維持
`scram-sha-256`。測試使用專用 `nutrilens_test_runner` 角色與 `postgres` 測試資料庫，
只授予建立隔離 schema 所需權限；連線字串與密碼只在測試程序環境存在，沒有寫入專案。

| 檢查 | 結果 |
| --- | --- |
| 既有 PostgreSQL storage／auth／交易／並行／重連 | 23/23 通過 |
| 營養 persistence：scan JTI replay、request 跨連線 replay、quota last-slot | 3/3 通過 |
| 合計 live PostgreSQL | 26/26 通過 |
| 測試後隨機 schema | 0 殘留 |

每個測試使用隨機 schema 並在 teardown 刪除，沒有修改 v1.0.2 正式 SQLite、Tavily／USDA
金鑰、使用者飲食紀錄或 production database。無密鑰的前置阻塞紀錄
[postgres-validation-blocked.json](postgres-validation-blocked.json) 保留不變；本批新證據見
[postgres-live-validation.json](postgres-live-validation.json)。

這解除的是 PostgreSQL persistence／跨連線測試環境阻擋，不等於第三層營養補全已開啟。
Mongo atomic repository、真 Tavily／模型 HTTP、來源權利 registry、跨重啟 HTTP route、
以及四個統計畫面的 v2 消費仍未驗收；`PRODUCTION_SOURCE_REGISTRY`、
`automatic_web_fallback_enabled` 與 `NUTRITION_ENRICHMENT_ROUTE_ENABLED` 繼續關閉。

## Source policy／adapter admission 閘門（2026-11-14）

PostgreSQL live 驗收後，先完成真 provider 前的 policy admission 回歸。web nutrition
policy、reviewed source adapter、profile/source repository 共 `82/82` 通過；測試確認
production registry 仍為 0，沒有合法 policy 時不會搜尋、擷取、建立 profile 或寫入快取。

| 檢查 | 結果 |
| --- | --- |
| web nutrition policy／identity／rights gate | 35/35 |
| reviewed markdown adapter／raw cell／unit／bound validation | 35/35 |
| source policy revision／profile hash／withdrawal／reuse | 12/12 |
| 合計 | 82/82 |

證據見[source-policy-admission-regression.json](source-policy-admission-regression.json)。本批沒有
Tavily、USDA、模型或使用者資料副作用，沒有修改 production registry。下一步才是以核准的
單一來源 policy 做無持久化的真 Tavily／模型 HTTP replay；若 USDA FDC 維持 API-only，則不
把它誤接成 Tavily 網頁來源。Mongo enrichment 繼續 fail-closed。

## 真 Tavily／模型單一來源 HTTP replay（2026-11-14）

以臺安醫院 QQ 王子地瓜球 PDF 做隔離 replay。Tavily Search 的兩個 production query 均 HTTP
成功：第一個回空集合，第二個回核准 PDF；接著 Extract 成功取得 1 個文件，保留 request id、
usage、content hash 與 retrieval version。relay 模型以固定 `NutritionExtractionV1` prompt
完成回應，項目完整且 `finish=stop`，但因來源不是 audited table 而回 `no_evidence`、9 個營養
選格全為 null。現有 reviewed Markdown adapter 對真實 Extract 文字預期回 `ambiguous_identity`，
因 PDF 表格被 Tavily 壓成單行，不能安全對齊營養欄位。

證據：[live-tavily-single-source-replay.json](live-tavily-single-source-replay.json)、
[live-tavily-model-replay.json](live-tavily-model-replay.json)、
[live-tavily-query-replay.json](live-tavily-query-replay.json)。本次未使用 production registry、
route、cache 或資料庫，未寫入使用者紀錄；來源權利仍未批准。這證明真 HTTP 路徑可工作，
但不代表第三層已開啟。下一步是先為已審核來源建立專用 adapter 及正反例，再做 authenticated
route 的跨重啟／配額／JTI replay；USDA FDC 仍走 API-only adapter，Mongo 與自動補全旗標維持關閉。

## SQLite-only SQL 清理回歸（2026-11-14）

本批將 v1.0.2 的 SQL backend 收斂為 SQLite：非空 `DATABASE_URL` 明確拒絕；移除 PostgreSQL
adapter、driver dependency 與舊 PostgreSQL tests。`test_database_selection.py` 還驗證沒有 PostgreSQL
driver 時 SQLite 與 app import 正常。JTI／scan context／authenticated enrichment route 的 targeted
suite 為32/32；完整後端 pytest 為906 tests、682 subtests 全通過，0 fail、0 skip。第45批
PostgreSQL 26/26 live integration 結果保留為歷史隔離證據，並非正式部署要求。

本批沒有啟動第三層、呼叫 Tavily／USDA／模型或讀取金鑰，沒有修改既有 SQLite 使用者資料、
`v1.0.1` 或本機 PostgreSQL service。`render.yaml` 仍指向 `v1.0.1` 並包含 `DATABASE_URL`，
README 已註明該舊 Blueprint 不適用於 SQLite-only `v1.0.2`；目前正式部署仍是 Windows + Tailscale + SQLite。

來源准入仍未達標：單筆 USDA FDC 固定 ID replay 不證明搜尋候選與食物身分匹配；Tavily 地瓜球
PDF 的表格無法可靠映射到原始欄位且權利未核准。production registry 為空，兩個 enrichment
flags 維持 false。後續只先設計與離線驗證 FDC candidate search／identity contract，不開正式路由。
證據：[sqlite-only-cleanup-regression.json](sqlite-only-cleanup-regression.json)。

## USDA FDC 候選搜尋與身分選擇離線合約（2026-11-14）

新增固定 endpoint 的 bounded FDC Search client，以及不具權威性的 `FdcCandidateSelectionV1`
prompt／validator。定向 client、adapter、selection tests 為 `31 passed`、`12 subtests passed`；
完整隔離後端為 `922/922 passed`、0 failed／skipped。validator 拒絕非 canonical
或超長 FDC ID、非分析資料類型／錯誤 metadata，且 state、preparation、components scope
未知或缺漏時不能產生 candidate suggestion。任何 suggestion 都是 `confirmation_required`，
不自動取得詳情、不建立營養 profile，也不提高影像信心。

證據見[fdc-candidate-selection-regression.json](fdc-candidate-selection-regression.json)。本批是
offline fake transport／contract testing，未呼叫 USDA Search、Tavily 或模型，未讀金鑰或使用者 DB。
還未驗證真中文 alias／英文 query 的 FDC 命中品質、同名食品與料理狀態相容。route wiring 前
必須讓 prompt 與 validator 共用同一 server-owned immutable item/candidate snapshot，並避免 scan
revision、item set 或候選 mapping 在兩階段漂移。下一步是受限 live USDA Search replay；在候選品質、
固定 ID detail adapter、人工確認與來源 policy 完成之前，production registry 與自動補全旗標維持關閉。

## 糯米腸 USDA FDC live Search replay（2026-11-14）

使用伺服器端 key 對固定 FDC Search API 發出3次 bounded search（page size 10）：第一次中文 query
因 Windows PowerShell native pipe 字元轉碼而作廢；英文 `rice sausage` 回10筆，但包含波多黎各／
西班牙香腸飯、一般豬牛香腸、煙燻香腸及美式 pork sausage rice links，沒有能安全確認為台式糯米腸的
等價項；改用 Python Unicode escape 正確送出中文「糯米腸」後，API 回應成功但0筆。逐筆清單與
副作用邊界見[fdc-live-search-replay.json](fdc-live-search-replay.json)。

這不是「USDA 完整資料庫沒有糯米腸」的證明，只代表兩種有效 query 的本次 bounded Search 結果。
它揭露中文直查的 miss 以及寬泛英文 query 的明顯誤配候選，因此不得從排名自動選 sausage 或 rice
profile。沒有取 food detail／營養數字、呼叫模型／Tavily、寫使用者資料或開 route。下一步先做受控
query normalization／少量英文別名離線測試，再決定是否多做 bounded live search；profile、source policy
與所有 enrichment flags 仍關閉。

## 受控 FDC query normalization 與 plan binding（2026-11-14）

新增 `FdcSearchQueryPlanV1`：原始食品名稱固定為第一個 query，英文 alias 只接受 server allowlist，
最多兩個且不允許重複；未知 state／preparation／components scope 時只保留原始名稱。plan 綁定
`item_id`、`scan_revision` 與 identity digest，名稱、品牌、variant 或 revision 變動會拒絕舊 plan。
`rice sausage`、品牌拼接與模型自產 alias 均被拒絕。

定向 query normalization suite `6 passed`、`6 subtests passed`；合併 FDC client／adapter／selection
suite `31 passed`、`18 subtests passed`。本批沒有新增 USDA Search、Detail、Tavily、模型或使用者 DB
副作用；沒有候選選擇、營養取值或影像信心變更。完整隔離回歸見
[fdc-query-normalization-regression.json](fdc-query-normalization-regression.json)。下一步才是用這個 plan
做第二輪受限 live Search，候選仍必須經同一 immutable snapshot 與 validator，不能依排名自動採用。

## 受控 alias 的 FDC live Search（2026-11-14）

依 `FdcSearchQueryPlanV1` 發出3次 bounded Search：原始「糯米腸」0筆；`glutinous rice sausage` 與
`Taiwanese glutinous rice sausage` 各10筆。兩組結果主要是糯米粉、熟糯米、米糕，並混入
sausage-and-rice，沒有能確認為台式糯米腸的候選。證據見[fdc-alias-live-search-replay.json](fdc-alias-live-search-replay.json)。

受控 alias 改善文字召回但未改善完整身份精度；安全結果仍為 `not_found`。本批沒有 food detail、
營養數字、Tavily、模型或使用者資料副作用，也沒有提高照片信心或開啟 route。後續不應再擴張模糊
alias，須先有 immutable candidate snapshot、人工確認或其他已核准來源。

## FDC immutable candidate snapshot binding（2026-11-14）

新增 `FdcCandidateSnapshotV1` 與 `FdcCandidateSelectionV2`：prompt 與 validator
共用同一份 server-owned normalized snapshot，並驗證 `scan_revision`、item-set／identity
digest、候選內容與模型回傳 digest。snapshot 不含營養值、份量、影像信心或健康資料；模型
suggestion 仍一律為 `confirmation_required`。

定向回歸 `38 passed`、`18 subtests passed`；完整隔離後端 `929/929 passed`、0 failed／skipped。
證據見 [fdc-candidate-snapshot-regression.json](fdc-candidate-snapshot-regression.json)。本批
只做離線契約與負例測試，沒有 USDA Search／Detail、Tavily、模型、key、使用者 DB、profile 或
route 副作用。候選快照已解除 prompt→validator mapping drift，但尚未具備自動營養補全能力；
固定 ID detail／adapter、使用者確認 UI、source policy 與 route authority 仍未完成。

## FDC 使用者確認契約（2026-11-14）

新增 `FdcCandidateConfirmationV1` validator。使用者只能選擇 immutable snapshot 內實際呈現的候選；`reject`／`defer` 不得攜帶 FDC ID。確認結果狀態為 `confirmed_pending_revision`，綁定 snapshot digest、scan revision 與 identity digest，並標記必須建立新的 server-owned scan revision 才能進入 Detail replay；不直接取得營養、不提高影像信心、不寫入 profile 或使用者資料庫。

定向 client／adapter／selection／confirmation suite 為 `40 passed`、0 failed；其中包含 Detail → `NutritionProfileV1` → 150g portion 的每100g換算回歸。完整隔離後端回歸為 `936 passed`、`0 skipped`、`0 failed`。本批沒有 live USDA Detail、Tavily、模型、key、route 或資料庫副作用；Detail adapter 只以 fake transport／離線 payload 驗證固定 endpoint、ID、adapter version、retrieval version、每100g限制與實際份量公式。下一步不是再做離線換算，而是完成 server-persisted snapshot／使用者確認 endpoint 與新的 server-owned scan revision；正式 route 不得信任客戶端自帶 snapshot。

## FDC candidate snapshot 的 SQLite server-owned 持久化（2026-11-14）

新增 `FdcCandidateSnapshotRepository`。它先載入 authenticated user 的 server-owned scan context，再由伺服器取得的 `candidates_by_item` 重新建立 `FdcCandidateSnapshotV1`；production-facing API 不接受 client snapshot 或 digest。資料表綁定 user、scan revision、item-set／snapshot digest、expiry 與狀態，候選漂移、錯誤使用者、過期、重啟及新 revision 會 fail-closed。

snapshot repository、scan context、selection 與固定 Detail adapter focused suite 為 `39 passed`、`21 subtests passed`。本批沒有 live USDA／Tavily／模型、API key、confirmation endpoint、前端 UI 或使用者飲食紀錄副作用。這只解除 server-owned snapshot storage 前置條件；actor／時間／idempotency 確認記錄、確認 endpoint、新 scan revision 與正式 route 仍未完成。

## FDC 使用者確認 durable contract（2026-11-15）

新增 SQLite-only `FdcCandidateConfirmationRepository`。它只接收確認 envelope，先由 server-owned snapshot repository 取回快照，再驗證使用者每個 item 的決策；不接受 client snapshot。記錄綁定 authenticated user、actor、scan revision、item-set／snapshot digest、request hash、idempotency key、建立時間與 expiry。

`confirm` 只回傳 `confirmed_pending_revision`，要求建立新的 server-owned scan revision，且 `photo_confidence_changed=false`；`reject`／`defer` 不得攜帶 FDC ID。相同 idempotency key 只可重播相同內容，錯誤 actor、digest、候選、過期、舊 revision 與衝突決策均 fail-closed。

confirmation／snapshot／selection focused suite 為 `28 passed`、`16 subtests passed`。本批沒有 HTTP confirmation endpoint、前端 UI、live FDC／Tavily／模型或營養 profile 副作用；下一步仍是 authenticated route 與新 scan revision transaction。

## Authenticated FDC confirmation HTTP contract（2026-11-15）

新增 `POST /nutrition/fdc/confirmation`，預設 `FDC_CONFIRMATION_ROUTE_ENABLED=false`。路由先驗證登入，再檢查旗標；只接受 user／scan／revision／idempotency 與確認 envelope，拒絕 client snapshot 或未知欄位。當時的 route boundary 回 `202 confirmed_pending_revision`，並明確回傳 `requires_new_scan_revision=true`、`photo_confidence_changed=false`；本狀態已由下一批的 SQLite 原子交易擴充，不直接取 Detail 或提高影像信心。

HTTP／repository／snapshot／selection focused suite 為 `33 passed`、`16 subtests passed`。未登入、feature-off、user mismatch、未知欄位、伪造候選與 repository typed error 均有測試。本批當時沒有新 revision 副作用；原子交易已在後續紀錄完成。前端 UI 與固定 Detail route 仍未完成。

## FDC confirmation 與 scan revision 的 SQLite 原子交易（2026-11-15）

確認 repository 現在於同一 `BEGIN IMMEDIATE` transaction 內驗證 active server-owned snapshot、保存 confirmation 與建立下一個 scan revision；舊 revision 同步標記為 `superseded`。成功結果保留使用者明確選取的 FDC ID、snapshot／identity digest 與 issued revision，回傳 `confirmed_revision_issued`、`requires_new_scan_revision=true`、`requires_detail_replay=true`，但不執行 Detail、不建立營養 profile，也不提高 photo confidence。拒絕與延後不建立 revision；混合決策會保留每個 item 的個別狀態，尚未確認的 item 不取得 FDC ID。

重播先查同一使用者的 idempotency key，再讀已 superseded 的舊 snapshot，因此相同 payload 重播原確認與 revision，不會多建版本；換 payload、actor、scan 或 digest 會衝突。新增 rollback（revision 與 confirmation 一起回滾）、SQLite 檔案重啟重播、reject/defer 無 revision、混合 confirm/defer 與 confidence 不變回歸。

| 驗收 | 結果 |
| --- | --- |
| confirmation + HTTP + scan-context focused suite | `23 passed` |
| 完整隔離後端 pytest | `970 passed`、`710 subtests passed`、0 skipped／failed；120.12 秒 |
| 外部副作用 | 0 USDA／Tavily／模型呼叫、0 API key read、0 Detail／profile 寫入、0 confidence 升級 |

新增 server-owned confirmation lookup，依 authenticated owner、confirmation、issued revision、expiry 與該 revision 仍 active 的狀態限制回傳，且只列出 `confirmed_pending_revision` 並有 FDC ID 的 item；跨 user 查詢不洩漏紀錄存在性。這完成的是確認持久化到 server-owned revision 的原子邊界與下一 route 的讀取前置，不是已可供使用者操作的功能。FDC Search 的糯米腸結果仍不可安全配對，不可因人工選擇以外的途徑用近似食品代填。

## 固定 FDC Detail replay HTTP boundary（2026-11-15）

現有 `POST /nutrition/fdc/detail` 已建立受限 HTTP 邊界，預設 `FDC_DETAIL_ROUTE_ENABLED=false`。請求只接受 `confirmation_id`、`scan_id`、`issued_scan_revision` 與 `item_id`；路由先驗證登入與 feature flag，再由 server-owned confirmation lookup 取回 active issued revision 的已確認 FDC ID，拒絕任意 client `fdc_id`。固定 USDA Detail client 會再次驗證數字 ID、固定 endpoint、response `fdcId`、大小／timeout／redirect／錯誤邊界；本 route 只回傳 provider document，不建立 nutrition profile、不寫使用者紀錄、不改 photo confidence。

`test_fdc_detail_api.py` focused suite 與 confirmation／scan suite 合計 `29 passed`；覆蓋未登入、feature-off 不讀 confirmation/provider、client ID injection、confirmation／revision 不存在、未確認 item 不呼叫 provider、provider response mismatch 的 sanitized error。沒有 live USDA、API key、Detail、profile 或手機端副作用；仍未完成 Detail → `NutritionProfileV1` → portion 的線上接續、source rights/policy、前端確認 UI 與真 HTTP／手機驗收，因此不能開啟此旗標或自動補全。

## FDC Detail profile／portion preview continuation（2026-11-15）

新增離線純函式 `build_fdc_detail_profile()`：server-owned FDC detail document 和 reviewed spec 經固定 adapter、evidence validator 後才建立 `NutritionProfileV1`；portion 以原始每100g來源格計算，不重縮放顯示數字。scan 中文顯示名稱與 FDC source description 分開保留；state、preparation、components、brand、variant 必須完全相容，unknown／None 不作 wildcard。缺少核心營養值、身份不符或重量未知時拒絕，不預設100g，也不輸出／更改 photo confidence。

Focused detail-profile/adapter/detail/repository suite 為 `59 passed`、`7 subtests passed`。以 150g fixture 驗得 52 kcal → 78 kcal、鈉 1mg → 1.5mg。此批沒有 route／SQLite 寫入／live provider 呼叫，source rights/policy、確認 UI 和真 HTTP／mobile 流程仍未完成；所有自動補全旗標保持關閉。

## FDC source policy contract（2026-11-15）

新增離線 `fdc_source_policy_service.py`，要求 FDC policy 明確標示 `usda_fdc_api`、固定 numeric FDC ID／Detail URL、per-100g table ID、adapter/retrieval version、完整來源身份與 server-approved review record。裸 Search candidate、錯 provider 或未批准 review 不可直接升格為 source policy。定向 validator suite `7 passed`；沒有 provider／模型／DB／profile 副作用，也沒有登錄 production source。下一步仍是 repository provenance 重驗與撤回／重啟／CAS 測試，所有自動補全旗標維持關閉。

## FDC policy durable regression 與 server-owned profile preview（2026-11-15）

補上 FDC policy 的 source ID／URL provenance 偽造、CAS 過期，以及 SQLite 重啟後撤回政策的專項回歸。新增 `FdcProfilePreviewService` 離線唯讀 coordinator：由 authenticated confirmation 取得 confirmed FDC ID，從 issued scan context 取得 item revision、身份與實際重量，從 active canonical FDC policy 取得固定 spec；固定 Detail provider 呼叫前後重新檢查所有授權資料，通過後才建立 `NutritionProfileV1` 與 portion preview。測試不接受 client FDC ID、document、policy、profile 或 weight，不寫 profile／飲食紀錄，不提高 photo confidence。

| 驗收 | 結果 |
| --- | --- |
| preview focused | `10 passed` |
| policy/repository/preview focused | `32 passed`、`9 subtests passed` |
| complete backend regression | `997 passed`、`721 subtests passed`、0 failed |
| network／persistence boundary | 0 live provider/model/key reads；0 route/UI/profile writes；flags and production registry remain disabled |

此 evidence 仍是 offline fake Detail／SQLite contract，測試 policy 不代表正式 rights admission。下一步是 preview persistence 與 accept/write transaction，需綁定 confirmation-issued revision、policy revision、detail/profile hash、expiry 和 profile CAS，並驗證 rollback、restart、idempotent replay、兩連線競態；在此之前不得開啟任何 enrichment route 或 automatic fallback。

## Scanner／UI server-owned reference 接線審查（2026-11-15）


前端 nutrition regression `124 passed`、scanner records `12 passed`，typecheck／lint 通過；後端 FDC snapshot／confirmation／Detail／preview focused suite `35 passed`。審查確認 scanner 目前只做 vision → optional enrichment，沒有 FDC confirmation／preview／accept call site，也沒有保留 scan reference。後端 candidate snapshot creation 尚未接入 vision route，亦沒有 authenticated snapshot read route，因此 UI 不能安全取得候選清單或 snapshot digest；本輪不做假接線、不開 flags。另已修正新增 enrichment item 缺少正重量時 fallback 到 `100g` 的問題，改為 unresolved。完整結論與下一步見 [scanner-server-reference-audit-20261115.json](scanner-server-reference-audit-20261115.json)。

## Server-owned FDC candidate search HTTP contract（2026-11-15）

新增預設關閉的 authenticated `POST/GET /nutrition/fdc/candidates`。POST 僅接受 `scan_id`、`scan_revision`，服務端從 SQLite 讀取完整 scan context，確認 TFDA 與 USDA FNDDS 檔案均健康後重跑本地 lookup；只對 high-confidence、validation-clean 且 `no_local_mapping` 的食物執行 server-allowlisted FDC Search。每 scan 最多 4 個未命中項目、12 次 Search、每次 5 筆 metadata、25 秒 deadline。超出預算或本地資料集不可用時 fail-closed。快照沿用 SQLite immutable snapshot repository，綁定 owner、revision、identity 與 digest；同程序 replay 不重查，GET 只能讀 owner 的 active snapshot。response 僅有候選身份 metadata 與 server references，沒有 nutrition values 或 Detail payload。

證據：[fdc-candidate-search-http-20261115.json](fdc-candidate-search-http-20261115.json)。定向 service/HTTP tests `13 passed`；合併 FDC snapshot/query/client/vision/enrichment focused suite（含隔離 SQLite HTTP integration）`66 passed`、`68 subtests passed`；完整 backend pytest `1032 passed`、`721 subtests passed`。未呼叫 live USDA、Tavily 或模型，未讀 API key，未寫 production SQLite/profile/record；所有 flags 仍為 false、source registry 維持空集合。scanner state/UI 與手機 bounded E2E 尚未接線；同一 revision 的 provider single-flight 僅保證單一程序，未驗證跨 process。

## Scanner FDC candidate reference transport（2026-11-15）

新增預設關閉的前端 `nutrition-fdc-candidate-api.ts`。它只傳 server-issued `scan_id`／`scan_revision`，嚴格驗證候選快照 projection 與 owner scan/revision/digest 一致性；候選資料只能作為之後人工確認的 metadata，不能作營養資料、Detail 或 AI 已認定的證據。空候選快照會明確保留為 `empty`，不與請求失敗混淆。

scanner 將 scan reference 和快照留在 Zustand 記憶體狀態，不保存 authority token。Search 只在 `EXPO_PUBLIC_FDC_CANDIDATE_SEARCH_ENABLED=true` 且有 Bearer token 時背景發出，預設 false；server response 只可附著於當前相同 reference、user 與 API host。new scan/scan start、clear、logout、account switch、API host change 均清空 references，舊 request 不得復活已清除狀態。此 transport 沒有改變掃描名稱、照片信心、營養數字或寫入紀錄。

證據：[fdc-candidate-scanner-reference-20261115.json](fdc-candidate-scanner-reference-20261115.json)。nutrition `131 passed`、scanner/lifecycle `15 passed`、typecheck/lint 通過；backend candidate integration `8 passed`（隔離 SQLite/fake FDC）。本批未啟用兩端旗標，沒有 live provider/key、production DB、profile 或 record 副作用。下一步為逐項候選確認 UI，但需先解決掃描器 client 可調重量與 FDC preview server-owned 重量的落差；手機/Tailscale enabled bounded E2E、source rights admission 與 cross-process Search single-flight 尚未完成。

## Phase 4: scanner → isolated SQLite HTTP → FDC preview browser E2E（2026-11-15）

本輪使用真實 scanner UI、Flask HTTP routes 與獨立暫存 SQLite；Playwright 未攔截 `/predict/vision-food` 或 `/nutrition/fdc/*`。只有 vision、FDC Search 與 Detail provider 使用固定 fake fixture，正式部署環境未改動。流程完成 gallery 選圖 → high-confidence unmatched 食物 → candidate snapshot → confirmation `202`、revision `0 → 1` → preview `200`。server weight 與 portion weight 均為 `150g`，`52 kcal/100g` 換算為 `78 kcal`。

測試發現並修正 scanner 在 local nutrition miss 時會丟棄 scan reference 的接線缺口。現在只接受 ID 相符、validation-clean 的 server-owned `recognized/unmatched` 項目；低信心與 validation-invalid 項目仍不進候選確認。SQLite 結果為 2 scan contexts、1 candidate snapshot、1 confirmation、1 active preview，0 nutrition profiles、0 meal records。一次慢速流程因既有 120 秒期限回 `409`；快速重跑成功，未延長 TTL。

| 驗收 | 結果 |
| --- | --- |
| browser → Flask HTTP | vision `200` → candidate `200` → confirmation `202`／revision `1` → preview `200`；相關路由無 Playwright interception |
| responsive | 390×844 與 1440×1000 無水平溢出；切換 viewport 後 preview 保留 |
| regression/static checks | scanner `18 passed`；preview HTTP integration `3 passed`；typecheck、ESLint、Expo web export 通過 |
| browser console | 0 runtime errors；僅既有 `pointerEvents` deprecation warning |
| side effects | 0 live USDA/Tavily/model；0 production DB、profile-accept 或 meal-record writes；正式 flags 未變更 |

完整證據：[fdc-profile-preview-sqlite-browser-e2e-20261115.json](fdc-profile-preview-sqlite-browser-e2e-20261115.json)。此 bounded E2E 不代表正式啟用：沒有測實體相機、另一裝置/Tailscale、真來源權利／registry、跨程序 Search reservation、profile accept 或飲食紀錄寫入。下一 gate 是來源權利／registry 與跨程序 reservation review；所有正式 flags 仍 false、production registry 為空，SQLite-only 決策不變。

## Source Rights Recheck（2026-11-15）

USDA FDC API Guide states the data is public domain under CC0 1.0 and requests attribution; API credentials must remain server-side and the default rate limit is 1,000 requests per IP per hour. This supports a possible item-specific FDC policy after identity, nutrient mapping and provenance review, but does not itself approve a production policy.

Tavily Help Center permits long-term storage and application display of its Search/Extract/Crawl output, but does not grant rights to underlying publisher content. Publisher-specific terms and attribution still apply, and Tavily asks customers to confirm the plan before sharing cached output across multiple customers. The current Platform Terms describe API access as for internal business purposes; the user's actual order form/account scope was not inspected. No publisher nutrition page is admitted by this review.

Code review found withdrawal blocks future authority/cache reads but does not physically purge profiles, previews, scan/candidate/confirmation records or enrichment request results. Cache expiry has a bounded purge; source withdrawal does not. Therefore the production source registry remains empty and all production flags stay off. Full evidence: [source-rights-recheck-20261115.json](source-rights-recheck-20261115.json).

## Phase 4: scanner → isolated SQLite HTTP → FDC preview browser E2E（2026-11-15）

本輪使用真實 scanner UI、Flask HTTP routes 與獨立暫存 SQLite；Playwright 未攔截 `/predict/vision-food` 或 `/nutrition/fdc/*`。只有 vision、FDC Search 與 Detail provider 使用固定 fake fixture，正式部署環境未改動。流程完成 gallery 選圖 → high-confidence unmatched 食物 → candidate snapshot → confirmation `202`、revision `0 → 1` → preview `200`。server weight 與 portion weight 均為 `150g`，`52 kcal/100g` 換算為 `78 kcal`。

測試發現並修正 scanner 在 local nutrition miss 時會丟棄 scan reference 的接線缺口。現在只接受 ID 相符、validation-clean 的 server-owned `recognized/unmatched` 項目；低信心與 validation-invalid 項目仍不進候選確認。SQLite 結果為 2 scan contexts、1 candidate snapshot、1 confirmation、1 active preview，0 nutrition profiles、0 meal records。一次慢速流程因既有 120 秒期限回 `409`；快速重跑成功，未延長 TTL。

| 驗收 | 結果 |
| --- | --- |
| browser → Flask HTTP | vision `200` → candidate `200` → confirmation `202`／revision `1` → preview `200`；相關路由無 Playwright interception |
| responsive | 390×844 與 1440×1000 無水平溢出；切換 viewport 後 preview 保留 |
| regression/static checks | scanner `18 passed`；preview HTTP integration `3 passed`；typecheck、ESLint、Expo web export 通過 |
| browser console | 0 runtime errors；僅既有 `pointerEvents` deprecation warning |
| side effects | 0 live USDA/Tavily/model；0 production DB、profile-accept 或 meal-record writes；正式 flags 未變更 |

完整證據：[fdc-profile-preview-sqlite-browser-e2e-20261115.json](fdc-profile-preview-sqlite-browser-e2e-20261115.json)。此 bounded E2E 不代表正式啟用：沒有測實體相機、另一裝置/Tailscale、真來源權利／registry、跨程序 Search reservation、profile accept 或飲食紀錄寫入。下一 gate 是來源權利／registry 與跨程序 reservation review；所有正式 flags 仍 false、production registry 為空，SQLite-only 決策不變。
