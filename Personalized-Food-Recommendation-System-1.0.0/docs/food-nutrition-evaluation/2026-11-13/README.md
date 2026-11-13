# 食物拍照、營養來源與 Tavily 實測報告

日期：2026-11-13。分支：`v1.0.1`；基準提交：`bb81e92`。

後續更新：2026-11-14已依指示切到v1.0.2，完成[Phase2b1基礎與Phase2b2a送出完整性驗收](../2026-11-14/README.md)。本文保留11月13日實驗與後端階段歷史；付費實驗總數不變，完整nullable前端／第三層仍未接線。

## 結論與範圍

Tavily 金鑰可用，已完成真實搜尋／擷取；目前中轉模型能處理取得的營養文字。可採「TFDA → 相容 USDA → Tavily 找來源／取原文 → 模型擷取 → 後端驗證及換算」。後續已完成本機修復、離線營養合約及Phase2a後端保存／風險；第三層與前端尚未正式串接，未寫入實際使用者資料或部署。

搜尋能增加候選來源，不能修復照片中的未知品牌、隱藏配方與估重誤差。找到官方網址、HTTP 200、模型 candidate、格式可解析，均不足以證明食品配對與數值可用。首版宜從人工核對的參考資料及來源轉接器開始。

已修訂[流程計畫書](../../plans/2026-11-13-web-nutrition-fallback.md)與[第二至四輪自行審查](../../plans/2026-11-13-web-nutrition-fallback-review.md)。以下明列失敗、限制與未驗證項目；第四輪新增純離線路由反例，既有付費總數不變。

## 實驗設計與總量

| 實驗 | 真實呼叫／觀察 | 證據 |
| --- | --- | --- |
| 原始照片重複 | 13 張既有圖，各 3 次，共 39 次 | [vision-original.json](vision-original.json) |
| JPEG quality=70 | 牛肉麵、便當各 3 次，共 6 次 | [vision-q70.json](vision-q70.json) |
| 中轉功能控制 | 搜尋請求、web_search_options、簡單 schema、function tool 各一次 | [capabilities.json](capabilities.json) |
| nullable 對照 | union、anyOf、JSON-object 三次 | [nullable-schema.json](nullable-schema.json) |
| 多案例文字擷取 | strict schema 6 次；JSON-object direct 2 次、Tavily 4 次 | [extraction.json](extraction.json)、[direct](extraction-json_object-direct.json)、[Tavily](extraction-json_object-tavily.json) |
| 真實正向／假品牌混合批次 | 醫院地瓜球、精確品牌湯品、假品牌，重複 3 次 | [positive-pipeline.json](positive-pipeline.json) |
| Tavily 初測與來源追查 | 8 Search、2 Extract | [tavily.json](tavily.json)、[tavily-followup.json](tavily-followup.json) |
| Tavily 參數對照 | 3 Search、4 Extract | [tavily-settings.json](tavily-settings.json) |
| 直接來源查核 | 11 個獨立候選網址，含失敗來源 | [sources.json](sources.json)、[sources-followup.json](sources-followup.json) |
| 現行資料流程觀察 | 隔離記憶體／臨時 SQLite API、前端真實 helper／store | [offline.json](offline.json)、[frontend.json](frontend.json) |
| 第四輪路由補查 | 兩層本機匹配、雙語映射、範圍／內餡、自訂基準、異常值及未配對上下文，零網路 | [routing-offline.json](routing-offline.json) |

模型合計 67 次 HTTP 嘗試，66 次 HTTP 200，一次 ReadTimeout。Tavily 合計 11 Search、6 Extract，17 次 HTTP 200，API 回報共 13 credits；單次 Extract usage=0 不等於免費。摘要可由[summary.json](summary.json)與離線彙整工具重建。

本次請求模型別名為 `[AN]gemini-4-hydrogen-high`，回傳字串為 `gemini-4-hydrogen`，底層版本未獨立證實。診斷直接使用目前設定的第一把中轉金鑰，無輪替／重試；照片兩個 worker，不代表正式金鑰池、並發或端到端效能。

回報 token 合計為 prompt 167,047、completion 45,113、total 361,440；供應商 total 含其他計數，不能將兩欄簡單相加或自行推算金額。所有金鑰未放進報告，`TavilyKey.txt` 已加入 `.gitignore`。正式設定應用後端環境變數。

## 照片穩定性與缺資料原因

39 次原始照片呼叫共辨識 128 項，80 項通過現行營養配對，48 項未納入：46 項缺相容營養配對、2 項辨識信心低。項目配對涵蓋率為 62.5%，不是辨識或營養準確率。

128 項中只有 2 項 confidence 低於 0.45；但全部 128 項 weight_confidence 均低於 0.75，已接受的 80 項也全部需確認。警示多不等於模型都看不懂食物，份量、配對與選填缺值須拆開。

食品名稱多重集合在 8/13 張圖的三次結果一致。原始照片呼叫 p50 15.036 秒、p95 最近名次法 26.468 秒、最大 27.826 秒。沒有獨立品名、配方或秤重真值，不能把一致性當正確性。

| 例子 | 實測 | 含義 |
| --- | --- | --- |
| 水餃照片 | 辨識項目總重 445／390／465g；已配對熱量 856／746／896kcal | 查到每100g仍受估重誤差影響 |
| 蛋糕照片 | 三次均600g、1716kcal | 穩定也可能穩定地偏離實際攝取量 |
| 牛肉麵原圖 | 三次肉品皆為「滷牛肉」，高自評信心但未配對 | 同義名稱可能造成既有資料未被找到 |
| 牛肉麵 q70 | 一次改稱「紅燒牛肉」，配到既有熟牛肉參考，已配對熱量變525kcal；其餘276／249 | 名稱／別名對合計影響大，不證明壓縮有益 |

Pillow quality=70 不等於 Expo quality=0.7 的手機管線。六次壓縮實驗不能與全部39次的混合涵蓋率相比而宣稱改善。手機相機、相簿、EXIF、HEIC及實際估重準確率仍未驗證。

## 中轉模型的搜尋與格式能力

現有 payload 及加上 web_search_options 各一次，均未回實際工具／grounding 證據。required function tool 控制有真實 tool_calls 封裝。這證明某種工具協議可用，不能推論中轉原生搜尋已可用或所有搜尋方法均不可用；獨立 Tavily 不依賴此問題。

小型 strict schema 控制通過，但複雜 nullable schema 六次原應回39項，僅回12項，且把缺鈉／缺纖維等輸出成0，有時 reason 說未知而數字仍是0。anyOf 控制也有缺值變0；union 控制逾時。原因在模型或中轉轉譯何處仍未定位。

改 JSON-object 並將完整格式寫進提示後，direct 批次回13/13項，Tavily文字批次回26/26項，觀察到預期 null。這只是有限控制較佳，不能保證後續永遠不漏項。後端仍須嚴格檢查型別、完整唯一 item_id 集合、來源ID、缺值、單位及食品身分。

擷取可耗40.052秒，strict 試驗最長49.208秒。原規劃25秒冷補全成功承諾不成立，只能作有界部分結果預算；快取／轉接器與真正背景作業須分開設計。

## Tavily 的方向限制與實際界限

依[官方搜尋指南](https://docs.tavily.com/documentation/best-practices/best-practices-search)，短而單一的 query 及 Search→Extract 兩段流程適合本用途。實測很長的糯米腸 query 主要回營養標示教學；簡短 `糯米腸 營養` 才回品牌食品，也混入不同地域食品。

| 控制／案例 | 實測與判斷 |
| --- | --- |
| 品牌網域 restrict＋精確品名 | 找到 GREEN & SAFE 正確湯品，仍有同站其他商品；需核對主商品 |
| country=taiwan | 首列仍為吉林糯米腸；地區加權不能作食品配對條件 |
| 假品名＋exact_match=true | 仍回5筆；標題及回傳摘要均無完整假品名。不能依參數宣告就當符合身分 |
| 不存在商品路徑 | Extract列成功，但內容為商店首頁；HTTP200與同網域不足 |
| 初輪basic text商品頁 | 缺營養表，直接HTML有表 |
| 後續同頁basic Markdown、advanced Markdown、advanced＋query | 三者都回完整表，內容雜湊相同；隨後basic text也有表。不能歸因advanced、格式或query改善 |

前10次Tavily初測回報9 credits；參數對照7次回報4 credits。初測Search 1.991–3.370秒，兩批Extract 18.559／5.604秒；後續同頁四次Extract約0.84–0.86秒，可能受快取或服務行為影響，不能宣稱冷路徑降至1秒。

官方支援 `include_domains`／`exclude_domains`、depth、地區、語言與日期等控制。`restrict` 和地域／語言排序加權的語意不同；語言變體尚未實測，不先當支援繁中精確過濾。Search advanced尚未比較。不要把完整營養JSON提示塞進query；固定格式留給後續模型與本地驗證。

Extract query 可將片段依需求重排，但可能漏份量與表頭；advanced偏重表格與嵌入內容，仍不保證擷取完整。詳見[Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Extract API](https://docs.tavily.com/documentation/api-reference/endpoint/extract)及[credits](https://docs.tavily.com/documentation/api-credits)。本輪未全面審核跨使用者重用及原來源保存條件。

## 可核對的正向來源

Tavily找到[臺安醫院 QQ王子地瓜球PDF](https://www.tahsda.org.tw/communitymedicine/files/20161126_RAOHEStreetMarketNight/QQ%E7%8E%8B%E5%AD%90%E5%9C%B0%E7%93%9C%E7%90%83.pdf)，已直接取回並渲染檢查原表。來源屬2016年饒河夜市特定攤商社區資料，75g一份；每100g為477.3kcal、蛋白0.6g、脂肪26.9g、碳水58.2g、纖維1.4g、鈉26mg、糖11.5g。飽和／反式脂肪未列，應保持null。

這可作明示的同類熟食參考候選，不能聲稱照片就是該攤、現行配方或各家平均值。年份、烹調與參考性質必須保留。

[GREEN & SAFE香菇赤肉羹](https://www.green-n-safe.com/Products/Content?id=MEG0028ABCS)有300g整包、每份及每100g表格；每100g為94.6kcal、蛋白9.5g、脂肪2.2g、碳水9.2g、鈉502mg、糖1.2g、飽和0.7g、反式0g，纖維未列。適用該品牌整包湯加肉的範圍，不能套到未知品牌的湯汁本身。

將醫院文字、精確產品HTML及假品牌反例混成一批，重複3次：原始純JSON僅2/3次，第三次外包完整Markdown code fence。以既有production parser離線重播後，三次的20項數值／null／ID檢查均通過，共60/60。這未涵蓋完整型別／單位／證據位置驗證，也不代表照片真值或完整生產管線已通過。

保留原始正向測試43/60的歷史計數；該測試程式對缺失item的三個null檢查有誤判。已修工具，未重跑付費呼叫；修正後原始純JSON檢查為40/60，移除完整外層圍欄的離線重播為60/60。不能引用原43/60作準確率。

模型 evidence 有省略號拼接，不能只憑自由引文認定證據。後續應由來源轉接器提供食品／table／row／column ID，後端從實際儲存格取值。

## 應拒絕或重新審核的來源

| 來源 | 問題與處置 |
| --- | --- |
| [HAN DIAN糯米腸](https://handian.co.uk/zh-tw/products/catering-products/sticky-rice-roll/) | 同列1506.2kJ與301.2kcal（前者約360kcal）、總脂肪0而飽和0.1；冷凍需加熱，不直接套台式烤糯米腸；鹽不當鈉 |
| [彰化肉羹麵](https://obesity.chshb.gov.tw/snack_content01.aspx?mno=26&sno=39) | 總重130g，蛋白＋碳水＋脂肪144.2g，基準衝突須審核 |
| [彰化肉羹](https://obesity.chshb.gov.tw/snack_content01.aspx?mno=37&sno=96) | 有330g／290kcal，缺鈉等欄位；可作部分來源候選，不能把鈉填0 |
| [深坑臭豆腐PDF](https://shenkeng.health.ntpc.gov.tw/archive/health_ntpc/22/file/education.pdf) | 305g估算含生豆腐、炸油及50g泡菜，並非熟豆腐本體，且缺鈉 |
| [廣弘地瓜球](https://www.gqfood.com.tw/product_d.php?id=256&lang=tw&tb=1) | 冷凍包餡且需油炸，不等於熟炸空心地瓜球；標示為圖片 |

政府、醫院或品牌網域只提供來源線索，不保證食品、重量與數值沒有矛盾。13例擷取中的candidate亦未自動通過上述本地檢查。

## 現行資料流程的隔離觀察

- 缺失／無效confidence預設0.5可通過0.45；布林true變1；110被截為1、1.2被視為0.012。布林重量true也變1g。新版須拒絕無效型別。
- 只有JPEG／PNG magic header的截斷假圖通過目前輸入檢查；未測真手機照片失敗率。
- 本機`滷牛肉`查無，`紅燒牛肉`／`燉牛肉`可配既有熟牛肉參考。先建立受狀態／scope限制且經審核的別名，不任用模型alternatives。
- 隔離記憶體與臨時SQLite API把null鈉保存為0；紀錄層nutrition_context被捨棄。SQLite重開仍是已失真的0。
- 前端scanner mapping丟來源URL及status；save丟重量／缺值旗標，糖與飽和／反式缺值變0；edit draft把缺鈉等變字串0。
- 真實store改重800→1600mg後保留舊警告；反覆改回原重則回800，未觀察到累積四捨五入漂移。仍缺原始每100g profile，並應重新評估風險。

以上測試只對記憶體、臨時SQLite及mock網路執行，未觸碰實際使用者紀錄。前端非實機／畫面端到端。既有後端全套unittest退出碼0（有預期例外日誌及SQLite ResourceWarning）；前端scanner／records／trends／insights相關38項通過。通過現有測試不表示上述新反例已修復。

## 名稱簡化與營養相容性

依使用者追問，「吉林糯米腸」可以提出通用品名「糯米腸」，但「吉林」可能是地域／料理風格，不能當成純品牌刪除後就認定與照片相同。保留display_name、original_visual_name、source_food_name、brand、region/style、preparation、scope及未知項；模型提出分類，後端驗證相容性。

確實同類且來源適用時，可顯示「糯米腸（同類參考值）」並保留完整來源；配方、狀態或範圍未知時不自動套表。改名稱不提升數字可信度。這是規劃規則，尚未對吉林來源作完整配方／營養審查。

## 尚未通過的放行條件

先修前兩層相容／排序與自訂基準、未配對ID／上下文、缺值與來源保存、unresolved／coverage、改重風險、合約相容及已驗證雙語映射；再接少量審核來源；最後擴大有界搜尋。合格官方命中項目不額外搜尋、不混不同來源的營養欄位，所有算式由程式執行。

未完成：獨立標註／秤重測試集、真手機相機／相簿、完整表格驗證器、正式並發／斷線／重啟、SSRF及供應商故障注入、舊版客戶端、全資料庫migration、保存權限與部署端到端驗收。無法承諾所有食品都補齊、25秒成功或高於某百分比的營養準確率。

## 重現與方法修正

無網路重建摘要：`python tools/summarize_nutrition_probes.py`。後端控制：`python tools/probe_nutrition_offline.py`；前端控制：`node --experimental-strip-types tools/probe_nutrition_frontend.mjs`，均僅生成診斷報告。
第四輪路由觀察已保存在routing-offline.json。第一批修復後，同一`python tools/probe_nutrition_routing.py`以socket阻擋連線，改寫入routing-repaired.json，避免覆寫修前證據；報告中historical_unmatched_payload_observation仍特指舊回應。均不修改原實驗summary.json的付費統計。

付費實驗必須明確帶`--live`；既有結果已保存，本輪不需重跑。工具入口為`probe_food_nutrition.py`、`probe_nullable_schema.py`、`probe_nutrition_sources.py`、`probe_tavily_nutrition.py`、`probe_tavily_settings.py`、`probe_nutrition_positive.py`；各工具`--help`列參數。`probe_nutrition_sources.py fetch`不帶live也會直接抓公開網站，並非純離線。

source初次解析的編碼優先序錯誤已修正，原紀錄保留為[sources-initial.json](sources-initial.json)，不是新成功來源。初期行內fetch命令引號錯誤發生於請求前；另一次參數工具列印遇Windows cp950無法編碼，當次結果已先保存，以`--resume`跳過已完成項目，沒有因此重送前三次搜尋。完整來源快照留在本機忽略目錄，公開證據保留URL、雜湊、回應與必要觀察。

## 第四輪純離線路由補測

重新檢查前兩層後，新增[routing-offline.json](routing-offline.json)。實際載入2,213筆TFDA與5,431筆USDA；後者只有12筆有中文名／別名。這是本機FNDDS資料集，不是USDA全庫線上搜尋；目前name_en也未參與自動匹配。隔離牛奶案例的中文＋精確英文欄位不命中，改成英文主名稱即命中，證明映射路徑有缺口，不代表任意英文翻譯都可採值。

已重現：已知韭菜水餃選成高麗菜水餃、泡麵本體與含湯共用同一表、矛盾raw白飯／dry泡麵仍有熟食候選，以及生甘藍TFDA排在熟食USDA前。原態優先是既有政策與測試行為；第四輪明確將其改列待修設計，保留相容候選中的TFDA優先。

自訂食品公開builder接受每份200g／400kcal及unit=per serving，建立每100g200kcal後，搜尋結果仍帶per serving，matcher再換算為100kcal。一般自訂優先控制正常，不能推論所有自訂或OCR結果都錯。另以合成值測得布林／負數／NaN核心可過關、錯誤份重可產負值／100倍放大／TypeError；現有資料快照未發現這三類異常核心值。

先前照片原始回應保留未配對地瓜球及糯米腸重量，但正式rejected回應不帶重量、state或item_id；同名兩份葉菜也不能按名稱唯一識別。補全前必須保存完整項目上下文。USDA缺檔回空字典亦已確認；未實作第三層，因此沒有觀察到故障後付費暴增，只把這條潛在退化路由補進設計防護。

現有影像匹配／資料匯入測試24/24通過，新反例仍未修復；診斷腳本不是修正後驗收。測試從backend執行：`python -m unittest discover -s tests -p test_vision_food_accuracy.py`。尚未完成正式協調器端到端、獨立準確率／秤重、保存與客戶端相容；完整待測表已同步至主計畫第15節。

## 第一批修復後的離線驗收

本節是目前狀態；前述「未修復／production未修改」保留為各輪歷史觀察。使用者已授權開始修復，現在正式後端本機流程已修改，尚未部署及啟用外搜。

- 相容性：內餡／品牌不任意刪除；拒raw白飯、dry泡麵套含湯、麵體套含湯、炒水餃套水煮及清燙菜套含油熟菜。相容候選才依自訂、TFDA、USDA排序；10筆生TFDA不會遮住熟USDA。
- 基準與數字：自訂200g400kcal修後200kcal/100g；矛盾雙表及不支援unit拒自動配。核心／選填數字拒bool、負值、非有限、數值字串與溢位；份重必須是正有限數字。實際資料核心異常數仍為0，TFDA 98筆核心null屬缺值。
- 辨識合約：完整JSON或完整外圍欄、舊外層陣列兼容；混文／重複鍵／非有限／截斷拒絕。數字信心無效不再補0.5，重量不夾限；method／scope固定enum。原名、英文、狀態、方法、範圍、兩種信心、總重與count保留於每項recognition_context，server ID分開同名項，尚未簽署及持久化。
- 資料健康：兩庫分開驗schema／數字／檔案，缺檔明確unavailable；API附健康且保留可用層結果。自動外搜旗標保持false，無正式搜尋協調器。未設預期輸出hash時顯示not_configured。

修前[routing-offline.json](routing-offline.json)不變；[routing-repaired.json](routing-repaired.json)記錄修後控制。[local-repaired-replay.json](local-repaired-replay.json)重播既有13圖、41項，配對從27減至18、23項待處理。這反映拒絕生熟／方法不相容候選，不能推論準確率升降；新prompt／模型成效尚未真實重測。毛豆、熟香腸、只有生食資料的配菜仍待補適用熟食來源，不偷偷套生食值。

新增56項測試（自訂basis19、辨識合約14、路由11、資料健康12），既有24項匹配／匯入按新政策更新部分預期。後端全套退出0：579項中556通過、23項真Postgres整合因未設定測試資料庫略過；49項vision測試在最後整合修改後通過。執行時設NUTRILENS_SKIP_LOCAL_ENV=1、空DATABASE_PATH並移除外部DB／relay環境設定；實際使用者資料庫未開啟。既有測試會產預期失敗注入日誌與SQLite ResourceWarning，未將其當成產品故障。

上述第一批當時仍未完成的營養表格欄列／九項可空profile／小於值／coverage，已完成第二批的限定adapter離線版本，詳下一節。缺值保存與舊客戶端、改重風險、簽署enrich上下文、來源授權與取回安全、正式Tavily協調器及真手機真值評估仍待完成。後續順序已回寫主計畫第15、19、23、24節。

## 第二批：營養合約與離線計算驗收

新增[profile-contracts.json](profile-contracts.json)，由`python tools/probe_nutrition_profile.py`在socket禁止連線下產生。兩庫只讀；未呼叫模型、Tavily或使用者資料庫。來源snapshot SHA與欄位缺值計數、13筆一致性待審的原始營養皆在報告中。

TFDA2213筆中330筆九欄完整、1870部分、13因糖／碳水不一致轉source_conflict；USDA5431筆皆只缺反式脂肪，其他八欄有值。partial不代表熱量／宏量皆缺，應逐營養欄位區分可用與未知。13筆不是官方錯誤率或準確率，需另查分析方法及批次；原資料與既有正式matcher未變。本機舊原始ZIP欄值也相同，但與manifest列數／hash不同，不作整份來源鏈驗證。

離線例子驗證200g400kcal→200kcal/100g→150g300kcal；鈉0.5g→500mg、kJ換kcal；`<0.1g`只有排他上界、點值null。unknown份量不預設100g；有未配對項時分母保留且整餐上界撤除。同名項分開、總重不乘count、空餐unknown、明確未食用才排除。

表格合約只選可信server adapter提供的儲存格；完整item_id與九欄驗證、原數字／單位／份重、缺鈉、無重量、錯狀態、惡意文字、假食品、雙能量／雙基準矛盾均有fixtures。模型選任一欄也無法避開可見矛盾。這不是HTML／PDF真解析器，沒有真來源adapter；prompt對注入文字的單元控制不是證明模型能抵抗所有提示注入。

新服務未接正式nullable結果。automatic_web_fallback_enabled仍false；正式保存／歷史／offline／改重風險仍待Phase2，舊numeric0／100g預覽仍有相容占位。沒有新增付費請求或部署。

本批新增74項離線測試：profile／coverage33項、表格evidence41項；加入原dataset health後，nutrition聚焦86項全通過。來源／目標固定enum、來源URL／時間／版本、JSON大小／深度／型別及循環控制亦有回歸。單元驗證不會自行證明來源可保存、身分適用性、DNS安全或真模型合約支援。Python編譯通過。

最終後端全套653項中630通過、23項未配置真Postgres整合略過，101.067秒、退出0。採前節相同環境隔離，只用memory／臨時SQLite／mock；既有錯誤注入與ResourceWarning仍在。三份文件與21份JSON查核、Python編譯及diff空白檢查通過；沒有新增付費請求或觸碰使用者資料庫。

## 第三批：Phase2a後端保存／風險驗收

新增[record-backend-regression.json](record-backend-regression.json)，由[隔離後端回歸工具](../../../tools/verify_nutrition_backend.py)產生。重建指令：`python tools/verify_nutrition_backend.py --output docs/food-nutrition-evaluation/2026-11-13/record-backend-regression.json`。工具設定skip local env、空DATABASE_PATH並清除外部DB／relay；不是呼叫付費模型的probe。合約以合成食品fixture／Flask本機client測試，不是照片辨識準確率。

v2 record／preview／history保持null、0、less_than、原始格及份重；未解食品與未知重量不從分母消失。改重及存檔使用相同原始profile重算，preview與save風險相同；手動改值標user_modified並保留原始來源與已知過敏原。來源任意上傳拒絕，當前本機food_key在server解析；沒有網路profile repository或簽章。

SQLite v1→v2 migration、檔案關閉重開、memory／fakeMongo快照往返、兩個同時revision更新、舊版讀／改／刪與分頁／重送保護均有回歸。歷史全範圍彙總無500筆上限，legacy_unknown不倒推舊0；每日不完整不作剩餘額度／不足結論，已知超量仍告警。

第一輪API測試找出兩條菜單漏擋、後續發現分頁遮住v2；均已修正。另修正手動修改抹除過敏原、原始快照fallback及極端值溢位。完整回歸第一次在DELETE介面整合途中失敗，介面完成後通過；再次加入舊版PATCH資料層競態保護後重跑最終回歸。新測試分為record合約、API、儲存、風險及每日進度五檔，結果由manifest明列。

限制：真Postgres23項未配置測試庫；Mongo僅fake，舊insert仍未保證並行重送唯一性。沒有實機UI、離線queue、OCR小於值全鏈、前端趨勢或正式推薦整合驗收。health僅公告限定v2流程；v2掃描／OCR暫拒，今日有v2時個人化推薦／菜單／摘要也在外部呼叫前暫拒。這不是整個Phase2完成；下一步Phase2b。自動Tavily仍停用，原67模型嘗試與17次Tavily付費統計不變。
