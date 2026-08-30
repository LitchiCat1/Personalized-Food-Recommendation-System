# Changelog

## v0.0.7e - 2026-08-26 (拍照菜單測試版)

### Added

- 新增「📷 拍照 / 📁 上傳實體菜單」功能：在「完整菜單」對話框內常駐提供上傳按鈕，支援使用者隨時拍照或選取照片，並透過 Gemini Vision AI 自動讀取菜單品項、價格與營養估算。
- 拍照流程現在會明確區分相機與相簿來源，並在未授權或裝置不支援時顯示可理解的錯誤提示。
- 菜單照片會先驗證圖片格式與 8 MB 大小限制，且僅在登入者的請求中產生推薦，不會覆寫共用餐廳資料。
- 菜單照片解析出的完整營養欄位會帶入「加入今日紀錄」，避免遺失糖、脂肪、纖維、鈣、鐵與油炸標記。
- 新增 Gemini API 多金鑰動態輪替機制 (Key Rotation)：解決 API 每分鐘 15 RPM 限流與 429 錯誤，確保多組 API Key 自動切換不中斷。

### Fixed

- **熱量物理校正 (Calorie Balance Algorithm)**：引入 $P \times 4 + C \times 4 + F \times 9 \approx \text{Calories}$ 驗算機制，修正牛肉麵等餐點高脂肪與標示總熱量不符合物理邏輯的問題。
- **全套 11 項營養指標補全**：補齊精緻糖、飽和脂肪、反式脂肪、膳食纖維、鈣與鐵欄位，防止記錄產生全為 0 的缺漏。
- **移除硬編碼樣板值**：徹底移除前端 `fiber || 3` 寫死 3g 纖維及「AI 摘要」餐點 `400 kcal` 樣板，改為讀取真實分析數值。
- **過濾 0 kcal 佔位符按鈕**：過濾 Google Places 店家的 `到店後選擇符合預算的餐點` 0 kcal 提示項目，隱藏該項目的「+ 加入今日紀錄」按鈕。
- 修正店家 AI 摘要遇到 Gemini 非嚴格 JSON 時顯示 `Expecting value` 解析例外；現在會嘗試下一組模型，全部失敗時回傳低信心且明確標示不可用的摘要。

### Changed

- 優化所有 Gemini 提示詞：要求只依可見/可信資料作答、明確標示估算與不確定性、遵守疾病安全優先順序，並統一使用低溫度與 JSON 回應格式。
- 營養標示 OCR 現在明確區分每份與每 100 公克/毫升；若標示基準不明或文字不可讀，保留 `null` 並提示人工核對，不再鼓勵模型補猜數值。

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
