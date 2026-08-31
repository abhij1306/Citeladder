# CiteLadder Design System

> Canonical visual and interaction contract for marketing, authentication, and
> the authenticated application. This is the only design-system document.

## Direction and identity

CiteLadder is a light-only, evidence-led enterprise system. The authenticated
application uses the **Prism Evidence Workspace**: a warm editorial canvas,
navy ink and actions, indigo analytical selection, semantic pastel evidence
washes, useful density, and deliberate negative space. It is an operating
workspace, not a wall of equal-weight KPI cards.

- **Name and domain:** CiteLadder, `citeladder.com`.
- **Logo:** the canonical full-colour horizontal CiteLadder lockup in
  `frontend/public/citeladder-logo.webp`; product, marketing, authentication, and
  onboarding surfaces reuse that asset rather than reconstructing the symbol and
  wordmark independently. `frontend/public/citeladder-favicon.ico` owns browser
  and installable-app iconography.
- **Voice:** direct, confident, specific. One idea per sentence. Prefer evidence
  and outcomes over generic AI language.
- **Typography:** Geist for UI, body, and data everywhere, with Plus Jakarta Sans reserved for
  website and focused-flow display headings. Authentication and onboarding share that roomier
  flow ladder; the authenticated application uses Geist and the even-number product ladder.
  Website and flow surfaces use a 16px reading baseline. Size,
  leading, weight, tracking, and
  colour are one role contract, never independent page-level choices.
- **Action and selection:** navy (`#14213D`) owns authenticated primary actions.
  Indigo owns analytical selection, links, and focus. Cyan, coral, lime, and
  amber are evidence/status families, never route decoration. Deferred public
  and focused-flow surfaces keep their scoped cobalt contract until their
  separately approved redesign.
- **Composition:** state before features. Product pages prioritise current state,
  movement, next action, then evidence. Marketing is more editorial but uses the
  same tokens, type, and restraint.

There is no user-selectable dark theme, parallel marketing colour namespace, or
route-local palette. Authentication and onboarding use one centred light-ground
flow; neither surface reserves viewport width for a decorative brand rail.

## Source of truth and implementation rules

`frontend/app/globals.css` is the sole owner of global tokens, the font binding,
cross-surface geometry, and global interaction rules. Its imported
`frontend/app/website-type.css` owns the named website/auth/onboarding flow roles,
flow-specific geometry, the legacy scoped size-rung compatibility layer, and the
website button treatment;
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
  legacy identifiers, and architecture ownership boundaries.

## Colour

Tokens are semantic; components use the role, not a colour value.

| Role | Token family | Use |
| --- | --- | --- |
| Canvas and structure | `background` (`#FAF9F6`), `background-alt` / `sidebar` (`#F7F6F2`), `well` (`#F1F0EB`) | Warm depth through tone and whitespace |
| Raised surfaces | `panel`, `input`, `elevated` (`#FFFFFF`) | Inputs, overlays, and meaningful semantic objects |
| Text | `foreground` (`#14213D`), `secondary` (`#475569`), `muted` / `subtle` (`#536176`), disabled (`#7B8494`) | Editorial ink roles |
| Borders | gray 200–500 semantic aliases | Minimal ledger rules and input edges, never decorative shells |
| Primary action | `action-*` | Navy authenticated primary actions |
| Selection and focus | `accent-*` | Indigo selection, links, tabs, and focus |
| Status and evidence | cyan, coral, lime, amber, `citation-*`, `run-*`, `score-*`, `chart-*` | Persisted evidence and status, always paired with a label or icon |

The authenticated selection accent is indigo: `#5542F6` at rest and `#4033C7`
for text, hover, and press. Navy owns primary actions. Product canvas is warm
`#FAF9F6`; structural regions use `#F7F6F2`; wells use `#F1F0EB`; raised inputs
and overlays are white. Marketing, authentication, and onboarding retain their
established scoped values.

Text hierarchy is semantic rather than route-specific: `foreground` owns headings,
primary values, and actions; `secondary` owns body copy and row values; `muted`
owns labels, captions, and supporting metadata; `subtle` is reserved for tertiary
metadata, placeholders, and unavailable-value marks. The design-system policy
requires all four neutral text roles to meet WCAG 2.1 AA normal-text contrast
(`4.5:1`) on every shared light surface, including `active`.

Deferred marketing remains monochrome-plus-cobalt under `.website-type`.
The authenticated app keeps functional evidence families because a data view
must remain legible at a glance. Functional colour never carries meaning alone.

## Typography

Two families only: Geist for UI, body, and data (`font-sans`) and for every authenticated-app heading; Plus Jakarta Sans is the website and focused-flow display face. Both are loaded through `next/font/google` with variable fonts and swap display. Interface weights remain concentrated at 400–600. Metrics, dates, ranks,
and percentages use tabular numerals, never a monospace face.

### Website and focused-flow ladder

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
| Flow title              | Plus Jakarta Sans |         28/34 → 32/38px |     600 |                       -0.025em | foreground                                  |
| Flow group title        | Geist             |                 17/24px |     600 |                        -0.01em | foreground                                  |
| Flow help               | Geist             |                 15/22px |     400 |                              0 | muted                                       |
| Flow metadata           | Geist             |                 14/20px |     500 |                              0 | muted; tabular numerals                     |
| Lead                    | Geist             |                 20/30px |     400 |                        -0.01em | secondary                                   |
| Large body              | Geist             |                 18/28px |     400 |                              0 | secondary                                   |
| Body baseline           | Geist             |                 16/24px |     400 |                              0 | secondary                                   |
| Navigation and actions  | Geist             |                 16/20px | 500–600 |                              0 | foreground or inverse                       |
| Label, caption, eyebrow | Geist             |                 14/20px | 500–600 | 0; +0.06em only when uppercase | muted or subtle                             |

Ordinary website paragraphs never render below 16px. Fourteen pixels is reserved
for short labels, metadata, captions, and legal support. Prose stays within a
45–75 character measure. Accent cobalt never carries a long paragraph. Large text
uses tighter leading and tracking; body text stays at zero tracking with more
leading. Pricing values are the one non-editorial website display role:
`website-data-display` uses Geist at 40/46px with tabular numerals and never
applies to prose or headings.

### Product app ladder

The authenticated enterprise application uses a strict Geist-only typography
ladder. It enforces consistent visual hierarchy, strict tabular numerals for metrics, and
high-density information architecture.
Ad-hoc inline text sizes, weights, and color overrides are prohibited in favor of token
classes.

| Role | Family | Size / line height | Weight | Tracking | Class / Token | Text Colour |
| --- | --- | ---: | ---: | ---: | :--- | :--- |
| Metadata / table header | Geist | 12/16px | 400–500 | 0 | `text-xs` | `text-secondary` / `text-muted` |
| Body and controls | Geist | 14/20px | 400 | 0 | `text-sm` | semantic text role |
| Emphasized body | Geist | 14/20px | 500 | 0 | `text-sm font-medium` | semantic text role |
| Section heading | Geist | 16/22px | 500 | 0 | `text-base font-medium` | `text-foreground` |
| Panel heading | Geist | 18/24px | 500 | 0 | `text-lg font-medium` | `text-foreground` |
| Page title | Geist | 24/32px | 500 | 0 | `text-2xl font-medium` | `text-foreground` |
| Primary metric | Geist | 28/36 or 32/40px | 500 | -0.02em | `text-3xl` / `text-4xl` + `tabular-nums` | `text-foreground` |

Fourteen pixels is the product baseline. Twelve pixels is reserved for short
labels, provenance, badges, and table headers. `text-2xs`, 10px and 11px product
text, `font-semibold`, and `font-bold` are retired from authenticated UI.

Availability labels such as **Not measured**, **Unavailable**, and **Unknown**
never inherit metric typography. They use the shared `UnavailableValue`
treatment: muted, 12/16px, regular weight, and zero tracking on every surface.

### High density layout and elevation standard

The product app is an enterprise data-dense environment. It uses diffuse elevation
and crisp semantic hairlines to maintain clear structure without visual clutter:

- **Elevation and borders**: structural sections are open on the canvas or use a
  tonal well. `Card` is reserved for a real semantic object and defaults to a
  white fill with no border or shadow. Shadows belong only to overlays, menus,
  drawers, dialogs, the command palette, and toasts.
- **Drawer and Sheet Composition**: Modals, slide-out drawers, and sheets already provide an
  elevated surface. They must **never** contain nested `<Card>` components. Field groups and
  lists inside drawers use clean structural section divisions (`space-y-4` / borderless rows).
  Multi-category editors use the shared underline tabs; the selected panel owns one linear
  field flow rather than a dashboard-like field grid.
- **Tab & Action Alignment**: Section headers with tabs and actions place controls on the same
  row (`flex items-center justify-between`) rather than wasting vertical canvas on an empty
  header row.
- **Custom Select Menus**: Filter dropdowns and page-kind selectors use custom Radix menus with
  `shadow-elevated`, the semantic overlay-radius role, and radio items—never raw browser-native
  `<select>` popups.

## Data and geometry

| Context                  |     Desktop |     Touch / compact |
| ------------------------ | ----------: | ------------------: |
| Top bar                  |        52px |                52px |
| Sidebar rail             |       220px |       mobile drawer |
| Content gutter           |        24px |                16px |
| Navigation / control row |        36px | 44px minimum target |
| Primary CTA              | 32–36px height | 44px minimum target |
| Table row                |        40px |     labelled record |

The content area caps at 1360px. Internal groups use 16–24px and major sections
separate by 32px. Compact gutters remain 16px; dialogs and drawers use 20px.
Authenticated-app geometry is role-driven: controls and fields use 10px corners,
semantic objects use 16px, and overlays use 16px. Marketing and authentication retain
their documented website treatment. Fully rounded geometry is reserved for chips, badges,
status dots, count pills, and filter toggles. Components consume the semantic geometry role;
they do not select a route-local radius.

`shadow-elevated` owns floating menus and popovers; `shadow-modal-value` owns
drawers and dialogs. No authenticated feature owns a shadow recipe.
Marketing sections breathe on a generous rhythm (`--section-y-*`, 120px desktop).

Authentication and onboarding share the `[data-flow-surface]` geometry owned by
`website-type.css`: a 64px bar (56px below 640px), 720px content measure, 880px
review measure, 24px gutters growing to 32px, 40px from title block to first
group, 32px between groups, 16px from help to controls, and 8px within a title
stack. Flow controls use 12px corners; selection chips are 36px high on desktop
and 44px on touch. The shell owns the scrolling main region and bottom action
bar so content height never creates a dead band above the primary action.

### Availability vocabulary

Product data never uses punctuation as its only empty-state explanation. Render the state that
is actually known: **Not measured** when no measurement exists, **Not run** when the workflow
has not started, **Not set** for missing user-configurable facts, **Unavailable** when evidence
or a provider cannot supply a value, **Not applicable** when the field does not apply, and
**Unknown** when the system cannot determine the state. An observed zero remains `0`; chart
series retain visual gaps for unavailable points and explain those gaps accessibly.

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
  arrives. Issues use one responsive master-detail workspace: a compact group
  list on the left and the selected group's occurrence evidence, affected URLs,
  remediation, and actions in a sticky right rail. Narrow screens stack the
  same regions without hiding evidence. Do not restore per-card expansion,
  queries, or cursor state.
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
  number. Issue severity, dimension, and affected page kinds use compact
  unboxed metadata labels; advisory rows use an Advisory label rather than a
  severity label. Affected-page counts stay at body scale and regular weight.
- Issue evidence belongs to a persisted occurrence and its directly linked
  evaluation. Group detail and URL detail reuse one bounded presenter for exact
  schema types/properties, heading transitions and scope, and offending control
  descriptors. Unknown shapes use labelled bounded fields, never raw JSON or a
  generic site-wide claim.
- AEO Readiness is a dimension ledger, never a gauge or mystery number. Its
  dedicated tab opens directly on that ledger; aggregate score, coverage, and
  page-count summaries stay in Overview instead of repeating in a second card.
  The table uses the same score, quality, coverage, and state roles as Overview
  for all seven dimensions; not-applicable rows remain visible and are not
  styled as failures. Overview provides the direct **View details** route into
  this tab.
  Evidence opens in the shared right-side sheet, failures first — a dimension
  can carry dozens of persisted evaluations, and an in-cell disclosure inflated
  one table row past the height of the viewport.
- Site Health Architecture leads with the persisted Internal linking and
  Structure depth summaries because they are primary AEO signals. Five
  site-level facts and an always-visible page-kind ledger follow. Page kind,
  pages, median depth, indexable count, duplicate
  metadata, and orphaned count never require disclosure; only a kind's assigned
  URL list expands in a bounded region. A read-only observed hierarchy then
  renders the persisted parent relationships and their evidence sources without
  client-side inference in its own bounded scroll region.
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
│ Route title                         Search · Ctrl K   Agent   │
├────────────┬─────────────────────────────────────────────────┤
│            │                                                 │
│ Overview   │  Supporting context                  Actions    │
│ Analyze    │                                                 │
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
| Top bar            | Visible route title, global search / command entry, and Agent entry | Route metrics or a second navigation level |
| Sidebar            | Five loop stations: Overview, Analyze, Act, Track, and Connect; station subnavigation owns its destinations | A third navigation level or disabled future items |
| Page header        | The top bar's visible route title; entity detail routes retain an accessible-only route label while their entity heading stays visible | Metrics |
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

Overview stays useful without an audit. Its canonical reading order is project identity plus
Facts, one next action plus Track, Project State, Movement, ranked actions, report proof, and Top
Insights. The top card places the project identity and actions first, followed by three
simultaneously visible tonal summaries: Positioning, Target Audience, and Offerings &
Competitors. These summaries stack on compact screens; the editor opens in the shared drawer
with **Facts & Positioning**, **Audience & Offerings**, and **Competitors** tabs. Its single save
action sits above the tablist, editable facts use the drawer's available vertical space, and
tracked competitors pair their names with the shared brand-logo treatment. There is no
Product loop station strip: four tiles restating pipeline state told the reader nothing they
could act on. Unavailable Track values use the explicit availability vocabulary rather than a
dash or fabricated zero; report actions do not render until a persisted audit/report exists.

Overview metric labels and values are separate roles. **Citation share** uses the shared surface
heading treatment and KPI value ladder as the other persisted Overview metrics; it never creates
a route-local display scale by styling the label and value as one oversized sentence.

AI Visibility uses three tabs—Trends, Mentions & Citations, and Query Fanout—with
Trends as the default and no parallel Overview surface. It carries no project
switcher of its own; the top bar owns project context.

- The Trends metric row is **exactly the five computed metrics** (Visibility
  Score, SOV mention, SOV response, brand mentions, owned citations). Sentiment
  and average position are never computed (decision B-2), so they are disclosed
  as **Not measured** in their rankings-table columns and are **not** stat cards — two
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
  the primary task. Auth and onboarding use one centred light flow shell with a
  compact wordmark bar; onboarding adds three-step progress and a sticky action bar.
- Onboarding review makes the category, buyer type, market scope, owned domains,
  and competitors directly confirmable. Prompt generation begins only after the
  user confirms the visible structured ICP facts.
- Website and app copy, data, feature claims, and workflow behaviour are outside
  this pass. Product previews may change layout, typography, colour, border,
  radius, or elevation only; their strings and scripted content stay unchanged.

## Component recipes

### Controls

App buttons use the 10px control-radius role with no decorative inset border.
Website and flow primary buttons use the same shared Button behaviour and blue
fill, but add the reference treatment: 12px corners, a subtle light inset edge,
a defined outer blue edge, and quiet elevation. Secondary, neutral, ghost, and
danger remain shared semantic variants. Every control has a direct label, a
visible focus ring (an opaque accent halo, ≥3:1), immediate pressed feedback, and
at least a 44px touch target.

Inputs use the semantic input and border roles. Labels sit with their control,
helper text explains constraints, and errors give a recovery instruction. Never
use placeholder text as the only label. Authentication and onboarding fields and
large flow buttons use the dedicated 12px auth-control radius; a composed input exposes one
focus ring on its shared frame rather than a second outline on its native input.

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
what is missing with the explicit availability vocabulary; a standalone dash is
never an empty-state label.

### Navigation and overlays

The marketing nav floats transparent over the hero and becomes a frosted white on
scroll, with no shadow. The app sidebar makes the active location obvious through
a quiet indigo tonal fill and indigo label, never through weight, translation, or
a leading rail.
Menus and custom listboxes use `shadow-elevated`, the semantic overlay-radius role, the shared
menu panel/item recipes, and a short system-curve entrance. Single-select filters use
radio menu items so the current value is visible without relying on colour.
Tooltips use the elevated rung and the 16px overlay-radius role; dialogs and drawers use
`shadow-modal-value` with the same overlay-radius role. Drawers are right-side modal contextual
sheets owned by `components/ui/drawer.tsx`. Their scrim dims and locks the page;
outside click, Escape, or the close control dismisses them, and focus returns to
the trigger. Controlled dialogs follow the same focus-return contract. Dialog and
drawer owners also provide modal padding and footer separation; consumers do not
recreate that chrome. Feature components never import Radix directly.

Tabs remain the underline treatment for navigation between views and for one
mutually exclusive data table within a surface (for example, Top pages and Top
queries). They provide keyboard navigation and preserve the selected tab's
focus. Segmented controls use one bordered-track recipe for compact single-select
changes within a view. Filter chips are the shared pill treatment for independent
or multi-select filters; they live in `components/ui`, not a feature directory.
The complete authenticated capability and ownership map lives in
[`ui-component-system.md`](ui-component-system.md). HeroUI is a reference for
state completeness, not an installed dependency.

Changing a chart interval retains the previous analytical content while the new
persisted projection loads. Mark the analytical region busy and show compact
loading feedback; do not replace it with a skeleton or let its labels describe
data that has not arrived.

## Motion and accessibility

Authenticated routes are wrapped by the lazy Motion provider. Pointer-opened menus use a barely visible 150–180ms origin-aware fade/shift.
Keyboard-opened command interfaces are immediate. Drawers use a short 220–260ms
right-side transition that remains interruptible. Press feedback starts on
pointer-down. Beyond that, a small, deliberate set of explanatory motions is
sanctioned, each one calm and reduced-motion-safe:

- the rotating answer-engine wordmarks and the product-window walkthrough;
- scroll **reveal** entrances (GSAP) that fade and rise a small distance and never
  hide server-rendered content after hydration;
- master-detail selection continuity and measured domain-owned expansion.
- onboarding research results resolving beneath the factual activity list with
  one 220ms fade-and-rise sequence and 60ms staggering.

Authenticated route content and tab indicators update immediately. Do not fade
either surface: navigation opacity transitions create a visible flash during
fast route and query-state changes.

Every one of these stops under `prefers-reduced-motion: reduce`: CSS animations and
transitions are neutralised globally, the SMIL pipeline dots are hidden, and the
GSAP reveals do not run. WCAG 2.1 AA is the minimum. Focus is always visible via an
opaque accent halo; state is never colour-only; forced-colours and print remain
usable.

## Review checklist

Before merging a visual change, verify:

- It uses semantic global tokens and an existing primitive where one applies.
- Website and focused-flow type use documented content roles with a 16px body
  baseline; authenticated-app type uses Geist at weights 400 and 500 only.
- Marketing stays monochrome-plus-blue; functional colour appears only in the app.
- The authenticated product canvas is `#FAF9F6`; structural panels use
  `#F7F6F2`; tonal wells use `#F1F0EB`.
- App controls use 10px, semantic objects use 16px, and overlays use 16px.
  Shadows appear only on floating surfaces.
- Any new motion is calm and stops under `prefers-reduced-motion`.
- Text, focus, status, loading, error, empty, keyboard, touch, reduced-motion,
  forced-colours, and mobile states remain usable.
- No website or app factual copy, data, claims, or workflow behaviour changes without explicit approval.
- App data absence uses an explicit semantic label; observed zero remains distinct and authored
  prose punctuation is unaffected.

The focused flow introduces no new colour family, gradient, decorative glow,
nested card, or competitor mutation. Solid cobalt fill is reserved for the
primary action and current-step mark; selected answers use the quiet accent
surface and border without changing font weight. The transaction flow and all
explicit confirmation gates remain unchanged.
- Repository-owned static, test, and appropriate visual commands pass. External
  or manual quality tools are never acceptance gates unless a deterministic
  repository command owns them.
