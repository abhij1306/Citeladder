# CiteLadder Design System

> Canonical visual and interaction contract for marketing, authentication, and
> the authenticated application. This is the only design-system document.

## Direction and identity

CiteLadder is a light-only, evidence-led enterprise system. It should feel calm,
precise, and engineered. It began from a Tesla-style restraint and has settled
into a refined, restrained Material-3-influenced light system: one chromatic accent,
generous whitespace, crisp micro-shadows over hairline borders, and a few
deliberate, quiet motion treatments.

- **Name and domain:** CiteLadder, `citeladder.com`.
- **Logo:** the canonical full-colour horizontal CiteLadder lockup in
  `frontend/public/citeladder-logo.webp`; product, marketing, authentication, and
  onboarding surfaces reuse that asset rather than reconstructing the symbol and
  wordmark independently. `frontend/public/citeladder-favicon.ico` owns browser
  and installable-app iconography.
- **Voice:** direct, confident, specific. One idea per sentence. Prefer evidence
  and outcomes over generic AI language.
- **Typography:** Plus Jakarta Sans for display headings and Inter for UI, body, and data,
  loaded from Google Fonts through `next/font/google`. The website and authentication surfaces
  use a 16px reading baseline and a content-role ladder; the authenticated app
  keeps its existing compact size scale. Size, leading, weight, tracking, and
  colour are one role contract, never independent page-level choices.
- **Accent:** a single Reference Blue (`#2667FF`) for primary actions, explicit
  selection, links, and focus. It is the only chromatic colour on the marketing
  surface and is always rendered as a flat semantic colour, not an atmospheric
  field.
- **Composition:** state before features. Product pages prioritise current state,
  movement, next action, then evidence. Marketing is more editorial but uses the
  same tokens, type, and restraint.

There is no user-selectable dark theme, parallel marketing colour namespace, or
route-local palette. The dark brand panel on login and onboarding is an intentional,
fixed composition inside an otherwise light product; it is not a theme.

## Source of truth and implementation rules

`frontend/app/globals.css` is the sole owner of global tokens, the font binding,
shared geometry, and global interaction rules. Its imported
`frontend/app/website-type.css` owns the named website/auth type roles, the
legacy scoped size-rung compatibility layer, and the website button treatment;
it does not own a second palette. Editorial and auth hierarchy uses the named
roles, while product UI consumes semantic Tailwind utilities and CSS custom
properties.

- Do not add `@theme`, a raw hex colour, a shared control recipe, or an
  unregistered animation outside `globals.css`.
- Do not create a marketing colour or elevation namespace. Marketing scenes and
  product screens use the same surface, status, elevation, and motion tokens. A
  scoped website type ladder is allowed because public/auth reading sizes and
  dense product UI have different jobs; embedded product previews explicitly reset
  to the app type ladder.
- Prefer existing primitives in `frontend/components/ui/` and
  `frontend/components/marketing/` before making a new one.
- `pnpm check:policy` guards raw colours outside the owner, stray `@theme` blocks,
  legacy identifiers, and the file line budgets.

## Colour

Tokens are semantic; components use the role, not a colour value.

| Role                | Token family                                                                                                                        | Use                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Canvas and surfaces | `background` (`#f8fafc`), `panel` / `elevated` (`#ffffff`), `panel-tonal` (`#f8fafc`), `background-alt` / `well` (`#f1f5f9`), `active` (`#e2e8f0`) | Luminous pearl paper canvas; crisp white panels and floating cards; subtle grey wells and frosted chrome              |
| Text                | `foreground` (`#0f172a`), `secondary` (`#334155`), `muted` (`#526173`), `subtle` (`#596777`), `inverse` (`#ffffff`)                          | Token-driven slate reading ramp; every neutral role remains AA-safe on every shared light surface                    |
| Borders             | `border` (`#e2e8f0`), `border-subtle` (`#f1f5f9`), `border-strong` (`#cbd5e1`), `border-bold` (`#94a3b8`)                                    | Crisp ledger hairlines for structured separation                                                                       |
| Primary action      | `accent-*`                                                                                                                          | Growth Cobalt (`#315CFF`) CTAs, active indicators, explicit selection, links, and focus rings                          |
| Status              | `success-*` (`#31a57a`), `warning-*` (`#d9822b`), `danger-*` (`#d96b55`), `info-*`, `neutral-bg`                                   | App only; always paired with text or an icon                                                                           |
| Evidence and scores | `citation-*`, `run-*`, `score-*`, `series-*`, `chart-*`                                                                             | Persisted evidence, audit status, score bands, and charts                                                              |

The accent is Growth Cobalt: `#315CFF` at rest, `#2347D9` on hover, and `#1A38B5` on press.
`accent-text` (`#1E40AF`) is the accessible cobalt for text on white or tinted backgrounds. Page canvas is a luminous pearl paper (`#f8fafc`), while panel, card,
dialog, and drawer surfaces are crisp white (`#ffffff`). `#f1f5f9` provides alternate surfaces and neutral wells; `#e2e8f0` is the active treatment.

Text hierarchy is semantic rather than route-specific: `foreground` owns headings,
primary values, and actions; `secondary` owns body copy and row values; `muted`
owns labels, captions, and supporting metadata; `subtle` is reserved for tertiary
metadata, placeholders, and unavailable-value marks. The design-system policy
requires all four neutral text roles to meet WCAG 2.1 AA normal-text contrast
(`4.5:1`) on every shared light surface, including `active`.

**Marketing is monochrome-plus-blue.** It uses only white, the ink ramp, and the
one cobalt — no status, score, or category colour. **The authenticated app keeps
the functional families** (status, score bands, run states, citation types, and
the categorical chart series, whose first series is the brand cobalt), because a
data view has to stay legible at a glance. Status colour never carries meaning
alone; it is always paired with a label or icon.

## Typography

Two families only: Plus Jakarta Sans for display headings (`font-display`) and Inter for
UI, body, and data (`font-sans`). Both are loaded through `next/font/google` with
variable fonts and swap display. Interface weights remain concentrated at 400–600. Metrics, dates, ranks,
and percentages use tabular numerals, never a monospace face.

### Website and authentication ladder

The website scale is role-based and starts from a 16px reading baseline. A role
owns its size, leading, weight, tracking, and colour as one unit. Public and auth
components consume these roles instead of assembling arbitrary size, leading,
tracking, weight, and colour combinations.

| Role                    | Family            |      Size / line height |  Weight |                       Tracking | Colour                                      |
| ----------------------- | ----------------- | ----------------------: | ------: | -----------------------------: | ------------------------------------------- |
| Hero display            | Plus Jakarta Sans | 44/48 → 56/60 → 64/68px |     600 |                        -0.04em | foreground; one short phrase may use accent |
| Page title              | Plus Jakarta Sans |         40/44 → 48/54px |     600 |                       -0.035em | foreground                                  |
| Section heading         | Plus Jakarta Sans |         32/38 → 40/46px |     600 |                        -0.03em | foreground                                  |
| Feature heading         | Plus Jakarta Sans |                 24/30px |     600 |                        -0.02em | foreground                                  |
| Small heading           | Plus Jakarta Sans |                 20/26px |     600 |                        -0.01em | foreground                                  |
| Lead                    | Inter             |                 20/30px |     400 |                        -0.01em | secondary                                   |
| Large body              | Inter             |                 18/28px |     400 |                              0 | secondary                                   |
| Body baseline           | Inter             |                 16/24px |     400 |                              0 | secondary                                   |
| Navigation and actions  | Inter             |                 16/20px | 500–600 |                              0 | foreground or inverse                       |
| Label, caption, eyebrow | Inter             |                 14/20px | 500–600 | 0; +0.06em only when uppercase | muted or subtle                             |

Ordinary website paragraphs never render below 16px. Fourteen pixels is reserved
for short labels, metadata, captions, and legal support. Prose stays within a
45–75 character measure. Accent cobalt never carries a long paragraph. Large text
uses tighter leading and tracking; body text stays at zero tracking with more
leading. Pricing values are the one non-editorial website display role:
`website-data-display` uses Inter at 40/46px with tabular numerals and never
applies to prose or headings.

### Product app ladder

The authenticated enterprise application uses a strict token-driven typography ladder
built on Inter (`font-sans`) and Plus Jakarta Sans (`font-display`). It enforces consistent visual
hierarchy, strict tabular numerals for metrics, and high-density information architecture.
Ad-hoc inline text sizes, weights, and color overrides are prohibited in favor of token
classes.

| Role                       | Family            | Size / line height |  Weight | Tracking | Class / Token                            | Text Colour                   |
| -------------------------- | ----------------- | -----------------: | ------: | -------: | :--------------------------------------- | :---------------------------- |
| App Hero / Screen Title    | Plus Jakarta Sans |            26/30px |     600 | -0.025em | `displayHeadingXlClasses`                | `text-foreground`             |
| Section / Surface Heading  | Plus Jakarta Sans |         16–18/23px |     600 | -0.015em | `text-base` / `text-lg font-display`     | `text-foreground`             |
| Primary KPI / Metric Value | Plus Jakarta Sans |    28/35 → 32/40px |     600 |  -0.02em | `text-2xl` / `text-3xl` + `tabular-nums` | `text-foreground`             |
| Metric Subtitle / Delta    | Inter             |            13/20px | 500–600 |        0 | `text-xs` + `tabular-nums`               | `text-secondary` / delta tone |
| UI / Form Field Label      | Inter             |            13/20px |     500 |        0 | `text-xs font-medium`                    | `text-foreground`             |
| Standard Body / Content    | Inter             |            14/21px |     400 |        0 | `text-sm text-secondary`                 | `text-secondary`              |
| Compact Body / Row Data    | Inter             |            13/20px |     400 |        0 | `text-xs text-secondary`                 | `text-secondary`              |
| Micro Eyebrow / Meta Pill  | Inter             |            12/16px |     600 |  +0.08em | `text-2xs uppercase`                     | `text-muted` / `text-subtle`  |

### High density layout and elevation standard

The product app is an enterprise data-dense environment. It uses diffuse elevation
and crisp semantic hairlines to maintain clear structure without visual clutter:

- **Elevation and borders**: Primary cards and surfaces use `bg-panel border border-border` with `shadow-card`.
  Hover states slightly deepen the hairline (`border-border-strong`) and lift (`shadow-card-hover`).
  Elevated menus and popovers use `bg-elevated` and `shadow-elevated`.
- **Drawer and Sheet Composition**: Modals, slide-out drawers, and sheets already provide an
  elevated surface. They must **never** contain nested `<Card>` components. Field groups and
  lists inside drawers use clean structural section divisions (`space-y-4` / borderless rows).
- **Tab & Action Alignment**: Section headers with tabs and actions place controls on the same
  row (`flex items-center justify-between`) rather than wasting vertical canvas on an empty
  header row.
- **Custom Select Menus**: Filter dropdowns and page-kind selectors use custom Radix menus with
  `shadow-elevated rounded-sm` and radio items—never raw browser-native `<select>` popups.

## Data and geometry

| Context                  |     Desktop |     Touch / compact |
| ------------------------ | ----------: | ------------------: |
| Top bar                  |        52px |                52px |
| Sidebar rail             |       236px |       mobile drawer |
| Content gutter           |        24px |                16px |
| Navigation / control row |        36px | 44px minimum target |
| Primary CTA              | 42px height | 44px minimum target |
| Table row                |        40px |     labelled record |

The content area caps at 1360px. Standard cards use 24px internal padding and gap.
The radius scale uses crisp micro-radii: 2px (`xs`, `sm`, controls/buttons/cards), 4px (`md`, `lg`, dialogs/popovers),
and 6px (`xl`, `2xl`); rounded-full (`rounded-full`) is retained for chips, badges, status dots, count pills, and filter toggles.
Elevation uses soft diffuse shadows (`shadow-card` and up), with semantic hairlines for crisp ledger definition.
Marketing sections breathe on a generous rhythm (`--section-y-*`, 120px desktop).

## Layout and content composition

### Application

- Use sections, ledgers, tables, and split workspaces as page architecture. Cards
  support a section; they do not replace one. Avoid nested decorative cards.
- Recommendations show impact, deterministic priority factors, affected scope,
  status, and links to persisted evidence. Do not invent confidence, effort,
  ownership, or causality.
- Site Health puts its crawl control and URL inventory before crawler-bot,
  file, and page-kind diagnostics. The one contextual crawl action stays
  visible while secondary diagnostics collapse.
- That contextual action is **Run new crawl** before or after a run and **Stop
  crawl** while the persisted crawl is active. **Export** is secondary;
  discovery and analysis are not separate user actions. Before a first run, use
  the actionable empty placeholder. During discovery, keep the first ten
  persisted inventory rows visible and enrich them in place as analysis
  arrives. Issue rows show severity, affected-page count, plain-language name,
  frozen problem description, and an evidence chip; persisted remediation is
  disclosed on expand as **How to fix**.
- Site Health progress names blocked and failed work beside completed work:
  **Blocked by robots.txt**, **HTTP 4xx**, **HTTP 5xx**, and **Timeouts** appear
  when non-zero. Waiting copy names a healthy host-gate or retry-backoff wait;
  stalled copy is reserved for backend-reported expired-lease evidence. Never
  describe a crawl as stuck solely because a browser-side timer elapsed.
- Site Health findings use separate **Defects** and **Advisories** views.
  Defects own severity and Opportunity eligibility. The headline says
  **defect issue types** in the default view and **advisory issue types** after
  switching views; supporting counters say class-labelled **occurrences** and
  **affected URLs** so visually adjacent quantities never masquerade as one
  number. Advisory rows use an Advisory label, not a severity chip.
- AEO Readiness is a dimension ledger, never a gauge or mystery number. Its
  table names pass, fail, not applicable, and coverage independently for all
  seven dimensions; not-applicable rows remain visible and are not styled as
  failures. Because one count is one rule evaluated on one page, the surface
  says so rather than letting the totals read as page counts. Evidence opens in
  the shared right-side sheet, failures first — a dimension can carry dozens of
  persisted evaluations, and an in-cell disclosure inflated one table row past
  the height of the viewport.
- Website Changes is an evidence ledger with four named classes and expandable
  before/after provenance. `Expected` is a secondary exact-link label, not a
  fifth severity. Unavailable and non-comparable states use distinct empty
  panels; partial comparisons lead with shared-URL-only and added/removed
  suppression copy. An observed zero renders as “No changes were observed,”
  never as unavailable.
- Mobile retains every critical action. Tables become labelled records; filters
  and evidence use full-height sheets.

#### Screen geometry

Every product screen uses one geometry. Learning it once should mean knowing where
to look on every page in the app.

```text
┌──────────────────────────────────────────────────────────────┐
│ Project / context      Date · Compare      Search    Agent   │
├────────────┬─────────────────────────────────────────────────┤
│            │                                                 │
│ Overview   │  Page title                          Actions    │
│ Analyze    │  Supporting context                             │
│ Act        │                                                 │
│ Track      │  ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│            │  │ Metric  │ │ Metric  │ │ Metric  │            │
│            │  └─────────┘ └─────────┘ └─────────┘            │
│ User Menu  │  Primary analytical surface                     │
│ (Settings) │  ──────────────────────────────────────         │
│            │                                                 │
│            │  Insights / findings / table                    │
└────────────┴─────────────────────────────────────────────────┘
```

Fixed responsibilities per region:

| Region             | Owns                                                                                                        | Never                                             |
| ------------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Top bar            | Project and context switching, date range and comparison window, global search, agent entry                 | Page-specific actions                             |
| Sidebar            | Five loop stations: Overview, Analyze, Act, Track, and Connect; station subnavigation owns its destinations | A third navigation level or disabled future items |
| Page header        | Title, one line of supporting context, and this page's actions                                              | Metrics                                           |
| Metric row         | Three to five headline numbers, each with coverage                                                          | More than five, or a metric without provenance    |
| Analytical surface | The one chart, table, or comparison this page exists for                                                    | Competing equal-weight surfaces                   |
| Insight list       | Ranked insight objects (below)                                                                              | Ad-hoc card shapes                                |

Date range and comparison live in the top bar because they apply to the whole
context, not to one chart. A page that needs its own time control is a page whose
scope is wrong.

Desktop navigation groups destinations under Overview, Analyze, Act, Track,
and Connect. The five-slot mobile bar uses those exact stations; one shared
accessible secondary-navigation component exposes each station's destinations.
Commerce is a conditional Analyze destination backed by persisted capability
evidence; hidden navigation never changes direct-route authorization.
The Agent is a top-bar button opening a right-side sheet, not a destination.
Escape closes it, focus returns to the trigger, and its context is limited to
typed workspace, project, canonical route, date range, and route filters.
The shipped sheet reuses the bounded explain/roadmap workspace and clears its
route preset when the active project changes; no DOM text or unpersisted page
data enters Agent context. Because the sheet is the workspace's only host, the
workspace carries no page chrome of its own: the drawer owns the one title and
description, the result region owns the one scroll container, the composer pins
below it, and task history is a collapsed disclosure rather than a sidebar rail.

Overview stays useful without an audit. Its order is canonical Facts and edit
drawer, one next action, and Track. There is no Product loop station strip:
four tiles restating pipeline state told the reader nothing they could act on.
Unavailable Track values use text and an em dash rather than fabricated zeroes;
report actions do not render until a persisted audit/report exists.

AI Visibility uses three tabs—Trends, Mentions & Citations, and Query Fanout—with
Trends as the default and no parallel Overview surface. It carries no project
switcher of its own; the top bar owns project context.

- The Trends metric row is **exactly the five computed metrics** (Visibility
  Score, SOV mention, SOV response, brand mentions, owned citations). Sentiment
  and average position are never computed (decision B-2), so they are disclosed
  as "—" in their rankings-table columns and are **not** stat cards — two
  permanently blank tiles pushed the row past the five-metric cap and read as
  broken.
- A trend chart renders only with at least two points. One run plots one dot;
  a full empty axis under a banner that already says there is no movement is
  noise. The same rule collapses the start-of-range ranking comparison until a
  second run exists.
- The two evidence tabs are **ruled rows, not nested cards**. An execution is a
  row inside the tab's one card — never a filled, bordered box holding a third
  layer of boxes around its citations or queries. Task/analysis/artifact ids are
  audit trail, so they live behind one collapsed **Provenance** disclosure per
  row rather than as raw truncated UUIDs across the primary surface.

#### The insight object

The product model is _acquire evidence → understand → detect gaps → create
opportunities → improve → verify → recommend next_. The reusable unit that model
produces is not a dashboard card — it is an **insight**, and it is the single most
important component in the system.

```text
┌─────────────────────────────────────────────────────────┐
│ HIGH PRIORITY                              SITE          │
│                                                          │
│ 47 product pages have weak buying-intent coverage        │
│                                                          │
│ Evidence                                                 │
│ 47 pages · /products/* · detected 2h ago                 │
│                                                          │
│ Why this matters                                         │
│ Pack expects purchase questions on product detail roles  │
│                                                          │
│ Potential impact                         High            │
│                                                          │
│ [View evidence]                         [Resolve →]      │
└─────────────────────────────────────────────────────────┘
```

Required anatomy, in this order:

1. **Priority** and **source layer** — the layer chip is how the user learns which
   system found this without reading the body.
2. **Claim** — one sentence, specific, quantified where a count exists.
3. **Evidence** — scope, selector, and observation time. Always resolves to
   persisted evidence.
4. **Why this matters** — grounded in a pack expectation, a demand signal, or a
   contradiction. Never a causal claim, never an invented benchmark.
5. **Potential impact** — from the deterministic priority formula, not a model.
6. **Two actions** — inspect, and act.

Rules:

- One insight component, used identically in Analyze, Act, Track, and the Growth
  Agent sheet. A station that invents its own finding card breaks coherence.
- The same insight in two places is the same server ID and the same cache identity.
- An insight with no resolvable evidence does not render.
- Coverage and unknown states use their text labels; an insight never implies
  completeness it does not have.
- Insights are ranked by the deterministic formula. The agent may group and explain
  them; it does not reorder them.
- On dense summary surfaces (such as the Command Center Overview), the 'Why this matters'
  section is omitted via `hideWhyThisMatters` to reduce vertical clutter while keeping priority,
  claim, evidence, potential impact, and actions directly visible.

### Marketing and auth

Marketing is editorial rather than dense, while staying recognisably part of the
product. A page is a vertical stack of full-width sections with content in a
centred container. Use the recipe: eyebrow, heading, short lead, evidence/media or
focused grid, then an optional CTA.

- Give sections breathing room on the global rhythm rather than route-local values.
- Prefer asymmetric text-and-media compositions, a proof ledger, or a concise grid
  over a wall of feature cards. The product UI is the "photography": a real
  workspace canvas carries the visual weight.
- Keep body copy around 60–70 characters wide and use one H1 per page.
- Auth uses the website type ladder and shared focus treatment; the form remains
  the primary task. The existing dark login/onboarding brand panel is preserved.
- Onboarding review makes positioning, target audience, and products/services
  editable and required, alongside owned domains and competitors. Prompt
  generation begins only after the user confirms those structured ICP facts.
- Website and app copy, data, feature claims, and workflow behaviour are outside
  this pass. Product previews may change layout, typography, colour, border,
  radius, or elevation only; their strings and scripted content stay unchanged.

## Component recipes

### Controls

App buttons are `rounded-sm` (6px) rectangles with no decorative inset border.
Website and auth primary buttons use the same shared Button behaviour and blue
fill, but add the reference treatment: 12px corners, a subtle light inset edge,
a defined outer blue edge, and quiet elevation. Secondary, neutral, ghost, and
danger remain shared semantic variants. Every control has a direct label, a
visible focus ring (an opaque accent halo, ≥3:1), immediate pressed feedback, and
at least a 44px touch target.

Inputs use the semantic input and border roles. Labels sit with their control,
helper text explains constraints, and errors give a recovery instruction. Never
use placeholder text as the only label.

### Panels, badges, and evidence

Elevation is shared between marketing and the app. The reference card treatment
uses a crisp near edge plus a soft neutral ambient shadow, as shown in reference
image 2. Elevation never implies that every region needs a white card: sections,
tables, and grouped rows may remain borderless on the white canvas or use the
`#F3F4F6` highlight. A surface receives elevation only when it floats, overlays,
or needs separation from adjacent content. Interactive cards may raise one rung
on hover — a deeper shadow and a small rise (`hover:-translate-y-0.5`) — as the
one sanctioned lift. Badges
pair a text label with their state mark; a colour, dot, or icon is never the sole
signal. Evidence rows identify source, measurement context, and the action that
opens the persisted record. Empty and loading states preserve layout and explain
what is missing.

### Navigation and overlays

The marketing nav floats transparent over the hero and becomes a frosted white on
scroll, with no shadow. The app sidebar makes the active location obvious through a
blue fill, a leading blue rail, and a Carbon-Dark label — not through weight.
Menus and custom listboxes use `shadow-elevated`, `rounded-md`, the shared menu
panel/item recipes, and a short system-curve entrance. Single-select filters use
radio menu items so the current value is visible without relying on colour.
Tooltips use the elevated rung and `rounded-md`; dialogs and drawers use
`shadow-modal-value` with `rounded-lg`. Drawers are right-side modal contextual
sheets owned by `components/ui/drawer.tsx`. Their scrim dims and locks the page;
outside click, Escape, or the close control dismisses them, and focus returns to
the trigger. Feature components never import Radix directly.

Tabs remain the underline treatment for navigation between views and for one
mutually exclusive data table within a surface (for example, Top pages and Top
queries). They provide keyboard navigation and preserve the selected tab's
focus. Segmented controls use one bordered-track recipe for compact single-select
changes within a view. Filter chips are the shared pill treatment for independent
or multi-select filters; they live in `components/ui`, not a feature directory.

Changing a chart interval retains the previous analytical content while the new
persisted projection loads. Mark the analytical region busy and show compact
loading feedback; do not replace it with a skeleton or let its labels describe
data that has not arrived.

## Motion and accessibility

Pointer-opened menus use a barely visible 150–180ms origin-aware fade/shift.
Keyboard-opened command interfaces are immediate. Drawers use a short 220–260ms
right-side transition that remains interruptible. Press feedback starts on
pointer-down. Beyond that, a small, deliberate set of explanatory motions is
sanctioned, each one calm and reduced-motion-safe:

- the rotating answer-engine wordmarks and the product-window walkthrough;
- scroll **reveal** entrances (GSAP) that fade and rise a small distance and never
  hide server-rendered content after hydration;
- the interactive-card hover lift.

Every one of these stops under `prefers-reduced-motion: reduce`: CSS animations and
transitions are neutralised globally, the SMIL pipeline dots are hidden, and the
GSAP reveals do not run. WCAG 2.1 AA is the minimum. Focus is always visible via an
opaque accent halo; state is never colour-only; forced-colours and print remain
usable.

## Review checklist

Before merging a visual change, verify:

- It uses semantic global tokens and an existing primitive where one applies.
- Website/auth type uses a documented content role with a 16px body baseline;
  app type keeps its compact scale. Both stay within weights 400–600.
- Marketing stays monochrome-plus-blue; functional colour appears only in the app.
- The default canvas is `#f8f9fc`, quiet tonal panels use `#f1f4f9`, and elevation
  does not force card backgrounds onto structural regions.
- Elevation uses the shared shadow tokens; radius uses the 4 / 6 / 8 / 12 / 16 / 20
  scale.
- Any new motion is calm and stops under `prefers-reduced-motion`.
- Text, focus, status, loading, error, empty, keyboard, touch, reduced-motion,
  forced-colours, and mobile states remain usable.
- No website or app copy, data, claims, or workflow behaviour changed.
- Focused tests, `pnpm check:policy`, and the appropriate build or visual checks
  pass. React Doctor is the final verification command.
