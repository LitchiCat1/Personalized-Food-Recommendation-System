# NutriLens Agent Update Brief

> Audience: future coding agents working inside this repository.
> Purpose: give a fast, source-of-truth handoff for the current `v0.0.3` workspace without reading the user-facing Word summary first.
> Date: 2026-07-11

## Read This First

This repository currently has a large uncommitted workspace. Do not assume the working tree is clean, and do not revert changes you did not make.

Current branch:

```text
v0.0.3
```

Current HEAD:

```text
dd9b6a4 add AI restaurant summaries
```

User-facing summary already created:

```text
docs/NutriLens_版本更新彙整_2026-07-11.docx
```

This Markdown file is for agents. It should be used as a handoff checklist before continuing implementation, testing, staging, or documentation cleanup.

## Hard Project Rules

- Follow `AGENTS.md` for frontend UI work. NutriLens is Figma-first.
- Preserve Expo Router tab route names: `index`, `scanner`, `recommend`, `history`, `profile`.
- Preserve product behavior, API contracts, data schema, Zustand state shape, and auth/user-scope assumptions unless the user explicitly asks for a breaking change.
- Shared UI components belong in `frontend/components/ui/`.
- Design tokens belong in `frontend/constants/theme.ts`.
- Do not add a UI kit package unless clearly justified.
- Use `@expo/vector-icons`, already present in the project.
- Nutrition numbers should use tabular number alignment where possible.
- Do not stage or commit secrets. Never print `.env.local` values.
- Do not stage `frontend/dist`, `node_modules`, `.env.local`, `frontend/.env.local`, `.agents/`, or `.opencode/`.

## Current Implementation Theme

The current version moves NutriLens toward:

```text
AI food safety radar for daily Taiwanese meals
```

The UI direction is a light, calm, data-dense graduation-demo health product, not the previous dark tech-card look and not a plain hospital form.

Primary demo story:

1. User sets health conditions and allergens in Profile.
2. User scans or manually records food in Scanner.
3. Dashboard shows today's nutrition state and sodium risk.
4. Recommend filters unsafe foods and finds nearby restaurants.
5. History shows seven-day calorie, sodium, and nutrient trends.

## Important New / Changed Files

Backend:

- `backend/app.py`
- `backend/config/disease_rules.json`
- `backend/config/allergen_taxonomy.json`
- `backend/services/disease_rule_service.py`
- `backend/services/medical_risk_service.py`
- `backend/services/open_food_facts_service.py`
- `backend/services/food_analysis_service.py`
- `backend/services/food_service.py`
- `backend/services/healthy_food_service.py`
- `backend/services/nutrition_label_service.py`
- `backend/services/profile_service.py`
- `backend/services/recommend_service.py`
- `backend/services/restaurant_ai_service.py`
- `backend/services/vision_food_service.py`
- `backend/repositories/storage.py`
- `backend/tests/test_api_routes.py`
- `backend/tests/test_services.py`

Frontend:

- `frontend/constants/theme.ts`
- `frontend/lib/api.ts`
- `frontend/store/useStore.ts`
- `frontend/app/_layout.tsx`
- `frontend/app/(tabs)/_layout.tsx`
- `frontend/app/(tabs)/index.tsx`
- `frontend/app/(tabs)/scanner.tsx`
- `frontend/app/(tabs)/recommend.tsx`
- `frontend/app/(tabs)/history.tsx`
- `frontend/app/(tabs)/profile.tsx`
- `frontend/components/AppContainer.tsx`
- `frontend/components/dashboard/CalorieRing.tsx`
- `frontend/components/dashboard/MealCard.tsx`
- `frontend/components/dashboard/NutrientBar.tsx`
- `frontend/components/scanner/ScannerManualTools.tsx`
- `frontend/components/scanner/ScannerResults.tsx`
- `frontend/components/ui/data-pill.tsx`
- `frontend/components/ui/metric-card.tsx`
- `frontend/components/ui/primary-button.tsx`
- `frontend/components/ui/progress-bar.tsx`
- `frontend/components/ui/screen-header.tsx`
- `frontend/components/ui/secondary-button.tsx`
- `frontend/components/ui/section-block.tsx`
- `frontend/components/ui/segmented-control.tsx`

Docs / coordination:

- `AGENTS.md`
- `docs/Multi_Agent_Collaboration_Plan.md`
- `docs/nutrilens-figma-redesign-brief.md`
- `docs/subagent-dispatch-mandate.md`
- `docs/subagent-scheduling-implementation-report.md`
- `docs/Project_Architecture_and_Status.md`
- `docs/NutriLens_版本更新彙整_2026-07-11.docx`
- `docs/NutriLens_Agent_Update_Brief_2026-07-11.md`

## Backend Summary

### Medical Metadata

New route:

```text
GET /medical-metadata
```

It returns:

- disease rule metadata
- allergen taxonomy
- shared medical disclaimer
- data source summary

Frontend Profile now prefers this endpoint to build condition/allergen option lists.

### Disease Rules

`backend/config/disease_rules.json` now uses stable English ids instead of Chinese object keys:

- `diabetes`
- `hypertension`
- `kidney_disease`
- `gout`
- `hyperlipidemia`

Rules now include governance and screening metadata such as:

- `id`
- `label_zh`
- `aliases`
- `category`
- `description`
- `screening_focus`
- `severity_options`
- `risk_nutrients`
- `rule_version`
- `review_status`
- `last_reviewed`
- `references`
- `medical_disclaimer`

### Allergen Taxonomy

New file:

```text
backend/config/allergen_taxonomy.json
```

It currently defines 10 allergen groups:

- peanut
- tree_nut
- milk
- egg
- soy
- wheat_gluten
- fish
- shellfish
- sesame
- sulfite

### Central Risk Engine

New service:

```text
backend/services/medical_risk_service.py
```

It centralizes:

- condition id normalization
- allergen id normalization
- allergen keyword/explicit matching
- GI blocking
- blocked labels
- blocked keywords
- nutrient caution/block thresholds
- risk messages for Scanner and Recommend

Recommendation and scanning safety warnings should use this shared service rather than reimplementing ad hoc checks.

### Storage / User Scope

`records.client_record_id` is now non-null and deduplicated by user. If the client does not send one, the server generates `server_record_<uuid>`.

`custom_foods` now uses:

```text
owner_key = user_id:food_id
```

This prevents different users' custom foods from overwriting or reading each other by `food_id` alone.

## Frontend Summary

### Theme

`frontend/constants/theme.ts` was changed from dark tech style to light health-product style.

Important tokens:

- light backgrounds
- green/blue/orange/purple/pink/cyan accents
- risk colors for sodium/allergen/condition warnings
- `Typography.number` for tabular nutrition numbers
- softer shadows

### Shared UI Components

New reusable components under `frontend/components/ui/`:

- `DataPill`
- `MetricCard`
- `PrimaryButton`
- `SecondaryButton`
- `ScreenHeader`
- `SectionBlock`
- `SegmentedControl`
- `ProgressBar`

Prefer these before adding one-off cards/buttons/chips in route files.

### Dashboard

`frontend/app/(tabs)/index.tsx`

Now emphasizes:

- today's nutrition state
- remaining calories
- sodium risk
- backend sync status
- scan CTA
- BMR/TDEE/current intake metrics
- nutrient progress
- meal timeline with warnings

### Scanner

`frontend/app/(tabs)/scanner.tsx`

Now emphasizes:

- scan/photo/manual/OCR flow
- health condition and allergen context
- pending record sync status
- portion correction
- rejected low-confidence detections
- OCR custom food save / quick add
- manual TFDA/custom food fallback

`ScannerResults` and `ScannerManualTools` were also restyled and simplified.

### Recommend

`frontend/app/(tabs)/recommend.tsx`

Now emphasizes:

- remaining calories
- number of filtered unsafe items
- safe recommendation count
- medical risk / safety badges
- preference and feedback reasons
- feedback actions: accepted/skipped/disliked
- nearby restaurant discovery through Google Places
- map selection / navigation / AI restaurant summary

Remember: Google Places does not provide reliable nutrition. The UI must keep explaining that nutrition must be confirmed by scanning or manual search.

### History

`frontend/app/(tabs)/history.tsx`

Now emphasizes:

- seven-day summary
- average calories
- total records / recorded days
- sodium-over-limit day count
- calorie bar chart
- nutrient weekly averages
- sodium risk trend
- concise insight notes

### Profile

`frontend/app/(tabs)/profile.tsx`

Now emphasizes:

- backend medical metadata loading
- profile sync banner
- account card
- BMR/TDEE/BMI and goal metrics
- modal profile editing
- validated profile draft
- condition catalog from `/medical-metadata`
- allergen catalog from `/medical-metadata`
- medical disclaimer
- Supabase sign-out handling

## Verification Snapshot

These commands were run successfully after the current implementation state and before this agent Markdown was added:

```powershell
cd backend
python -m unittest discover -s tests -p "test_*.py"
```

Result:

```text
Ran 29 tests in 3.605s
OK
```

```powershell
cd frontend
npm run typecheck
```

Result:

```text
tsc --noEmit passed
```

```powershell
cd frontend
npm run lint
```

Result:

```text
expo lint passed
```

```powershell
cd frontend
npm run build:web
```

Result:

```text
Expo exported static web output to dist
13 static routes exported
```

If making any further code changes, rerun the relevant subset. If touching frontend, rerun at least:

```powershell
cd frontend
npm run typecheck
npm run lint
npm run build:web
```

If touching backend, rerun:

```powershell
cd backend
python -m unittest discover -s tests -p "test_*.py"
```

## Known Handoff Notes

- `docs/nutrilens-figma-redesign-brief.md` says Gate 4 was not started when that brief was written. The current workspace has since implemented a large Expo UI translation. Update that brief before treating it as final project status.
- Terminal output may show mojibake for Chinese filenames/text. Validate with Unicode-aware reads rather than trusting PowerShell display.
- Use quoted paths or `-LiteralPath` for paths containing `(tabs)`.
- The working tree contains generated/untracked files besides this brief. Inspect before staging.
- `frontend/dist` may be regenerated by `npm run build:web`; do not stage it unless the user explicitly wants deploy artifacts.
- The Word document in `docs/` is user-facing. This file is agent-facing and can be terse/operational.

## Suggested Next Agent Actions

1. Run `git status --short` and decide with the user what should be staged.
2. Update `docs/nutrilens-figma-redesign-brief.md` Gate 4 if preparing a formal closeout.
3. Do a manual UI smoke pass on Dashboard, Scanner, Recommend, History, and Profile.
4. Confirm no secret or local env values are included in staged files.
5. Re-run backend/frontend verification after any additional code edits.

## Current `git diff --stat` Snapshot

```text
.gitignore                                         |   4 +
backend/app.py                                     |  31 +-
backend/config/disease_rules.json                  | 145 +++-
backend/repositories/storage.py                    |  84 +-
backend/services/disease_rule_service.py           | 139 +++-
backend/services/food_analysis_service.py          |  65 +-
backend/services/food_service.py                   |  29 +-
backend/services/healthy_food_service.py           |  38 +-
backend/services/nutrition_label_service.py        |   1 +
backend/services/profile_service.py                |  15 +-
backend/services/recommend_service.py              | 135 ++--
backend/services/restaurant_ai_service.py          |  25 +
backend/services/vision_food_service.py            |  31 +-
backend/tests/test_api_routes.py                   | 156 ++--
backend/tests/test_services.py                     | 237 +++---
docs/Project_Architecture_and_Status.md            |  62 +-
frontend/app/(tabs)/_layout.tsx                    |   6 +-
frontend/app/(tabs)/history.tsx                    | 282 +++----
frontend/app/(tabs)/index.tsx                      | 297 +++----
frontend/app/(tabs)/profile.tsx                    | 811 +++++++++----------
frontend/app/(tabs)/recommend.tsx                  | 867 ++++++++-------------
frontend/app/(tabs)/scanner.tsx                    | 381 +++------
frontend/app/_layout.tsx                           |  15 +-
frontend/components/AppContainer.tsx               |   8 +-
frontend/components/dashboard/CalorieRing.tsx      |  55 +-
frontend/components/dashboard/MealCard.tsx         | 125 ++-
frontend/components/dashboard/NutrientBar.tsx      |  80 +-
frontend/components/scanner/ScannerManualTools.tsx | 107 ++-
frontend/components/scanner/ScannerResults.tsx     | 256 +++---
frontend/constants/theme.ts                        | 141 ++--
frontend/lib/api.ts                                |  63 ++
frontend/store/useStore.ts                         |   4 +-
32 files changed, 2232 insertions(+), 2463 deletions(-)
```
