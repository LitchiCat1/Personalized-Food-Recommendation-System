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
- Gate 4: Not started. Expo implementation should begin only after reviewing the Figma design.

Note: the active Figma plan is Starter and allows three pages. The design is therefore organized into three pages instead of the original six-page wish list.

## Figma Page Structure

1. `00 Design Tokens`
2. `01 Component Library`
3. `02 App Screens`

## Created Screen Frames

All app frames are 390x844:

- `01 Dashboard`
- `02 Scanner`
- `03 Recommend`
- `04 History`
- `05 Profile`

The `02 App Screens` page also includes `Responsive implementation notes` for 375, 390, 430, 768, and centered desktop web adaptation.

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

First viewport shows today's food safety radar, calories, sodium risk, protein status, meal count, scan CTA, BMR/TDEE/sodium metrics, and a meal timeline.

### Scanner

Shows a dark camera viewfinder only inside the scanning surface, bounding boxes for recognized food, confidence labels, a sodium flag, recognition results, and an add-to-record CTA.

### Recommend

Shows remaining calories, filtered unsafe items, match score, nearby restaurant map pins, walking route, safe restaurant selection, and a top recommendation with nutrition metrics.

### History

Shows seven-day averages, calorie goal band, sodium risk trend, and concise demo notes for live presentation.

### Profile

Shows account summary, BMR/TDEE/BMI metrics, health-condition filters, allergen/safety chips, nutrition targets, and save profile CTA.

## Implementation Handoff

When implementing the Expo UI:

1. Translate these Figma tokens into `frontend/constants/theme.ts`.
2. Build shared UI components in `frontend/components/ui/`.
3. Keep feature components under their feature folders.
4. Preserve API calls, Zustand state shape, data schema, and Expo Router tab route names:
   - `index`
   - `scanner`
   - `recommend`
   - `history`
   - `profile`
5. Use `@expo/vector-icons`; do not add a new UI kit.
6. Verify with:
   - `cd frontend && npm run typecheck`
   - `cd frontend && npm run lint`
   - `cd frontend && npm run web`
