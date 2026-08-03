# Changelog

## v0.0.6 - 2026-08-03

### Added

- Added editable nutrition-label food names with whitespace validation and persisted final values.
- Added idempotent dietary record saves, visible success/error feedback, and a retryable local synchronization queue.
- Added authenticated record-backed dietary trends with same-day aggregation and latest continuous seven-day selection.
- Added a dashboard dietary record manager with inclusive date ranges, responsive record lists, editing, deletion confirmation, and error recovery.
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
