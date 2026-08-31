# Commerce UI redesign

> **Status:** Implemented. Shipped in the Commerce workspace rebuild.
> **Scope:** `frontend/components/products/**` and `frontend/lib/products/**`.
> No backend contract change, no database change, no new endpoint.
> **Authority:** [`design.md`](../design.md) owns every token and primitive
> referenced here. Where this plan and `design.md` disagree, `design.md` wins.

## The actual problem

The Commerce workspace has four tabs — Catalog, Competitors, Buyer Prompts,
AI Shelf. **Every tab is a verb, and every tab makes you re-pick the noun.**

```text
Catalog        [ product/category table ]
Competitors    [ target selector ] Discover      -> candidates for that target
Buyer Prompts  [ target selector ] Generate      -> prompts for that target
AI Shelf       [ target selector ]               -> metrics for that target
```

Three selectors for one question — "which category or product am I working
on?" — asked three times, answered three times, remembered zero times. The
selection states are genuinely independent in the code: `CompetitorsPanel` and
`BuyerPromptsPanel` each hold their own `useState`, and AI Shelf's lives even
further away, in `products-screen.tsx` as `shelfSelection`. Switching tabs
loses your place; a reload loses all three.

That is why the same control appears everywhere. Replacing the dropdown with a
nicer dropdown does not fix it — the repetition is the bug, not the widget.

A second, smaller problem follows from the first: because each tab must work
standalone, each one re-states catalog context (crawl progress, projection
counts, target name) in its own header, and none of them can show the one thing
a merchandiser actually wants — *for this category: here is the shelf position,
here are the competitors on it, here are the prompts that measured it.*

## The shape

**Invert it. The catalog is the navigation; everything else is a view of the
selected target.**

```text
┌─ Commerce ─────────────────────────────────────────────────────────────┐
│  Catalog status · 33 products · 8 categories    [Refresh] [Import CSV] │
├──────────────────────────┬─────────────────────────────────────────────┤
│  CATALOG (the spine)     │  DETAIL for the selected target             │
│                          │                                             │
│  [search…]               │  Instant-Read Thermometers      category    │
│  ▸ Categories        (8) │  ────────────────────────────────────────   │
│    ☐ Cookware Sets   2   │  Shelf position   Share of shelf   1st-pos  │
│    ☑ Instant-Read    2   │      2.4              38%            12%    │
│    ☐ Hygrometers     1   │                                             │
│    ☐ Kitchen Utensil 13  │  Competitors on this shelf         [Find]   │
│  ▸ Products         (33) │    all-clad.com          approved           │
│    ☐ TempSpike TP972     │    lodgecastiron.com     pending  ✓ ✕       │
│    ☐ TempPro TP620       │                                             │
│                          │  Prompts that measure it        [Generate]  │
│  2 selected              │    best instant read thermometer under $50  │
│  [ Find competitors ]    │    which thermometer works with an iPhone   │
│  [ Generate prompts  ]   │                                             │
└──────────────────────────┴─────────────────────────────────────────────┘
```

Three rules make it work:

1. **One selection, in the URL.** `?target=category:<uuid>` replaces three
   `useState` hooks. It survives a reload, a tab switch, and a shared link, and
   it is the same value the launch payload uses — so what you see is what runs.
2. **Selection is a click on a row, never a dropdown.** The list you are
   already reading is the picker. There is no separate control to open, and no
   third place for the target name to disagree with the other two.
3. **Bulk work is table selection, not a multi-select menu.** Checkboxes in the
   list gutter, and an action bar that appears only when rows are checked —
   the standard data-table pattern, and the one place multi-target runs belong.
   (The `TargetMultiSelect` added as an interim fix is superseded by this and
   should be deleted, not restyled.)

## What each region owns

| Region | Owns | Never does |
|---|---|---|
| Workspace header | Catalog-wide state and catalog-wide actions: crawl status, projection counts, Refresh, Import CSV | Anything scoped to one target |
| Catalog list | Search, category/product grouping, selection (single and bulk), counts | Any per-target detail |
| Bulk action bar | Multi-target Find competitors / Generate prompts, and its progress | Appears at all when nothing is checked |
| Detail pane | Everything about ONE target: shelf metrics, competitors, prompts, corrections | Re-state catalog-wide status |

The detail pane is ordered **outcome first, inputs beneath** — per `design.md`,
"state before features": shelf metrics are the answer, competitors and prompts
are how it was measured.

## Replacing the tabs

The four tabs collapse into one screen. Two things they carried still need a
home:

- **AI Shelf** becomes the top band of the detail pane. It is the outcome for
  the selected target, not a separate destination.
- **Catalog corrections** (rename a category, edit a product) move into the
  detail pane as an inline edit affordance on the target you already selected,
  replacing the per-row `Edit`/`Rename` buttons in a wide table.

Keep `?tab=` accepting the four historical values and redirect each to the
equivalent target-scoped view, so existing links do not 404.

## Design-system compliance

Non-negotiable, and the reason this is a plan rather than a patch:

- Build from `frontend/components/ui/` primitives. The list rows, checkboxes,
  badges, buttons, and empty states all already exist. **Do not add a
  primitive without checking `design.md` first.**
- No raw hex, no `@theme` outside `globals.css`, no route-local palette.
  Selection uses the accent role (`accent-*`) because explicit selection is
  exactly what that token is for.
- Numeric columns are right-aligned and tabular; metric values use the
  `score-*` / `series-*` families, not ad-hoc colour.
- Every region needs its four states designed, not defaulted: loading
  (skeleton), empty (what to do next), error (what failed and the retry), and
  the partial state where a crawl is still projecting.
- The layout is two-pane on wide viewports and single-pane with a back
  affordance below the `md` breakpoint. The list must not become a horizontally
  scrolling table on a laptop.

## Accessibility

- The catalog list is a listbox-or-grid with roving tabindex and full
  Arrow/Home/End navigation, owned by the shared `Tabs` module.
- Selecting a row moves focus predictably and announces the detail change via a
  live region; it must not steal focus into the detail pane mid-keyboard-run.
- Bulk selection exposes an accessible "N selected" summary and a select-all
  with an indeterminate state.

## Delivery sequence

Each step ships green and leaves the screen usable.

1. **Lift selection to the URL.** One `useCommerceTarget()` hook replaces the
   three `useState` hooks. No visual change; this is the change that makes the
   rest possible.
2. **Build the catalog list** as the spine, with search, grouping, and
   single selection driving the URL value.
3. **Build the detail pane** with the shelf band, then move the competitor and
   prompt sections into it, deleting each tab as its content lands.
4. **Add bulk selection** and the action bar; delete `TargetMultiSelect`.
5. **Move corrections** into the detail pane; delete the wide catalog tables.
6. **Retire the tab shell**, keeping `?tab=` redirects.

## Out of scope

No backend contract, endpoint, schema, or migration change. The multi-target
run API already accepts a target list, and the shelf, competitor, and prompt
reads are already target-scoped — this is a composition change on top of
contracts that are already right.

## Resolved at delivery

1. **One collapsed category tree**, with products nested beneath their
   categories and the opaque search header pinned while the rail scrolls.
   Categories show their product count and render a disclosure only when they
   have children. Category bulk selection includes all child products; products
   without a known category remain visible in an explicit fallback group.
2. **A category detail drills into its own products**, so there is one
   navigation model rather than two.
3. **No cross-target shelf view.** A "shelf across the whole catalog" report is
   a separate surface if it is ever wanted, not part of this screen.
