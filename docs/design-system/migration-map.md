# CiteLadder UI Design-System — Migration & Convergence Plan

> **Authoritative Phased Execution Plan**
> **Status**: Implementation-Ready Sequence
> **Date**: August 2026
> **Execution Rule**: Implement in numbered phase order. Run repository validation gates (`.\scripts\check.ps1` and `.\scripts\test.ps1`) after completing each phase.

---

## 1. Phased Delivery Roadmap

```text
Phase 0: Token & CSS Bridge Hardening
  └── Phase 1: Core Form Controls & Actions (Button, Input, Checkbox, Radio, Switch, Field)
        └── Phase 2: Overlays & Floating Surfaces (Dialog, Drawer, Dropdown, Popover, Tooltip, Toast)
              └── Phase 3: Navigation, Tabs & Toolbars (Tabs, NestedTabs, SegmentedControl, AnalyticsToolbar)
                    └── Phase 4: Data Display & Metrics (Badge, FilterChip, ChoiceChip, Card, Table, ScoreRing, Progress)
                          └── Phase 5: Feedback & Status States (Alert, EmptyState, Skeleton, UnavailableValue)
                                └── Phase 6: Surface Harmonization (Auth, Onboarding, Workspaces)
                                      └── Phase 7: Deprecations, Raw Bypasses & Final Gate Verification
```

---

## 2. Phase-by-Phase Execution Checklist

---

### Phase 0: Design Tokens & CSS Bridge Hardening
**Objective**: Guarantee that all theme custom properties, radii, and multi-slot class variance helpers are firmly locked and verified by AST policy scripts.

- [ ] **CSS Variables & Radii Verification**:
  - Verify `--radius-control: 6px`, `--radius-card: 8px`, `--radius-overlay: 10px` in `frontend/app/globals.css`.
  - Verify shadow tokens (`--shadow-card`, `--shadow-dropdown`, `--shadow-overlay`).
- [ ] **Class Variance Authority (CVA) Utilities**:
  - Verify CVA helper typings in `frontend/components/ui/*-variants.ts`.
- [ ] **AST Policy Check Alignment**:
  - Run `node frontend/scripts/check-design-system.mjs` to establish clean baseline.

---

### Phase 1: Core Form Controls & Actions
**Objective**: Eliminate raw input bypasses and modernize core action/input primitives with multi-slot anatomy.

- [ ] **`Button` & `Pressable` (`components/ui/button.tsx`, `pressable.tsx`)**:
  - Add optional `startContent` and `endContent` slots.
  - Refine loading spinner alignment.
  - Ensure 6px radius and focus-visible ring (`focus-visible:ring-1 focus-visible:ring-accent`).
- [ ] **`Input` & `Textarea` (`components/ui/input.tsx`)**:
  - Add `startContent` (e.g. prefix icons, currency symbols) and `endContent` (e.g. clear button, visibility toggles).
  - Split `Textarea` into a dedicated file `components/ui/textarea.tsx`.
- [ ] **`SearchField` (`components/ui/search-field.tsx`)**:
  - Standardize search icon `startContent`, loading indicator, and `clearButton` end trigger.
- [ ] **`Field` (`components/ui/field.tsx`)**:
  - Standardize accessible `label`, `description`, and `errorMessage` slot layout.
- [ ] **`Checkbox` (`components/ui/checkbox.tsx`)**:
  - Verify Radix `@radix-ui/react-checkbox` wrapping and 4px radius.
  - Replace raw `<input type="checkbox">` in:
    - `components/prompts/prompt-form-dialog.tsx`
    - `components/runs/audit-schedules.tsx`
    - `components/products/catalog-list.tsx`
- [ ] **`RadioGroup` (`components/ui/radio-group.tsx`)**:
  - Re-align with `@radix-ui/react-radio-group` and support chip variant.
- [ ] **`Switch` (`components/ui/switch.tsx`)**:
  - Refine sliding thumb geometry (5px track height, 4px thumb, smooth transform transition).

---

### Phase 2: Overlays & Floating Surfaces
**Objective**: Standardize dialog, drawer, dropdown, and tooltip slot structures and backdrop elevations.

- [ ] **`Dialog` (`components/ui/dialog.tsx`)**:
  - Standardize `DialogHeader`, `DialogBody`, `DialogFooter` structure.
  - Maintain `@radix-ui/react-dialog` focus trap and backdrop blur (`backdrop-blur-xs`).
- [ ] **`Drawer` (`components/ui/drawer.tsx`)**:
  - Standardize right-side slide-over panel with header, scrollable body, and action footer.
- [ ] **`Dropdown` (`components/ui/dropdown.tsx`)**:
  - Add `DropdownSection` for labeled command groupings.
  - Standardize menu item padding (`px-2.5 py-1.5 text-sm`) and hover background (`bg-active`).
- [ ] **`Popover` & `Tooltip` (`components/ui/popover.tsx`, `tooltip.tsx`)**:
  - Verify inverse high-contrast dark tooltip styling (`bg-foreground text-background`).
- [ ] **`Toast` (`components/ui/toast.tsx`)**:
  - Expand `useToast` to support tone variants (`info`, `success`, `warning`, `danger`).

---

### Phase 3: Navigation, Tabs & Toolbars
**Objective**: Harmonize tab indicators, segmented controls, and analytics toolbars.

- [ ] **`Tabs` & `NestedTabs` (`components/ui/tabs.tsx`, `nested-tabs.tsx`)**:
  - Standardize underline active indicator transition (2px accent bar).
  - Add badge slot support for tab counters.
- [ ] **`SegmentedControl` (`components/ui/segmented-control.tsx`)**:
  - Align sliding pill highlight easing with HeroUI Solid Tabs.
- [ ] **`AnalyticsToolbar` (`components/ui/analytics-toolbar.tsx`)**:
  - Lock standard spacing, date picker dropdown, and fetch indicator alignment.

---

### Phase 4: Data Display, Metrics & Badges
**Objective**: Consolidate badges, chips, cards, tables, and metric visualizations.

- [ ] **`Badge`, `FilterChip` & `ChoiceChip` (`components/ui/badge.tsx`, `filter-chip.tsx`, `choice-chip.tsx`)**:
  - Maintain discriminated union WCAG color+dot requirement for `Badge`.
  - Standardize `FilterChip` tabular count badge and toggle behavior.
  - Create canonical `frontend/components/ui/choice-chip.tsx` primitive supporting single-select and multi-select pill geometries, keyboard navigation (Arrow keys/Space/Enter), and focus rings.
  - Migrate consumers in `frontend/components/onboarding/choice-controls.tsx` to the canonical `components/ui/choice-chip.tsx` primitive.
  - Validate accessibility, state attributes (`aria-pressed` / `aria-checked`), and visual consistency.
- [ ] **`Card` (`components/ui/card.tsx`)**:
  - Lock standard slots: `CardHeader`, `CardTitle`, `CardDescription`, `CardEyebrow`, `CardContent`.
  - Apply 8px card radius (`rounded-md`) and `--shadow-card`.
- [ ] **`Table` & `Pagination` (`components/ui/table.tsx`, `table-pagination.tsx`, `cursor-pager.tsx`)**:
  - Ensure sticky header backdrop-blur and responsive card transformation.
  - Standardize pagination footer typography and button sizes.
- [ ] **`ScoreRing`, `ScoreBar`, `ActivityProgress`**:
  - Verify SVG stroke math and color band mappings (`score-high`, `score-medium`, `score-low`).

---

### Phase 5: Feedback & Status States
**Objective**: Consolidate empty states and streamline feedback alerts.

- [ ] **`Alert` & `MutationNotice` (`components/ui/alert.tsx`, `mutation-notice.tsx`)**:
  - Standardize tone icons and action button layout.
- [ ] **`EmptyState` (`components/ui/empty-state.tsx`)**:
  - **Step 1 — Canonical API Enhancement**: Update `frontend/components/ui/empty-state.tsx` to support the complete slot anatomy: `icon` (Lucide icon component), `heading` (string), `description` (string or ReactNode), `action` (ReactNode CTA button/trigger), and optional `footnote` (string or ReactNode).
  - **Step 2 — Consumer Migration**: Migrate every consumer of feature-specific empty states to `frontend/components/ui/empty-state.tsx`, preserving all required action buttons, event handlers, and descriptive copy:
    - Migrate callers of `frontend/components/visibility/empty-state.tsx`
    - Migrate callers of `frontend/components/prompts/prompt-empty-state.tsx`
    - Migrate callers of `frontend/components/traffic/empty-state.tsx`
    - Migrate callers of `frontend/components/ai-referrals/empty-state.tsx`
    - Migrate callers of `frontend/components/settings/integrations-empty-state.tsx`
  - **Step 3 — Delete Feature Implementations**: Once all callers have been safely migrated and verified by tests, delete the 5 redundant feature-specific files (`components/visibility/empty-state.tsx`, `components/prompts/prompt-empty-state.tsx`, `components/traffic/empty-state.tsx`, `components/ai-referrals/empty-state.tsx`, `components/settings/integrations-empty-state.tsx`).
- [ ] **`Skeleton` (`components/ui/skeleton.tsx`)**:
  - Provide convenient skeleton presets (e.g. `SkeletonText`, `SkeletonAvatar`, `SkeletonCard`).

---

### Phase 6: Surface Harmonization
**Objective**: Propagate modernized primitives across all product surfaces.

- [ ] **Authentication Surface (`components/auth/`)**:
  - Replace raw `<button>` password toggle in `auth-form.tsx` with `Input` end content slot.
- [ ] **Onboarding Surface (`components/onboarding/`)**:
  - Migrate `ChoiceChip` and `ToggleChip` in `choice-controls.tsx` to use the canonical `frontend/components/ui/choice-chip.tsx` primitive.
- [ ] **Feature Workspaces (`components/site-health/`, `visibility/`, `demand/`, `products/`, `runs/`, `settings/`)**:
  - Replace remaining raw inputs in `catalog-list.tsx`, `audit-schedules.tsx`, and `billing-settings.tsx`.
  - Replace raw search inputs with `SearchField`.

---

### Phase 7: Deprecations, Raw Cleanups & Validation Gates
**Objective**: Delete dead code and pass the full static and runtime verification suite.

- [ ] **Delete Obsolete Files & Update Design-System Inventory**:
  - Delete `frontend/components/ui/donut.tsx` (dead chart prototype).
  - Remove/archive the unused `DonutChart` entries from `component-map.json` and `component-map.md` upon deleting `donut.tsx`.
  - Run a stale-reference check (e.g. `rg -i "donut\.tsx|DonutChart" frontend/ docs/design-system/`) to verify that the design-system inventory and codebase no longer reference the deleted component.
- [ ] **AST Design System Verification**:
  - Run `node frontend/scripts/check-design-system.mjs`.
  - Run `node frontend/scripts/design-system-source-checks.mjs`.
- [ ] **Full Repository Validation**:
  - Run `.\scripts\check.ps1` (Ruff, Mypy, Oxlint, TypeScript `tsc --noEmit`, API contract, Complexity checks).
  - Run `.\scripts\test.ps1` (Affected backend & frontend vitest suites).

---

## 3. Verification & Gate Criteria

Every PR implementing a phase from this migration map must satisfy:
1. **Zero New Dependencies**: `pnpm list` must show no HeroUI or React Aria packages added.
2. **Zero Radix Leaks**: Direct imports from `@radix-ui/*` must remain 0 outside `frontend/components/ui/`.
3. **Zero Raw Element Bypasses**: No native `<input type="checkbox">`, un-boxed alerts, or raw buttons outside design system primitives.
4. **Clean Static Gates**: `.\scripts\check.ps1` passes with 0 lint, type, or AST check failures.
5. **Clean Test Suite**: `.\scripts\test.ps1` passes with all component and unit tests green.
