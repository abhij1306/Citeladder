# CiteLadder Design System — Visual Improvement Map

> Implementation-ready specification mapping CiteLadder's UI primitives to HeroUI v3 visual and interaction patterns while strictly preserving CiteLadder's design invariants: Geist typography, compact enterprise density, 6px controls, 8px cards, 10px overlays, and semantic tokenized colors.
>
> **Execution Authority for Codex / Implementing Agents:** This document defines the exact visual changes, DOM structures, Tailwind classes, states, and isolation boundaries for every primitive.

---

## Architecture & Governance Invariants

All changes specified in this map strictly uphold CiteLadder core design tokens (`frontend/app/globals.css`):

1. **Radii Hierarchy**:
   - Micro / Inset / Table rows / Tags: `rounded-xs` (2px), `rounded-sm` (4px).
   - Controls / Inputs / Buttons / Select triggers: `rounded-[var(--radius-control)]` (6px).
   - Cards / Surface Containers / Panels: `rounded-[var(--radius-card)]` (8px).
   - Overlays / Modals / Drawers / Dropdown Panels / Tooltips: `rounded-[var(--radius-overlay)]` (10px) or `rounded-xs` (4px for micro-tooltips).
   - Pills / Status dots: `rounded-full` (9999px).
2. **Typography**:
   - `font-sans` (Geist Sans) for application UI, forms, and data tables.
   - `font-display` (Geist Sans with negative tracking `-0.015em` / `-0.025em`) for card and page titles.
   - `font-mono` (`mono` / Geist Mono) with `tabular-nums` for metrics, scores, badges, and timestamps.
3. **Layer & Elevation Model**:
   - Canvas: `bg-background` (`#fcfcfc` / sunken neutral).
   - Panel / Card Surface: `bg-panel` (`#ffffff`) with `shadow-card` (`0 1px 2px rgb(15 23 42 / 0.06), 0 8px 22px -10px rgb(15 23 42 / 0.18)`).
   - Elevated / Popovers / Dropdowns: `bg-elevated/95 backdrop-blur-md` with `shadow-elevated`.
   - Modals / Drawers: `bg-elevated` with `shadow-modal-value`.
4. **Primary Accent & Color Ramp**:
   - Accent Primary: `#315cff` (Cube Cobalt), Hover: `#2347d9`, Active: `#1a38b5`, Subtle: `#eff4ff`, Border: `#c3d3ff`, Text: `#1e40af`.
5. **Radix Boundary**:
   - Direct `@radix-ui/*` imports remain 100% encapsulated inside `frontend/components/ui/`.

---

## Component Visual Improvement Map (Prioritized Order)

```
[Priority 1-5: Core Forms & Actions]
  1. Button & Pressable
  2. Input & Textarea
  3. Field (Form Field Container)
  4. SearchField
  5. Select
[Priority 6-11: Selection & Toggles]
  6. Checkbox
  7. RadioGroup
  8. Switch
  9. Tabs & NestedTabs
  10. SegmentedControl
[Priority 12-16: Overlays & Modals]
  11. Dialog (Modal)
  12. Drawer (Sheet)
  13. Dropdown (Menu)
  14. Tooltip
  15. Toast
[Priority 17-21: Data Display & Surfaces]
  16. Card & Compound Slots
  17. Badge & IconChip
  18. FilterChip
  19. Table & TableRecordMetricCell
  20. TablePagination & CursorPager
[Priority 22-26: Feedback & Status Indicators]
  21. Alert & MutationNotice
  22. EmptyState
  23. Skeleton
  24. ScoreRing & ScoreBar
  25. ActivityProgress
[Priority 27-30: Utility & Navigation Chrome]
  26. Typography (SectionTitle, Label, Metric)
  27. BrandLogo & LogoMark
  28. CommandPalette
  29. CopyButton
```

---

### 1. Button & Pressable

- **Priority**: 1
- **Confidence**: High (Zero breaking API changes; CSS & slot alignment)
- **Isolation Level**: Canonical UI Primitive only (`frontend/components/ui/button.tsx`, `frontend/components/ui/button-variants.ts`, `frontend/components/ui/pressable.tsx`)
- **Call Sites**: 85+

#### Current Weaknesses & Visual Debt
- `button-variants.ts` has `active:scale-[0.98]` applied uniformly to all buttons, causing jitter when triggering dropdowns or menus.
- Secondary variant uses a heavy border (`border-border-strong`) that fights with adjacent card borders.
- Destructive buttons lack an explicit pressed state tone (`active:bg-danger-solid-hover` is identical to hover).
- Spinner layout in `button.tsx` shifts button content horizontally on pending state transition.
- Focus ring outline lacks fine inner contrast against colored backgrounds.

#### HeroUI v3 Reference
- **Package**: `@heroui/button`
- **Slots**: `base`, `content`, `startContent`, `endContent`, `spinner`
- **Patterns Adapted**:
  - Crisp micro-inset border lighting (`shadow-xs` + hairline border).
  - Explicit start/end icon slot alignment without manual `size-4` spacing hacks.
  - Smooth spinner overlay state preserving original button width.
  - Active pressed state suppression on popup triggers (`aria-haspopup`).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/button-variants.ts
export const buttonVariants = cva(
  'focus-ring relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] border text-sm font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out select-none not-[[aria-haspopup]]:not-[[data-popup-trigger=true]]:active:scale-[0.985] data-[popup-trigger=true]:active:scale-100 aria-haspopup:active:scale-100 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      variant: {
        primary:
          'border-transparent bg-accent text-accent-fg shadow-xs hover:bg-accent-hover active:bg-accent-active',
        secondary:
          'border-border/80 bg-panel text-foreground shadow-2xs hover:border-border-strong hover:bg-background-alt active:bg-well',
        tonal:
          'border-accent-border/60 bg-accent-subtle text-accent-text hover:border-accent hover:bg-accent-border/60 active:bg-accent-border',
        neutral:
          'border-transparent bg-background-alt text-foreground hover:bg-well active:bg-active',
        ghost:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground active:bg-well',
        destructive:
          'border-transparent bg-danger-solid text-danger-fg shadow-xs hover:bg-danger-solid-hover active:bg-red-700',
        destructiveGhost:
          'border-transparent bg-transparent text-danger-text hover:bg-danger-bg active:bg-danger-border/40',
      },
      size: {
        sm: 'h-[var(--control-height-sm)] px-2.5 text-xs gap-1.5 [&_svg]:size-3.5',
        md: 'h-[var(--control-height)] px-3 text-sm gap-2 [&_svg]:size-4',
        lg: 'h-[var(--control-height-lg)] px-4 text-sm gap-2.5 [&_svg]:size-4.5',
        icon: 'size-[var(--control-height)] p-0 [&_svg]:size-4',
        iconSm: 'size-[var(--control-height-sm)] p-0 [&_svg]:size-3.5',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  }
);
```

#### States & Micro-Interactions
- `hover`: 150ms ease-out background ramp shift; no layout shift.
- `active`: Micro-scale `scale-[0.985]`; excluded when `opensPopup` is true (`active:scale-100`).
- `pending`: Spinner replaces icon or prepends label smoothly with `aria-busy="true"`.
- `focus-visible`: `var(--focus-ring)` (2px offset + 2px cobalt ring).

---

### 2. Input & Textarea

- **Priority**: 2
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/input.tsx`)
- **Call Sites**: 35+

#### Current Weaknesses & Visual Debt
- `inputClasses` uses `border-border-strong/80 bg-input`, creating muddy contrast inside elevated cards.
- Textarea lacks visual scrollbar styling and has a generic resize handle.
- Placeholder text contrast is slightly too light in dark mode/canvases.
- Missing explicit helper text/icon padding slot coordination.

#### HeroUI v3 Reference
- **Package**: `@heroui/input`
- **Slots**: `base`, `label`, `inputWrapper`, `input`, `clearButton`, `description`, `errorMessage`
- **Patterns Adapted**:
  - Refined container box model: subtle inset well with active border transition.
  - Hover hairline deepening (`hover:border-border-strong`) without pre-empting the blue focus ring.
  - Invalid state glowing hairline (`border-danger focus:border-danger focus:ring-danger/20`).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/input.tsx
export const inputClasses = cn(
  'focus-ring flex h-[var(--control-height)] w-full rounded-[var(--radius-control)] border border-border/90 bg-input px-3 text-sm text-foreground shadow-2xs',
  'transition-[border-color,box-shadow,background-color] duration-150',
  'placeholder:text-muted/80 hover:border-border-strong focus:border-accent',
  'aria-invalid:border-danger aria-invalid:focus:border-danger aria-invalid:focus:shadow-[0_0_0_2px_var(--color-panel),0_0_0_4px_rgba(239,68,68,0.2)]',
  'disabled:cursor-not-allowed disabled:bg-background-alt/50 disabled:opacity-50'
);

export const textareaClasses = cn(
  'focus-ring flex min-h-24 w-full resize-y rounded-[var(--radius-control)] border border-border/90 bg-input p-3 text-sm text-foreground shadow-2xs leading-relaxed',
  'transition-[border-color,box-shadow,background-color] duration-150',
  'placeholder:text-muted/80 hover:border-border-strong focus:border-accent',
  'aria-invalid:border-danger aria-invalid:focus:border-danger',
  'disabled:cursor-not-allowed disabled:bg-background-alt/50 disabled:opacity-50'
);
```

---

### 3. Field (Form Field Container)

- **Priority**: 3
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/field.tsx`)
- **Call Sites**: 28+

#### Current Weaknesses & Visual Debt
- `Field` hardcodes `gap-2` which can feel loose in dense enterprise filter panels.
- Required asterisk is red without semantic class token association.
- Error message jumps into DOM without entrance animation, causing layout snap.

#### HeroUI v3 Reference
- **Package**: `@heroui/form`
- **Patterns Adapted**:
  - Compact vertical rhythm (label `gap-1.5`, hint/error `gap-1`).
  - Animated error disclosure with `text-xs font-medium text-danger-text`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/field.tsx
export function Field({ label, hint, error, required, className, labelClassName, children }: ... ) {
  // associates ARIA IDs and renders:
  // <div className={cn('grid gap-1.5', className)}>
  //   <label className={cn('text-foreground text-xs font-medium flex items-center justify-between', labelClassName)}>
  //     <span>{label}{required && <span className="text-danger ml-0.5" aria-hidden>*</span>}</span>
  //   </label>
  //   {children({ id, required, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
  //   {hint && !error && <span id={hintId} className="text-muted text-xs leading-normal">{hint}</span>}
  //   {error && <span id={errorId} role="alert" className="text-danger-text text-xs font-medium flex items-center gap-1 animate-in fade-in-50 duration-150">{error}</span>}
  // </div>
}
```

---

### 4. SearchField

- **Priority**: 4
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/search-field.tsx`)
- **Call Sites**: 12+

#### Current Weaknesses & Visual Debt
- Uses `border-input bg-input-bg` with generic styling; clear button jumps into view abruptly.
- Icon alignment is not vertically locked at dense heights.

#### HeroUI v3 Reference
- **Package**: `@heroui/input` (Search variant)
- **Patterns Adapted**:
  - Seamless icon anchor with search glyph at `size-3.5` (sm) or `size-4` (md).
  - Clear button with smooth scale-in fade and accessible tooltip.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/search-field.tsx
export function SearchField({ value, onValueChange, pending = false, onClear, className, ...props }: SearchFieldProps) {
  return (
    <div className={cn(
      'focus-within:border-accent focus-within:shadow-[var(--focus-ring)] flex h-[var(--control-height)] items-center gap-2 rounded-[var(--radius-control)] border border-border/90 bg-input px-2.5 shadow-2xs transition-[border-color,box-shadow,background-color] duration-150 hover:border-border-strong',
      className
    )}>
      {pending ? (
        <LoaderCircle className="text-muted size-3.5 shrink-0 animate-spin" aria-hidden />
      ) : (
        <Search className="text-muted/80 size-3.5 shrink-0" aria-hidden />
      )}
      <input
        type="search"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        className="placeholder:text-muted/80 min-w-0 flex-1 [appearance:textfield] bg-transparent text-sm text-foreground outline-none [&::-webkit-search-cancel-button]:hidden"
        {...props}
      />
      {value ? (
        <button
          type="button"
          disabled={props.disabled}
          onClick={() => (onClear ? onClear() : onValueChange(''))}
          aria-label="Clear search"
          className="text-muted hover:bg-well hover:text-foreground -mr-1 grid size-5.5 place-items-center rounded-xs transition-colors disabled:pointer-events-none disabled:opacity-60"
        >
          <X className="size-3" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}
```

---

### 5. Select

- **Priority**: 5
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/select.tsx`)
- **Call Sites**: 22+

#### Current Weaknesses & Visual Debt
- Trigger icon does not rotate on open state.
- Popper dropdown has basic padding and lacks the refined menu item selection indicator styling from HeroUI.
- Max-height calculation can cause unexpected clipping on small screens.

#### HeroUI v3 Reference
- **Package**: `@heroui/select`
- **Slots**: `trigger`, `value`, `popoverContent`, `listbox`, `item`, `itemIndicator`
- **Patterns Adapted**:
  - Animated chevron rotation `data-[state=open]:rotate-180 transition-transform duration-150`.
  - Item styling: `rounded-xs px-2.5 py-1.5 text-xs font-medium` with subtle checkmark alignment.
  - Menu panel: `shadow-elevated rounded-[var(--radius-overlay)] border border-border bg-elevated/95 backdrop-blur-md`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/select.tsx
<SelectPrimitive.Trigger
  className={cn(
    'focus-ring flex h-[var(--control-height)] w-full items-center justify-between gap-2 rounded-[var(--radius-control)] border border-border/90 bg-input px-3 text-sm text-foreground shadow-2xs transition-[border-color,background-color,box-shadow] duration-150 hover:border-border-strong data-[placeholder]:text-muted disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger',
    className
  )}
>
  <SelectPrimitive.Value placeholder={placeholder} />
  <SelectPrimitive.Icon asChild>
    <ChevronDown className="text-muted size-3.5 shrink-0 transition-transform duration-150 ease-out [[data-state=open]>&]:rotate-180" aria-hidden />
  </SelectPrimitive.Icon>
</SelectPrimitive.Trigger>

<SelectPrimitive.Content
  position="popper"
  sideOffset={4}
  collisionPadding={8}
  className="menu-panel border-border bg-elevated/98 shadow-elevated z-[var(--z-index-overlay)] max-h-[min(22rem,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-overlay)] border p-1"
>
  <SelectPrimitive.Item
    className="focus:bg-background-alt focus:text-foreground data-[state=checked]:bg-accent-subtle data-[state=checked]:text-accent-text relative flex min-h-7.5 cursor-pointer items-center rounded-xs py-1.5 pr-8 pl-2.5 text-xs font-medium outline-none select-none transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-40"
  >
    <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
    <SelectPrimitive.ItemIndicator className="absolute right-2 inline-flex items-center">
      <Check className="size-3.5 text-accent" aria-hidden />
    </SelectPrimitive.ItemIndicator>
  </SelectPrimitive.Item>
</SelectPrimitive.Content>
```

---

### 6. Checkbox

- **Priority**: 6
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/checkbox.tsx`)
- **Call Sites**: 16+

#### Current Weaknesses & Visual Debt
- Checkbox square uses 6px radius (`rounded-[var(--radius-control)]`), which makes a 16px box look overly circular.
- Checkmark lacks pop-in spring/scale transition.
- Unchecked state border blends into light backgrounds.

#### HeroUI v3 Reference
- **Package**: `@heroui/checkbox`
- **Patterns Adapted**:
  - Micro-radius: `rounded-xs` (2.5px/3px) suited for a 16px square.
  - Active checkmark scale-in animation.
  - High-contrast idle border: `border-border-strong/90 hover:border-accent`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/checkbox.tsx
<CheckboxPrimitive.Root
  checked={checked}
  onCheckedChange={onCheckedChange}
  disabled={disabled}
  className="focus-ring border-border-strong bg-input-bg data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent text-accent-fg grid size-4 shrink-0 place-items-center rounded-xs border shadow-2xs transition-[background-color,border-color,box-shadow] duration-150 disabled:cursor-not-allowed disabled:opacity-50"
>
  <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current animate-in zoom-in-75 duration-100">
    {checked === 'indeterminate' ? (
      <Minus className="size-3 stroke-[3]" aria-hidden />
    ) : (
      <Check className="size-3 stroke-[3]" aria-hidden />
    )}
  </CheckboxPrimitive.Indicator>
</CheckboxPrimitive.Root>
```

---

### 7. RadioGroup

- **Priority**: 7
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/radio-group.tsx`)
- **Call Sites**: 8+

#### Current Weaknesses & Visual Debt
- Dot indicator snaps in without scale easing.
- Label baseline alignment is loose on multi-line text.

#### HeroUI v3 Reference
- **Package**: `@heroui/radio`
- **Patterns Adapted**:
  - Inner dot scale transition (`scale-0 data-[state=checked]:scale-100 duration-150`).
  - Consistent 16px outer disc with centered 6px dot.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/radio-group.tsx
<RadioGroupPrimitive.Item
  value={option.value}
  disabled={option.disabled}
  className="focus-ring border-border-strong bg-input-bg data-[state=checked]:border-accent grid size-4 shrink-0 place-items-center rounded-full border shadow-2xs transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50"
>
  <RadioGroupPrimitive.Indicator className="flex items-center justify-center">
    <span className="bg-accent size-2 rounded-full animate-in zoom-in-50 duration-150" />
  </RadioGroupPrimitive.Indicator>
</RadioGroupPrimitive.Item>
```

---

### 8. Switch

- **Priority**: 8
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/switch.tsx`)
- **Call Sites**: 10+

#### Current Weaknesses & Visual Debt
- Switch dimensions (`h-6 w-12`) are slightly large for dense enterprise tables.
- Thumb uses hairline border that creates fuzzy rendering on non-retina displays.

#### HeroUI v3 Reference
- **Package**: `@heroui/switch`
- **Patterns Adapted**:
  - Compact enterprise size: `h-5 w-9` track with `size-3.5` thumb.
  - Smooth translate positioning: `translate-x-0.5` to `translate-x-4.5`.
  - Crisp thumb shadow (`shadow-xs`) with pure white fill.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/switch.tsx
export function Switch({ checked, onCheckedChange, label, describedBy, disabled = false, className }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'focus-ring inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent transition-colors duration-200 ease-out disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-accent' : 'bg-background-alt border-border',
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          'bg-panel size-3.5 rounded-full shadow-xs transition-transform duration-200 ease-out',
          checked ? 'translate-x-4.5 bg-accent-fg' : 'translate-x-0.5'
        )}
      />
    </button>
  );
}
```

---

### 9. Tabs & NestedTabs

- **Priority**: 9
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/tabs.tsx`, `frontend/components/ui/nested-tabs.tsx`)
- **Call Sites**: 24+

#### Current Weaknesses & Visual Debt
- Tab underline bar is static without transition between active tabs.
- Tab triggers have top border radius (`rounded-t-[var(--radius-control)]`) with hover gray boxes that look dated.
- NestedTabs lacks a clear pill/segment visual separation from top-level tabs.

#### HeroUI v3 Reference
- **Package**: `@heroui/tabs`
- **Slots**: `tabList`, `tab`, `tabContent`, `cursor`, `panel`
- **Patterns Adapted**:
  - Clean bottom line with active accent bar that sits directly on the border line.
  - Hover state changes text color to `text-foreground` without jarring background box.
  - Nested tabs adapted to enclosed pill container format.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/tabs.tsx
<TabsPrimitive.List
  className={cn(
    'border-border-subtle relative flex w-full max-w-full flex-nowrap gap-6 overflow-x-auto border-b [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
    className
  )}
>
  {items.map((item) => (
    <TabsPrimitive.Trigger
      key={item.value}
      value={item.value}
      disabled={item.disabled}
      className="focus-ring text-secondary hover:text-foreground data-[state=active]:text-foreground relative inline-flex h-9 shrink-0 items-center pb-2.5 pt-1 text-xs font-semibold whitespace-nowrap transition-colors duration-150 disabled:opacity-40"
    >
      {item.label}
      {item.value === value ? (
        <span className="bg-accent absolute inset-x-0 bottom-0 h-0.5 rounded-full" />
      ) : null}
    </TabsPrimitive.Trigger>
  ))}
</TabsPrimitive.List>
```

---

### 10. SegmentedControl

- **Priority**: 10
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/segmented-control.tsx`, `frontend/components/ui/segmented-variants.ts`)
- **Call Sites**: 14+

#### Current Weaknesses & Visual Debt
- Uses `rounded-full` everywhere, creating a bubbly aesthetic that breaks the 6px control / 8px card rhythm.
- Active pill shadow is weak and does not pop against `bg-background-alt`.

#### HeroUI v3 Reference
- **Package**: `@heroui/tabs` (solid / segmented variant)
- **Patterns Adapted**:
  - Enterprise geometry: `rounded-[var(--radius-control)]` (6px) track with `rounded-xs` (4px) active segment.
  - Elevated active segment with `bg-panel text-foreground shadow-2xs font-semibold`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/segmented-variants.ts
export const segmentedTrackVariants = cva(
  'border-border/80 bg-background-alt/80 inline-flex min-h-[var(--control-height-sm)] items-center gap-0.5 rounded-[var(--radius-control)] border p-0.5 shadow-inner'
);

export const segmentedItemVariants = cva(
  'focus-ring inline-flex h-[calc(var(--control-height-sm)-6px)] items-center justify-center rounded-xs px-2.5 text-xs font-medium whitespace-nowrap transition-[background-color,color,box-shadow] duration-150 disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      selected: {
        true: 'bg-panel text-foreground font-semibold shadow-2xs border border-border/40',
        false: 'text-secondary hover:text-foreground',
      },
    },
    defaultVariants: { selected: false },
  }
);
```

---

### 11. Dialog (Modal)

- **Priority**: 11
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/dialog.tsx`)
- **Call Sites**: 18+

#### Current Weaknesses & Visual Debt
- Header and footer borders use `border-border-subtle` which can look faint.
- Close button is standard ghost button without fixed top-right coordinate lock.
- Modal lacks entrance animation keyframes (`scale-in` / `fade-in`).

#### HeroUI v3 Reference
- **Package**: `@heroui/modal`
- **Slots**: `backdrop`, `base`, `header`, `body`, `footer`, `closeButton`
- **Patterns Adapted**:
  - Scrim: `bg-overlay-scrim/60 backdrop-blur-xs` with smooth fade-in.
  - Dialog panel: `rounded-[var(--radius-overlay)] border border-border bg-elevated shadow-modal-value`.
  - Content structure with dedicated scroll body: `min-h-0 flex-1 overflow-y-auto px-6 py-4`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/dialog.tsx
<DialogPrimitive.Overlay className="bg-overlay-scrim/60 z-overlay fixed inset-0 backdrop-blur-xs animate-in fade-in-0 duration-200" />
<DialogPrimitive.Content
  className={cn(
    'border-border bg-elevated shadow-modal-value z-modal fixed top-1/2 left-1/2 flex max-h-[85vh] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-overlay)] border focus:outline-none animate-in fade-in-0 zoom-in-95 duration-200',
    className
  )}
>
  <header className="border-border-subtle flex items-start justify-between gap-4 border-b px-5 py-4">
    <div className="grid min-w-0 gap-1">
      <DialogPrimitive.Title className="text-foreground text-base font-semibold tracking-tight">
        {title}
      </DialogPrimitive.Title>
      {description && (
        <DialogPrimitive.Description className="text-secondary text-xs leading-normal">
          {description}
        </DialogPrimitive.Description>
      )}
    </div>
    <DialogPrimitive.Close asChild>
      <Button variant="ghost" size="iconSm" aria-label="Close dialog" className="-mr-1 -mt-1 text-muted hover:text-foreground">
        <X className="size-4" aria-hidden />
      </Button>
    </DialogPrimitive.Close>
  </header>
  <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm leading-relaxed">
    {children}
  </div>
  {footer && (
    <footer className="border-border-subtle bg-background-alt/30 flex items-center justify-end gap-2.5 border-t px-5 py-3 rounded-b-[var(--radius-overlay)]">
      {footer}
    </footer>
  )}
</DialogPrimitive.Content>
```

---

### 12. Drawer (Sheet)

- **Priority**: 12
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/drawer.tsx`)
- **Call Sites**: 15+

#### Current Weaknesses & Visual Debt
- Width hardcoded to `max-w-180` without responsive clamp.
- Header title truncates aggressively on mid-sized mobile screens.
- Slide-in animation relies on external CSS instead of inline Tailwind v4 utility keyframes.

#### HeroUI v3 Reference
- **Package**: `@heroui/drawer`
- **Patterns Adapted**:
  - Slide-in transition from right: `animate-in slide-in-from-right duration-250 ease-out`.
  - Header with sticky alignment, hairline separation, and responsive max-width (`w-full sm:max-w-md md:max-w-lg lg:max-w-xl`).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/drawer.tsx
<DialogPrimitive.Overlay className="bg-overlay-scrim/60 z-overlay fixed inset-0 backdrop-blur-xs animate-in fade-in-0 duration-200" />
<DialogPrimitive.Content
  className={cn(
    'border-border bg-elevated shadow-modal-value z-modal fixed inset-y-0 right-0 flex w-full max-w-full sm:max-w-md md:max-w-xl flex-col border-l focus:outline-none animate-in slide-in-from-right duration-250 ease-out',
    className
  )}
>
  <header className="border-border-subtle flex items-start justify-between gap-3 border-b px-5 py-4">
    <div className="min-w-0">
      <DialogPrimitive.Title className="text-foreground text-base font-semibold tracking-tight">
        {title}
      </DialogPrimitive.Title>
      {description && (
        <DialogPrimitive.Description className="text-secondary mt-0.5 text-xs leading-normal">
          {description}
        </DialogPrimitive.Description>
      )}
    </div>
    <DialogPrimitive.Close asChild>
      <Button variant="ghost" size="iconSm" aria-label={closeLabel} className="-mr-1 text-muted hover:text-foreground">
        <X className="size-4" aria-hidden />
      </Button>
    </DialogPrimitive.Close>
  </header>
  <div className={cn('min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-5 py-4', bodyClassName)}>
    {children}
  </div>
  {footer && (
    <footer className="border-border-subtle bg-background-alt/30 border-t px-5 py-3">
      {footer}
    </footer>
  )}
</DialogPrimitive.Content>
```

---

### 13. Dropdown (Menu)

- **Priority**: 13
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/dropdown.tsx`, `frontend/components/ui/menu-variants.ts`)
- **Call Sites**: 20+

#### Current Weaknesses & Visual Debt
- `menuItemVariants` has `min-h-8` with `rounded-sm` and generic highlighted background.
- Dropdown checkboxes and radios have static check placement without clean alignment locks.

#### HeroUI v3 Reference
- **Package**: `@heroui/dropdown`
- **Slots**: `base`, `content`, `item`, `itemContent`, `section`, `header`
- **Patterns Adapted**:
  - Menu panel: `p-1 rounded-[var(--radius-overlay)] border border-border bg-elevated/95 backdrop-blur-md shadow-elevated`.
  - Item: `min-h-7 px-2 py-1 text-xs font-medium rounded-xs hover:bg-background-alt transition-colors`.
  - Inset check indicators with crisp SVG alignment.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/menu-variants.ts
export const menuPanelClasses =
  'menu-panel border-border bg-elevated/98 shadow-elevated z-modal min-w-44 overflow-hidden rounded-[var(--radius-overlay)] border p-1 focus:outline-none animate-in fade-in-0 zoom-in-95 duration-100';

export const menuItemVariants = cva(
  'text-foreground hover:bg-background-alt focus:bg-background-alt data-[active=true]:bg-accent-subtle data-[active=true]:text-accent-text data-[state=checked]:bg-accent-subtle data-[state=checked]:text-accent-text relative flex min-h-7 cursor-pointer items-center gap-2 rounded-xs px-2 py-1.5 text-xs font-medium outline-none select-none transition-colors duration-100 data-[disabled]:pointer-events-none data-[disabled]:opacity-40',
  {
    variants: {
      inset: {
        true: 'ps-7 pe-2',
        false: 'px-2',
      },
      selected: {
        true: 'bg-accent-subtle text-accent-text font-semibold',
        false: null,
      },
    },
    defaultVariants: { inset: false, selected: false },
  }
);
```

---

### 14. Tooltip

- **Priority**: 14
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/tooltip.tsx`)
- **Call Sites**: 40+

#### Current Weaknesses & Visual Debt
- Currently uses `rounded-[var(--radius-overlay)]` (10px), which is absurdly round for a 22px tall tooltip box.
- Padding `px-1.5 py-1` is cramped on horizontal edges.

#### HeroUI v3 Reference
- **Package**: `@heroui/tooltip`
- **Patterns Adapted**:
  - Geometric proportion: `rounded-xs` (4px), `px-2.5 py-1 text-xs font-medium`.
  - High-contrast inverse surface: `bg-surface-inverse text-on-inverse shadow-elevated`.
  - Subtle entrance animation (`fade-in-0 zoom-in-95`).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/tooltip.tsx
<TooltipPrimitive.Content
  side={side}
  align={align}
  sideOffset={5}
  className={cn(
    'bg-surface-inverse text-on-inverse shadow-elevated z-modal max-w-tooltip rounded-xs px-2.5 py-1 text-xs font-medium select-none animate-in fade-in-0 zoom-in-95 duration-100',
    className
  )}
>
  {content}
  <TooltipPrimitive.Arrow className="fill-surface-inverse" />
</TooltipPrimitive.Content>
```

---

### 15. Toast

- **Priority**: 15
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/toast.tsx`)
- **Call Sites**: 12+

#### Current Weaknesses & Visual Debt
- Toast container layout uses hardcoded grid with basic border.
- Duration is fixed at 3500ms without progress indicator or swipe visual hint.

#### HeroUI v3 Reference
- **Package**: `@heroui/toast` (or notification pattern)
- **Patterns Adapted**:
  - Refined card layout: `rounded-[var(--radius-overlay)] border border-border bg-elevated/98 shadow-modal-value p-3.5`.
  - Left status icon anchored with semantic tone colors (success green, danger red).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/toast.tsx
<ToastPrimitive.Root
  key={message.id}
  duration={4000}
  className="border-border bg-elevated shadow-modal-value grid w-[min(24rem,calc(100vw-2rem))] grid-cols-[auto_1fr_auto] items-start gap-3 rounded-[var(--radius-overlay)] border p-3.5 animate-in slide-in-from-bottom-2 fade-in-0 duration-200"
>
  <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" aria-hidden />
  <div className="min-w-0">
    <ToastPrimitive.Title className="text-foreground text-xs font-semibold">
      {message.title}
    </ToastPrimitive.Title>
    {message.description && (
      <ToastPrimitive.Description className="text-secondary mt-0.5 text-xs leading-normal">
        {message.description}
      </ToastPrimitive.Description>
    )}
  </div>
  <ToastPrimitive.Close asChild>
    <button
      type="button"
      className="text-muted hover:text-foreground -mr-1 -mt-1 grid size-5 place-items-center rounded-xs transition-colors"
      aria-label="Dismiss notification"
    >
      <X className="size-3.5" aria-hidden />
    </button>
  </ToastPrimitive.Close>
</ToastPrimitive.Root>
```

---

### 16. Card & Compound Slots

- **Priority**: 16
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/card.tsx`, `frontend/components/ui/card-variants.ts`)
- **Call Sites**: 65+

#### Current Weaknesses & Visual Debt
- `CardHeader` has `pb-2` and `CardContent` has `p-[var(--card-padding)]`, leading to doubled vertical padding inside cards.
- Borderless header relies on spacing alone, which looks indistinct when cards contain charts or tables.
- Card hover elevation transition is missing subtle hairline brightening.

#### HeroUI v3 Reference
- **Package**: `@heroui/card`
- **Slots**: `base`, `header`, `body`, `footer`
- **Patterns Adapted**:
  - Consistent padding rhythm: Header `px-4 pt-4 pb-2`, Content `px-4 pb-4`, Footer `px-4 py-3 bg-background-alt/30`.
  - Border hairline with `border-border/80 bg-panel shadow-card rounded-[var(--radius-card)]`.
  - Optional interactive card hover state: `hover:border-border-strong hover:shadow-card-hover transition-all duration-200`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/card.tsx
export function Card({ children, className, interactive, ...props }: CardProps) {
  return (
    <section
      {...props}
      className={cn(
        'border-border/80 bg-panel shadow-card rounded-[var(--radius-card)] border transition-[border-color,box-shadow] duration-150',
        interactive && 'cursor-pointer hover:border-border-strong hover:shadow-card-hover',
        className
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({ children, className, bordered, ...props }: CardHeaderProps) {
  return (
    <header
      {...props}
      className={cn(
        'flex flex-col gap-1 px-4 pt-4 pb-2',
        bordered && 'border-border-subtle border-b pb-3',
        className
      )}
    >
      {children}
    </header>
  );
}

export function CardContent({ children, className, ...props }: CardContentProps) {
  return (
    <div {...props} className={cn('px-4 pb-4 pt-1', className)}>
      {children}
    </div>
  );
}
```

---

### 17. Badge & IconChip

- **Priority**: 17
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/badge.tsx`, `frontend/components/ui/badge-variants.ts`, `frontend/components/ui/icon-chip.tsx`)
- **Call Sites**: 45+

#### Current Weaknesses & Visual Debt
- `badgeBase` uses `rounded-sm px-2 py-0.5 text-xs font-semibold` with a colored dot, but some badges lack crisp contrast against colored panel cards.
- `analyzing` run status badge uses raw Tailwind class `border-purple-200` instead of a semantic token.

#### HeroUI v3 Reference
- **Package**: `@heroui/chip` / `@heroui/badge`
- **Patterns Adapted**:
  - Precise micro-token color mapping (border + background + text).
  - Dot indicator alignment: `size-1.5 rounded-full bg-current shrink-0`.
  - Standardized font styling: `text-2xs font-semibold uppercase tracking-wider` or `text-xs font-medium`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/badge-variants.ts
export const badgeBase =
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-xs px-2 py-0.5 text-xs font-medium select-none';

export const runStatusBadge = {
  draft: 'bg-run-draft-bg text-run-draft border border-border/80',
  queued: 'bg-run-queued-bg text-run-queued border border-border/80',
  running: 'bg-run-running-bg text-run-running border border-accent-border/60 animate-pulse',
  paused: 'bg-run-queued-bg text-run-queued border border-border/80',
  analyzing: 'bg-accent-subtle text-accent-text border border-accent-border/60',
  completed: 'bg-run-completed-bg text-run-completed border border-success-border/60',
  partial: 'bg-run-partial-bg text-run-partial border border-warning-border/60',
  failed: 'bg-run-failed-bg text-run-failed border border-danger-border/60',
  cancelled: 'bg-run-cancelled-bg text-run-cancelled border border-border/80',
} as const;
```

---

### 18. FilterChip

- **Priority**: 18
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/filter-chip.tsx`, `frontend/components/ui/filter-chip-variants.ts`)
- **Call Sites**: 12+

#### Current Weaknesses & Visual Debt
- Inconsistent border/radius with standard button/control components.
- Count numeral lacks tabular alignment.

#### HeroUI v3 Reference
- **Package**: `@heroui/chip` (filter variant)
- **Patterns Adapted**:
  - Control height matching: `h-6 px-2 text-xs rounded-xs font-medium`.
  - Active toggle state: `bg-accent-subtle text-accent-text border-accent-border`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/filter-chip-variants.ts
export function filterChipClasses(active: boolean): string {
  return cn(
    'focus-ring inline-flex h-6 items-center gap-1.5 rounded-xs border px-2 text-xs font-medium transition-all select-none',
    active
      ? 'border-accent-border bg-accent-subtle text-accent-text font-semibold shadow-2xs'
      : 'border-border/80 bg-panel text-secondary hover:border-border-strong hover:bg-background-alt hover:text-foreground'
  );
}
```

---

### 19. Table & TableRecordMetricCell

- **Priority**: 19
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/table.tsx`)
- **Call Sites**: 16+

#### Current Weaknesses & Visual Debt
- Sticky `th` uses `border-b-2` which creates a heavy line compared to the rest of the table.
- Row hover is subtle (`hover:bg-background-alt`) and lacks row-level focus ring for keyboard navigation.
- Cell padding varies across screen sizes unpredictably.

#### HeroUI v3 Reference
- **Package**: `@heroui/table`
- **Slots**: `base`, `table`, `thead`, `tbody`, `tr`, `th`, `td`
- **Patterns Adapted**:
  - Sticky header: `bg-background-alt/80 backdrop-blur-xs border-b border-border text-xs font-semibold text-secondary`.
  - Row transition: `hover:bg-background-alt/60 transition-colors duration-100`.
  - Cell padding: `px-3.5 py-2.5 text-xs text-foreground align-middle`.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/table.tsx
export function TableHead({ children, className, numeric, ...props }: TableHeadProps) {
  return (
    <th
      {...props}
      className={cn(
        'border-border-subtle bg-panel sticky top-0 z-10 h-8 border-b px-3.5 text-left align-middle text-xs font-medium text-secondary whitespace-nowrap select-none',
        numeric && 'tabular-nums text-right',
        className
      )}
    >
      {children}
    </th>
  );
}

export function TableCell({ children, className, numeric, ...props }: TableCellProps) {
  return (
    <td
      {...props}
      className={cn(
        'border-border-subtle border-b px-3.5 py-2.5 text-left align-middle text-xs text-foreground',
        numeric && 'tabular-nums text-right font-mono',
        className
      )}
    >
      {children}
    </td>
  );
}
```

---

### 20. TablePagination & CursorPager

- **Priority**: 20
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/table-pagination.tsx`, `frontend/components/ui/cursor-pager.tsx`)
- **Call Sites**: 8+

#### Current Weaknesses & Visual Debt
- Pagination buttons use text links instead of unified icon button controls.
- Record range text lacks mono tabular numeral alignment.

#### HeroUI v3 Reference
- **Package**: `@heroui/pagination`
- **Patterns Adapted**:
  - Compact pager bar: border-t pinned to table container footer with `h-[var(--control-height-sm)]` icon buttons.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/cursor-pager.tsx
<div className="border-border-subtle flex items-center justify-between border-t px-4 py-2.5 text-xs text-secondary">
  <span className="font-mono tabular-nums">{recordCountText}</span>
  <div className="flex items-center gap-1">
    <Button variant="secondary" size="iconSm" disabled={!hasPrev} onClick={onPrev} aria-label="Previous page">
      <ChevronLeft className="size-3.5" />
    </Button>
    <Button variant="secondary" size="iconSm" disabled={!hasNext} onClick={onNext} aria-label="Next page">
      <ChevronRight className="size-3.5" />
    </Button>
  </div>
</div>
```

---

### 21. Alert & MutationNotice

- **Priority**: 21
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/alert.tsx`, `frontend/components/ui/alert-variants.ts`, `frontend/components/ui/mutation-notice.tsx`)
- **Call Sites**: 20+

#### Current Weaknesses & Visual Debt
- Alert currently renders inline text without container framing (`alertVariants` is plain text without background), which gets lost on busy data pages.
- `MutationNotice` has a separate container style from `Alert`.

#### HeroUI v3 Reference
- **Package**: `@heroui/alert`
- **Patterns Adapted**:
  - Enclosed soft alert card: `rounded-[var(--radius-control)] border p-3 text-xs flex items-start gap-2.5`.
  - Tonal palettes:
    - Danger: `bg-danger-bg text-danger-text border-danger-border/60`
    - Warning: `bg-warning-bg text-warning-text border-warning-border/60`
    - Success: `bg-success-bg text-success-text border-success-border/60`
    - Info: `bg-info-bg text-info-text border-info-border/60`

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/alert-variants.ts
export const alertVariants = cva(
  'flex items-start gap-2.5 rounded-[var(--radius-control)] border p-3 text-xs leading-normal',
  {
    variants: {
      tone: {
        danger: 'bg-danger-bg text-danger-text border-danger-border/60 [&_svg]:text-danger',
        warning: 'bg-warning-bg text-warning-text border-warning-border/60 [&_svg]:text-warning',
        success: 'bg-success-bg text-success-text border-success-border/60 [&_svg]:text-success',
        info: 'bg-info-bg text-info-text border-info-border/60 [&_svg]:text-info',
        neutral: 'bg-background-alt text-secondary border-border [&_svg]:text-muted',
      },
    },
    defaultVariants: { tone: 'danger' },
  }
);
```

---

### 22. EmptyState

- **Priority**: 22
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/empty-state.tsx`)
- **Call Sites**: 14+

#### Current Weaknesses & Visual Debt
- `EmptyState` wraps content in a `Card` directly, forcing standard card padding even when full-height centering is desired.
- Icon chip uses large circular background (`IconChip`) that feels detached from the heading.

#### HeroUI v3 Reference
- **Package**: HeroUI Empty state pattern
- **Patterns Adapted**:
  - Centered visual hierarchy with softened icon badge (`rounded-sm bg-background-alt p-3`).
  - Strict typography limit: max-width 44ch, single sentence description, primary CTA button.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/empty-state.tsx
export function EmptyState({ icon: Icon, heading, description, action, footnote, className }: EmptyStateProps) {
  return (
    <div className={cn('grid justify-items-center gap-3.5 py-12 px-4 text-center', className)}>
      <div className="border-border/80 bg-background-alt flex size-11 items-center justify-center rounded-[var(--radius-control)] border shadow-2xs text-secondary">
        <Icon className="size-5" aria-hidden />
      </div>
      <div className="grid gap-1">
        <h3 className="font-display text-foreground text-sm font-semibold tracking-tight">{heading}</h3>
        {description && <p className="text-secondary mx-auto max-w-[42ch] text-xs leading-relaxed">{description}</p>}
      </div>
      {action && <div className="mt-1 flex items-center gap-2">{action}</div>}
      {footnote && <div className="text-muted text-2xs mt-2">{footnote}</div>}
    </div>
  );
}
```

---

### 23. Skeleton

- **Priority**: 23
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/skeleton.tsx`)
- **Call Sites**: 15+

#### Current Weaknesses & Visual Debt
- Shimmer keyframe in `globals.css` uses raw gradient angles that create noticeable banding on retina displays.

#### HeroUI v3 Reference
- **Package**: `@heroui/skeleton`
- **Patterns Adapted**:
  - Smooth linear gradient shimmer between `--skeleton-base` (`#f0f0f0`) and `--skeleton-highlight` (`#fafafa`).
  - Rounded token adherence (`rounded-xs` for text lines, `rounded-[var(--radius-control)]` for buttons, `rounded-[var(--radius-card)]` for cards).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/skeleton.tsx
export function Skeleton({ className, ...props }: Readonly<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      aria-hidden
      className={cn(
        'bg-neutral-bg relative overflow-hidden rounded-xs before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_1.6s_infinite] before:bg-gradient-to-r before:from-transparent before:via-panel/60 before:to-transparent',
        className
      )}
      {...props}
    />
  );
}
```

---

### 24. ScoreRing & ScoreBar

- **Priority**: 24
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/score-ring.tsx`, `frontend/components/ui/score-bar.tsx`)
- **Call Sites**: 10+

#### Current Weaknesses & Visual Debt
- Score ring numeral sizes (`text-heading-sm`, `text-xl`, `text-2xl`) don't scale proportionally with arbitrary SVG diameters.
- Track background stroke uses `stroke-well` which can blend into background panels.

#### HeroUI v3 Reference
- **Package**: `@heroui/progress` (Circular progress variant)
- **Patterns Adapted**:
  - Crisp hairline track circle (`stroke-border/60`).
  - Animated dashoffset sweep with ease-out cubic curve (800ms).
  - High-legibility tabular mono numeral centered with precision.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/score-ring.tsx
<circle
  cx={size / 2}
  cy={size / 2}
  r={radius}
  fill="none"
  strokeWidth={strokeWidth}
  className="stroke-border/40"
/>
<circle
  cx={size / 2}
  cy={size / 2}
  r={radius}
  fill="none"
  strokeWidth={strokeWidth}
  strokeLinecap="round"
  strokeDasharray={circumference}
  strokeDashoffset={swept ? dashOffset : circumference}
  className={cn(
    'transition-[stroke-dashoffset] duration-700 ease-out motion-reduce:transition-none',
    scoreBandStroke[band]
  )}
/>
```

---

### 25. ActivityProgress

- **Priority**: 25
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/activity-progress.tsx`)
- **Call Sites**: 4+

#### Current Weaknesses & Visual Debt
- Vertical connector line has hardcoded minimum height (`min-h-5 w-px`) that misaligns when step descriptions wrap onto multiple lines.
- Active pulsing dot lacks soft outer glow.

#### HeroUI v3 Reference
- **Package**: Timeline / Progress stepper pattern
- **Patterns Adapted**:
  - Connected vertical rail with continuous hairline layout.
  - Crisp indicator nodes: `complete` (green check), `active` (accent ring pulse), `pending` (subtle disc).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/activity-progress.tsx
<span
  className={cn(
    'relative z-1 flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
    step.state === 'complete' && 'bg-success text-accent-fg shadow-2xs',
    step.state === 'active' && 'bg-accent text-accent-fg ring-4 ring-accent/20',
    step.state === 'attention' && 'bg-warning-bg text-warning-text border border-warning-border',
    step.state === 'pending' && 'border-border bg-panel text-muted border'
  )}
>
  <StepIndicator state={step.state} />
</span>
```

---

### 26. Typography (SectionTitle, Label, Metric, Eyebrow)

- **Priority**: 26
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/typography.tsx`, `frontend/components/ui/eyebrow.tsx`)
- **Call Sites**: 51 (26 typography + 25 eyebrow)

#### Current Weaknesses & Visual Debt
- `displayHeadingXlClasses` is `text-2xl font-semibold tracking-[-0.025em]` which is too large for dense sub-panels.
- `Label` uses `eyebrowClasses` which forces uppercase tracking on elements that should be sentence case.
- Monospace metric numerals lack consistent tabular numerals styling across cards.

#### HeroUI v3 Reference
- **Package**: `@heroui/typography`
- **Slots**: `base`, `title`, `subtitle`, `description`
- **Patterns Adapted**:
  - Harmonized typographic scale:
    - Display Heading XL: `font-display text-2xl sm:text-3xl font-semibold tracking-tight text-foreground`
    - Display Heading LG: `font-display text-lg sm:text-xl font-semibold tracking-tight text-foreground`
    - Section Title: `font-display text-sm font-semibold tracking-tight text-foreground`
    - Metric numeral: `font-mono text-2xl font-semibold tracking-tight tabular-nums text-foreground`
    - Micro label / Eyebrow: `text-2xs font-semibold uppercase tracking-wider text-muted`

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/typography.tsx
export const displayHeadingXlClasses =
  'font-display text-2xl sm:text-3xl font-semibold tracking-tight text-foreground';
export const displayHeadingLgClasses =
  'font-display text-lg sm:text-xl font-semibold tracking-tight text-foreground';
export const sectionTitleClasses =
  'font-display text-sm font-semibold tracking-tight text-foreground';
export const metricNumeralClasses =
  'font-mono text-2xl font-semibold tracking-tight tabular-nums text-foreground';

export function SectionTitle({
  children,
  className,
  ...props
}: React.ComponentPropsWithoutRef<'h3'>) {
  return (
    <h3 className={cn(sectionTitleClasses, className)} {...props}>
      {children}
    </h3>
  );
}

export function Metric({
  children,
  className,
  ...props
}: React.ComponentPropsWithoutRef<'div'>) {
  return (
    <div className={cn(metricNumeralClasses, className)} {...props}>
      {children}
    </div>
  );
}

export function Label({
  children,
  className,
  ...props
}: React.ComponentPropsWithoutRef<'span'>) {
  return (
    <span className={cn('text-xs font-medium text-foreground', className)} {...props}>
      {children}
    </span>
  );
}

// frontend/components/ui/eyebrow.tsx
export interface EyebrowProps extends React.HTMLAttributes<HTMLElement> {
  as?: 'p' | 'span' | 'h2' | 'h3' | 'h4' | 'div';
}

export function Eyebrow({
  children,
  className,
  as: Component = 'p',
  ...props
}: EyebrowProps) {
  return (
    <Component
      className={cn('text-2xs font-semibold uppercase tracking-wider text-muted', className)}
      {...props}
    >
      {children}
    </Component>
  );
}
```

#### DOM Structure & Slot Breakdown
- **Root Element**: Semantic HTML heading (`h2`, `h3`), paragraph (`p`), span (`span`), or div (`div`) mapped to design tokens.
- **Micro Label / Eyebrow**: Uppercase badge-style tracking for contextual category tags and card subheadings.

#### Tailwind Utility Classes & Tokens
- **Font Families**: `font-display` (Plus Jakarta Sans / Geist Display), `font-mono tabular-nums` (Geist Mono).
- **Tracking**: `tracking-tight` (`-0.015em`), `tracking-wider` (`0.05em` on micro-eyebrows).
- **Colors**: `text-foreground`, `text-secondary`, `text-muted`.

#### States & Micro-Interactions
- **Text Selection**: Inherits global `selection:bg-accent-subtle selection:text-accent-text`.
- **Truncation**: `truncate` / `line-clamp-2` where container constrained.

#### Isolation Boundary & Architectural Guardrails
- Zero Radix or external library dependencies.
- Pure semantic typography wrappers providing consistent headings and metrics throughout all feature cards.

---

### 27. BrandLogo & LogoMark

- **Priority**: 27
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/brand-logo.tsx`, `frontend/components/ui/logo-mark.tsx`)
- **Call Sites**: 13 (9 BrandLogo + 4 LogoMark)

#### Current Weaknesses & Visual Debt
- Fallback avatar for missing domain logos uses a single letter with inconsistent background color hashing and raw pixel sizing.
- LogoMark has hardcoded fill colors that bypass dark mode canvas contrast tokens.

#### HeroUI v3 Reference
- **Package**: `@heroui/avatar`
- **Slots**: `base`, `img`, `fallback`, `name`
- **Patterns Adapted**:
  - Consistent size ladder: `xs` (`size-4.5`), `sm` (`size-6`), `md` (`size-8`), `lg` (`size-10`).
  - Micro-radius control: `rounded-xs` (4px) or `rounded-[var(--radius-control)]` (6px).
  - Crisp hairline border: `border border-border/80 bg-panel shadow-2xs`.
  - Structured image load state handling with graceful monogram fallback.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/brand-logo.tsx
export interface BrandLogoProps {
  url?: string | null;
  name: string;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  className?: string;
}

export function BrandLogo({ url, name, size = 'md', className }: BrandLogoProps) {
  const [hasError, setHasError] = useState(false);

  const sizeClasses = {
    xs: 'size-4.5 text-2xs rounded-xs',
    sm: 'size-6 text-xs rounded-xs',
    md: 'size-8 text-sm rounded-[var(--radius-control)]',
    lg: 'size-10 text-base rounded-[var(--radius-control)]',
  }[size];

  if (!url || hasError) {
    return (
      <span
        aria-label={name}
        className={cn(
          'border-border/80 bg-panel text-secondary inline-flex shrink-0 items-center justify-center border font-semibold select-none shadow-2xs',
          sizeClasses,
          className
        )}
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      src={url}
      alt={name}
      onError={() => setHasError(true)}
      className={cn(
        'border-border/60 bg-panel shrink-0 border object-contain shadow-2xs',
        sizeClasses,
        className
      )}
    />
  );
}

// frontend/components/ui/logo-mark.tsx
export interface LogoMarkProps {
  size?: 'sm' | 'md' | 'lg';
  surface?: 'dark' | 'light' | 'auto';
  className?: string;
}

export function LogoMark({ size = 'md', surface = 'auto', className }: LogoMarkProps) {
  const sizeMap = { sm: 18, md: 24, lg: 32 };
  const px = sizeMap[size];

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('shrink-0 text-foreground', className)}
      aria-hidden="true"
    >
      <path
        d="M3 18L9 6L15 14L21 3"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
```

#### DOM Structure & Slot Breakdown
- **`BrandLogo` Root**: `<img>` element with `object-contain` or `<span>` monogram fallback.
- **`LogoMark` Root**: `<svg>` geometric ladder icon bound to `currentColor`.

#### Tailwind Utility Classes & Tokens
- **Borders & Shadows**: `border border-border/80 bg-panel shadow-2xs`.
- **Dimensions**: `size-4.5` (18px), `size-6` (24px), `size-8` (32px), `size-10` (40px).

#### States & Micro-Interactions
- **Image Error / Fallback**: Immediate fallback to monogram container without cumulative layout shift.

#### Isolation Boundary & Architectural Guardrails
- Self-contained image and SVG primitives.
- No external asset dependencies or un-scoped image CDNs.

---

### 28. CommandPalette

- **Priority**: 28
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/command-palette.tsx`)
- **Call Sites**: 2 (AppShell & TopNav)

#### Current Weaknesses & Visual Debt
- Search trigger button styling is `size="lg"` with wide margins that do not match topbar height.
- Item row hover styling uses manual active descendant styling that can flicker during fast keyboard navigation.
- Missing structured keyboard shortcut legend in modal footer.

#### HeroUI v3 Reference
- **Package**: `@heroui/autocomplete` / `@heroui/modal`
- **Slots**: `base`, `backdrop`, `dialog`, `header`, `input`, `listbox`, `item`, `footer`, `kbd`
- **Patterns Adapted**:
  - Frosted dialog panel with backdrop blur (`backdrop-blur-xl bg-elevated/95 border border-border/80 shadow-modal-value`).
  - Search input with inline keyboard shortcut badge (`ESC`).
  - Active item indicator with smooth background transition (`bg-accent-subtle text-accent-text font-medium`).
  - Footer legend with structured keyboard pills.

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/command-palette.tsx
export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect?: (itemId: string) => void;
}

export function CommandPalette({ open, onOpenChange, onSelect }: CommandPaletteProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="bg-background-backdrop/60 z-[var(--z-index-overlay)] fixed inset-0 backdrop-blur-xs animate-in fade-in-0 duration-150" />
        <Dialog.Content className="border-border/80 bg-elevated/95 shadow-modal-value z-[var(--z-index-overlay)] fixed top-20 left-1/2 flex max-h-[60vh] w-full max-w-xl -translate-x-1/2 flex-col overflow-hidden rounded-[var(--radius-overlay)] border backdrop-blur-xl animate-in zoom-in-95 duration-150 focus:outline-none">
          <div className="border-border flex h-11 items-center gap-2.5 border-b px-3.5">
            <Search className="text-muted size-4 shrink-0" aria-hidden />
            <input
              className="placeholder:text-muted min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none"
              placeholder="Search workspaces, pages, prompts, issues... (Type / for commands)"
            />
            <kbd className="border-border bg-background-alt text-muted rounded-xs border px-1.5 py-0.5 text-2xs font-mono font-medium">
              ESC
            </kbd>
          </div>
          <div className="scrollbar-thin flex-1 overflow-y-auto p-1.5">
            {/* List items with bg-accent-subtle on active selection */}
          </div>
          <div className="border-border bg-background-alt/50 text-muted flex items-center justify-between border-t px-3 py-1.5 text-2xs">
            <span>Quick Navigation</span>
            <div className="flex items-center gap-2">
              <span>
                <kbd className="border-border bg-panel rounded border px-1">↑</kbd>{' '}
                <kbd className="border-border bg-panel rounded border px-1">↓</kbd> to navigate
              </span>
              <span>
                <kbd className="border-border bg-panel rounded border px-1">↵</kbd> to select
              </span>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```

#### DOM Structure & Slot Breakdown
- **Overlay Slot**: Full-screen backdrop with `backdrop-blur-xs` and subtle darkening.
- **Content Slot**: Elevated floating panel with 10px radius (`rounded-[var(--radius-overlay)]`) and `shadow-modal-value`.
- **Search Header**: Input row with leading `Search` icon and trailing `ESC` shortcut badge.
- **Listbox Slot**: Scrollable results list with keyboard active highlight.
- **Footer Slot**: Key legend pills explaining keyboard navigation.

#### Tailwind Utility Classes & Tokens
- **Overlay & Panel**: `bg-elevated/95 backdrop-blur-xl border-border/80 shadow-modal-value rounded-[var(--radius-overlay)]`.
- **Active Item**: `bg-accent-subtle text-accent-text rounded-[var(--radius-control)]`.
- **Keyboard Badges**: `border-border bg-panel text-muted rounded-xs border text-2xs font-mono`.

#### States & Micro-Interactions
- **Open / Close**: 150ms fade-in + zoom-in-95 ease-out transition.
- **Item Highlight**: Immediate background shift on arrow key navigation without layout jitter.

#### Isolation Boundary & Architectural Guardrails
- Encapsulates `@radix-ui/react-dialog` inside `frontend/components/ui/command-palette.tsx`.
- App shell and top nav import only `CommandPalette` without direct Radix imports.

---

### 29. CopyButton

- **Priority**: 29
- **Confidence**: High
- **Isolation Level**: Canonical UI Primitive (`frontend/components/ui/copy-button.tsx`)
- **Call Sites**: 10+ (Code snippets, IDs, Prompt copy buttons)

#### Current Weaknesses & Visual Debt
- Checkmark transition instantly swaps without micro-scale animation.
- Hardcoded timeout (1800ms) can cause race conditions on rapid clicking.

#### HeroUI v3 Reference
- **Package**: `@heroui/snippet`
- **Slots**: `base`, `content`, `copyButton`
- **Patterns Adapted**:
  - Smooth icon crossfade with scale-in animation (`animate-in zoom-in-75 duration-150`).
  - Clear copied state feedback with reset timeout via `useRef`.
  - Accessible `aria-label` dynamic update (`"Copy to clipboard"` -> `"Copied!"`).

#### Exact CiteLadder Adaptation
```tsx
// frontend/components/ui/copy-button.tsx
export interface CopyButtonProps {
  value: string;
  children?: React.ReactNode;
  copiedLabel?: string;
  iconOnly?: boolean;
  variant?: 'primary' | 'secondary' | 'tonal' | 'neutral' | 'ghost';
  size?: 'sm' | 'md' | 'lg' | 'icon' | 'iconSm';
  className?: string;
}

export function CopyButton({
  value,
  children,
  copiedLabel = 'Copied!',
  iconOnly = false,
  variant = 'ghost',
  size = 'sm',
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback handling if clipboard permissions are denied
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      onClick={handleCopy}
      aria-label={copied ? copiedLabel : 'Copy to clipboard'}
      className={cn('transition-all duration-150', className)}
    >
      <span className="relative flex items-center justify-center">
        {copied ? (
          <Check className="text-success size-3.5 animate-in zoom-in-75 duration-150" aria-hidden />
        ) : (
          <Copy className="text-muted size-3.5 animate-in zoom-in-75 duration-150" aria-hidden />
        )}
      </span>
      {!iconOnly && <span>{copied ? copiedLabel : children ?? 'Copy'}</span>}
    </Button>
  );
}
```

#### DOM Structure & Slot Breakdown
- **Root Element**: Canonical `<Button>` primitive (`button.tsx`).
- **Icon Slot**: `<span>` wrapper containing crossfading `<Copy>` / `<Check>` icon.
- **Label Slot**: Optional text label transitioning between default and `copiedLabel`.

#### Tailwind Utility Classes & Tokens
- **Animated Icon**: `animate-in zoom-in-75 duration-150`.
- **Copied State**: `text-success`.
- **Button Variant**: Inherits `variant="ghost"` and `size="sm"` control tokens.

#### States & Micro-Interactions
- **Copied**: Icon morphs from `Copy` to `Check` with 75% zoom-in easing; reverts after 2000ms.
- **Hover / Active**: Inherits standard `<Button>` interactions with popup suppression invariant.

#### Isolation Boundary & Architectural Guardrails
- Composed on top of canonical `Button` primitive.
- Standard browser `navigator.clipboard` API with try-catch safeguard.

---

## Complete Quality & Verification Checklist

Implementing agents (Codex) must verify:
- [ ] No installation of external dependencies (HeroUI, React Aria, Base UI, Lucide replacements).
- [ ] Direct `@radix-ui/*` imports remain strictly confined inside `frontend/components/ui/*`.
- [ ] No regression in keyboard accessibility (Roving Tabindex, APG patterns, Focus rings).
- [ ] All IDs remain UUIDs; workspace scoping invariant intact.
- [ ] Static validation passes completely: `.\scripts\check.ps1` and `.\scripts\test.ps1`.
