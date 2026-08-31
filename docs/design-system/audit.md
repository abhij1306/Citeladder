# CiteLadder UI Design-System Audit & Component Inventory

> **Status**: Comprehensive Discovery & Inventory
> **Date**: August 2026
> **Scope**: Main Application (`frontend/app/(app)`), Onboarding (`frontend/app/(onboarding)`), Authentication (`frontend/app/(auth)`), Marketing Primitives, Shared Primitives (`frontend/components/ui`), and Design Policy Enforcement.

---

## 1. Executive Summary & Objective

CiteLadder is an enterprise growth intelligence platform built on Next.js 15 (App Router), Tailwind CSS v4, Radix UI headless primitives, TanStack Query v5, and Lucide React. This audit provides a mechanical, evidence-based inventory and structural classification of all frontend components, surfaces, tokens, and design debt across the repository.

### Key Inventory Totals
- **Total Frontend TypeScript/TSX Files**: 663 files
- **Total Component Files (`frontend/components/**`)**: 266 files
- **Design System UI Files (`frontend/components/ui/`)**: 54 files (47 active components + 7 variant/helper files)
- **Radix UI Packages Installed**: 11 packages (`@radix-ui/react-checkbox`, `@radix-ui/react-collapsible`, `@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-popover`, `@radix-ui/react-radio-group`, `@radix-ui/react-select`, `@radix-ui/react-slot`, `@radix-ui/react-tabs`, `@radix-ui/react-toast`, `@radix-ui/react-tooltip`)
- **Direct Radix Imports Outside `components/ui/`**: **0 files** (100% encapsulation achieved via AST linter rules)
- **Raw Element Bypasses Identified**:
  - Raw `<input type="checkbox">` in 3 feature components (prompts dialog, audit schedules, catalog list)
  - Raw `<input type="number">` in 1 feature component (audit schedules)
  - Raw `<input id="billing-country-input">` in 1 feature component (billing settings)
  - Raw `<button>` password visibility toggle in 1 auth component (auth form)
  - Unused / zero-consumer UI primitives: 4 (`checkbox`, `radio-group`, `disclosure`, `donut`)

---

## 2. Design System Architecture & Enforcement

### 2.1 CSS Variables & `@theme` Token Architecture
CiteLadder enforces a single-theme, light-first enterprise design token system defined in `frontend/app/globals.css`:
- **Typography Scale**: Geist Sans (`font-sans`) for product interface and body; Plus Jakarta Sans (`font-heading`) for marketing and display headers (`.website-type`).
- **Control Radii**:
  - `--radius-control: 6px` (`rounded-sm` / `rounded`): buttons, inputs, segmented controls, badges, chips.
  - `--radius-card: 8px` (`rounded-md`): cards, tables, panels, dialog content.
  - `--radius-overlay: 10px` (`rounded-lg`): modal wrappers, popovers, dropdown menus, drawers.
- **Shadow Tokens**:
  - `--shadow-card`: `0 1px 3px 0 rgb(0 0 0 / 0.04), 0 1px 2px -1px rgb(0 0 0 / 0.04)` (subtle hairline elevation).
  - `--shadow-dropdown`: `0 4px 12px 0 rgb(0 0 0 / 0.08)` (menu / popover lift).
  - `--shadow-overlay`: `0 12px 32px 0 rgb(0 0 0 / 0.12)` (modal dialog / drawer lift).
  - `--shadow-brand`: glow and spotlight tokens for dark brand panels.

### 2.2 AST Guardrails & Quality Scripts
Two automated AST validation scripts enforce design system boundaries before commits:
1. `frontend/scripts/check-design-system.mjs`: AST linter forbidding raw colors, un-boxed alerts, and direct Radix imports.
2. `frontend/scripts/design-system-source-checks.mjs`: Verifies CVA variants, token usage, and semantic roles.

---

## 3. Component Taxonomy & Usage Audit

The 54 UI primitives and helpers in `frontend/components/ui/` are classified below by family with consumer counts:

### 3.1 Buttons & Actions
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Button` | `frontend/components/ui/button.tsx` | `@radix-ui/react-slot` | **78** | Core action primitive. Variants: `primary`, `secondary`, `tonal`, `neutral`, `ghost`, `destructive`, `destructiveGhost`. Sizes: `sm`, `md`, `lg`, `icon`. Supports `asChild` and `pending` states. |
| `Pressable` | `frontend/components/ui/pressable.tsx` | Native `<button>` | **18** | Unstyled interactive wrapper for table rows, clickable cards, and chips. |
| `CopyButton` | `frontend/components/ui/copy-button.tsx` | `Button` + `Toast` | **3** | Copy-to-clipboard button with checkmark swap and toast feedback. |

### 3.2 Form Inputs & Controls
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Input` | `frontend/components/ui/input.tsx` | Native `<input>` | **22** | Standard text input with focus-ring, error state, and md/lg size variants. |
| `Textarea` | `frontend/components/ui/input.tsx` | Native `<textarea>` | **4** | Multi-line textarea sharing styling with `Input`. |
| `SearchField` | `frontend/components/ui/search-field.tsx` | Native `<input>` | **2** | Search input with leading search icon, spinner, and clear button. |
| `Field` | `frontend/components/ui/field.tsx` | Accessible wrapper | **9** | Accessible form field wrapping label, description/hint, and error message with unique IDs. |
| `Select` | `frontend/components/ui/select.tsx` | `@radix-ui/react-select` | **7** | Full Radix select wrapper with `EMPTY_VALUE` sentinel handling. |
| `MarketSelect` | `frontend/components/ui/market-select.tsx` | `@radix-ui/react-select` | **2** | Domain-specific ISO country & language select with flag/code formatting. |
| `Checkbox` | `frontend/components/ui/checkbox.tsx` | `@radix-ui/react-checkbox` | **0** | **DEBT**: Zero consumers. Feature components use native `<input type="checkbox">`. |
| `RadioGroup` | `frontend/components/ui/radio-group.tsx` | `@radix-ui/react-radio-group` | **0** | **DEBT**: Zero consumers. Features use custom chip radio buttons. |
| `Switch` | `frontend/components/ui/switch.tsx` | Native `<button role="switch">` | **2** | Custom button switch with sliding thumb track. |
| `SegmentedControl` | `frontend/components/ui/segmented-control.tsx` | Custom ARIA radiogroup | **2** | Pill-style segmented control with roving tabindex and keyboard navigation. |
| `CsvImport` | `frontend/components/ui/csv-import.tsx` | Native file input | **1** | File upload drop zone for CSV catalog imports. |

### 3.3 Navigation & Routing
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Tabs` / `TabPanel` | `frontend/components/ui/tabs.tsx` | `@radix-ui/react-tabs` | **6** | Accessible tabs with underline active indicator and intent pre-fetching. |
| `NestedTabs` | `frontend/components/ui/nested-tabs.tsx` | `@radix-ui/react-tabs` | **2** | Secondary tab bar for nested audit views. |
| `AnalyticsToolbar` | `frontend/components/ui/analytics-toolbar.tsx` | Dropdown + Segmented | **2** | Unified toolbar for date ranges, granularity, and live fetch indicators. |

### 3.4 Overlays & Feedback
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Alert` | `frontend/components/ui/alert.tsx` | Accessible container | **62** | Feedback callout. Tones: `neutral`, `info`, `success`, `warning`, `danger`. |
| `Dialog` | `frontend/components/ui/dialog.tsx` | `@radix-ui/react-dialog` | **10** | Modal dialog with header, body, footer, and focus trap. |
| `Drawer` | `frontend/components/ui/drawer.tsx` | `@radix-ui/react-dialog` | **7** | Slide-out right panel for deep evidence inspection and side sheets. |
| `Dropdown` | `frontend/components/ui/dropdown.tsx` | `@radix-ui/react-dropdown-menu` | **11** | Context menu with items, radio groups, checkbox items, and separators. |
| `Popover` | `frontend/components/ui/popover.tsx` | `@radix-ui/react-popover` | **1** | Floating overlay with collision detection and portaled placement. |
| `Tooltip` | `frontend/components/ui/tooltip.tsx` | `@radix-ui/react-tooltip` | **20** | High-contrast inverse dark tooltips with custom delay. |
| `Toast` | `frontend/components/ui/toast.tsx` | `@radix-ui/react-toast` | **1** | Provider + imperative `useToast` hook for bottom-right notification stack. |
| `MutationNotice` | `frontend/components/ui/mutation-notice.tsx` | `Alert` + `Button` | **6** | Standard mutation failure alert with retry button. |
| `CommandPalette` | `frontend/components/ui/command-palette.tsx` | `@radix-ui/react-dialog` | **1** | Global Cmd+K quick navigation search modal. |
| `Skeleton` | `frontend/components/ui/skeleton.tsx` | Shimmer div | **41** | Loading placeholder with gradient animation. |

### 3.5 Data Display & Metrics
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Card` | `frontend/components/ui/card.tsx` | Container | **52** | Standard panel surface with `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`. |
| `Badge` | `frontend/components/ui/badge.tsx` | Discriminated union | **49** | Status indicators with WCAG color+dot requirement. Variants: `status`, `sentiment`, `classification`, `run-status`, `neutral`. |
| `FilterChip` | `frontend/components/ui/filter-chip.tsx` | Toggle button | **3** | Interactive filter pill with count badge. |
| `IconChip` | `frontend/components/ui/icon-chip.tsx` | Div container | **4** | Circular/rounded background for icons. |
| `ScoreRing` | `frontend/components/ui/score-ring.tsx` | SVG circle | **3** | Circular score gauge (0–100) with color banding. |
| `ScoreBar` | `frontend/components/ui/score-bar.tsx` | SVG/HTML bar | **2** | Horizontal score progress bar. |
| `ScoreBand` | `frontend/components/ui/score-band.ts` | Helper logic | **4** | Maps 0–100 numerical scores to `high`, `medium`, `low` tokens. |
| `TrendChart` | `frontend/components/ui/trend-chart.tsx` | SVG line chart | **7** | Historical trend series for Visibility and Traffic. |
| `Sparkline` | `frontend/components/ui/sparkline.tsx` | SVG micro-chart | **1** | Compact inline trend visualization. |
| `ActivityProgress` | `frontend/components/ui/activity-progress.tsx` | Stepper + progress | **2** | Vertical progress timeline for multi-step AI discovery jobs. |
| `UnavailableValue` | `frontend/components/ui/unavailable-value.tsx` | Muted text / em-dash | **34** | Strict data representation for `not_measured`, `not_set`, `zero`, and `unavailable`. |
| `Typography` | `frontend/components/ui/typography.tsx` | Typographic roles | **26** | `SectionTitle`, `Label`, `Metric`, `displayHeadingLgClasses`, `displayHeadingXlClasses`. |
| `Eyebrow` | `frontend/components/ui/eyebrow.tsx` | Span | **25** | Micro-uppercase header (`text-2xs font-semibold tracking-wider uppercase`). |
| `BrandLogo` | `frontend/components/ui/brand-logo.tsx` | Image + Fallback | **9** | Favicon loader with monogram fallback. |
| `LogoMark` | `frontend/components/ui/logo-mark.tsx` | SVG | **4** | CiteLadder product logo for light and dark surfaces. |

### 3.6 Tables & Collections
| Component | File Path | Radix / Base | Consumers | Status / Quality Note |
|---|---|---|---|---|
| `Table` | `frontend/components/ui/table.tsx` | Semantic `<table>` | **17** | Full suite: `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell`, `TableRecordMetricCell`. Sticky headers and mobile card fallback. |
| `TablePagination` | `frontend/components/ui/table-pagination.tsx` | Pager controls | **2** | Page-number based pagination with item count and `useTablePage` state hook. |
| `CursorPager` | `frontend/components/ui/cursor-pager.tsx` | Prev/Next buttons | **5** | Opaque cursor pagination for Site Health crawls and issue ledgers. |
| `EmptyState` | `frontend/components/ui/empty-state.tsx` | Card / Panel | **6** | Structured empty state with icon, title, description, and action button. |

### 3.7 Dead / Unused / Deprecate Candidates
| Component | File Path | Consumers | Recommendation |
|---|---|---|---|
| `DonutChart` | `frontend/components/ui/donut.tsx` | **0** | **DELETE**: Unused prototype chart. `ScoreRing` and `TrendChart` own data visualization. |
| `Disclosure` | `frontend/components/ui/disclosure.tsx` | **0** | **RADIX_ALIGN**: Keep as canonical Radix Collapsible wrapper for upcoming FAQ and crawl issue disclosures. |

---

## 4. Surface-by-Surface Component Audit

### 4.1 Main Application Surface (`frontend/app/(app)`)
The main application uses the full enterprise token palette with `font-sans` (Geist), strict 6px/8px radii, and compact data density.

#### Key Workspaces & Call Site Distribution:
1. **Site Health (`components/site-health/`, 28 files)**:
   - Extensively uses `Card`, `Badge` (run-status, status), `Table`, `CursorPager`, `ScoreRing`, `ScoreBar`, `Alert`, `Drawer`, `Skeleton`, `UnavailableValue`.
   - Complete encapsulation of crawl state, page classification evidence, and defect inspector.
2. **AI Visibility (`components/visibility/`, 14 files)**:
   - Uses `Tabs`, `Table`, `Badge`, `TrendChart`, `AnalyticsToolbar`, `Dropdown`, `Dialog`, `Tooltip`, `UnavailableValue`.
   - Contains a local `components/visibility/empty-state.tsx` that duplicates the canonical `components/ui/empty-state.tsx`.
3. **Content Intelligence (`components/content/`, 6 files)**:
   - Uses `Card`, `Button`, `Input`, `Textarea`, `Badge`, `Drawer`, `Alert`, `ActivityProgress`.
   - Skill picker and content strategy editor panels.
4. **Demand Intelligence (`components/demand/`, 5 files)**:
   - Uses `Card`, `Drawer`, `Badge`, `Button`, `Table`, `Alert`.
   - Signal cards, demand detector bar, and journey evidence drawer.
5. **Commerce Suite (`components/products/`, 11 files)**:
   - Uses `Card`, `Button`, `Input`, `Badge`, `Skeleton`, `Alert`, `CsvImport`.
   - **Identified Debt**: `catalog-list.tsx` uses raw `<input type="checkbox">` and raw `<input>` instead of `Checkbox` and `SearchField`.
6. **Runs & Schedules (`components/runs/`, 11 files)**:
   - Uses `Card`, `Button`, `Select`, `Badge`, `Table`, `TablePagination`, `Alert`, `MutationNotice`.
   - **Identified Debt**: `audit-schedules.tsx` uses raw `<input type="checkbox">` and raw `<input type="number">`.
7. **Prompt Portfolio (`components/prompts/`, 13 files)**:
   - Uses `Dialog`, `Button`, `Input`, `Textarea`, `Select`, `Table`, `TablePagination`, `Alert`.
   - **Identified Debt**: `prompt-form-dialog.tsx` uses raw `<input type="checkbox">` for cohort/enabled toggles.
8. **Settings & Billing (`components/settings/`, `components/billing/`, 12 files)**:
   - Uses `Card`, `Button`, `Badge`, `Dialog`, `Alert`, `Skeleton`.
   - **Identified Debt**: `billing-settings.tsx` uses raw `<input id="billing-country-input">`.

### 4.2 Onboarding Surface (`frontend/app/(onboarding)`)
The onboarding flow is a split-screen experience pairing a dark `BrandCanvas` sidebar with a light interactive stage column.
- **Components (`components/onboarding/`, 7 files)**:
  - `onboarding-layout.tsx`: `BrandCanvas`, `AuthWordmark`, `StepMarker` (vertical timeline).
  - `onboarding-stages.tsx`: `BrandStage` (`Field`, `Input`, `MarketSelect`, `Button`), `DiscoveryStage` (`ActivityProgress`, `Alert`, `Button`), `ReviewStage` (`IcpConfirmation`, `ReviewStep`, `Button`, `Alert`).
  - `choice-controls.tsx`: `ReviewSection`, `ChipRow`, `ChoiceChip`, `ToggleChip` (`Pressable`, `Button`).
  - **Design System Alignment**: Choice chips use full-pill radii (`rounded-full`) and custom focus rings. These should be formalized as specialized Chip / Filter variants.

### 4.3 Authentication Surface (`frontend/app/(auth)`)
The authentication surface mirrors the split-canvas onboarding layout.
- **Components (`components/auth/`, 2 files)**:
  - `brand-panel.tsx`: `BrandCanvas` (radial glow, ambient ribbons), `AuthWordmark`.
  - `auth-form.tsx`: `Field`, `Input`, `Button`, `Alert`.
  - **Identified Debt**: Password visibility toggle uses a raw `<button>` instead of `Button` with `variant="ghost"` or an end-content slot.

---

## 5. Token & Design System Debt Summary

1. **Checkbox & Radio Primitives Underutilized**:
   - Canonical `components/ui/checkbox.tsx` and `components/ui/radio-group.tsx` exist and wrap Radix, but have **0 consumers** because feature forms were implemented with raw inputs.
2. **Duplicated Empty States**:
   - Five feature workspaces implement custom empty state components (`ai-referrals/empty-state.tsx`, `visibility/empty-state.tsx`, `traffic/empty-state.tsx`, `prompts/prompt-empty-state.tsx`, `settings/integrations-empty-state.tsx`) instead of reusing `components/ui/empty-state.tsx`.
3. **Compound Search Inputs**:
   - `components/ui/search-field.tsx` has only 2 consumers while several pages (e.g., `products/catalog-list.tsx`, `projects/project-switcher.tsx`) implement custom search input wrappers.
4. **Pagination Bifurcation**:
   - Two distinct pagination patterns exist (`TablePagination` for offset pages, `CursorPager` for keyset cursors). Both are valid but need unified styling.
5. **Switch Component Architecture**:
   - `components/ui/switch.tsx` is implemented with a native button rather than `@radix-ui/react-switch`.

---

## 6. Audit Verdict

CiteLadder possesses an exceptionally clean foundation with **zero Radix leaks** and strong AST enforcement. The primary opportunities for convergence are:
1. Migrating raw `<input>` elements in feature forms to canonical UI primitives (`Checkbox`, `Input`, `SearchField`).
2. Consolidating domain empty states into the single canonical `EmptyState` component.
3. Structuring UI component internals using multi-slot architectures inspired by HeroUI v3 while retaining CiteLadder's Radix runtime, 6px/8px radii, and enterprise light token system.
