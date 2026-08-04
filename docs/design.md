# CiteLadder Design System

> Canonical visual and interaction contract. This is the only design-system
> document in the repository.

## Direction

CiteLadder is one light-only enterprise system across the authenticated product,
authentication, reports, and marketing. Its operating loop is:

> Identify and analyze → resolve → improve → remeasure → repeat.

The interface is dense, flat, evidence-led, and operational. Marketing uses more
space and stronger composition, but the same tokens, controls, typography,
iconography, and motion rules. The approved command-center composition is the
movement-and-actions split: project state first, a dominant movement chart beside
the ranked action queue, then a non-causal proof ledger.

## Identity

- Product name: **CiteLadder**; canonical domain: **citeladder.com**.
- UI and data face: Geist, loaded with `next/font/google`.
- Display face: self-hosted Apfel Grotezk, retained from the prior product.
- Mark: a simple single-colour citation/progression symbol. It must work at 16px,
  in enterprise teal or monochrome, without a literal ladder or magnifier.
- Voice: precise, confident, evidence-led, operational, and direct. Never use
  generic “AI magic” language or imply product-feed management.

## Tokens

`frontend/app/globals.css` is the only global token owner. Tokens are semantic
Tailwind `@theme` values; there is no primitive alias layer and no route-specific
marketing namespace.

- Accent: `#006D77`; hover `#005A63`; pressed `#00444B`; focus `#007F87`;
  subtle `#E6F4F3`; border `#A8DADC`; foreground `#FFFFFF`.
- Canvas is a cool near-white; operational surfaces are white; ink is a cool
  near-black. Status colours encode state only and always carry text.
- Desktop geometry: 48px top bar, 224px rail, 20px gutter, 32px nav rows, 32px
  controls. Touch geometry: 52px bar, 16px gutter, 44px rows and controls.
- Radius scale: 2px indicators, 4px compact controls, 6px controls, 8px panels.
  Full radius is reserved for avatars and binary toggles.
- Standard cards use the shared `--shadow-card` elevation token; interactive
  cards use `--shadow-card-hover`. Menus, tooltips, dialogs, drawers, and other
  temporary overlays retain the deeper `--shadow-modal-value` rung.
- Metrics, ranks, dates, and percentages use tabular numerals, never monospace.

## Composition

- State precedes features. A project landing view exposes state, change, the next
  action, and improvement evidence within one viewport.
- Dense means aligned rows and direct labels, not smaller unreadable type.
- Cards are not page architecture. Use sections, ledgers, tables, and split
  workspaces; never nest decorative cards.
- Recommendations expose impact, deterministic priority factors, affected scope,
  status, and links to persisted evidence. Do not invent confidence, effort,
  ownership, or causation.
- Charts identify metric, unit, timeframe, measurement context, and provenance.
  The brand is the first series; at most five categorical series appear together.
- Mobile preserves every critical action. Tables become labeled records; filters
  and evidence use full-height sheets; reordering includes up/down controls.

## Motion and accessibility

- Motion communicates state or causality: 120ms feedback, 180ms state changes,
  and 260ms drawers/route continuity using one ease-out curve.
- No looping decoration, rotating words/logos, cursor spotlights, glass, glow, or
  gradients. Marketing may use one entrance and one product-demonstration recipe.
- Reduced motion renders the finished composition without hiding content.
- WCAG 2.1 AA is the minimum. Focus is always visible; state is never colour-only;
  touch targets are at least 44px; forced-colours and print remain usable.

## Governance

Components consume semantic utilities only. Raw colours, arbitrary visual values,
page-local shared controls, unregistered motion/easing, one-off breakpoints, and
legacy design namespaces are prohibited. `pnpm check:policy` enforces the single
token owner, component inventory, elevation/motion rules, and zero legacy brand or
theme references.
