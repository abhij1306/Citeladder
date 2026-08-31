# CiteLadder Design System — Surface Improvement Map

> Implementation guide identifying surface-specific visual inconsistencies, layout gaps, and HeroUI-inspired structural improvements across all 10 major CiteLadder surfaces.
>
> **Scope Rule**: This document details ONLY the visual and layout refinements that remain on surfaces *after* canonical UI primitives have been upgraded. It preserves all query logic, state machines, routes, and data pipelines.

---

## 1. Authentication (`(auth)/login`, `auth-form.tsx`, `brand-panel.tsx`)

### Current Visual Gaps & Debt
- **Raw Password Toggle**: `frontend/components/auth/auth-form.tsx` uses a raw `<button type="button">` with inline eye icon instead of a slot-enabled input or standard ghost button.
- **Form Card Framing**: The login card on the right column lacks a subtle card border on light mode, relying on page background contrast.
- **Brand Panel Ribbon Drift**: `BrandCanvas` glow ribbons have hardcoded pixel widths (`w-[600px]`, `w-[650px]`) that can cause horizontal scrollbar flashes during responsive resize.

### Visual Target & HeroUI-Inspired Polish
- Clean split-screen layout with `BrandCanvas` on desktop (`min-[900px]`) and unified white login card on mobile.
- Form inputs with seamless inline eye toggle anchored inside `Input` `endContent` slot.
- Submit button with smooth pending spinner that preserves button label geometry.

### Exact Surface Changes
- `frontend/components/auth/auth-form.tsx`:
  - Replace raw eye button with `Button variant="ghost" size="iconSm"` or `Input` end-adornment.
  - Wrap email/password inputs with `Field` to guarantee uniform 6px label-to-control spacing and animated error messages.
- `frontend/components/auth/brand-panel.tsx`:
  - Add `overflow-hidden` to outer container and constrain ribbon geometry with percentage-based max-widths.

---

## 2. Onboarding (`(onboarding)/start`, `onboarding-layout.tsx`, `choice-controls.tsx`, `onboarding-stages.tsx`)

### Current Visual Gaps & Debt
- **ChoiceChip Full Pill Geometry**: `choice-controls.tsx` defines `chipBase` with `rounded-full`, which contradicts the 6px control radius standard.
- **Manual Check Mark Layout**: `ChipMark` manually conditionally renders `<Check />` or `<Plus />`, which caused previous width reflow bugs.
- **Step Indicator Rail**: `OnboardingSidebar` step rail line is hardcoded (`left-4.5 w-0.5`), which misaligns when step titles wrap on medium viewports.

### Visual Target & HeroUI-Inspired Polish
- Multi-step wizard with connected vertical stepper rail (`ActivityProgress` / Stepper pattern).
- Enterprise choice chips with `rounded-[var(--radius-control)]` (6px) or `rounded-xs` (4px) with crisp 1px active cobalt ring.
- Smooth transition between Discovery and Review stages without viewport jump.

### Exact Surface Changes
- `frontend/components/onboarding/choice-controls.tsx`:
  - Update `chipBase` from `rounded-full` to `rounded-[var(--radius-control)]` (6px).
  - Use `Checkbox` or `RadioGroup` item primitives internally for `ChoiceChip` and `ToggleChip`.
- `frontend/components/onboarding/onboarding-layout.tsx`:
  - Connect `StepMarker` using continuous flex column border layout rather than absolute positioning.

---

## 3. Main App Shell (`app-shell.tsx`, `sidebar-nav.tsx`, `project-switcher.tsx`, `agent-sheet.tsx`, `user-menu.tsx`)

### Current Visual Gaps & Debt
- **Command Palette Trigger**: In `app-shell.tsx`, the topbar search input uses custom pseudo-button markup that feels disconnected from `SearchField`.
- **Project Switcher Dropdown**: The workspace switcher button has inconsistent hover padding compared to navigation links.
- **Agent Sheet Drawer**: `agent-sheet.tsx` uses custom sheet overlay classes instead of the canonical `Drawer` primitive.

### Visual Target & HeroUI-Inspired Polish
- Frosted topbar (`bg-background/80 backdrop-blur-md border-b border-border-subtle`) with centered, compact `CommandPalette` trigger (`h-8 px-3 rounded-[var(--radius-control)] bg-input/80 border border-border/80`).
- Sidebar nav links with 4px corner radius (`rounded-xs`), crisp 16px icon alignment, and active background `bg-panel shadow-2xs font-semibold text-foreground`.
- Growth Agent right-hand drawer integrated via canonical `Drawer` primitive.

### Exact Surface Changes
- `frontend/components/layout/app-shell.tsx`:
  - Standardize header grid: `h-13 px-4 grid grid-cols-[auto_1fr_auto] items-center gap-4`.
  - Unify `CommandPalette` trigger styling with standard search field.
- `frontend/components/layout/sidebar-nav.tsx`:
  - Apply `rounded-xs px-2.5 py-1.5 text-xs font-medium` to all navigation item links.
- `frontend/components/layout/agent-sheet.tsx`:
  - Wrap agent drawer contents inside canonical `Drawer` with `title="Growth Agent"`.

---

## 4. Site Health (`components/site-health/`)

### Current Visual Gaps & Debt
- **Score Section Visual Weight**: `score-section.tsx` contains 3 distinct score cards with slightly varying internal paddings (`p-4` vs `p-5`).
- **Issues Catalog Table / Drawer**: `issues-catalog.tsx` and `issue-evidence.tsx` have manual table cell borders that double with outer card borders.
- **Page Kind Badge Inconsistency**: `page-kind-badge.tsx` re-implements badge pill logic instead of calling `Badge`.

### Visual Target & HeroUI-Inspired Polish
- Harmonized 3-column scorecard with circular `ScoreRing` (80px diameter), tabular score breakdown, and subtle change delta pills.
- Clean issues catalog table with sticky header (`TableHead`), crisp row hover (`hover:bg-background-alt/60`), and quick-inspection click opening canonical `Drawer`.
- Standardized `PageKindBadge` delegating directly to `Badge variant="neutral"`.

### Exact Surface Changes
- `frontend/components/site-health/score-section.tsx`:
  - Wrap score cards in standard `Card` with `CardContent` (16px padding throughout).
- `frontend/components/site-health/page-kind-badge.tsx`:
  - Refactor to wrap `Badge` primitive with semantic page kind label mapping.
- `frontend/components/site-health/issues-catalog.tsx` & `pages-table.tsx`:
  - Replace raw `<table>` tags with `Table`, `TableHeader`, `TableHead`, `TableBody`, `TableRow`, `TableCell`.
  - Add `CursorPager` at table container footer.

---

## 5. AI Visibility (`components/visibility/`)

### Current Visual Gaps & Debt
- **Duplicate Local Empty State**: `frontend/components/visibility/empty-state.tsx` duplicates the canonical `frontend/components/ui/empty-state.tsx`.
- **Rankings Table Cell Alignment**: Numerical engine citation percentages in `rankings-table.tsx` lack `tabular-nums` and right-alignment in table headers.
- **Engine Comparison Cards**: Card heights vary depending on whether competitor badges are present.

### Visual Target & HeroUI-Inspired Polish
- Engine market share comparison grid with uniform height cards, branded engine chips (ChatGPT, Perplexity, Gemini, Claude), and linear `ScoreBar` meters.
- Rankings table with right-aligned numeric citation share columns (`font-mono tabular-nums`).
- Deletion of local `empty-state.tsx` in favor of canonical `EmptyState`.

### Exact Surface Changes
- `frontend/components/visibility/empty-state.tsx`:
  - Delete and redirect all call sites to `frontend/components/ui/empty-state.tsx`.
- `frontend/components/visibility/rankings-table.tsx`:
  - Standardize numeric columns with `TableCell numeric` and `TableHead numeric`.
- `frontend/components/visibility/engine-comparison.tsx`:
  - Set `h-full flex flex-col justify-between` on comparison cards with unified `CardHeader` and `CardContent`.

---

## 6. Content Intelligence (`components/content/`)

### Current Visual Gaps & Debt
- **Skill Picker Grid**: `skill-picker.tsx` uses custom button cards with manual hover borders and irregular icon sizes.
- **Brief Generation Drawer**: `content-screen-panels.tsx` mixes modal dialogs and slide-out drawers for content review.

### Visual Target & HeroUI-Inspired Polish
- Interactive skill picker grid with `Card interactive` cards, standard `rounded-[var(--radius-card)]`, 16px icon boxes, and active cobalt ring on selection.
- Content brief drawer using canonical `Drawer` with sticky header action bar ("Approve Brief", "Export Markdown").

### Exact Surface Changes
- `frontend/components/content/skill-picker.tsx`:
  - Refactor skill selection items to use `Card interactive` with `data-selected={selected}` styling.
- `frontend/components/content/content-screen-panels.tsx`:
  - Standardize drawer layout with `Drawer` and `Button` action bar in `footer` slot.

---

## 7. Demand Intelligence (`components/demand/`)

### Current Visual Gaps & Debt
- **Demand Signal Cards**: `demand-signal-card.tsx` has inconsistent badge placement in the top-right header.
- **Evidence Inspector**: `demand-evidence-drawer.tsx` has unstyled JSON / query evidence pre blocks.

### Visual Target & HeroUI-Inspired Polish
- Structured demand signal cards with `CardHeader` containing title + intent `Badge`, `CardContent` with query volume meter, and footer with CTA button.
- Evidence drawer featuring formatted JSON syntax box with `CopyButton` and `Tabs` for Raw / Normalized views.

### Exact Surface Changes
- `frontend/components/demand/demand-signal-card.tsx`:
  - Convert to canonical `Card` slots (`CardHeader`, `CardContent`).
- `frontend/components/demand/demand-evidence-drawer.tsx`:
  - Wrap code / query blocks in `bg-neutral-bg rounded-[var(--radius-control)] border border-border/80 p-3 font-mono text-xs`.

---

## 8. Commerce Suite (`components/products/`)

### Current Visual Gaps & Debt
- **Raw Checkboxes & Search**: `catalog-list.tsx` uses native `<input type="checkbox">` and `<input type="search">` instead of `Checkbox` and `SearchField`.
- **Target Shelf Band**: `target-shelf-band.tsx` has custom pill buttons that break control radius consistency.

### Visual Target & HeroUI-Inspired Polish
- Dense product catalog table with canonical batch selection via `Checkbox`, unified search via `SearchField`, and category filter via `Select`.
- Competitor target shelf cards with standardized 6px buttons.

### Exact Surface Changes
- `frontend/components/products/catalog-list.tsx`:
  - Replace `<input type="checkbox">` with `Checkbox`.
  - Replace raw search input with `SearchField`.
  - Replace raw pagination with `CursorPager`.
- `frontend/components/products/target-shelf-band.tsx`:
  - Standardize button controls to `Button variant="secondary" size="sm"`.

---

## 9. Runs & Schedules (`components/runs/`)

### Current Visual Gaps & Debt
- **Raw Inputs in Schedule Config**: `audit-schedules.tsx` uses native `<input type="number">` and `<input type="checkbox">`.
- **Launch Audit Modal**: `launch-dialog.tsx` has custom modal framing instead of canonical `Dialog`.
- **Execution Log Table**: Status column uses un-tokenized status colors.

### Visual Target & HeroUI-Inspired Polish
- Full audit schedule configuration using `Field`, `Input`, `Select`, and `Checkbox`.
- Audit launch modal using canonical `Dialog` with step progression (`ActivityProgress`).
- Executions table with standardized `Badge` using `runStatusBadge` tokens.

### Exact Surface Changes
- `frontend/components/runs/audit-schedules.tsx`:
  - Replace the number input with `Input` and the independently selectable engine inputs with `Checkbox`.
- `frontend/components/runs/launch-dialog.tsx`:
  - Convert custom modal wrapper to `Dialog`.
- `frontend/components/runs/runs-table.tsx` & `executions-table.tsx`:
  - Use `Table` primitives and `Badge` status styling.

---

## 10. Settings & Billing (`components/settings/`, `components/billing/`)

### Current Visual Gaps & Debt
- **Raw Inputs in Billing Form**: `billing-settings.tsx` uses `<input id="billing-country-input">`.
- **Integration Cards**: `integration-card.tsx` has custom toggle switches and disconnected connect buttons.
- **Usage Meters**: `usage-meter.tsx` uses custom progress bar heights that don't match `ScoreBar`.

### Visual Target & HeroUI-Inspired Polish
- Workspace and billing settings configured entirely with `Field`, `Input`, and `Select`.
- Integration cards with standardized `CardHeader` (logo + title + `Switch`), `CardContent` (description + status `Badge`), and `CardFooter` (reconnect action).
- Usage meters utilizing unified `ScoreBar` with tabular numeric usage fractions (`font-mono`).

### Exact Surface Changes
- `frontend/components/settings/billing-settings.tsx`:
  - Replace raw country input with `Select` or `Input`.
- `frontend/components/settings/integration-card.tsx`:
  - Standardize on `Card` and canonical `Switch`.
- `frontend/components/billing/usage-meter.tsx`:
  - Replace custom meter divs with `ScoreBar` / `Progress` primitive.

---

## Surface Implementation Summary Matrix

| Surface | Priority | Primary Debt to Eliminate | Primitives Leveraged |
|---|---|---|---|
| **1. Auth** | 1 | Raw password button, form card framing | `Input` (slots), `Button`, `Field` |
| **2. Onboarding** | 2 | `rounded-full` ChoiceChips, step rail alignment | `ChoiceChip`, `Checkbox`, `RadioGroup` |
| **3. Main App Shell** | 3 | Topbar search trigger, agent drawer framing | `CommandPalette`, `Drawer`, `Button` |
| **4. Site Health** | 4 | Scorecard padding drift, raw table tags | `ScoreRing`, `Card`, `Table`, `CursorPager` |
| **5. AI Visibility** | 5 | Duplicate `empty-state.tsx`, numeric table alignment | `Table`, `ScoreBar`, `EmptyState`, `Badge` |
| **6. Content** | 6 | Ad-hoc skill picker cards, brief review drawers | `Card interactive`, `Drawer`, `Button` |
| **7. Demand** | 7 | Signal card header alignment, raw JSON pre blocks | `Card`, `Badge`, `CopyButton`, `Tabs` |
| **8. Commerce** | 8 | Raw checkbox & search inputs in catalog | `Checkbox`, `SearchField`, `Table`, `CursorPager` |
| **9. Runs** | 9 | Raw inputs in schedules, custom launch modal | `Dialog`, `Input`, `Checkbox`, `Badge`, `ActivityProgress` |
| **10. Settings & Billing** | 10 | Raw inputs in billing, custom integration cards | `Field`, `Input`, `Select`, `Switch`, `Card` |
