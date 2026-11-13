# NutriLens Figma Redesign Brief

## Current Figma File

- File name: `NutriLens Mobile App Redesign`
- File key: `ON5Rvv1Qt9EIyWd3CDsOFo`
- File URL: https://www.figma.com/design/ON5Rvv1Qt9EIyWd3CDsOFo
- Created: 2026-06-18
- Figma account: `LitchiCat`

## Gate Status

- Gate 1: Passed. `codex mcp list` shows `figma` enabled with bearer-token auth.
- Gate 2: Passed. New Figma design file was created.
- Gate 3: Passed. Five 390x844 mobile app screen frames were created and validated with Figma screenshots.
- Gate 4: Passed. The Expo implementation has translated the five Figma app screens into the current tab UI while preserving route names and existing data flow.

Note: the active Figma plan is Starter and allows three pages. The design is therefore organized into three pages instead of the original six-page wish list.

## Figma Page Structure

1. `00 Design Tokens`
2. `01 Component Library`
3. `02 App Screens`

## Created Screen Frames

Mobile app frames are 390x844 and use the `v0.0.3 Mobile` prefix:

- `v0.0.3 Mobile / 01 Dashboard`
- `v0.0.3 Mobile / 02 Scanner`
- `v0.0.3 Mobile / 03 Recommend`
- `v0.0.3 Mobile / 04 History`
- `v0.0.3 Mobile / 05 Profile`

Desktop Web frames are 1280x800 and use the `v0.0.3 Web` prefix:

- `v0.0.3 Web / 01 Dashboard`
- `v0.0.3 Web / 02 Scanner`
- `v0.0.3 Web / 03 Recommend`
- `v0.0.3 Web / 04 History`
- `v0.0.3 Web / 05 Profile`

The `02 App Screens` page also includes `v0.0.3 Responsive UI Specification` for 375, 390, 430, 768, and 1280 widths. Mobile and tablet retain bottom tabs; desktop Web uses a persistent sidebar and multi-column task layouts.

## Design Thesis

"AI food safety radar for daily Taiwanese meals."

The first viewport uses a scan/radar nutrition card motif to show food recognition, sodium risk, protein status, meal count, and scan CTA. The visual direction is light, data-rich, and demo-ready rather than a generic medical dashboard.

## Visual System

Core palette:

- Rice paper: `#F7FAF4`
- Card white: `#FFFFFF`
- Ink leaf: `#14201B`
- Tea text: `#40524A`
- Radar green: `#1F9D72`
- Data blue: `#2F80ED`
- Guava pink: `#D95F8D`
- Soy amber: `#B66A18`
- Risk red: `#E25555`
- Fiber cyan: `#1496A6`

Typography:

- Inter Extra Bold for numeric readouts and screen titles.
- Inter Bold/Medium/Regular for labels, UI text, and dense data surfaces.
- Implementation should use tabular number alignment for kcal, g, mg, percentages, and scores.

Signature components:

- Radar nutrition card
- Scan viewfinder with bounding boxes
- Risk chips
- Nutrition metric cards
- Recommendation match card
- Map/list recommendation card
- Seven-day trend chart
- Profile safety filter chips

## Screen Notes

### Dashboard

First viewport shows today's food safety radar, calories, sodium risk, scan CTA, safety alerts, and recent meals. BMR/TDEE are kept in the profile instead of the primary dashboard flow.

### Scanner

Shows a dark camera viewfinder only inside the scanning surface, bounding boxes for recognized food, confidence labels, a sodium flag, recognition results, and an add-to-record CTA.

### Recommend

Shows remaining calories, filtered unsafe items, match score, nearby restaurant map pins, walking route, safe restaurant selection, and a top recommendation with nutrition metrics.

### History

Shows seven-day averages, calorie goal band, sodium risk trend, and concise demo notes for live presentation.

### Profile

Shows account summary, BMR/TDEE/BMI metrics, health-condition filters, allergen/safety chips, nutrition targets, and save profile CTA.

## Implementation Status

The `v0.0.3` Figma handoff has been implemented in the Expo app:

1. Figma tokens are represented in `frontend/constants/theme.ts`.
2. Shared UI components were added under `frontend/components/ui/`.
3. Feature components remain under their feature folders.
4. API calls, Zustand state shape, data schema, and Expo Router tab route names were preserved:
   - `index`
   - `scanner`
   - `recommend`
   - `history`
   - `profile`
5. The implementation uses existing Expo/React Native primitives and `@expo/vector-icons`; no new UI kit was added.
6. Latest verification commands for this UI pass:
   - `cd frontend && npm run typecheck`
   - `cd frontend && npm run lint`
   - `cd frontend && npm run build:web`
7. Desktop Web uses a 1280px application shell with persistent navigation at 1024px and above; mobile and tablet controls remain width-adaptive with 44px minimum touch targets.
