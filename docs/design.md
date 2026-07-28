# Design System — Searchify

> The **written form** of the Searchify design system, and its authority. The app runs on the
> **Atlassian Design System**, flat 2.0: **`frontend/app/ds-tokens.css`** holds the ADS
> primitives (`--ds-*`; ADS light/semantic ramps plus neutral dark overrides) and
> **`frontend/app/globals.css`** holds the semantic layer that maps onto them. The previous
> Figma port — royal blue `#2756FF` and the authored warm-charcoal "dusk" dark deck — is fully
> replaced. The public surface (marketing routes **and** the logged-out auth screens) still
> runs its own creative system, **Searchify Proof**, in
> `frontend/app/(marketing)/marketing-theme.css`; folding it onto the ADS layer is Phase 2.
> Machine guards keep this document, the token files, elevation, and WCAG AA in sync
> (`frontend/app/globals.test.ts`, `frontend/scripts/check-design-tokens.mjs`,
> `frontend/scripts/check-elevation.mjs`).
> Companion docs: [`../Agents.md`](../Agents.md), [`invariants.md`](invariants.md),
> [`backend-architecture.md`](backend-architecture.md), [`frontend-architecture.md`](frontend-architecture.md).

## 1. Overview

- **Two files, one direction of flow.** `ds-tokens.css` owns ADS *values*; `globals.css` owns
  *meanings* and the Tailwind bridge. Components consume **bridged Tailwind semantic tokens
  only** — never raw hex (no-raw-hex guard), and never a bare `--ds-*` name.

  ```
  ds-tokens.css  →  globals.css  →  @theme inline  →  components
  (ADS values)      (semantics)     (utilities)       (classes)
  ```

- **Aesthetic**: dense, confident **B2B analytics** in the Atlassian visual language — a
  `#F7F8F9` sunken canvas, white panels separated by **a tint step and a 1px alpha hairline**,
  one **ADS blue accent `#0C66E4`** reserved for data, links, active states and focus rings,
  the ADS accent ramp for every semantic hue, **Google Sans** for UI text and data
  (tabular numerals — no monospace is shipped), **Space Grotesk** for app
  headings/display (marketing headlines stay **Geist Medium**), 4px grid, WCAG 2.1 AA.
- **Elevation is the ADS surface/shadow pairing, and it is a hard rule** — see §4a. Cards
  rest on the raised rung and carry **no border** (light, not an outline, separates the
  card); interactive cards lift to the overlay rung on hover; true overlays own the overlay
  rung. Nothing else casts a shadow, and `check-elevation.mjs` enforces the rung
  assignments. This replaced the short-lived "flat 2.0" experiment: an all-flat UI read as
  dull and unfinished, and the borderless-elevated model is what atlassian.design, Gmail,
  and Trello actually ship.
- **Light is the default theme.** Dark is a full sibling and costs almost nothing to maintain:
  every semantic token resolves through a `var(--ds-*)` that already flips, so the dark block
  in `globals.css` is a single `color-scheme: dark` line. Every documented text/surface pair in
  **both** themes meets **AA ≥ 4.5:1**, computed programmatically in `globals.test.ts`.

## 2. Theme model

Two explicit surface hierarchies. `:root` = light (default), `html[data-theme='dark']` = dark —
the selector under which **both** files declare their values. A pre-hydration script sets
`data-theme` before first paint. **Light is the default**: the bootstrap resolves
`stored choice → light`; the OS preference is intentionally not consulted — only an explicit
stored `dark` choice (from any ThemeToggle) opts into dark.

**Light surface ladder:** canvas `--bg-base #F1F2F4` (`--ds-surface-canvas`, see §4) → panels
`--bg-panel #FFFFFF` (`surface`) → `--bg-elevated #FFFFFF` (`surface-raised`) → overlays
`#FFFFFF`. Sidebar = panel `#FFFFFF`.

**Dark surface ladder:** canvas `#111111` → panel `#181818` → elevated `#202020` → overlay
`#282828` (strictly ascending luminance). Sidebar = panel. Neutral surfaces, text and borders
use an achromatic editor-style ramp; semantic accent/status colors remain ADS.

Note the inversion: **the canvas is recessed and cards sit on it.** The tint step plus the
raised shadow carry the hierarchy — the card is borderless, so the two together do all of
the separation. `--bg-alt` (6%) and `--bg-well` (14%) are the
ADS **alpha** neutral at two depths, and `--bg-active` (31%) is the pressed step — because they
are alpha, a quiet button or a well looks correct on a white card, on the sunken canvas, and
inside a tinted panel. An opaque grey only ever matched one of the three.

**The accent no longer changes hue between themes.** Under the dusk system light royal blue +
dark violet was a deliberate split; ADS uses one blue family throughout
(`#0C66E4` → `#579DFF`), so the two themes now agree. In both, the accent is reserved for
links, active states, focus rings and data visualization. Owned citations track the accent
(blue); the former green owned-citation identity remains dropped.

## 3. Atlassian → Searchify token mapping

Rule: **the semantic name stays, the value comes from ADS.** This is what made the port
tractable — because all 218 components already consumed bridged semantic names only, and the
repo held zero raw hex, zero palette-direct utilities and zero `dark:` variants, repointing the
value layer restyled the whole app without touching component code.

| ADS primitive | Searchify token(s) | Notes |
|---|---|---|
| `accent.gray.subtlest` / neutral dark override (as `--ds-surface-canvas`) | `--bg-base` | the app canvas is **recessed** — `#F1F2F4` / `#111111`; a measured departure from ADS `surface.sunken` (§4) |
| `elevation.surface` | `--bg-panel`, `--bg-sidebar` | cards, tables, and the sidebar+topbar chrome frame |
| `elevation.surface.raised` | `--bg-elevated` | dropdowns, drawers, tooltips; in light it equals `surface` (ADS separates them with the raised shadow, which flat 2.0 bans) |
| `elevation.surface.overlay` | `--surface-overlay` | modal/palette surface |
| `color.background.neutral` / `-hovered` / `-pressed` | `--bg-alt` / `--bg-well` / `--bg-active` | **alpha**, at 6% / 14% / 31%; the quiet-control interaction ladder |
| `color.background.input` | `--bg-input` | field fill; replaced the old `bg-well` resting state so hover has somewhere to go |
| `color.text` / `.subtle` / `.subtlest` / `.disabled` | `--text-primary` / `--text-secondary` / `--text-muted` / `--text-subtle` | `subtlest` is captions (4.6:1, gated); `disabled` is decorative only |
| `color.text.inverse` | `--text-inverse`, `--text-on-inverse` | on accent/bold fills; `--text-on-inverse` pairs with `--bg-inverse` (`background.neutral.bold`) for the tooltip — 7.65:1 both themes |
| `color.link` | `--accent-text`, and `--text-link` as its alias | **no `--text-accent` token exists** |
| `color.border` / `.bold` / `.focused` (+ `--ds-border-subtle`) | `--border-subtle` + `--border` / `--border-strong` / `--border-focus` | **alpha hairlines** so an edge composes over any tint, in two real tiers: 6% (`#091E420F` / `#A1BDD914`) inside, 14% (`#091E4224` / `#A6C5E229`) at the edge |
| `color.background.brand.bold` + `-hovered` / `-pressed` | `--accent` / `--accent-hover` / `--accent-active` | `#0C66E4`; `--accent-soft` kept, derived via `color-mix(in srgb, var(--accent-subtle) 45%, transparent)` |
| `color.background.accent.<hue>.{subtlest,subtler,bolder}` + `color.text.accent.<hue>` | every status, sentiment, citation, run-status and score-band family | the whole point of the ramp: `subtlest` fill + matching `text` ink is the AA-safe pairing, so ~110 domain tokens are composed rather than hand-picked |
| `color.background.danger.bold` + `-hovered` | `--danger-solid` / `--danger-solid-hover` | ADS states this pair for exactly this case and both already clear AA against white (5.2:1 / 6.7:1), so unlike the Figma port **no hand-deepening is needed** |
| `color.background.accent.<hue>.bolder` | `--chart-1..8`; `--series-1..5` alias `--chart-1..5` | one hue per slot: blue, green, orange, red, purple, teal, yellow, magenta. Keeps the "fold into Other" rule in `series-palette.ts` |
| `color.background.neutral.bold` | `--chart-tooltip-bg`, with NEW `--chart-tooltip-fg` | the tooltip foreground used to be a literal `text-white` — the one genuine token gap in the old system |
| `elevation.shadow.raised` | `--shadow-2`, `--shadow-card-value` | the card rung — every Card rests on it, borderless |
| `elevation.shadow.overlay` | `--shadow-3`, `--shadow-4`, `--shadow-card-hover-value`, `--shadow-lg-value`, `--shadow-modal` | overlays, plus the hover lift of interactive cards. `--shadow-1` and `--shadow-xs/sm/elevated` are `none` |
| `radius.{xsmall,small,medium,large,xlarge}` (2/4/8/12/16) | `--radius-xs/sm/md/lg/xl`; `--radius-2xl` = 16; `--radius-full` kept | **buttons are rounded-md (8px), not pills**; badges are `rounded-sm` (4px) |
| `space.025…1000` | existing `--space-1..20` 4px grid, **unchanged** | the two scales already agree; renaming would churn ~40 contract entries for no visual gain |
| Google Sans, Space Grotesk, Geist | `--font-primary-family` = Google Sans stack; `--font-display-family` = Space Grotesk stack; `--font-mono-family` aliases the Google Sans stack (no monospace shipped) | next/font in `app/layout.tsx`; `--font-sans` remains the body/UI variable; marketing `--font-mkt-display` keeps the Geist stack |

## 4. Token values

**`ds-tokens.css`** declares ~150 ADS-based primitives under `:root` and
`html[data-theme='dark']`. Light values and semantic ramps come from `@atlaskit/tokens`;
dark surfaces, neutral text, borders and the gray ramp use a deliberate achromatic override.
The package is deliberately **not** a dependency: it ships ~1600 variables we do not use, and
its theming runtime applies its own `data-color-mode` / `data-theme` attributes, which would
collide with the hand-rolled bootstrap in `lib/theme.ts`. Read the file for the values; the
nine-hue accent ramp is uniform by design (`subtlest`, `subtler`, `subtle`, `bolder`, `text`
× blue, green, red, orange, yellow, teal, purple, magenta, gray).

**`globals.css`** declares the semantic layer. No literal colour is authored there — every
value is a `var(--ds-*)`, which is why the dark theme needs no restatement. Read the file for
the mapping; §3 above is its summary and `check-design-tokens.mjs` is its contract.

Two domain decisions worth recording, because they changed meaning rather than value:

1. **Citation competitor moved orange → magenta.** Warning is now orange, and a competitor
   citation sitting in the same hue as a warning read as an error state.
2. **Score bands became a true four-step ramp** — red → orange → yellow → green. The old set
   spent two rungs on green (`good` `#10B981`, `high` `#22C55E`), which made 50–74% and
   75–100% nearly indistinguishable at badge size.

And two deliberate departures from the literal ADS token set, both measured:

1. **The app canvas is `--ds-surface-canvas` (`#F1F2F4`, ADS `accent.gray.subtlest`), not the
   sunken surface.** ADS ships a single sunken (`#F7F8F9`), which sits only 2.54 ΔE76 from a
   white card — below perceptual threshold, which is exactly why the first flat pass was
   invisible. The canvas step takes card↔canvas separation to 4.66. Dark uses neutral
   editor charcoal `#111111`; `--bg-input` shares the canvas, so a field reads as an inset well on a
   white card (4.66) instead of disappearing into it (0.00).
2. **Borders are two real tiers.** `--ds-border-subtle` (`#091e420f` light / `#ffffff12`
   dark — the neutral 7% white alpha; ADS ships no `border.subtle`) for chrome frames,
   overlay edges, structural panels, in-card separators and
   table rules, `--ds-border` (`#091e4224` light / `#ffffff1f` dark) for form fields and the
   interactive chips whose affordance is an outline (card edges are gone — §4a):
   4.66 vs 11.61 ΔE76 on white.
   `globals.test.ts` asserts the subtle alpha stays strictly weaker. The inverse pair
   `--bg-inverse` / `--text-on-inverse` (7.65:1 both themes) backs the tooltip.

### 4a. Elevation — the five rules

Machine-enforced by `scripts/check-elevation.mjs`, wired into `pnpm check:policy`.

The model is the **borderless, elevation-driven surface** — the Gmail/Trello/
atlassian.design arrangement. A surface is separated by *light* (its shadow rung) and the
canvas tint step, not by a drawn outline. Borders survive only where they carry structure:
table rules, in-card separators, and form fields, all at the 6% subtle tier.

1. **Cards rest on the raised rung and carry no border.** `Card` is `bg-panel` +
   `shadow-card` (`--ds-shadow-raised`) + `--radius-lg`, edge-free. The shadow is the
   separator; the canvas tint step (4.66 ΔE76) backs it up.
2. **Interactive cards lift on hover.** A clickable card rises to `shadow-card-hover` (the
   overlay rung) with a 2px translate — the same affordance as a Trello card.
3. **Shadow only on cards and true overlays** — modal, dropdown, popover, tooltip, toast,
   command palette — through the single `shadow-modal-value` rung. The guard holds an
   explicit allowlist of the files permitted to apply it; adding one is a design decision.
   Tables, sidebars, inputs, tabs, badges and page headers cast nothing.
4. **Borders are structural, not decorative, and live at the subtle tier.** Card edges are
   gone entirely; chrome frames, overlay edges, table rules and fields keep a 1px alpha
   hairline at `--border-subtle` (6%). The 14% `--border` tier remains for the few edges
   that must read on any tint (form fields).
5. **No gradients on UI chrome, no glass/blur, no inner catchlight rings.** Gradients are
   display art only (`components/marketing/`), never a control or container.

The guard also asserts the token half of the policy: `--shadow-card-value` must resolve to
`var(--ds-shadow-raised)`, `--shadow-card-hover-value` to `var(--ds-shadow-overlay)`, and
`--shadow-xs-value` / `--shadow-sm-value` / `--shadow-elevated-value` to `none`. A component
scan alone cannot see that — if those values move, every surface silently re-depths itself.

**What this replaced.** The "flat 2.0" revision banned every in-flow shadow and leaned on a
1px hairline for all separation. It measured correctly (the canvas/card tint step is real)
but read dull: a wall of hairline-outlined white boxes on gray. The elevated model keeps the
measured tint step, drops the card border outright, and puts the ADS raised shadow back —
which is what `elevation.surface.raised` / `elevation.shadow.raised` exist for. The dark
theme's `0 0 0 1px` warm catchlight ring stays gone — ADS dark separates its four surface
steps by fill alone, and the ring was compensating for a ladder that did not.

Consequences already applied: the secondary button lost its hairline and rides the raised
rung instead (a borderless white button); the segmented control's active pill stays
shadowless (white on a tinted track already separates them); the tooltip rides the inverse
pair (`bg-surface-inverse` / `text-on-inverse`, a bold surface that needs no hairline); and
`.logo-mark` keeps its flat `--accent` fill — a three-stop gradient on the one mark present
on every screen was the loudest possible exception to rule 5.

## 5. Dark theme

There is no separate dark value table, and that is the design. `globals.css` contains exactly:

```css
html[data-theme='dark'] {
  color-scheme: dark;
}
```

Every semantic token resolves through a `var(--ds-*)` indirection, and `ds-tokens.css` already
flips all ~150 primitives under the same selector. `--bg-panel` is `var(--ds-surface)` in both
themes and simply resolves to `#FFFFFF` or `#181818`. The old dark block restated 120
hand-authored values and could drift out of step with light; this one cannot. **If a token
appears to need a dark override here, that is a signal the primitive layer is missing one** —
add it to `ds-tokens.css` instead. The architecture guard's 900-line budget on `globals.css`
exists partly to keep restated dark values from creeping back.

## 6. Dark-theme spec (hard constraints, machine-enforced)

`globals.test.ts` enforces:

1. **Surface ladder ordering** — strict luminance ordering `--bg-base` `<` `--bg-panel` `≤`
   `--bg-elevated`, in both themes. This is the invariant flat design actually depends on: it
   is the only thing distinguishing the surfaces.
2. **AA ≥ 4.5:1 for every documented pair** — the same programmatic pair list as light (body,
   accent, and every status/sentiment/citation/run/score `*-text` on its `*-bg`), with
   translucent fills composited over `--bg-panel`.
3. **The accent stays in one blue family across both themes** (200–230°), guarded both ways so
   a later edit can neither drift it to violet nor off into cyan.
4. **Chart hue stability** — `--chart-1..8` change lightness between themes but not hue (ADS
   ramps are hue-stable to within a degree), so a series keeps its identity across a theme
   switch while staying legible on both canvases. The old palette held one value for both
   themes and paid for it in dark.
5. **Flat elevation** — the four in-flow shadow rungs resolve to `none`; only the overlay rung
   casts.
6. **Decorative-only tones are never body text** — `--text-subtle` (ADS `text.disabled`) is
   asserted present but excluded from ratio gating (dividers, the `—` placeholder).

**Two constraints from the dusk system are deliberately gone**, and are recorded as reversals
in `globals.test.ts` rather than silently deleted:

- **The "never near-black" luminance floor.** It was an aesthetic rule for the warm-charcoal
  deck (base `#262522` ≈ 0.0185). The neutral dark canvas remains near-black
  (`surface-sunken #111111`) and intentionally follows editor-style contrast.
- **The soft-shadow-stack assertion.** There is no dark shadow stack left to be soft.

## 7. Type scale — Figma verbatim

Body/UI sans = **Google Sans** 400/500/600/700 (`--font-sans` → `--font-primary-family`);
headings/display = **Space Grotesk** 500 (`--font-space-grotesk` → `--font-display-family`).
**No monospace is shipped** — `--font-mono-family` aliases the Google Sans stack, and the
`.mono` / `font-mono` recipe keeps **tabular numerals**
(`font-variant-numeric: tabular-nums`) for **metric values, percentages,
counts, positions, timestamps, code and keyboard hints** so columns align; it is never used
for labels. Semantic `h1`–`h6` elements resolve to Space Grotesk; marketing display
utilities resolve to Geist Medium (marketing-only face, §11).

The ladder is the ADS `font.*` composite scale. **13px and 15px do not exist.** Every step
carries its own line-height, and the heading steps bake their weight into the token, so call
sites carry size only (an explicit `font-*`/`leading-*` utility still wins — Tailwind emits
it after the baked default). `--text-heading-xs` and `--text-heading-sm` exist as separate
names because ADS's 14px and 16px headings collide on *size* with `--text-sm`/`--text-base`
but not on line-height or weight, and Tailwind cannot express two line-heights for one size
token.

| Token | Size / line-height | Weight | ADS source | Use |
|---|---|---|---|---|
| `--text-2xs` | 11px / 16px | 400 | `font.body.small` | micro captions |
| `--text-xs` | 12px / 16px | 400 | `font.body.UNSAFE_small` | captions, timestamps, the eyebrow recipe |
| `--text-sm` | 14px / 20px | 400 | `font.body` | **the body default** — table cells, secondary lines |
| `--text-base` | 16px / 24px | 400 | `font.body.large` | lead paragraphs only |
| `--text-heading-xs` | 14px / 16px | 500 | `font.heading.xsmall` | card titles, panel h3 |
| `--text-heading-sm` | 16px / 20px | 500 | `font.heading.small` | section h2, dialog titles, wordmark |
| `--text-lg` | 20px / 24px | 500 | `font.heading.medium` | page `<h1>` |
| `--text-xl` | 24px / 28px | 500 | `font.heading.large` | onboarding / empty-page titles |
| `--text-2xl` | 29px / 32px | 500 | `font.heading.xlarge` | rare, hero numerals |
| `--text-hero` | 35px / 40px | 500 | `font.heading.xxlarge` | app display ceiling — name kept, was 48px |
| `--text-display-1` | clamp, 35 → 64px / 1.04 | 500 | above the ADS ceiling | marketing hero (aliased as `--text-mkt-d1`) |
| `--text-display-2` | clamp, 29 → 48px / 1.08 | 500 | above the ADS ceiling | marketing section head (aliased as `--text-mkt-d2`) |

- The eyebrow recipe is ADS `font.heading.xxsmall` — 12/16 @600, **no uppercase, no
  tracking** — composed at the call site as `text-xs font-semibold` (`eyebrowClasses`); there
  is no dedicated eyebrow token.
- Weights: `--weight-normal: 400`, `--weight-medium: 500`, `--weight-semibold: 600`,
  `--weight-bold: 700` — heading tokens run at 500. Intentional 600-weight call sites use
  explicit `font-semibold`, including the eyebrow recipe above, table headers, and form labels;
  `bold` is a true 700 (the Google Sans 700 cut is loaded).
- **There is no letter-spacing anywhere.** ADS defines no tracking rungs, so the
  `--tracking-*` namespace is removed from the bridge (`--tracking-*: initial`), every
  `tracking-*` utility class is deleted (zero-ceiling guard in `check-ads-scale.mjs`), and no
  `--text-*--letter-spacing` modifier exists — including the display steps.
- Retired: `--text-data-lg` (the 22px step — it had zero call sites) and the old 48px hero
  value. Machine-enforced: `check-ads-scale.mjs` fails on `text-data-lg` and on any
  arbitrary `text-[…]` size.
- Line-height tokens (explicit overrides only — line-height normally arrives with the size
  token): `--leading-none: 1`, `--leading-tight: 1.2`, `--leading-snug: 1.35`,
  `--leading-normal: 1.5`.

## 8. Spacing (ADS `space.*` ladder), radii, controls

**Spacing steps** — the ADS ladder, each rung a `var(--ds-space-*)` reference: `--space-0: 0`,
`--space-025: 2px`, `--space-050: 4px`, `--space-075: 6px`, `--space-100: 8px`,
`--space-150: 12px`, `--space-200: 16px`, `--space-250: 20px`, `--space-300: 24px`,
`--space-400: 32px`, `--space-500: 40px`, `--space-600: 48px`, `--space-800: 64px`,
`--space-1000: 80px`. **28px and 56px do not exist**; 2px and 6px are new. Component
spacing otherwise uses Tailwind's built-in 4px scale — its off-ladder steps (10/14/28/36/44/
56px) are counted and capped by `check-ads-scale.mjs` so the count can only go down.

**Density + shell geometry:** `--card-padding: var(--space-200)` (16px),
`--card-gap: var(--space-200)` (card grids), `--content-gutter: var(--space-300)` (24px page
gutter), `--sidebar-width: 240px`, `--topbar-height: 48px`, `--nav-item-height: 32px`,
`--content-max-width: 1440px`. The shell consumes these as `var()` escapes
(`w-[var(--sidebar-width)]`, `h-[var(--topbar-height)]`, `gap-[var(--card-gap)]`,
`max-w-[var(--content-max-width)]`, `h-[var(--nav-item-height)]`) — no px literals.

**Radii (the ADS `radius.*` scale, every rung resolving through `--ds-radius-*`):**
`--radius-xs: 2px` (`radius.xsmall` — tags, the smallest chips), `--radius-sm: 4px`
(`radius.small` — badges, skeletons, the logo mark), `--radius-md: 8px` (`radius.medium` —
**buttons**, inputs), `--radius-lg: 12px` (`radius.large` — cards, panels), `--radius-xl:
16px` (`radius.xlarge` — modals, large cards), `--radius-2xl: 16px` (aliases xl),
`--radius-full: 9999px` (**pill** — chips, toggles, segmented control, avatar). Arbitrary
`rounded-[Npx]` values and bare `rounded` are normalised onto this ladder.

**Controls:** `--control-height-sm: 24px` (ADS compact), `--control-height: 32px` (ADS
default), `--control-height-lg: 38px` (kept, not the ADS 40 — the launch dialog's large
controls are tuned to it), `--interactive-border-width: 1px`. Table:
`--table-row-height: 40px`, `--table-header-height: 32px`,
`--table-cell-padding-x: var(--space-150)`, `--table-cell-padding-y: var(--space-075)`,
`--table-font-size: var(--text-sm)`, `--table-header-font-size: var(--text-xs)`.

## 9. Tailwind v4 bridge (`@theme inline`)

Bridge the raw variables to semantic Tailwind utilities so components reference **only** the
bridged names (`bg-background`, `text-foreground`, `border-border`, `bg-accent`,
`text-accent-text`, `text-link`, `bg-citation-owned`, `text-run-completed`, `bg-score-high`,
`text-score-good-text`, `stroke-series-1`, `bg-chart-2`, `shadow-card`, `rounded-md`,
`font-mono`, `text-hero`, …). Shape:

```css
@theme inline {
  --font-sans: var(--font-primary-family);
  --font-mono: var(--font-mono-family);
  --font-display: var(--font-display-family); /* Space Grotesk */
  --color-background: var(--bg-base);
  --color-panel: var(--bg-panel);
  --color-foreground: var(--text-primary);
  --color-secondary: var(--text-secondary);
  --color-muted: var(--text-muted);
  --color-inverse: var(--text-inverse);
  --color-link: var(--text-link);
  --color-border: var(--border);
  --color-accent: var(--accent);
  --color-accent-active: var(--accent-active);
  --color-success: var(--success); /* + warning/danger/info + *-bg/*-border/*-text */
  --color-sentiment-positive: var(--sentiment-positive); /* + neutral/negative */
  --color-citation-owned: var(--citation-owned); /* + competitor/third-party + *-bg/*-border/*-text */
  --color-run-completed: var(--run-completed); /* + every run-status */
  --color-score-high: var(--score-high); /* + low/mid/good + *-bg/*-border/*-text/*-ring */
  --color-chart-1: var(--chart-1); /* + chart-2..8 + series-1..5/series-other aliases */
  --shadow-card: var(--shadow-card-value); /* the card rung (raised); + card-hover — xs/sm/elevated stay `none` (§4a) */
  --shadow-modal-value: var(--shadow-modal); /* the overlay rung — allowlisted overlays only */
  /* type sizes (incl. --text-hero/--text-display-1/-2), radii,
     line-heights bridged here too (§7–§8) — no tracking namespace */
}
```

**Implementation rules:** raw hex lives **only** in `ds-tokens.css` (and, for marketing,
`marketing-theme.css`) — `globals.css` now authors none at all; components use bridged tokens
only (no-raw-hex guard) and never a bare `--ds-*` name; **both themes are always fully
defined**; `data-theme` is set pre-hydration. `--shadow-1..4` stay raw-only (bridging them as
`--shadow-1: var(--shadow-1)` would be circular) — components consume the semantic aliases,
of which only `shadow-modal-value` is non-empty.

## 10. Component-primitive inventory

All CVA-driven, token-only, Radix where relevant, lucide icons. Ported to the Figma specs
(buttons/badges/elevation, score ring, sparkline) — see the component source in
`frontend/components/ui/`, which is now the authority.

| Primitive | Notes |
|---|---|
| `button` | **rounded-md (8px) — pill variants retired.** Primary = accent fill + `--accent-fg` (white) text + accent-tinted shadow, 14px/500; hover/active walk `--accent-hover`/`--accent-active`. Secondary = panel bg + `--border` hairline; ghost = transparent + accent-subtle hover; destructive = danger tokens. Sizes sm/md/lg/icon; `asChild`; icon slot. |
| `badge` | pill (`--radius-full`) 11.5px/500 with token bg/border/text. Variants map to tokens: `status` (success/warning/danger/info), `sentiment`, `classification` (**owned = Figma blue**, competitor, third-party), `run-status` (all 8), `score-band` (low/mid/good/high). |
| `card` | `bg-panel` + `shadow-card` (raised rung) + `--radius-lg`, **borderless**; interactive cards lift to `shadow-card-hover` + 2px rise on hover; header/title/description/content slots + optional mono eyebrow panel label. |
| `table` (dense) | 32px sticky header (the `--text-xs` @600 eyebrow recipe, muted), 40px rows, 14px cells, mono tabular numerals for numeric columns, neutral-50 row hover, sortable carets; shared `table-pagination` footer (mono indicator + ghost Prev/Next, clamp-only reconciliation). |
| `score-ring` | Figma geometry: rounded linecap, 0.8s sweep transition, ring color from `--score-*-ring`, track from the theme; center numeral (`md` = `--text-heading-sm`, `lg` = `--text-xl`, `hero` = `--text-hero`); ARIA label with %. **Band thresholds stay 25/50/75 — `score-band.ts` unchanged.** |
| `sparkline` | trend-colored 1.5px polyline + end dot (Sparkline.tsx). |
| `donut` | segmented ring for per-engine / citation share; hover-thicken + mono center value; legend; ARIA. |
| `tabs` / `segmented` | underline tabs (2px accent indicator, per VisibilityDashboard.tsx) + a pill segmented control (`--segmented-bg`, active = accent-fg on accent). |
| `input` / `field` | 14px text, `--border` hairline, `--radius-sm`, focus = accent border + `--focus-ring`; `field` wraps label + help + error. |
| `dialog` | Radix modal; `--overlay-scrim`, `bg-elevated`, `--shadow-4`, `--radius-xl`. |
| `command-palette` | ⌘K/Ctrl+K navigation over nav destinations + workspace projects, plus the sidebar command row that opens it. Radix dialog primitive directly (not `dialog` — a palette's header is its input); same scrim/surface tokens. Substring filter, clamped cursor, `role="listbox"` + `aria-activedescendant`. |
| `dropdown` | Radix menu; `bg-elevated`, `border`, `--shadow-3`. |
| `tooltip` | Radix; inverse chip (`--chart-tooltip-bg`), `--text-xs`. |
| `skeleton` | `--skeleton-base` → `--skeleton-highlight` shimmer (~1.2s). |
| `empty-state` | shared icon chip + heading + body + CTA slots. |
| `typography` | scale classes for every §7 token incl. `text-hero` / `text-data-lg`. |
| `series-palette` | values resolve from the `--chart-*` aliases; class strings (`stroke-series-N`) unchanged. |
| `history-drawer` | right-side Radix drawer for run history / execution list. |

## 11. Per-screen prose

The app shell is a fixed **240px left sidebar** + **48px topbar** + scrolling content region
(4px grid, `--content-gutter` padding). Auth and onboarding screens are exceptions (no
shell).

### 11.1 App shell (`(app)/layout.tsx`) — Figma shell geometry (AppShell.tsx), grouped nav kept

**Sidebar (240px, `bg-sidebar`)**: logo row (LogoCube + wordmark), project switcher
(brand avatar + name, dropdown), the **command row**, then the grouped nav — the existing
**Analyze / Improve** groups stay (the Figma flat nav is not adopted) with mono-uppercase
eyebrow group labels.
Nav rows are 32px, 14px, `--text-secondary`; the **active item** is `--accent-subtle` bg +
`--accent-text` + a **3px left accent bar** with the icon at full opacity; hover = bg-alt.
Bottom = user card (avatar + name/email). **Topbar (48px, `bg-panel`)**: left = the current
page's title (15px/600, the single h1) + header slot (filters/actions); right = export hook,
theme toggle, user affordances. Content scrolls independently. A first-run gate redirects
zero-project users to `/onboarding` (and waits for the projects query to settle before
redirecting — no flash).

**Command palette (⌘K / Ctrl+K).** `components/ui/command-palette.tsx` owns both the global
key binding and the sidebar command row that triggers it, so the two can never disagree. It
indexes every `NAV_GROUPS` destination plus every project in the workspace; choosing a
project calls `setActiveProjectId` (which re-scopes the API client's workspace header) rather
than navigating, and the active one is marked `Current`.

Built on the Radix dialog primitive directly, **not** `components/ui/dialog.tsx` — that
wrapper owns a title/description/close header, and a palette's header is its input. It reuses
the same scrim and surface tokens, so the two stay consistent. The accessible name comes from
an `sr-only` `Dialog.Title`, with `aria-describedby={undefined}` opting out of the description
Radix otherwise expects.

**Focus is handed back explicitly.** Radix returns focus to its own `Trigger`, but the ⌘K path
has no trigger — without the explicit hand-back, closing drops focus to `<body>` and the caller
loses their place in the page. The palette records `document.activeElement` when the shortcut
fires (and the sidebar button records itself), then restores it on close, guarding with
`isConnected` because switching project re-renders the shell and can unmount the original
element. Regression-tested in `command-palette.test.tsx`.

Filtering is a plain substring match over label + group. There is deliberately no fuzzy
matcher and no index: the corpus is ~12 nav items plus a handful of projects, where
subsequence matching mostly produces surprising ranking for no measurable gain. The cursor is
**clamped during render** rather than corrected in an effect, so a filter that shrinks the
list can never render a frame with nothing selected. `role="listbox"` +
`aria-activedescendant` keeps focus in the input while the selection moves.

**Layout.** Rows are grouped under Analyze / Improve / Switch project headings rather than
carrying a right-aligned group label, and each row leads with its canonical nav glyph (projects
render `ProjectSwitcher`'s initials avatar instead). Results keep ONE flat order for the
keyboard cursor and are re-sectioned from that list at render time — grouping first and
flattening for keys would let the highlighted row and the Enter target drift apart. A footer
states the keyboard controls, since this is a keyboard surface first.

The search input suppresses the global `:focus-visible` outline
(`focus-visible:outline-none!`). It is the only focusable element and is focused for as long
as the palette is open, so the ring would be a permanent blue rectangle carrying no
information. The `!` is required: that global rule is unlayered and would otherwise win over
a utility regardless of specificity.

### 11.2 Auth (`/login`, `/register`)

Split-screen `(auth)` layout restyled in the Figma language: brand panel (token-driven,
per the approved mockups) + form panel with an elevated form card (`--shadow-2`,
`--radius-lg`), larger type, three OAuth buttons above an email divider (coming-soon →
accessible 503 inline notice), inline `ApiError` danger alert, login/register toggle link,
theme toggle top-right. The pages own the single h1.

### 11.3 Onboarding (`/onboarding`) — Figma-styled, AI auto-discovery (OnboardingScreen.tsx)

First-run route group **without** the app shell (SessionGuard + ProjectProvider; the layout
redirects to `/projects` when projects exist). **Full-screen split**: left panel = logo
header + sign-out, a top progress stepper, the step form, and a footer pager (Back/Continue
+ "Step N of M"); right panel = a **live preview** that summarizes the brand, then populates
discovered competitors/domains/prompts as they arrive, then mirrors the review selection.
Flow: **Brand** (name + website URL + derived-domain preview + explicit AI consent
checkbox) → **Discovery** (competitor + owned-domain + prompt suggestions fire in parallel;
animated staged progress; per-section status + retry) → **Review** (pre-filled **editable**
competitor rows, domain chips, prompt rows with theme/intent; market defaults US/en with
inline change) → **Finish** (create project + prompt set + prompts, refetch the projects query,
then confirm that the Free Site Health crawl is queued before the user opens `/projects`). When
the agent is unconfigured (503) the flow degrades
to a manual-entry fallback with an inline notice — onboarding never requires the agent.

### 11.4 Active-project Dashboard and product tour (`/projects`)

The Dashboard leads with a brand header (BrandLogo + snapshot timestamp from `generated_at`)
and the report action, then four executive **metric tiles** — borderless raised cards, each
pairing an `IconChip` glyph with a large mono numeral; the two scores (visibility, site
health) take their score-band text colour, counts stay neutral, and missing values render the
muted `—`. Analyze/Improve follow as grids of source-linked **section cards**: section icon
chip, state badge (ready = success, running = info, not_setup = warning, failed = danger,
empty = neutral), the section's primary metric, and a hover lift (`shadow-card-hover` + 2px
rise + arrow slide). Only persisted projections are displayed, and the report action
downloads the authenticated PDF blob. Project management follows as a secondary section.

The Driver.js tour is themed as a first-class surface (`app/tour.css`, scoped by the
`searchify-tour` popover class): the popover rides the elevated/overlay tokens with the
display face for titles and the app's own primary/quiet button pair, the stage uses a 12px
cutout radius, and the scrim resolves `var(--overlay-scrim)` per theme. Steps carry explicit
`side`/`align` placement, a mono `n of total` progress readout, stable `data-tour` targets,
honors reduced-motion preferences, keeps keyboard controls enabled, and persists its current
route-aware step for each workspace member. A missing target quietly stops after bounded
retries rather than obscuring the application.

### 11.5 Visibility workspace (`/visibility`) — Figma dashboard (VisibilityDashboard.tsx)

One workspace: filter bar (run selector defaulting to the latest completed run, engine pill
filters) above the accessible four-tab underline tablist — **Overview** (default), Trends,
Mentions & Citations, Query Fanout; the active tab mirrors in `?tab=`. Overview leads with
the **hero metric card**: ScoreRing 140 + the run's Visibility Score as a 48px hero numeral
(`--text-hero`), supporting-metric delta chips (SOV, Mentions, Citations, Avg Rank — chips
render only where the API provides the series; Avg Position and Sentiment stay `—`), and
run info. Below: the competitors **rankings table** with per-row sparklines (where trends
exist), the **Share of Voice donut** (hover-thicken, mono center value), and the per-engine
by-model card. Empty state (no completed runs): shared `empty-state` linking to `/runs`.

### 11.6 Prompts (`/prompts`, `/prompt-research`)

**Your Prompts** — read-only, score-annotated: summary banner, search, dense table grouped
by topic with expandable group rows; Visibility Score as a score-band badge (derived from
persisted audit evidence), Avg Position and Sentiment `—`. **Prompt Research** — the
management workspace: topics rail (pill items + mono counts, accent-subtle active), toolbar
(filter, search, CSV bulk upload, Add prompt, consent-gated Generate), Active / Proposed /
Archived underline tabs with mono counts, dense table (Prompt, Theme badge, Intent, Branded
badge, Enabled toggle, row actions), shared pagination, CSV preview dialog, shared
empty-state.

### 11.7 Runs (`/runs`, `/runs/[runId]`, executions)

Pill status filter chips (mono counts) above the audits table (run-status badge, mono
counts, timestamp) + Launch dialog (prompt-set + engine chips + repetitions). Run detail:
progress panel (counts + badge + pulsing live dot while active + Cancel), export links,
executions table. Execution detail: evidence card — answer text, `search_used` badge,
citations with owned/competitor/third-party badges (owned = Figma blue), mention chips,
mono score dict; Sentiment `—`.

### 11.8 Measurement + action surfaces

**Site Health** (`/site-health`) — crawl/page detail: score presentation
(score-band tokens), issue grouping layout, page table. **Issues**, **Content**,
**Knowledge Base** (description/positioning/products/audience editor + consent-gated "Draft
with AI" review flow), **Products**, **Analytics**, **Traffic**, **Settings** (providers /
integrations) — the same Figma-language reskin: tokens + new primitives, hierarchy and
spacing per this document, shared empty-state; no contract or data-flow changes.
**Setup** (`/setup`) keeps its wizard flow restyled; `/setup/new` stays for additional
projects.
## Marketing creative system (the `.mkt` contract)

The public surface — every `(marketing)` route **and** the logged-out auth screens
(`/login`, `/register`) — runs **Searchify Proof**, a fully independent creative system.
"Marketing pages have no relation to the app" still holds; Proof simply replaces the retired
dark **Signal/Dusk** identity. Source of truth for the direction:
[`searchify-brand-deck.html`](searchify-brand-deck.html).

**Architecture.** Tokens live in `frontend/app/(marketing)/marketing-theme.css` as a Tailwind
v4 `@theme` block in the `mkt-` namespace, imported by `globals.css` (Tailwind builds
utilities from a single `@import 'tailwindcss'` graph — a second import would duplicate
preflight and the whole utility layer). Sections are built from **utilities plus the
primitives in `components/marketing/primitives/`**; the theme file additionally holds only
the scene rules a utility cannot express (the wallpaper and SVG stroke geometry). Every
keyframe and scroll timeline lives in the sibling `marketing-motion.css`. Hex lives ONLY in
those two files; marketing components stay hex-free.

After the ADS fold-in the theme file keeps only four genuinely brand-differentiating buckets:
the **warm paper/ink neutrals**, the **three vendor engine colours**, the **two fluid display
steps** above the ADS 35px ceiling (riding the shared `--text-display-1/-2` rungs), and the
**marketing layout widths**. Everything else — ink, hairlines, state hues, radii, type — is a
verbatim ADS value held as literal hex or as a theme-independent alias, never a `--ds-*`
semantic name that would flip under `html[data-theme='dark']`: Proof is light-only.

**A 400-line budget on `marketing-theme.css` is machine-enforced**
(`scripts/check-frontend-architecture.mjs`), with a companion 300-line budget on
`marketing-motion.css`. The previous marketing stylesheet reached **6,846 lines** of global
`.mkt` cascade because nothing stopped it growing. If a new section needs CSS in the theme
file, it needs a **primitive** instead — that is the rule the budget exists to force. When a
genuinely new *concern* arrives (as motion did), give it an owner; do not raise the ceiling.

**Palette.** Warm paper and exact ink carry the page; colour is rationed to states, provider
identity and evidence marks — never to headlines.

| Role | Value | Token |
|---|---|---|
| page canvas | `#F5F5F0` | `--color-mkt-paper` |
| raised / inset fields | `#FBFBF8` | `--color-mkt-paper-raised` |
| panels | `#FFFFFF` | `--color-mkt-surface` |
| band tint (sunken) | `#E9E9E0` | `--color-mkt-surface-sunk` |
| band tint (wash) | `#EAF1FA` | `--color-mkt-wash` |
| primary ink | `#172B4D` (12.9:1) | `--color-mkt-ink` |
| body copy | `#44546F` (7.0:1) | `--color-mkt-ink-soft` |
| meta / captions (paper/surface only) | `#626F86` (4.6:1) | `--color-mkt-ink-muted` |
| hairline | `#091E4224` | `--color-mkt-line` |
| wallpaper base | `#CBDAF1` | `--color-mkt-sky` |

The paper is the brand; the ink ramp and the hairline are the **same ADS values the app
ships** (`#172B4D` / `#44546F` / `#626F86`, `#091E4224`), so marketing and app read as one
product. `#626F86` at 4.64:1 is the tightest pair in the system — it passes AA, but the
margin is 0.14, so any future darkening of the paper must re-derive this token first. That
tightness also caps where the token may sit: on the darker band fills it falls below AA
(4.16:1 on sunken, 4.46:1 on wash), so **ink-muted is legal on paper and surface only** —
meta text on a sunken or wash band steps up to `--color-mkt-ink-soft` (6.27 / 6.73:1).

**Mark vs text — the rule that governs every state hue.** A hue that works as a *fill* is not
automatically legible as *text*. Each state therefore ships in two forms: the **mark**
(≥ 3:1, dots/bars/tiles only) and the **`-text` variant** (≥ 4.5:1, safe for copy). The
deck's own values all failed as text, which is why the split exists.

| State | Mark (≥ 3:1) | Text (≥ 4.5:1) |
|---|---|---|
| proof / active + linked | `#0C66E4` | `#0C66E4` (4.76:1) |
| evidence / verified | `#1F845A` | `#216E4E` (5.64:1) |
| signal / decline + refusal | `#CA3521` | `#AE2A19` (6.11:1) |
| review / needs attention | `#B65C02` | `#974F0C` (5.58:1) |

Blue is the one hue that needs no split: `#0C66E4` clears AA on paper as both mark and text,
so proof ships a single token plus a `#0055CC` (6.05:1) hover step. The other three hues keep
their `-text` siblings, and all four mark values are the ADS `*-bolder` steps — "needs
review" is ADS **orange**, not yellow, which reads sickly on warm paper.

Ratios are computed against `#F5F5F0` — the lightest surface the system paints text on, so
passing there passes on white too. Machine-enforced in `frontend/app/globals.test.ts`
("the Proof contract"), which also asserts the system is light-only and that every state hue
except proof has a `-text` sibling.

**Type.** Marketing body copy is **Google Sans** like the app, while display copy keeps its
own **Geist Medium** face — `--font-mkt-display` aliases the Geist stack directly (the app's
Space Grotesk display face is product-only), and every
`--text-mkt-*` step aliases the shared ADS ladder in `ds-type.css` (§7), so
13px and 15px do not exist here either and there is no letter-spacing at any step. Figures
and "meta" labels use the shared `font-mono tabular-nums` recipe (Google Sans with tabular
numerals — no monospace is shipped) — the deck faked
tabular figures with a font-feature hack (`.mkt-num`), and the fix is the real tabular
recipe the app already uses, the same way every number in the app aligns. Eight names
(`text-mkt-d1 … text-mkt-meta`) — d1/d2 ride the two fluid display steps, d3 = `--text-2xl`,
d4 = `--text-xl`, lead/body = `--text-base` (marketing body stays one step above the app's
14px), sm = `--text-sm`, meta = `--text-xs`.

**Display ladder.** `d1`/`d2` resolve to **35 → 64px** and **29 → 48px** fluid
(`--text-display-1`/`-2`, line-heights 1.04/1.08, weight 500 baked). The earlier scale capped
at 72px and floored at **44px**, which wrapped an 18ch headline into four or five stubby
lines on a phone — so headlines read as oversized and cramped at once.

**Weights.** Google Sans static cuts only — display runs at `font-medium` (500), body at 400,
meta at 600. The off-axis 460/540 stops are gone with Manrope: they required the variable
face, and the ADS ladder has no rungs between Regular and Medium.

**Shape and rhythm.** Marketing shares the ADS shape scale (`2 / 4 / 8 / 12 / 16 / full`)
with the app — the deck's fifteen-radius sprawl and the six-name marketing alias set are
gone; only two named aliases remain, `radius-mkt-sm` (8px) and `radius-mkt-lg` (16px), and
everything else uses the shared `rounded-*` utilities. Marketing is **flat**: separation
comes from a tint step plus a 1px `border-mkt-line` hairline, never from elevation — the
only shadow left in the section is `shadow-modal-value` on the nav's two overlays (lens and
dropdown), the same modal token the app uses. One container (1240px) and one gutter
(`clamp(20px, 4vw, 40px)`). Vertical rhythm belongs to the `<Section>` primitive — sections
never set their own padding, which is what keeps every page breathing identically.

**Scenes.** One recurring wallpaper (`public/brand/wallpaper.svg` — sky/coral/mint) stays
behind every product moment as display art, but the windows inset on it are now **opaque
white panels with hairline borders** — no glass, no backdrop blur, no alpha to police (flat
rule 5). The slate scene-ink ramp is gone with the glass: scene copy uses the shared ink
ramp, so contrast inside a scene is the same measured contrast as everywhere else.
Illustrative figures live inside `aria-hidden` scenes and always carry a visible
"Example data" mark; page copy contains no invented numbers.

**Band rhythm.** Sections alternate background **tone** so pages read as a rhythm of bands
rather than one long sheet. `<Section>` takes a `tone` prop with four fills — `paper`
(`#F5F5F0`, the canvas), `surface` (`#FFFFFF`), `sunken` (`#E9E9E0`), and `wash`
(`#EAF1FA`, the cool accent beat). The steps are deliberately small — ΔE2000 against paper
is 3.32 for surface, 3.21 for sunken, 7.12 for wash — enough to register as a band change,
never enough to read as a new page. The rule is **no two adjacent bands share a tone**;
wherever the tone changes, the `divided` hairline is dropped because the tint step already
draws the boundary. Panels sitting on a band keep their `border-mkt-line` hairline
regardless of the fill beneath them, and a card never matches its band: cards on `paper`
are `bg-mkt-surface` (ΔE 3.32), cards on `surface` are `bg-mkt-paper` (3.32), cards on
`sunken` or `wash` are `bg-mkt-surface` (6.46 / 5.56) — tint step plus hairline, never
the hairline alone. Scenes inside `WallpaperPanel` frames are display art and exempt.
Text follows the same per-fill discipline: `--color-mkt-ink-muted` is paper/surface-only
(4.16 on sunken, 4.46 on wash — both below AA), so band meta text uses
`--color-mkt-ink-soft`; proof keeps its text role on paper (4.76) and wash (4.57) but is
mark/link-only on sunken (4.26). The Proof contract in `globals.test.ts` gates every
text colour against each band fill, not just paper.

**Motion** is 5/10: one easing pair, 140–220ms interaction feedback plus longer explanatory
beats, transform and opacity only, scroll reveals that settle rather than bounce, and everything gated on
`prefers-reduced-motion` — where scenes hold their finished state rather than freezing
mid-animation.

Motion lives in its own owner, **`marketing-motion.css`** (budget 300 lines), split out of the
theme file when the scroll-reveal work pushed it past 400. Same principle as the theme budget:
keyframes and scroll timelines are a separate concern from tokens, so they get an owner rather
than a raised ceiling. The `--animate-mkt-*` bindings stay in the `@theme` block; their
keyframes live in the motion file.

**Scroll reveals are CSS-only**, driven by `animation-timeline: view()` inside an `@supports`
guard. This is a hard constraint, not a preference: an earlier JS implementation swapped the
server-rendered node for an opacity-zero motion node after hydration and **made every route
visibly flash**, which is why `Reveal` was previously reduced to a pass-through div. The
current design cannot regress that way — elements server-render in their **finished** state
and animate only where view timelines exist, so there is no hydration boundary to flash
across, and an unsupported browser or a disabled-JS client simply gets the static page.
Anything above the fold is already past its entry range at load, so the hero never animates.

`Reveal` marks a single block (`[data-mkt-reveal]`); `StaggerGroup` marks a container whose
direct children each key off their **own** scroll position, so the cascade tracks the scroll
instead of running ahead of it on a fixed delay. The generic selector excludes the stagger
container (`:not([data-mkt-reveal='stagger'])`) — animating both group and children fades
every item twice. **Never introduce motion here that content depends on to become visible.**

**Hero marquee.** Two counter-moving strips fill the bottom of the first screen: the provider
roster travelling right, buyer questions travelling left. Opposite directions are the point —
engines and questions are the two axes the product crosses, so one shared direction would read
as a single list. `Marquee` renders the item list N times (`copies`, default 4) and the CSS
translates by the width of exactly **one** copy, so copy 2 lands where copy 1 began and the
loop is seamless. Translating a fixed `-50%` would tear as soon as the copy count changed;
`--mkt-marquee-copy` is `1/N`, so the distance follows the content. `copies` must be high
enough that one copy overflows the viewport — a short list that fits on screen visibly empties
before looping, which is the usual cause of a marquee that stutters at the seam. Every copy
after the first is `aria-hidden`, so the list is announced once. Motion pauses on hover, and
under reduced motion the track stops at its start and becomes a plain horizontal scroll region.

Both strips sit **directly on the paper** — no cards, borders or fills. Provider marks are the
official brand geometry from `engine-logo.tsx` in each provider's own colour, and the questions
are quoted and italic so they read as things buyers ask rather than as claims we are making.


## 13. Motion + accessibility (app)

- **Motion**: `--transition-fast: 100ms`, `--transition-base: 180ms`,
  `--transition-slow: 280ms`, all `cubic-bezier(0.4, 0, 0.2, 1)`. Respect
  `prefers-reduced-motion` (non-essential transitions/shimmer disabled). Skeleton shimmer
  ~1.2s loop.
- **Accessibility**: every documented text/surface pair meets **AA ≥ 4.5:1** in both themes
  (programmatic suite; muted/subtle tokens are decorative-only and never body text). Focus
  is always visible: the ADS **2px `--border-focus` outline** (`:focus-visible`) plus the
  tokenized `--focus-ring` shadow on `.focus-ring` components — `border-focused` is a lighter
  blue than `--accent` on purpose, so the ring stays visible against an accent-filled button.
  `score-ring`, `donut`, and
  charts carry ARIA labels with the numeric value. `forced-colors` mode falls back to system
  colors; badges keep a text label (never color-only meaning). Print rules drop backgrounds.
  Interactive targets ≥ 30px height.

## 14. Implementation checklist

1. Author `app/ds-tokens.css` — the ADS-based primitives, `:root` +
   `html[data-theme='dark']`, including the documented neutral dark overrides.
2. Author the semantic layer in `globals.css` on top of it (§3–§4). Every value is a
   `var(--ds-*)`; the dark block is `color-scheme: dark` and nothing else (§5).
3. Add the `@theme inline` bridge (§9) — components use bridged tokens only.
4. **No raw hex outside `ds-tokens.css`** (app) and `app/(marketing)/marketing-theme.css`
   (marketing + auth). `globals.css` authors none.
5. **Keep the elevation rungs as assigned (§4a)** — cards rest on `shadow-card` (raised) and
   carry no border; interactive cards lift to `shadow-card-hover`; only allowlisted overlays
   carry `shadow-modal-value`. Nothing else casts a shadow.
6. **Both themes always defined**; `data-theme` set pre-hydration; **light is the default**
   (stored choice → light; the OS preference is not consulted).
7. The numeric recipe (`.mono` / `font-mono`) gets `font-variant-numeric: tabular-nums`;
   all metrics use it. No monospace face is loaded.
8. Ship `prefers-reduced-motion`, `forced-colors`, `print`, and theme-swap suppression rules.
9. Load **Google Sans** (weights 400/500/600/700), **Space Grotesk** (500), and **Geist
   Medium** (500, marketing-only) via
   next/font in `app/layout.tsx` (`--font-sans`, `--font-space-grotesk`, `--font-geist`).
   `--font-display-family` resolves to Space Grotesk and marketing `--font-mkt-display` aliases
   the Geist stack. Never name a next/font variable `--font-display`: that name is the bridged `@theme` token.
10. **Marketing is still a separate system, for now.** Folding `--mkt-*` onto the ADS layer is
    Phase 2 of the ADS adoption; until then marketing and the logged-out auth screens stay
    light-only.
11. Keep the guards green: `app/globals.test.ts` (palette + name-set sync + WCAG suite +
    §6 dark assertions + the Proof contract), `scripts/check-design-tokens.mjs` (required vars
    across `ds-tokens.css`, `globals.css` and `marketing-theme.css`),
    `scripts/check-elevation.mjs` (§4a), `scripts/check-token-escapes.mjs` (no raw hex, no
    token escapes), `scripts/check-ads-scale.mjs` (the type/spacing ladders), and
    `scripts/check-frontend-architecture.mjs` (line budgets, including the 400-line ceiling on
    `marketing-theme.css` and 700 on `globals.css`).
