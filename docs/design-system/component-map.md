# CiteLadder UI Design-System — Component Mapping Matrix

> **Authoritative Inventory & Convergence Target Matrix**
> **Date**: August 2026
> **Machine-Readable Companion**: [`docs/design-system/component-map.json`](component-map.json)

---

## 1. Allowed Convergence Actions & Legend

- **`KEEP`**: Component is architecturally sound, properly tokenized, and has clean caller ergonomics. Retain with no breaking changes.
- **`NORMALIZE`**: Component is functional but needs minor internal refactoring (e.g. adopting multi-slot structure, standardizing focus-visible states, or refining CVA variants).
- **`CONSOLIDATE`**: Duplicate or fragmented implementations across feature folders must be merged into this canonical primitive.
- **`TOKENIZE`**: Component has hardcoded styles or non-standard utility classes that must be bound to `globals.css` semantic design tokens.
- **`RADIX_ALIGN`**: Component wraps a Radix UI primitive; ensure its API, keyboard navigation, and accessibility semantics strictly follow Radix patterns.
- **`HEROUI_INSPIRE`**: Component structure or visual transitions should be modeled after HeroUI v3 without taking on external dependencies.
- **`KEEP_DOMAIN_SPECIFIC`**: Component has specialized business logic or domain types; keep in its current location rather than forcing into generic `components/ui/`.
- **`DELETE`**: Dead, unused, or obsolete code to be removed from the repository.

---

## 2. Complete Component Mapping Table

| Component Name | File Path | Radix Primitive | HeroUI v3 Reference | Call Sites | Action | Confidence | Rationale |
|---|---|---|---|---|---|---|---|
| **Button** | `frontend/components/ui/button.tsx` | `@radix-ui/react-slot` | `@heroui/button` | **78** | `NORMALIZE` | HIGH | Core action primitive. Add explicit startContent/endContent slots while keeping @radix-ui/react-slot. |
| **Pressable** | `frontend/components/ui/pressable.tsx` | None | `@heroui/button` | **18** | `KEEP` | HIGH | High-utility unstyled interactive wrapper for table rows, cards, and custom chip click targets. |
| **CopyButton** | `frontend/components/ui/copy-button.tsx` | None | `@heroui/snippet` | **3** | `NORMALIZE` | HIGH | Add smooth icon swap transition inspired by HeroUI Snippet copy button. |
| **Input** | `frontend/components/ui/input.tsx` | None | `@heroui/input` | **22** | `NORMALIZE` | HIGH | Extract startContent and endContent slots for icons, prefixes, and clear triggers. |
| **Textarea** | `frontend/components/ui/input.tsx` | None | `@heroui/input` | **4** | `CONSOLIDATE` | HIGH | Split out of input.tsx into a standalone textarea.tsx primitive with standard min-height tokens. |
| **SearchField** | `frontend/components/ui/search-field.tsx` | None | `@heroui/input` | **2** | `CONSOLIDATE` | HIGH | Migrate un-migrated raw search inputs (e.g. products/catalog-list.tsx, projects/project-switcher.tsx) to this canonical component. |
| **Field** | `frontend/components/ui/field.tsx` | None | `@heroui/form` | **9** | `NORMALIZE` | HIGH | Standardize accessible label, description, and error message IDs and ARIA bindings. |
| **Select** | `frontend/components/ui/select.tsx` | `@radix-ui/react-select` | `@heroui/select` | **7** | `RADIX_ALIGN` | HIGH | Fully encapsulated Radix select. Refine item padding and dropdown shadow to match HeroUI listbox. |
| **MarketSelect** | `frontend/components/ui/market-select.tsx` | `@radix-ui/react-select` | `@heroui/select` | **2** | `KEEP_DOMAIN_SPECIFIC` | HIGH | Domain wrapper for ISO country and language selection in onboarding and settings. |
| **Checkbox** | `frontend/components/ui/checkbox.tsx` | `@radix-ui/react-checkbox` | `@heroui/checkbox` | **0** | `CONSOLIDATE` | HIGH | Zero consumer debt! Migrate 3 raw <input type="checkbox"> usages in feature dialogs and tables to this primitive. |
| **RadioGroup** | `frontend/components/ui/radio-group.tsx` | `@radix-ui/react-radio-group` | `@heroui/radio` | **0** | `CONSOLIDATE` | HIGH | Zero consumer debt! Align with onboarding ChoiceChip to provide standard radio group selection. |
| **Switch** | `frontend/components/ui/switch.tsx` | None | `@heroui/switch` | **2** | `HEROUI_INSPIRE` | MEDIUM | Modernize thumb and track transition geometry inspired by HeroUI Switch. |
| **SegmentedControl** | `frontend/components/ui/segmented-control.tsx` | None | `@heroui/tabs` | **2** | `NORMALIZE` | HIGH | Pill-style segmented control with roving tabindex. Align transition easing with HeroUI Solid Tabs. |
| **Tabs / TabPanel** | `frontend/components/ui/tabs.tsx` | `@radix-ui/react-tabs` | `@heroui/tabs` | **6** | `RADIX_ALIGN` | HIGH | Clean Radix Tabs wrapper with underline indicator and intent pre-fetching. |
| **NestedTabs** | `frontend/components/ui/nested-tabs.tsx` | `@radix-ui/react-tabs` | `@heroui/tabs` | **2** | `KEEP` | HIGH | Secondary tab bar for deep audit sub-navigation. |
| **Dialog** | `frontend/components/ui/dialog.tsx` | `@radix-ui/react-dialog` | `@heroui/modal` | **10** | `RADIX_ALIGN` | HIGH | Standard modal dialog. Align slot padding (header, body, footer) and backdrop blur with HeroUI Modal. |
| **Drawer** | `frontend/components/ui/drawer.tsx` | `@radix-ui/react-dialog` | `@heroui/drawer` | **7** | `RADIX_ALIGN` | HIGH | Slide-out right panel for deep evidence inspection. Robust return focus management. |
| **Dropdown** | `frontend/components/ui/dropdown.tsx` | `@radix-ui/react-dropdown-menu` | `@heroui/dropdown` | **11** | `RADIX_ALIGN` | HIGH | Standard context menu. Add DropdownSection for labeled menu groups. |
| **Popover** | `frontend/components/ui/popover.tsx` | `@radix-ui/react-popover` | `@heroui/popover` | **1** | `RADIX_ALIGN` | HIGH | Floating popover with collision detection and portaled placement. |
| **Tooltip** | `frontend/components/ui/tooltip.tsx` | `@radix-ui/react-tooltip` | `@heroui/tooltip` | **20** | `NORMALIZE` | HIGH | High-contrast inverse dark tooltips. Ensure root provider is singular. |
| **Toast** | `frontend/components/ui/toast.tsx` | `@radix-ui/react-toast` | `@heroui/toast` | **1** | `RADIX_ALIGN` | HIGH | Radix Toast provider with swipe-to-dismiss and fixed viewport. |
| **Alert** | `frontend/components/ui/alert.tsx` | None | `@heroui/alert` | **62** | `NORMALIZE` | HIGH | High-frequency feedback banner. Standardize icon pairing and title/description composition. |
| **Badge** | `frontend/components/ui/badge.tsx` | None | `@heroui/chip` | **49** | `NORMALIZE` | HIGH | Model discriminated union badge system with WCAG color+dot requirement. |
| **FilterChip** | `frontend/components/ui/filter-chip.tsx` | None | `@heroui/chip` | **3** | `NORMALIZE` | HIGH | Filter pill with tabular count badge. |
| **IconChip** | `frontend/components/ui/icon-chip.tsx` | None | `@heroui/avatar` | **4** | `KEEP` | HIGH | Container for rounded feature/category icons. |
| **Card** | `frontend/components/ui/card.tsx` | None | `@heroui/card` | **52** | `NORMALIZE` | HIGH | Standard panel surface with CardHeader, CardTitle, CardDescription, CardContent. |
| **Table** | `frontend/components/ui/table.tsx` | None | `@heroui/table` | **17** | `NORMALIZE` | HIGH | Enterprise analytics table with sticky headers, tabular numerals, and responsive card transformation. |
| **TablePagination** | `frontend/components/ui/table-pagination.tsx` | None | `@heroui/pagination` | **2** | `NORMALIZE` | HIGH | Offset pagination footer with useTablePage state hook. |
| **CursorPager** | `frontend/components/ui/cursor-pager.tsx` | None | `@heroui/pagination` | **5** | `KEEP` | HIGH | Keyset cursor navigation for Site Health crawls and issue ledgers. |
| **EmptyState** | `frontend/components/ui/empty-state.tsx` | None | `@heroui/card` | **6** | `CONSOLIDATE` | HIGH | Canonical empty state. Consolidate domain empty states across visibility, prompts, and traffic. |
| **Skeleton** | `frontend/components/ui/skeleton.tsx` | None | `@heroui/skeleton` | **41** | `NORMALIZE` | HIGH | Linear gradient shimmer. Add multi-shape presets (avatar, text, card). |
| **ActivityProgress** | `frontend/components/ui/activity-progress.tsx` | None | `@heroui/progress` | **2** | `NORMALIZE` | HIGH | Vertical progress timeline for multi-stage background discovery jobs. |
| **ScoreRing** | `frontend/components/ui/score-ring.tsx` | None | `@heroui/progress` | **3** | `HEROUI_INSPIRE` | HIGH | SVG circular score gauge mapped to semantic score tokens. |
| **ScoreBar** | `frontend/components/ui/score-bar.tsx` | None | `@heroui/progress` | **2** | `HEROUI_INSPIRE` | HIGH | Horizontal score progress bar. |
| **ScoreBand** | `frontend/components/ui/score-band.ts` | None | None | **4** | `KEEP` | HIGH | Pure scoring helper mapping 0–100 numbers to high, medium, low tokens. |
| **TrendChart** | `frontend/components/ui/trend-chart.tsx` | None | None | **7** | `KEEP_DOMAIN_SPECIFIC` | HIGH | Domain-specific analytics chart for Visibility and Traffic. |
| **Sparkline** | `frontend/components/ui/sparkline.tsx` | None | None | **1** | `KEEP_DOMAIN_SPECIFIC` | HIGH | Inline metric trend micro-chart. |
| **UnavailableValue** | `frontend/components/ui/unavailable-value.tsx` | None | None | **34** | `KEEP` | HIGH | Strict data representation for not_measured, not_set, zero, and unavailable. |
| **Typography** | `frontend/components/ui/typography.tsx` | None | `@heroui/typography` | **26** | `KEEP` | HIGH | Core type ladder helpers (SectionTitle, Label, Metric, displayHeadingClasses). |
| **Eyebrow** | `frontend/components/ui/eyebrow.tsx` | None | None | **25** | `KEEP` | HIGH | Micro-uppercase section label (text-2xs font-semibold tracking-wider uppercase). |
| **BrandLogo** | `frontend/components/ui/brand-logo.tsx` | None | `@heroui/avatar` | **9** | `NORMALIZE` | HIGH | Favicon loader with monogram fallback. |
| **LogoMark** | `frontend/components/ui/logo-mark.tsx` | None | None | **4** | `KEEP` | HIGH | CiteLadder product logo for light and dark surfaces. |
| **MutationNotice** | `frontend/components/ui/mutation-notice.tsx` | None | `@heroui/alert` | **6** | `KEEP` | HIGH | Mutation failure banner mapping API error envelopes to retry actions. |
| **CommandPalette** | `frontend/components/ui/command-palette.tsx` | `@radix-ui/react-dialog` | `@heroui/autocomplete` | **1** | `NORMALIZE` | HIGH | Global Cmd+K quick navigation search modal. |
| **CsvImport** | `frontend/components/ui/csv-import.tsx` | None | None | **1** | `KEEP` | HIGH | Catalog CSV drag-and-drop input wrapper. |
| **AnalyticsToolbar** | `frontend/components/ui/analytics-toolbar.tsx` | `@radix-ui/react-dropdown-menu` | None | **2** | `KEEP` | HIGH | Standardized compound toolbar for date ranges and granularity. |
| **Disclosure** | `frontend/components/ui/disclosure.tsx` | `@radix-ui/react-collapsible` | `@heroui/accordion` | **0** | `RADIX_ALIGN` | MEDIUM | Keep as canonical Radix Collapsible wrapper for upcoming FAQ and issue disclosures. |
| **DonutChart** | `frontend/components/ui/donut.tsx` | None | None | **0** | `DELETE` | HIGH | Unused prototype chart. Remove from codebase. |

---

## 3. High-Priority Feature Consolidation Targets

Below are specific feature files identified during the audit that must be updated to consume the canonical primitives:

1. **`frontend/components/prompts/prompt-form-dialog.tsx`**:
   - Replace native `<input type="checkbox">` (lines 126–131, 141–146) with `<Checkbox>`.
2. **`frontend/components/runs/audit-schedules.tsx`**:
   - Replace native `<input type="checkbox">` (lines 153–163) with `<Checkbox>`.
   - Replace native `<input type="number">` (lines 139–146) with `<Input type="number">`.
3. **`frontend/components/products/catalog-list.tsx`**:
   - Replace native `<input type="checkbox">` (lines 108–117) with `<Checkbox>`.
   - Replace native search `<Input>` (lines 290–295) with `<SearchField>`.
4. **`frontend/components/settings/billing-settings.tsx`**:
   - Replace native `<input id="billing-country-input">` (lines 291–299) with `<Input>`.
5. **`frontend/components/auth/auth-form.tsx`**:
   - Replace raw `<button type="button">` password toggle (line 91) with `Button variant="ghost"` or `Input endContent`.
6. **Consolidate 5 Domain Empty States into `components/ui/empty-state.tsx`**:
   - `frontend/components/visibility/empty-state.tsx` -> `components/ui/empty-state.tsx`
   - `frontend/components/prompts/prompt-empty-state.tsx` -> `components/ui/empty-state.tsx`
   - `frontend/components/traffic/empty-state.tsx` -> `components/ui/empty-state.tsx`
   - `frontend/components/ai-referrals/empty-state.tsx` -> `components/ui/empty-state.tsx`
   - `frontend/components/settings/integrations-empty-state.tsx` -> `components/ui/empty-state.tsx`
