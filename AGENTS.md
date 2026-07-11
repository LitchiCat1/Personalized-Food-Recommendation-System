# NutriLens Figma-First UI Rules

These rules apply to frontend UI work for this Expo React Native project.

## Current Direction

- The existing app UI is considered disposable. Do not treat the current visual styling as the target design.
- Generate the next UI in Figma first, then implement the Expo screens from that Figma source of truth.
- Preserve product behavior, API contracts, data schema, Zustand state shape, and Expo Router tab route names:
  - `index`
  - `scanner`
  - `recommend`
  - `history`
  - `profile`

## Required Figma Workflow

Before modifying UI code from a design:

1. Confirm Figma MCP tools are available in the active Codex session.
2. If creating a new file, use `figma-create-new-file` / `create_new_file`.
3. Use `figma-use` and `figma-generate-design` for Figma canvas writes.
4. Build the Figma design as a mobile-first app system:
   - Design tokens page
   - Component library page
   - Five app screen frames
   - Optional presentation/demo flow frame
5. Validate with Figma screenshots before implementing code.
6. Implement the Expo UI by translating the Figma frames into React Native components and StyleSheet tokens.
7. Verify with:
   - `cd frontend && npm run typecheck`
   - `cd frontend && npm run lint`
   - `cd frontend && npm run web`

If Figma tools are unavailable, stop before UI implementation and fix MCP/plugin loading first.

## Project Styling Conventions

- Use `frontend/constants/theme.ts` for color, spacing, typography, radius, and elevation tokens.
- Shared components belong in `frontend/components/ui/`.
- Feature components stay under their feature directories, such as:
  - `frontend/components/dashboard/`
  - `frontend/components/scanner/`
  - `frontend/components/maps/`
- Route files under `frontend/app/(tabs)/` should orchestrate data and layout, not contain large reusable component definitions unless tightly route-specific.
- Use Expo/React Native primitives and existing dependencies. Do not add a UI kit package unless it is clearly justified.
- Use `@expo/vector-icons` already present in the project; do not add another icon package.
- Use tabular number alignment for nutrition numbers: kcal, g, mg, percentages, scores.
- Touch targets must be at least 44px.
- Avoid visible instructional copy that explains app features instead of helping the user complete the task.

## New Visual Direction

The next design should not be a generic medical dashboard. It should feel like a polished graduation-demo health product with a distinctive food intelligence identity.

Design thesis:

- "AI food safety radar for daily Taiwanese meals."
- The signature element should be a scan/radar nutrition card motif: food recognition, health filtering, and recommendation confidence should be visible in the first viewport.
- Use a light base, but allow controlled contrast and vivid data accents. Avoid the previous dark-tech-card look and avoid a plain hospital form look.

Preferred traits:

- Mobile-first, dense but calm.
- High confidence data surfaces.
- Food imagery or food-shaped visual cues where useful.
- Clear risk colors for sodium/allergen/condition warnings.
- UI suitable for live demo: scanner, safety filtering, nutrition tracking, map recommendation, Supabase/Render integration should be obvious.

## Figma Implementation Gates

Gate 1: MCP available

- `codex mcp list` must show `figma` enabled.
- Active Codex tools must include Figma tools such as `use_figma`, `create_new_file`, `get_metadata`, `get_screenshot`, or `generate_figma_design`.

Gate 2: Figma file created

- Create or select one Figma file for `NutriLens Mobile App Redesign`.
- Record the file URL or file key in `docs/nutrilens-figma-redesign-brief.md`.

Gate 3: Figma screens created

- Create frames for 390x844 and ensure responsive rules can adapt to 375, 430, 768, and centered desktop web.
- Required screen frames:
  - `01 Dashboard`
  - `02 Scanner`
  - `03 Recommend`
  - `04 History`
  - `05 Profile`

Gate 4: Code implementation

- Replace current UI implementation only after screenshots/design context exist.
- Keep route names and data flow stable.
