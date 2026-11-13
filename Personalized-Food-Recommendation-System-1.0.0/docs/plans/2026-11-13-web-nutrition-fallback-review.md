# 第三層營養補全：第二至四輪自行審查紀錄

日期：2026-11-13。對象：[流程計畫書](2026-11-13-web-nutrition-fallback.md)。
版本：第二輪為實測前歷史查核；第三輪為實測及使用者追問後修訂；第四輪補查前兩層路由與未測門檻。最近更新2026-11-14，現行判斷以後續交付審查及主計畫第26節為準。
方式：第二輪先完成初稿，再從第 1 至 16 節重讀，將承諾、資料流與現有程式逐一對照。
限制：第二輪為同一代理自行審查，當時未實測；第三輪依授權實測但尚未實作。後續修復已修改後端，Phase2a另由儲存、風險及API代理獨立交叉檢查；仍不等於外部安全或營養專業審核。

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
