# CiteLadder Prism Evidence Workspace — Audited Visual Redesign Plan

## Summary and audit baseline

Replace the authenticated app’s current basic, card-heavy dashboard styling with a calm editorial operating workspace derived from:

- HTC Global’s warm canvas, navy ink, restrained weights, semantic pastel washes, and negative space.
- SETO’s quiet application chrome and spatial clarity.
- Panacea’s useful data density, without its KPI-card wall.

The redesign may recompose surfaces but must preserve routes, product behavior, data, actions, URL state, TanStack Query ownership, Radix semantics, accessibility, and responsive capability.

Current production audit:

- 87 `<Card>` instances across 51 authenticated production files.
- 111 `font-semibold` uses across 47 files.
- 95 `text-2xs` uses across 54 files and 240 `text-xs` uses across 84 files.
- No literal 10px or 11px product classes; the problem is excessive use of the smallest metadata rung. `text-2xs` currently aliases 12px.
- 188 border utilities across 73 files.
- 33 card/elevated shadow references across 20 files.
- The shared Card always adds a border and shadow.
- The shell uses repeated separators and backdrop blur.
- Visible route titles are normally suppressed, weakening orientation and page hierarchy.
- Existing static policy passes but explicitly enforces parts of the superseded system, so policy and implementation must cut over together.

Highest-impact consumers are Overview, Visibility, Demand, Site Health, Issues, Content, Settings/Billing, Runs, and the Growth Agent.

## Design contract and shared interfaces

### Colour system

`frontend/app/globals.css` remains the sole palette and semantic-token owner. Use two layers:

- Palette scales: `gray`, `indigo`, `cyan`, `coral`, `lime`, and `amber`.
- Semantic aliases consumed by components and features: canvas, structural surface, raised surface, well, text roles, selection, focus, action, status, evidence, and chart roles.

Palette anchors:

- Gray: `0 #FFFFFF`, `50 #FAF9F6`, `100 #F7F6F2`, `200 #F1F0EB`, `300 #E7E5DE`, `400 #C9C7C0`, `500 #7B8494`, `600 #536176`, `700 #475569`, `800 #253352`, `900 #14213D`.
- Indigo: `50 #F8F7FF`, `100 #F0EFFF`, `200 #DED9FF`, `300 #C1B8FF`, `500 #6B5CFF`, `600 #5542F6`, `700 #4033C7`.
- Cyan: `50 #EDF7F7`, `100 #DDF1F2`, `500 #00A9C5`, `700 #155E75`.
- Coral: `50 #FFF3F0`, `100 #FFE4DE`, `500 #FF6E56`, `700 #9A3412`.
- Lime: `50 #F4F8EC`, `100 #E6F0D1`, `500 #9ACD32`, `700 #3F6212`.
- Amber remains the warning family.

Semantic mapping:

- Canvas: gray 50.
- Structural section/sidebar: gray 100.
- Tonal well: gray 200.
- Raised/input/overlay: gray 0.
- Primary text and primary actions: gray 900.
- Secondary text: gray 700.
- Muted text: gray 600.
- Selection and focus: indigo 600/700 with indigo 50/100 states.
- Cyan, coral, lime, and amber remain evidence/status families and never become arbitrary route decoration.

Deferred public and focused-flow surfaces retain their scoped `.website-type` contract until the final approved slice. Do not introduce parallel app-v1/app-v2 namespaces.

### Typography and spacing

Geist remains the authenticated-app family. Use only weights 400 and 500.

Product roles:

- Metadata/table header: 12/16, used only for short labels, provenance, badges, and table headings.
- Body/control: 14/20.
- Emphasized body: 14/20 at 500.
- Section heading: 16/22 at 500.
- Panel heading: 18/24 at 500.
- Page title: 24/32 at 500 and visible on every route.
- Primary metric: 28/34 or 32/38 at 500 with tabular numerals.

Remove `text-2xs` after consumers migrate. Product text must never use 10px or 11px, and ordinary body/table content must not use the 12px metadata role.

Use one spacing ladder: 4, 8, 12, 16, 24, 32, and 48px. Desktop content gutters become 24px, compact gutters remain 16px, major sections use 32px separation, and internal groups use 16–24px.

### Geometry and primitives

- Controls: 10px radius.
- Semantic objects: 16px radius.
- Overlays: 16px radius.
- Pills: filters, compact selection, lifecycle/status, and count indicators only.
- Shadows: overlays, menus, drawers, dialogs, command palette, and toasts only.

Shared owners must provide:

- Visible `PageHeader` with title, supporting context, and route actions.
- Typography role recipes/components.
- Unboxed metric groups and metric items.
- Editorial section headers and ledgers.
- Workspace panes for existing master-detail and editor/history layouts.
- A Card reserved for real semantic objects; its default has no border or shadow.
- Navy primary buttons, quiet tonal secondary buttons, and indigo analytical selection.
- Flat inputs/selects, understated tabs, minimal table rules, and quieter badges.

Do not add another component library or change backend/public API contracts.

## Implementation slices

1. **Foundation and authority cutover**
   - Replace authenticated palette, semantic aliases, typography, spacing, radii, elevation, and primitive defaults.
   - Update design-policy checks alongside the new contract: reject authenticated `font-semibold`/`font-bold`, `text-2xs`, arbitrary raw colours, feature-owned shadows, nested Cards, and direct palette use where a semantic role exists.
   - Update `docs/design.md` as the single design authority and synchronize the component-system contract. Do not create a root `DESIGN.md`.
   - Preserve deferred marketing/auth/onboarding behavior through their existing scoped owner.

2. **Application shell and global hierarchy**
   - Flatten sidebar and top bar; remove glass, hover translation, repeated separators, the blue rail, and unnecessary chrome.
   - Separate sidebar and workspace through tone and negative space.
   - Use an indigo tonal active navigation state.
   - Make page titles visible by default, with summaries and actions aligned consistently.
   - Preserve the five stations, mobile navigation, command palette, project switcher, user menu, and Agent sheet behavior.

3. **Overview and analytical surfaces**
   - Recompose Overview, AI Visibility, Search Demand, Traffic, and AI Referrals.
   - Replace KPI-card grids with unboxed metric strips.
   - Put the primary chart/table directly in the workspace.
   - Present ranked findings and evidence as ledgers or meaningful insight objects.
   - Keep unknown, unavailable, not-applicable, and observed-zero states explicit.

4. **Site Health and evidence inspection**
   - Recompose Website tabs, Overview, Pages, Architecture, AEO Readiness, Changes, URL detail, and Issues.
   - Preserve all lifecycle truth, polling, URL state, coverage distinctions, and the Issues master-detail behavior.
   - Use tonal selection, gutters, and sticky contextual regions instead of nested cards.
   - Keep dense tables at 14px body size and 12px headers.

5. **Action workspaces**
   - Recompose Opportunities, Content, and the Growth Agent.
   - Opportunities remain valid semantic objects but may not contain nested cards.
   - Content becomes a coherent history/work/evidence workspace.
   - The Agent remains a right-side sheet with the same typed context and explicit mutation boundaries.

6. **Operational workspaces**
   - Recompose Commerce, Prompts, Runs, run detail, schedules, and evidence drawers.
   - Preserve resizable/master-detail behavior, filters, selection, execution provenance, and launch dialogs.
   - Replace metric tiles and boxed subgroups with shared metric, ledger, and pane primitives.

7. **Connect and configuration**
   - Recompose Settings, Integrations, Providers, connection flows, property selection, and Billing.
   - Use editorial settings rows: label and explanation paired with the control.
   - Integration/provider records remain semantic objects; nested configuration sections remain flat.
   - Preserve every validation, permission, connection, billing, and error state.

8. **Authenticated cleanup and handoff**
   - Search every authenticated production consumer for retired Card recipes, old shadows, border shells, smallest-rung typography, obsolete cobalt actions, and route-local visual recipes.
   - Delete superseded variants and static-policy compatibility code.
   - Update behavior tests that relied on old cosmetic classes to assert semantics and interactions instead.
   - Run repository validation and then stop for the user’s own rendered visual review.

9. **Approval-gated public and focused-flow redesign**
   - Do not begin without explicit approval after the user reviews the completed authenticated app.
   - Once approved, apply the same Prism Evidence world to marketing, login/register, and onboarding with larger responsive typography, more generous spacing, stronger editorial imagery, and marketing-appropriate rounded compositions.
   - Cover public chrome, homepage, solutions, enterprise, pricing, demo, comparison, blog, FAQ/legal, product-preview scenes, auth, and onboarding.
   - Preserve factual copy, SEO/schema output, auth behavior, onboarding confirmation gates, and public routes unless separately authorized.
   - Remove the temporary scoped compatibility boundary only after every public/focused-flow consumer has migrated.

## Test and acceptance plan

- Add or update primitive and policy tests for token ownership, contrast, typography roles, Card nesting, shadow ownership, button variants, tables, tabs, overlays, and visible page headings.
- Preserve route component tests for loading, empty, error, unavailable, mobile, keyboard, URL-state, and mutation behavior.
- Do not add screenshot tests, visual-regression tooling, generated review captures, or an automated visual-review pass. The user owns final rendered visual review.
- Deterministic completion still requires, in order from the repository root:
  - `.\scripts\check.ps1`
  - `.\scripts\test.ps1`
- If the work is split across separate implementation tasks or PRs, each completed task must satisfy the repository’s required gates.

## Assumptions

- “Prism Evidence Workspace” is the selected visual direction.
- Violet replaces cobalt as the brand/selection accent; navy owns primary actions.
- Route composition may change, but product behavior, IA, APIs, state ownership, and evidence semantics may not.
- Login, registration, onboarding, and marketing remain deferred until the explicit final-slice approval.
- Concurrent dirty-worktree changes are user-owned and must be preserved.
