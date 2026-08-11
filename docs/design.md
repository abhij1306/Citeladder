# CiteLadder Design System

> Canonical visual and interaction contract for marketing, authentication, and
> the authenticated application. This is the only design-system document.

## Direction and identity

CiteLadder is a light-only, evidence-led enterprise system. It should feel calm,
precise, and engineered. It began from a Tesla-style restraint and has settled
into a refined, Untitled-UI-influenced light system: one chromatic accent,
generous whitespace, crisp micro-shadows over hairline borders, and a few
deliberate, quiet motion treatments.

- **Name and domain:** CiteLadder, `citeladder.com`.
- **Logo:** a monochrome rounded inverted L with one rounded horizontal line
  through its middle. The middle line is 10 units long, and the visible whitespace
  above that line and between it and the bottom line is equal. Clipped inner and
  softly offset outer shadows add depth without introducing another visible
  contour. The mark inherits the surrounding foreground colour on every surface.
- **Voice:** direct, confident, specific. One idea per sentence. Prefer evidence
  and outcomes over generic AI language.
- **Typography:** Satoshi for display headings and Switzer for UI, body, and data,
  both self-hosted as variable WOFF2 files through `next/font/local`. The website and authentication surfaces
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

| Role                | Token family                                                                                    | Use                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Canvas and surfaces | `background` and `panel` (white), `background-alt` / `well` (`#F3F4F6`), `sidebar`              | White is the default canvas; subtle neutral gray groups or highlights content without turning every region into a card |
| Text                | `foreground` (#101828), `secondary` (#344054), `muted` (#475467), `subtle` (#667085), `inverse` | Untitled UI 10-step Gray reading ramp                                                                                  |
| Borders             | `border` (#e4e7ec), `border-subtle` (#f2f4f7), `border-strong` (#d0d5dd)                        | Crisp hairlines for subtle separation                                                                                  |
| Primary action      | `accent-*`                                                                                      | Reference Blue (`#2667FF`) CTAs, explicit selection, links, and focus                                                  |
| Status              | `success-*`, `warning-*`, `danger-*`, `info-*`, `neutral-bg`                                    | App only; always paired with text or an icon                                                                           |
| Evidence and scores | `citation-*`, `run-*`, `score-*`, `series-*`, `chart-*`                                         | Persisted evidence, audit status, score bands, and charts                                                              |

The accent is Reference Blue: `#2667FF` at rest, darkened on hover and press.
`accent-text` is a darker accessible blue for text on white. Page, panel, card,
dialog, and drawer surfaces are white. `#F3F4F6` is the shared neutral highlight
for grouped regions, wells, hover, and quiet emphasis. Pale-blue fills do not act
as atmosphere, section backgrounds, or generic highlights.

**Marketing is monochrome-plus-blue.** It uses only white, the ink ramp, and the
one blue — no status, score, or category colour. **The authenticated app keeps
the functional families** (status, score bands, run states, citation types, and
the categorical chart series, whose first series is the brand blue), because a
data view has to stay legible at a glance. Status colour never carries meaning
alone; it is always paired with a label or icon.

## Typography

Two families only: Satoshi for display headings (`font-display`) and Switzer for
UI, body, and data (`font-sans`). Both are self-hosted through `next/font/local`:
one upright Satoshi variable WOFF2 and upright plus italic Switzer variable WOFF2
files cover the used styles without runtime stylesheet requests or unused static
cuts. Interface weights remain concentrated at 400–600. Metrics, dates, ranks,
and percentages use tabular numerals, never a monospace face.

### Website and authentication ladder

The website scale is role-based and starts from a 16px reading baseline. A role
owns its size, leading, weight, tracking, and colour as one unit. Public and auth
components consume these roles instead of assembling arbitrary size, leading,
tracking, weight, and colour combinations.

| Role                    | Family  |      Size / line height |  Weight |                       Tracking | Colour                                      |
| ----------------------- | ------- | ----------------------: | ------: | -----------------------------: | ------------------------------------------- |
| Hero display            | Satoshi | 44/48 → 56/60 → 64/68px |     600 |                        -0.04em | foreground; one short phrase may use accent |
| Page title              | Satoshi |         40/44 → 48/54px |     600 |                       -0.035em | foreground                                  |
| Section heading         | Satoshi |         32/38 → 40/46px |     600 |                        -0.03em | foreground                                  |
| Feature heading         | Satoshi |                 24/30px |     600 |                        -0.02em | foreground                                  |
| Small heading           | Satoshi |                 20/26px |     600 |                        -0.01em | foreground                                  |
| Lead                    | Switzer |                 20/30px |     400 |                        -0.01em | secondary                                   |
| Large body              | Switzer |                 18/28px |     400 |                              0 | secondary                                   |
| Body baseline           | Switzer |                 16/24px |     400 |                              0 | secondary                                   |
| Navigation and actions  | Switzer |                 16/20px | 500–600 |                              0 | foreground or inverse                       |
| Label, caption, eyebrow | Switzer |                 14/20px | 500–600 | 0; +0.06em only when uppercase | muted or subtle                             |

Ordinary website paragraphs never render below 16px. Fourteen pixels is reserved
for short labels, metadata, captions, and legal support. Prose stays within a
45–75 character measure. Accent blue never carries a long paragraph. Large text
uses tighter leading and tracking; body text stays at zero tracking with more
leading. Pricing values are the one non-editorial website display role:
`website-data-display` uses Switzer at 40/46px with tabular numerals and never
applies to prose or headings.

### Product app ladder

The authenticated app keeps the current compact `--text-*` sizes. Replacing Public
Sans with Switzer must not change their computed sizes, control heights, table
density, or screen geometry. Product previews embedded on the website use the app
ladder because they depict product UI, while surrounding editorial copy uses the
website ladder.

## Data and geometry

| Context                  |     Desktop |     Touch / compact |
| ------------------------ | ----------: | ------------------: |
| Top bar                  |        48px |                52px |
| Sidebar rail             |       224px |       mobile drawer |
| Content gutter           |        20px |                16px |
| Navigation / control row |        32px | 44px minimum target |
| Primary CTA              | 40px height | 44px minimum target |
| Table row                |        36px |     labelled record |

The content area caps at 1383px. Standard cards use 16px internal padding and gap.
The radius scale is 4px (`xs`), 6px (`sm`, controls/buttons), 8px (`md`), 12px
(`lg`, standard cards), 16px (`xl`), and 20px (`2xl`, feature panels); a full
radius is reserved for badges, dots, and toggles. Elevation is Untitled-UI
micro-shadows layered over hairline borders (`shadow-card` and up), never a heavy
drop. Marketing sections breathe on a generous rhythm (`--section-y-*`, 120px
desktop).

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
  arrives. Remediation subtitles use persisted remediation text.
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
│ Site       │  Supporting context                             │
│ Content    │                                                 │
│ Demand     │  ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│ Growth     │  │ Metric  │ │ Metric  │ │ Metric  │            │
│            │  └─────────┘ └─────────┘ └─────────┘            │
│ Reports    │                                                 │
│            │  Primary analytical surface                     │
│ Settings   │  ──────────────────────────────────────         │
│            │                                                 │
│            │  Insights / findings / table                    │
└────────────┴─────────────────────────────────────────────────┘
```

Fixed responsibilities per region:

| Region             | Owns                                                                                        | Never                                          |
| ------------------ | ------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Top bar            | Project and context switching, date range and comparison window, global search, agent entry | Page-specific actions                          |
| Sidebar            | Workspace links plus primary destinations grouped under Site, Content, and Demand Intelligence | A third navigation level or disabled future items |
| Page header        | Title, one line of supporting context, and this page's actions                              | Metrics                                        |
| Metric row         | Three to five headline numbers, each with coverage                                          | More than five, or a metric without provenance |
| Analytical surface | The one chart, table, or comparison this page exists for                                    | Competing equal-weight surfaces                |
| Insight list       | Ranked insight objects (below)                                                              | Ad-hoc card shapes                             |

Date range and comparison live in the top bar because they apply to the whole
context, not to one chart. A page that needs its own time control is a page whose
scope is wrong.

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

- One insight component, used identically in Site, Content, Demand, and the Growth
  Agent. A layer that invents its own finding card breaks the product's coherence.
- The same insight in two places is the same server ID and the same cache identity.
- An insight with no resolvable evidence does not render.
- Coverage and unknown states use their text labels; an insight never implies
  completeness it does not have.
- Insights are ranked by the deterministic formula. The agent may group and explain
  them; it does not reorder them.

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
- Onboarding review shows the discovered profile, owned domains, and competitors.
  Generated prompt candidates stay out of setup chrome; they may seed the project
  without becoming a separate review portfolio.
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

Tabs remain the underline treatment for navigation between views. Segmented
controls use one bordered-track recipe for compact single-select changes within
a view. Filter chips are the shared pill treatment for independent or
multi-select filters; they live in `components/ui`, not a feature directory.

## Motion and accessibility

Pointer-opened menus use a barely visible 150–180ms origin-aware fade/shift.
Keyboard-opened command interfaces are immediate. Drawers use a short 220–260ms
right-side transition that remains interruptible. Press feedback starts on
pointer-down. Beyond that, a small, deliberate set of explanatory motions is
sanctioned, each one calm and reduced-motion-safe:

- the **architecture pipeline** diagram (platform section) — accent dots flowing
  along conduit paths;
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
- The default canvas is white, quiet highlight is `#F3F4F6`, and elevation does
  not force card backgrounds onto structural regions.
- Elevation uses the shared shadow tokens; radius uses the 4 / 6 / 8 / 12 / 16 / 20
  scale.
- Any new motion is calm and stops under `prefers-reduced-motion`.
- Text, focus, status, loading, error, empty, keyboard, touch, reduced-motion,
  forced-colours, and mobile states remain usable.
- No website or app copy, data, claims, or workflow behaviour changed.
- Focused tests, `pnpm check:policy`, and the appropriate build or visual checks
  pass. React Doctor is the final verification command.
