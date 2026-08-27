# NutriLens UI Rules

These rules apply to frontend UI work for this Expo React Native project.

## Current Direction

- Treat the current Expo implementation, design tokens, shared components, and recorded Figma redesign as the baseline design system.
- Make incremental UI changes directly in Expo when they preserve the established visual language and product behavior. Figma may be used for larger redesigns, but it is not a prerequisite for implementation.
- Preserve product behavior, API contracts, data schema, Zustand state shape, and Expo Router tab route names:
  - `index`
  - `scanner`
  - `recommend`
  - `history`
  - `profile`

## Required UI Workflow

Before modifying UI code:

1. Inspect the affected route, shared components, design tokens, data source, and responsive behavior.
2. Keep domain decisions in typed helpers or services instead of embedding them in route-level presentation code.
3. Implement with the existing Expo/React Native primitives and shared design tokens.
4. Validate the rendered result at mobile and desktop widths. Check text wrapping, touch targets, overflow, loading, empty, error, and data-driven states that the change affects.
5. Verify with:
   - `cd frontend && npm run typecheck`
   - `cd frontend && npm run lint`
   - `cd frontend && npm run build:web`

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

## UI Implementation Gates

Gate 1: Context understood

- Identify the affected data contract and reuse the existing source of truth.
- Confirm unrelated behavior, route names, and state shape remain stable.

Gate 2: Responsive implementation

- Design for 390x844 first and ensure the layout adapts to 375, 430, 768, and centered desktop web.
- Reuse `frontend/constants/theme.ts` and shared UI components.

Gate 3: Rendered validation

- Start the Expo web app and inspect the changed state at representative mobile and desktop widths.
- Capture local screenshots when visual behavior changes and check for clipping, overlap, unreadable contrast, and unstable layout.

Gate 4: Code verification

- Run typecheck, lint, and the web export before considering the UI change complete.
