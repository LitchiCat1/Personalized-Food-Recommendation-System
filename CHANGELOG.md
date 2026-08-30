# Changelog

## v0.0.8b - 2026-08-30 (菜單照片辨識修正版)

### Fixed

- **菜單照片辨識失敗**：修正 Web 相簿只回傳 blob/data URI 時未送出圖片的問題；後端現在依實際圖片位元組辨識 MIME，並支援 Gemini 目前可用模型輪替，避免舊模型停用或 429 配額讓密集中文菜單直接變成空結果。
- **菜單 OCR 結果遺失**：支援 Gemini 多段回應、欄位別名與截斷 JSON 的可用前綴；過濾沒有價格的分類標題，並保留同名小／大份品項。
- **菜單上傳診斷**：辨識失敗會回傳可理解的 API key、配額、服務忙碌或圖片格式訊息；失敗時不會清空店家既有菜單資料。

## v0.0.8 - 2026-08-29

### Added

- **菜單拍照上傳**：「上傳實體菜單照片」按鈕現在會詢問「📷 拍照」或「📁 從相簿選擇」，並在拍照前請求相機權限，不再只能從相簿挑選既有圖片。

### Fixed

- **AI 摘要營養素缺漏**：「智慧推薦」AI 摘要的個人化推薦餐點（`recommended_foods`）先前只由 Gemini 提供品名與理由，膳食纖維、鈣、鐵三項在缺乏估算邏輯下永遠為 0；補上依食物關鍵字的保守估算，比照既有膳食纖維規則。
- **營養素進度不隨疾病更新**：後端早已依 PDF 臨床準則計算疾病專屬的每日營養目標（`calculate_pdf_daily_targets`），但只用於 AI 摘要提示詞，首頁「營養素進度」進度條的目標值從未套用，一律使用固定預設值。`/records/<user_id>` 現在會回傳 `nutrition_targets`，首頁全部 11 項營養素目標會依使用者當前疾病動態更新。
- **推薦卡片過早顯示「+ 加入今日紀錄」**：「智慧推薦」店家卡片在使用者查看完整菜單或 AI 摘要前，其推薦品項本屬粗略猜測資料，卻已顯示「+ 加入今日紀錄」按鈕，容易把不準確的營養數值寫入飲食紀錄；改為僅在完整菜單與 AI 摘要中提供加入按鈕。
- **拍照上傳按鈕在網頁版完全無反應**：react-native-web 的 `Alert.alert`在網頁平台是空函式，導致「拍照 / 相簿」選擇對話框點擊後沒有任何反應。改為使用自訂 Modal（比照既有刪除確認對話框樣式），網頁與原生平台皆可正常運作。
- **營養素目標顯示未四捨五入**：`nutrition_targets` 先前直接回傳未經處理的浮點數（如 `38.147999999999996`），造成首頁進度條顯示雜訊數字；改用既有的 `_display_number` 邏輯統一四捨五入至小數點下一位。
- **AI 摘要「加入今日紀錄」數據異常**：`handleQuickAddRecord` 先前用 `item.calories || 350` 這類 `||` 寫法帶入預設值，導致 AI 摘要中合法為 0 的數值（例如「無糖茶」「黑咖啡」等真實熱量／蛋白質／碳水／脂肪／鈉為 0 的推薦品項）被誤判為「未提供」，被硬套上 350 kcal／15g 蛋白質／45g 碳水／10g 脂肪／500mg 鈉的樣板數字，造成每次加入這類低熱量推薦餐點時數據明顯失真。改用 `??`，只在數值真的缺漏（`null`/`undefined`）時才套用預設值。
- **拍照上傳菜單「選擇完照片就沒反應」**：上傳實體菜單照片後，成功／失敗／「AI 沒辨識到餐點」都只呼叫了在網頁版是空函式的 `Alert.alert`（或原生平台不支援的 `alert()`），使用者選完照片後除了讀取中動畫消失外完全沒有任何提示，容易誤以為功能故障。改為在畫面上顯示可關閉的 `FeedbackBanner`：辨識成功、辨識失敗（含錯誤訊息）、以及辨識結果為空（例如未設定 Gemini API key 或照片內容無法解析）都會有明確文字說明；「+ 加入今日紀錄」的成功／失敗提示與 AI 摘要載入失敗提示也一併改用同一機制。
- **AI 食物辨識頁同一批網頁版無回應問題**：「拍照 / 相簿 / 營養標示 / 手動搜尋」頁的相機錯誤、辨識結果、OCR 結果、搜尋結果、自訂食品儲存等 15 處提示同樣都用了網頁版空函式的 `Alert.alert`；沿用該頁已有的 `FeedbackBanner` 機制統一顯示，並在每個動作開始時清除前一次的提示，避免舊訊息殘留誤導。
- **個人檔案頁「登出」在 Demo 模式下網頁版按了沒反應**：未設定 Supabase Auth 時點擊「登出」、以及儲存個人資料成功、登出失敗都只呼叫了 `Alert.alert`；改用畫面上的 `FeedbackBanner`，讓使用者知道「目前未啟用 Supabase Auth，無法登出」而不是誤以為按鈕失效。原生平台的登出確認對話框（`Platform.OS !== 'web'` 分支）維持使用 `Alert.alert`，網頁版原本就已改用 `window.confirm` 不受影響。
- **拍照上傳實體菜單「AI 沒辨識到餐點」（Gemini 已設定金鑰時）**：`parse_menu_image_with_gemini` 先前不論實際上傳的圖片格式為何，一律把 `inlineData.mimeType` 寫死為 `image/jpeg`；若使用者上傳的是 PNG（許多手機截圖、部分相機皆為 PNG），Gemini 會收到型別標示錯誤的圖片資料，可能因此完全讀不到內容卻仍回傳 HTTP 200，導致「辨識成功但零品項」且無任何錯誤訊息。改為比照現有 `nutrition-label` OCR 端點，透過 `decode_image_base64` 依實際位元組偵測正確的 PNG/JPEG/GIF/WebP mimeType。同時強化辨識 prompt，明確要求「即使品項很多也要逐一列出、不可只挑幾項」並放寬「需精算物理熱量一致性」的措辭（下游 `validate_and_balance_nutrition` 本來就會校正），並將 `maxOutputTokens` 提高到 8192，降低密集菜單（十幾到數十項）因輸出過長或模型過度謹慎而回傳空陣列的機率；同時在「HTTP 200 但零品項」時記錄 `finishReason`，方便日後從 Render logs 診斷。

## v0.0.7e - 2026-08-26 (拍照菜單測試版)

### Added

- 新增「📷 拍照 / 📁 上傳實體菜單」功能：在「完整菜單」對話框內常駐提供上傳按鈕，支援使用者隨時拍照或選取照片，並透過 Gemini Vision AI 自動讀取菜單品項、價格與營養估算。
- 新增 Gemini API 多金鑰動態輪替機制 (Key Rotation)：解決 API 每分鐘 15 RPM 限流與 429 錯誤，確保多組 API Key 自動切換不中斷。

### Fixed

- **熱量物理校正 (Calorie Balance Algorithm)**：引入 $P \times 4 + C \times 4 + F \times 9 \approx \text{Calories}$ 驗算機制，修正牛肉麵等餐點高脂肪與標示總熱量不符合物理邏輯的問題。
- **全套 11 項營養指標補全**：補齊精緻糖、飽和脂肪、反式脂肪、膳食纖維、鈣與鐵欄位，防止記錄產生全為 0 的缺漏。
- **移除硬編碼樣板值**：徹底移除前端 `fiber || 3` 寫死 3g 纖維及「AI 摘要」餐點 `400 kcal` 樣板，改為讀取真實分析數值。
- **過濾 0 kcal 佔位符按鈕**：過濾 Google Places 店家的 `到店後選擇符合預算的餐點` 0 kcal 提示項目，隱藏該項目的「+ 加入今日紀錄」按鈕。

## v0.0.7d - 2026-08-18

### Added

- 在所有推薦餐點（店家卡片、AI 摘要提醒、完整菜單 Modal）旁新增「+ 加入今日紀錄」按鈕，點擊可直接將詳細營養素寫入當日飲食紀錄並動態累計進度條。
- 為所有店家（包含 Google Places 店家）提供通用的「完整菜單」解析與 3~5 項安全餐點推薦。
- 新增根據使用者疾病禁忌、過敏原、剩餘熱量/營養素目標與預算自動排序截取 Top 3~5 項最佳餐點的推薦機制。

### Changed

- 更新菜單評分排序，優先隔離反式脂肪、高油炸、過敏原等不符條件餐點至「不符合/需注意餐點」區塊。
- 更新 Blueprint 與部署腳本版本標籤至 `v0.0.7d`。

## v0.0.7c - 2026-08-17

### Added

- Added Google Places official website and Google Maps links to nearby restaurant results.
- Added a conditional external "店家網站／菜單" entry when Google Places provides an official restaurant website.
- Added a Google Maps store-information entry for traditional shops without a public website, so users can inspect the store's current photos and details without invented menu data.

### Changed

- Google Places restaurants no longer invoke the Gemini/template-generated detailed-menu flow; local catalog restaurants retain their existing menu analysis.
- Updated Render services and the desktop sidebar version label to `v0.0.7c`.

### Fixed

- Fixed Blueprint deployments sending API requests to the original project's backend instead of the backend created in the same deployment.
- Made Render deployments require Supabase Auth by default and fail closed with a configuration error instead of silently loading the `demo_user` / 王小明 profile.
- Render now prompts for Supabase and Google Places settings once on the backend, then exposes the required public build values to the frontend through Blueprint service references.

### Validation

- Added focused Google Places link tests covering successful website discovery and non-blocking detail lookup failure.

## v0.0.7b - 2026-08-14

### Added

- Added complete record, scanner, OCR, TFDA search, history, and PostgreSQL support for refined sugar, saturated fat, trans fat, calcium, iron, and fried-food status.
- Added disease-aware daily nutrition targets and food-risk handling for diabetes, gout, hyperlipidemia, hypertension, and stage 3-5 chronic kidney disease.
- Added backward-compatible normalization from `refined_sugar` to the canonical `sugar` field.

### Changed

- Updated nutrition labels to total carbohydrates, refined sugar, total fat, dietary fiber, sodium, calcium, and iron terminology.
- Made Supabase authentication explicit through `EXPO_PUBLIC_SUPABASE_AUTH_REQUIRED`, matching the backend deployment mode.
- Updated Render services to deploy from `v0.0.7b`.

### Removed

- Removed the standalone meal recommendation list, recommendation feedback controls, `/recommend/<user_id>` API, feedback APIs, recommendation service, and dedicated feedback storage initialization.
- Kept nearby restaurant search, Google Places map, navigation, menu inspection, and restaurant summaries available on the `recommend` route.

### Validation

- Backend unit/API tests and frontend TypeScript checks cover the retained record, scanner, history, disease-rule, and nearby restaurant flows.

## v0.0.7 - 2026-08-07

### Added

- Added Google Places API (New) v1 fallback to handle projects with disabled Legacy Places API.
- Added multi-version Gemini model selection (trying `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-flash` in sequence) to resolve model deprecations on newer keys.
- Added local location fallback flat coordinate shifting for mock restaurants in dev catalog, guaranteeing markers show up during off-grid offline local testing.
- Added detailed offline empty-state helper guides inside the menu Modal to direct users to camera scanning and AI summaries.

### Changed

- Refactored nearby restaurant search recommendations to dynamically feed dish details into the top-level food recommendation panel with restaurant names as source labels.
- Replaced general healthy bento dummy items in scraper default fallback with an empty list for unknown restaurant names.

### Validation

- Backend model list fallback tests and Google Places v1 integration verified via HTTP API.
- Typecheck and Metro bundle compilation completed successfully.

### Deployment Notes

- Clear database cache of old placeholder menus if testing new keys.
- Keep standard environment variables for production.

## v0.0.6 - 2026-08-03


### Added

- Added editable nutrition-label food names with whitespace validation and persisted final values.
- Added idempotent dietary record saves, visible success/error feedback, and a retryable local synchronization queue.
- Added authenticated record-backed dietary trends with same-day aggregation and latest continuous seven-day selection.
- Added a dashboard dietary record manager with inclusive date ranges, responsive record lists, editing, deletion confirmation, and error recovery.
- Added a shared calendar date picker and manual creation of validated today or historical dietary records.
- Added backward-compatible record pagination plus authenticated `PATCH` and `DELETE` endpoints keyed by `client_record_id`.
- Added focused scanner, date-range, trend, record mutation, and API route tests.

### Changed

- Dashboard and trend data now refetch through the shared Zustand record revision after record creation, synchronization, editing, or deletion.
- Updated Expo, package, desktop UI, Render Blueprint, and deployment documentation versions to `v0.0.6`.

### Validation

- Backend unit and API suites, frontend scanner/date/trend tests, typecheck, lint, and Expo web export passed.
- Responsive QA covered 375, 390, 430, 768, and 1280px widths with no horizontal overflow.
- Browser QA covered inclusive same-day, cross-month, cross-year, empty, loading, API error/recovery, edit retry, delete cancel, and delete failure states.

### Deployment Notes

- No database schema migration is required; existing record fields and API response schemas remain unchanged.
- Render services now track the `v0.0.6` release branch and retain the existing environment variables.

## v0.0.4 - 2026-07-18

### Added

- Added disease-sensitive nutrient markers to the dashboard, backed by the existing disease-rule metadata with local fallbacks.
- Added a shared daily nutrition progress context covering targets, consumed amounts, remaining amounts, progress percentages, goal types, and over-target amounts.
- Added personalized Google Places restaurant AI summaries that use the authenticated user's current diseases and daily nutrition progress.
- Added explicit handling for nutrients that are near or over their upper limit, with disease restrictions taking priority over filling other nutrition gaps.
- Added personalized food recommendations and reasons to the restaurant AI summary UI.
- Added service and authenticated API route tests for disease context, nutrition overages, prompt construction, and restaurant summary responses.

### Changed

- Simplified the recommendation page so meal and nearby restaurant sections remain visible in one responsive flow.
- Updated the frontend version, CI release branch, Render Blueprint branch, and deployment documentation to `v0.0.4`.
- Replaced the stale backend CI file list with a full `compileall` syntax check so new and renamed Python modules are covered automatically.
- Updated frontend contribution guidance to use the implemented Expo design system as the baseline for incremental UI work.

### Validation

- Backend: 35 unit and API tests passed.
- Frontend: typecheck, lint, and Expo web export passed.
- Responsive QA: verified at 390x844 and 1440x1000 with no horizontal overflow and 44px AI summary touch targets.

### Deployment Notes

- No database schema migration is required.
- Render must retain the existing Supabase, Gemini, Google Places, and database environment variables.
