# CiteLadder UI Design-System — HeroUI Reference Mapping

> **Reference Repository**: [HeroUI v3 (`https://github.com/heroui-inc/heroui/tree/v3`)](https://github.com/heroui-inc/heroui/tree/v3)
> **Documentation**: [HeroUI v3 Docs (`https://heroui.com/en/docs/react/components`)](https://heroui.com/en/docs/react/components)
> **Purpose**: Map HeroUI v3 component architecture, slot patterns, and visual styling to CiteLadder's Radix-grounded, enterprise token system.
>
> **Core Architectural Principle**:
> - **DO NOT add HeroUI as a dependency.**
> - **DO NOT introduce React Aria.**
> - **DO NOT replace Radix UI.**
> - **DO adapt**: Multi-slot composition, class-variance-authority (CVA) structure, focus-visible treatments, and semantic slot ergonomics.
> - **DO ignore**: HeroUI dynamic color paletting, custom React Aria hooks, deep Framer Motion transitions, and default 12px/16px rounded pill radii.

---

## 1. HeroUI v3 Architecture Overview

In HeroUI v3, components are organized across two primary monorepo directories:
1. `packages/react/src/components/<component-name>/`: Component implementation, props interface, subcomponents, and compound rendering.
2. `packages/styles/src/components/<component-name>.styles.ts`: Multi-slot Tailwind style definitions via `tv()` (Tailwind Variants) or CVA.
3. `packages/react/src/components/<component-name>/<component-name>.stories.tsx`: Canonical Storybook stories demonstrating all states and variants.

### Multi-Slot Pattern Convention
HeroUI separates a component into distinct DOM slots rather than applying monolithic utility strings. This pattern solves layout fragility when adding icons, prefixes, hints, or loaders.

---

## 2. Component Family Reference Specifications

---

### 2.1 Buttons & Actions

#### `Button` & `ButtonGroup`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/button/button.tsx`
  - Styles: `packages/styles/src/components/button.styles.ts`
  - Stories: `packages/react/src/components/button/button.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Outer container (display, inline-flex, items-center, justify-center, radius, transition, focus-visible ring).
  - `startContent`: Leading icon/element container.
  - `endContent`: Trailing icon/element container.
  - `spinner`: In-flight loading indicator container.
- **States**: `idle`, `hover`, `focus-visible`, `active`/`pressed`, `disabled`, `pending`/`loading`.
- **CiteLadder Adaptation**:
  - Keep `@radix-ui/react-slot` (`Slot` / `asChild`) and CVA in `frontend/components/ui/button-variants.ts`.
  - Adopt explicit `startContent` and `endContent` slots in `frontend/components/ui/button.tsx` to eliminate ad-hoc `gap` and `svg` sizing issues.
  - Retain 6px radius (`rounded-sm`), 1px borders, and micro-shadows.
- **What to Ignore**: HeroUI gradient/neon color variants, `scale-[0.97]` tap bounce, React Aria `useButton`.

#### `Pressable`
- **HeroUI Reference**: `packages/react/src/components/button/button.tsx` (unstyled / light mode).
- **CiteLadder Adaptation**: Keep `frontend/components/ui/pressable.tsx` as the unstyled native interactive primitive for table rows, clickable cards, and chip targets.

#### `CopyButton` / `Snippet`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/snippet/snippet.tsx`
  - Styles: `packages/styles/src/components/snippet.styles.ts`
- **Anatomy & Slots**: `base`, `content`, `copyButton`.
- **CiteLadder Adaptation**: Keep `frontend/components/ui/copy-button.tsx` wrapping `Button` + `useToast`. Adopt HeroUI's smooth swap transition between copy icon and checkmark.

---

### 2.2 Form Inputs & Controls

#### `Input` & `Textarea`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/input/input.tsx`, `textarea.tsx`
  - Styles: `packages/styles/src/components/input.styles.ts`
  - Stories: `packages/react/src/components/input/input.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Outer container managing full-width layout.
  - `label`: Label element.
  - `inputWrapper`: Visual container (border, background, radius, shadow, focus ring).
  - `innerWrapper`: Flex wrapper holding `startContent`, `input`, `endContent`, `clearButton`.
  - `input`: Raw HTML `<input>` or `<textarea>`.
  - `description`: Helper/hint text.
  - `errorMessage`: Validation error message.
- **States**: `idle`, `hover`, `focus-within`, `disabled`, `invalid`/`aria-invalid`, `readOnly`.
- **CiteLadder Adaptation**:
  - Refactor `frontend/components/ui/input.tsx` to support `startContent` (e.g. currency `$`, domain `https://`, search icon) and `endContent` (e.g. clear button, password visibility toggle).
  - Split `Textarea` into a dedicated file with auto-resize and `min-h-[80px]`.
  - Maintain CiteLadder tokens: `bg-panel`, `border-border`, `focus:border-accent`, `focus:ring-1 focus:ring-accent`, `text-sm`.
- **What to Ignore**: Floating labels (inside/outside), custom label animation transforms.

#### `SearchField` / `SearchInput`
- **HeroUI Reference**: `packages/react/src/components/input/input.tsx` (variant `type="search"` with start/end content).
- **CiteLadder Adaptation**:
  - Normalize `frontend/components/ui/search-field.tsx` with Lucide `Search` as `startContent`, `Loader2` for `pending`, and `X` as `clearButton`.
  - Migrate raw search inputs across the catalog and switcher to this component.

#### `Field` / `Form`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/form/form.tsx`
  - Styles: `packages/styles/src/components/form.styles.ts`
- **Anatomy & Slots**: `base`, `label`, `description`, `errorMessage`.
- **CiteLadder Adaptation**:
  - Standardize `frontend/components/ui/field.tsx` render-prop pattern and automatic `id`, `aria-describedby`, `aria-invalid` bindings.

#### `Select` & `MarketSelect`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/select/select.tsx`, `packages/react/src/components/listbox/listbox.tsx`
  - Styles: `packages/styles/src/components/select.styles.ts`
  - Stories: `packages/react/src/components/select/select.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Outer select wrapper.
  - `trigger`: Clickable trigger displaying selected value and chevron.
  - `value`: Text representation of active option.
  - `popover`: Floating portaled panel.
  - `listbox`: Scrollable options list (`role="listbox"`).
  - `item`: Individual select option (`role="option"`).
  - `itemIndicator`: Checkmark indicator for selected item.
- **States**: `open`, `closed`, `focused`, `disabled`, `invalid`.
- **CiteLadder Adaptation**:
  - Retain `@radix-ui/react-select` encapsulation in `frontend/components/ui/select.tsx`.
  - Apply HeroUI listbox item hover padding (`px-2.5 py-1.5 text-sm rounded-sm`) and micro-elevation (`shadow-dropdown`).
  - Keep `MarketSelect` as a domain wrapper for ISO country/language codes.
- **What to Ignore**: React Aria `useSelect` and heavy custom scrolling physics.

#### `Checkbox` & `CheckboxGroup`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/checkbox/checkbox.tsx`
  - Styles: `packages/styles/src/components/checkbox.styles.ts`
  - Stories: `packages/react/src/components/checkbox/checkbox.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Label container wrapping input and text.
  - `wrapper`: Visual box (`size-4 rounded-xs border`).
  - `icon`: Check / Minus SVG icon.
  - `label`: Description text.
- **States**: `unchecked`, `checked`, `indeterminate`, `hover`, `focus-visible`, `disabled`.
- **CiteLadder Adaptation**:
  - Elevate `frontend/components/ui/checkbox.tsx` (wrapping `@radix-ui/react-checkbox`) to replace all raw `<input type="checkbox">` in forms.
  - Use 4px radius (`rounded-xs`), `border-border`, `data-[state=checked]:bg-accent`, `data-[state=checked]:border-accent`.

#### `RadioGroup` & `ChoiceChip`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/radio/radio-group.tsx`, `radio.tsx`
  - Styles: `packages/styles/src/components/radio.styles.ts`
  - Stories: `packages/react/src/components/radio/radio-group.stories.tsx`
- **Anatomy & Slots**: `base`, `wrapper`, `control` (inner dot), `label`.
- **CiteLadder Adaptation**:
  - Re-align `frontend/components/ui/radio-group.tsx` with `@radix-ui/react-radio-group`.
  - Provide a `variant="chip"` mode inspired by `components/onboarding/choice-controls.tsx` for pill-style mutually exclusive choices.

#### `Switch`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/switch/switch.tsx`
  - Styles: `packages/styles/src/components/switch.styles.ts`
  - Stories: `packages/react/src/components/switch/switch.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Full container.
  - `wrapper`: Pill track (`h-5 w-9 rounded-full bg-well border border-border`).
  - `thumb`: Sliding circle (`size-4 rounded-full bg-panel shadow-xs translate-x-0 data-[state=checked]:translate-x-4`).
  - `label`: Accompanying text.
- **CiteLadder Adaptation**:
  - Modernize `frontend/components/ui/switch.tsx` using the slot anatomy. Retain crisp keyboard `focus-visible` ring.

---

### 2.3 Overlays & Feedback

#### `Dialog` (Modal) & `Drawer`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/modal/modal.tsx`, `packages/react/src/components/drawer/drawer.tsx`
  - Styles: `packages/styles/src/components/modal.styles.ts`, `drawer.styles.ts`
  - Stories: `packages/react/src/components/modal/modal.stories.tsx`
- **Anatomy & Slots**:
  - `wrapper`: Fixed viewport overlay.
  - `backdrop`: Dimming backdrop (`bg-black/40 backdrop-blur-xs`).
  - `base`: Dialog panel container (`bg-panel border border-border shadow-overlay rounded-lg`).
  - `header`: Title & description container (`border-b border-border-subtle p-5`).
  - `body`: Scrollable content container (`p-5`).
  - `footer`: Action buttons row (`border-t border-border-subtle p-4 flex justify-end gap-2.5`).
  - `closeButton`: Top-right dismiss icon.
- **CiteLadder Adaptation**:
  - Align `frontend/components/ui/dialog.tsx` and `frontend/components/ui/drawer.tsx` with standard `header`/`body`/`footer` slots.
  - Retain `@radix-ui/react-dialog` focus lock, ESC handling, and portal positioning.

#### `Dropdown` & `ContextMenu`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/dropdown/dropdown.tsx`, `menu.tsx`
  - Styles: `packages/styles/src/components/dropdown.styles.ts`
  - Stories: `packages/react/src/components/dropdown/dropdown.stories.tsx`
- **Anatomy & Slots**: `base`, `trigger`, `menu`, `item`, `itemIndicator`, `section`, `divider`.
- **CiteLadder Adaptation**:
  - Standardize `frontend/components/ui/dropdown.tsx` wrapping `@radix-ui/react-dropdown-menu`.
  - Implement HeroUI-style `DropdownSection` for grouping menu commands with micro-labels.

#### `Popover` & `Tooltip`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/popover/popover.tsx`, `packages/react/src/components/tooltip/tooltip.tsx`
  - Styles: `packages/styles/src/components/popover.styles.ts`, `tooltip.styles.ts`
- **CiteLadder Adaptation**:
  - Retain `@radix-ui/react-popover` in `frontend/components/ui/popover.tsx` and `@radix-ui/react-tooltip` in `frontend/components/ui/tooltip.tsx`.
  - Tooltips use inverse high-contrast styling (`bg-foreground text-background text-xs rounded-xs px-2 py-1 shadow-sm`).

#### `Toast` & `Alert`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/toast/toast.tsx`, `packages/react/src/components/alert/alert.tsx`
  - Styles: `packages/styles/src/components/toast.styles.ts`, `alert.styles.ts`
- **Anatomy & Slots**: `base`, `iconWrapper`, `mainWrapper`, `title`, `description`, `closeButton`.
- **CiteLadder Adaptation**:
  - Normalize `frontend/components/ui/alert.tsx` with semantic tone tokens (`info`, `success`, `warning`, `danger`, `neutral`).
  - Maintain `@radix-ui/react-toast` in `frontend/components/ui/toast.tsx` with imperative `useToast` dispatching.

---

### 2.4 Data Display, Tables & Collections

#### `Table` & `Pagination`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/table/table.tsx`, `packages/react/src/components/pagination/pagination.tsx`
  - Styles: `packages/styles/src/components/table.styles.ts`, `pagination.styles.ts`
  - Stories: `packages/react/src/components/table/table.stories.tsx`
- **Anatomy & Slots**:
  - `base`: Overflow wrapper with horizontal scroll.
  - `table`: Semantic HTML `<table>`.
  - `thead`: Header row container (`sticky top-0 bg-well/80 backdrop-blur-xs border-b border-border`).
  - `tbody`: Table body.
  - `tr`: Row (`hover:bg-active transition-colors border-b border-border-subtle`).
  - `th`: Column header (`text-2xs font-semibold uppercase tracking-wider text-muted py-2.5 px-3`).
  - `td`: Data cell (`text-sm text-secondary py-2.5 px-3`).
  - `sortIcon`: Sorting direction arrow.
- **CiteLadder Adaptation**:
  - Refine `frontend/components/ui/table.tsx` to provide sticky header backdrop-blur and responsive card mode.
  - Unify `frontend/components/ui/table-pagination.tsx` and `frontend/components/ui/cursor-pager.tsx` using HeroUI pagination item geometry.

#### `Badge` & `Chip`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/chip/chip.tsx`, `badge.tsx`
  - Styles: `packages/styles/src/components/chip.styles.ts`
  - Stories: `packages/react/src/components/chip/chip.stories.tsx`
- **Anatomy & Slots**: `base`, `dot`, `content`, `avatar`, `closeButton`.
- **CiteLadder Adaptation**:
  - CiteLadder's `frontend/components/ui/badge.tsx` is already a model discriminated union system.
  - Add explicit dot and closeButton slots for interactive filter chips and removable tags.

#### `Card` & `Surface`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/card/card.tsx`
  - Styles: `packages/styles/src/components/card.styles.ts`
- **Anatomy & Slots**: `base`, `header`, `body`, `footer`.
- **CiteLadder Adaptation**:
  - Retain `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent` subcomponent composition in `frontend/components/ui/card.tsx`.

#### `Progress` & `ScoreRing`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/progress/progress.tsx`, `circular-progress.tsx`
  - Styles: `packages/styles/src/components/progress.styles.ts`, `circular-progress.styles.ts`
- **Anatomy & Slots**: `base`, `track`, `indicator`, `label`, `value`.
- **CiteLadder Adaptation**:
  - Align `frontend/components/ui/score-bar.tsx` and `frontend/components/ui/score-ring.tsx` SVG stroke math and transitions with HeroUI Progress/CircularProgress.

#### `Skeleton`
- **HeroUI Reference**:
  - React Component: `packages/react/src/components/skeleton/skeleton.tsx`
  - Styles: `packages/styles/src/components/skeleton.styles.ts`
- **CiteLadder Adaptation**:
  - Keep `frontend/components/ui/skeleton.tsx` linear gradient shimmer using `--skeleton-base` and `--skeleton-highlight` variables.

---

## 3. What to Adapt vs What to Ignore Matrix

| Architectural Feature | Adapt from HeroUI v3 | Ignore / Retain CiteLadder Standard |
|---|---|---|
| **Component Primitives** | Slot decomposition (`base`, `wrapper`, `input`, `label`, `description`) | Retain Radix UI headless primitives; do not install `@heroui/*` |
| **State Primitives** | State naming (`data-hover`, `data-focus-visible`, `data-disabled`) | Retain standard React state & Radix data attributes (`data-state`) |
| **Styling Engine** | Slot class variance conventions | Retain Tailwind CSS v4 `@theme` and `globals.css` token mappings |
| **Typography** | Type density patterns for compact tables and forms | Retain Geist Sans (App) and Plus Jakarta Sans (Marketing/Auth) ladders |
| **Radii & Geometry** | Layout spacing & grid ratios | Retain strict 6px (control), 8px (card), 10px (overlay) radii; no 16px/24px pills |
| **Color Palettes** | Semantic tone groupings (`info`, `success`, `warning`, `danger`) | Retain CiteLadder neutral slate + warm accent token bridge |
| **Accessibility (A11y)** | Keyboard navigation conventions, ARIA labels, focus-visible rings | Retain Radix accessible keyboard handling; do not install `react-aria` |
| **Motion** | CSS transition timings (`150ms ease-out`) | Retain `ui-motion.css` tokens; do not add heavy Framer Motion springs |
