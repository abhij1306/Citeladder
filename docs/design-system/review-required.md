# CiteLadder UI Design-System — Decisions & Review Required

> **Architectural Decisions & Judgment Calls for Engineering Review**
> **Status**: Open Architectural Decisions & Trade-Offs
> **Date**: August 2026

This document records the specific architectural decisions, trade-offs, and boundary judgments identified during the design-system audit. Each item outlines the context, options, trade-offs, and recommended path forward.

---

## 1. Decision Items

---

### Item 1: `Switch` Implementation — Native Button vs `@radix-ui/react-switch`

- **Context**:
  CiteLadder's `frontend/components/ui/switch.tsx` is currently implemented as a native `<button role="switch" aria-checked={checked}>` with a sliding thumb `<span>`. It has 2 consumers. In `@radix-ui/react-checkbox`, `@radix-ui/react-dialog`, etc., Radix is installed, but `@radix-ui/react-switch` is not in `package.json`.
- **Options**:
  - **Option A (Recommended)**: Retain the lightweight native button implementation with HeroUI-inspired track and thumb CSS transition geometry. It requires zero new dependencies, handles `Enter` and `Space` natively, and provides exact control over the 16px/24px pill radius.
  - **Option B**: Add `@radix-ui/react-switch` to `package.json` to unify headless state management with other form controls.
- **Trade-offs**: Option A avoids package churn for a 20-line component. Option B ensures Radix form integration (hidden `<input>` for native form submission).
- **Recommendation**: **Option A (Retain Native Button + HeroUI Track/Thumb Geometry)**.

---

### Item 2: Empty State Consolidation Strategy

- **Context**:
  There is a canonical `frontend/components/ui/empty-state.tsx` (used by 6 consumers). However, five feature folders have built their own ad-hoc empty state components:
  1. `frontend/components/visibility/empty-state.tsx`
  2. `frontend/components/prompts/prompt-empty-state.tsx`
  3. `frontend/components/traffic/empty-state.tsx`
  4. `frontend/components/ai-referrals/empty-state.tsx`
  5. `frontend/components/settings/integrations-empty-state.tsx`
- **Options**:
  - **Option A (Recommended)**: Delete all 5 feature-specific empty states and consolidate onto `components/ui/empty-state.tsx`. Enhance `EmptyState` props to support `icon`, `heading`, `description`, `action` (ReactNode), and optional `footnote`.
  - **Option B**: Keep domain empty states as domain wrappers around `components/ui/empty-state.tsx`.
- **Trade-offs**: Option A eliminates ~250 lines of duplicate UI boilerplate and enforces visual unity across all empty screens. Option B allows localized helper props.
- **Recommendation**: **Option A (Delete domain empty states; consolidate onto canonical primitive)**.

---

### Item 3: Multi-Select, Combobox & Tag Filter Ergonomics

- **Context**:
  CiteLadder currently handles multi-selection in two distinct ways:
  1. **Chip Toggles**: Onboarding (`choice-controls.tsx`) uses `ToggleChip` and `ChoiceChip` with `aria-pressed` or hidden radio buttons.
  2. **Table / Bulk Row Selection**: Feature tables (e.g. `products/catalog-list.tsx`, `prompts/page.tsx`) use checkboxes.
- **Options**:
  - **Option A (Recommended)**: Formalize `FilterChip` and `ChoiceChip` into `components/ui/` as first-class primitives for keyword and category selection, while standardizing table row selection on canonical `Checkbox`.
  - **Option B**: Introduce a heavy Combobox / MultiSelect dropdown primitive wrapping `@radix-ui/react-popover`.
- **Trade-offs**: Option A matches the existing UI design language where filtering occurs directly on visible chips rather than hidden inside multi-select dropdown menus.
- **Recommendation**: **Option A (Formalize visible Chip primitives + standard Checkbox)**.

---

### Item 4: Table Implementation — Semantic HTML vs Virtualized Headless Grid

- **Context**:
  `frontend/components/ui/table.tsx` uses semantic HTML (`<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`) with sticky headers, tabular numerals, 2px bottom under-rules, and responsive card transformation on mobile. Tables are paginated via `TablePagination` (page offsets) or `CursorPager` (keyset cursors) capping rendered rows to <= 50 items.
- **Options**:
  - **Option A (Recommended)**: Retain semantic HTML `Table` + `useTablePage` / `CursorPager`. 50-row pages render instantly without virtualization overhead, maintain native browser accessibility, and preserve standard text selection.
  - **Option B**: Introduce TanStack Table or virtualized DOM rendering (`react-window`).
- **Trade-offs**: Option A is lightweight, highly accessible, and does not require a heavyweight table runtime. Option B introduces complexity unneeded for 50-item paginated lists.
- **Recommendation**: **Option A (Retain Semantic Table + Paginated Limits)**.

---

### Item 5: Motion & Transition Boundaries

- **Context**:
  CiteLadder separates UI motion into two tiers:
  1. **Marketing & Auth**: Framer Motion and GSAP for entrance effects and ambient glow ribbons (`frontend/components/auth/brand-panel.tsx`).
  2. **Product Interface**: Fast, deterministic CSS transitions (`frontend/app/ui-motion.css`) with duration `150ms` and `ease-out`, respecting `prefers-reduced-motion`.
- **Options**:
  - **Option A (Recommended)**: Maintain this strict separation. The product application interface should use CSS transitions limited to compositor-friendly properties such as `transform` and `opacity`, respect reduced-motion preferences, and avoid inflating bundle size.
  - **Option B**: Expand Framer Motion into `components/ui/` primitives (e.g. dialogs, dropdowns).
- **Trade-offs**: Option A reduces runtime JavaScript and avoids transitioning layout-affecting properties; performance benefits must still be confirmed through profiling. Option B introduces additional runtime JavaScript overhead.
- **Recommendation**: **Option A (Keep CSS-only transitions in product UI; restrict motion libraries to marketing/canvas)**.

---

### Item 6: Form & Validation Standard

- **Context**:
  Most forms (e.g. `PromptFormDialog`, `BrandStage`, `AuthForm`) use `react-hook-form` + `zodResolver`. A few isolated forms (e.g. `audit-schedules.tsx`, `billing-settings.tsx`) use local `useState` hooks.
- **Options**:
  - **Option A (Recommended)**: Standardize all multi-field interactive dialogs and forms on `react-hook-form` + `zod` schemas, wrapping inputs in `Field` for consistent error messages.
  - **Option B**: Allow ad-hoc `useState` in smaller single-field controls.
- **Trade-offs**: Option A ensures consistent validation, keyboard submission, and error focus handling across the entire app.
- **Recommendation**: **Option A (Standardize all form dialogs on react-hook-form + zod)**.

---

### Item 7: Unused Component Deletions (`donut.tsx`)

- **Context**:
  `frontend/components/ui/donut.tsx` has **0 consumers** across the codebase. `ScoreRing` (SVG circle) and `TrendChart` (time series) own all production data visualization.
- **Recommendation**: **Delete `frontend/components/ui/donut.tsx` during Phase 7 cleanup**.
