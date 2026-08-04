# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary customers are enterprise commerce teams. They use CiteLadder to understand how answer engines represent their brands, catalogs, and competitors — then act on visibility gaps.

## Product Purpose

CiteLadder is a commerce-focused AEO (AI Engine Optimization) analysis product. It measures how brands and products appear inside answer-engine responses (ChatGPT, Gemini, Claude), scores those appearances deterministically from persisted evidence, and turns patterns into strategy — visibility, citations, share-of-voice, product-level mentions, and related commerce intelligence.

Success means an enterprise team can run audits on their own provider keys, trust scores that trace back to raw answers, and improve how AI channels describe their catalog and brand.

## Positioning

Commerce-focused AEO analysis with deep expertise in crawling and product data — not a generic “AI visibility dashboard” and not a feed-management or feed-optimization tool. Differentiating mechanism: observe answer engines with BYOK keys, freeze catalog identity into audits, score deterministically from immutable artifacts (no LLM re-summarization of results), and ground product/brand conclusions in crawl + product-data depth.

## Operating Context

- Workspace-scoped product: brand + competitors + prompts → one-time audits across logical engines → Visibility dashboard and Run/Executions evidence explorer.
- Sibling commerce surface (`/products`): Discover, Catalog, AI Conversations, Market Intelligence.
- Broader AEO suite is documented (Site Health, Traffic, Content, Opportunities, integrations, Agent/MCP); shipped slice centers on visibility + emerging commerce intelligence.
- Browser hits the Next.js app same-origin; API is `/api/v1` proxied to the backend.

## Capabilities and Constraints

- Logical engines: `chatgpt | gemini | claude`; transports `openai | anthropic | google`; BYOK, Fernet-encrypted at rest; secrets never returned in DTOs.
- Deterministic analysis from `RawResponseArtifact` provenance; reports are projections, never re-calls to providers for scoring.
- UUID PKs; workspace membership auth on every project-owned query.
- Sentiment and average position are not computed yet (UI shows em-dash).
- **Undecided / open:** visual identity and the incumbent design system are explicitly open to replacement; current UI is not a binding aesthetic commitment.
- **Public copy ban:** never describe CiteLadder as product-feed optimization, and never imply a feed-ops or feed-management job in app or marketing copy.

## Brand Commitments

- Product name: **CiteLadder**.
- Marketing line in use: “See your market through AI’s eyes”; observes how answer engines describe brand, products, and competitors; traces conclusions to source answers; BYOK encrypted at rest.
- Voice for public surfaces: enterprise commerce / AEO analysis — never partner-internal or feed-tool language.
- Brand assets use the single-color CiteLadder citation/progression mark. Geist is loaded through `next/font/google` for UI text; self-hosted Apfel Grotezk remains the display face. Product and marketing share the light-only semantic system owned by `frontend/app/globals.css`.

## Evidence on Hand

- Runnable product and marketing surfaces under `frontend/`; architecture and roadmap under `docs/`.
- No confirmed external testimonials, case studies, press quotes, or named customer logos for fabrication. Do not invent partner or customer names as public proof.

## Product Principles

1. **Commerce AEO** — optimize how AI channels talk about brands and products; never ship feed-management framing.
2. **Evidence over narrative** — every score traces to a persisted answer artifact; do not invent proof or re-author results with an LLM.
3. **Enterprise trust** — BYOK, encrypted secrets, workspace boundaries; copy and UX should feel credible to large commerce teams.
4. **Crawl and catalog depth** — product data and crawling expertise are part of the product story; surface them as commerce intelligence, not feed tooling.
5. **Visual system is provisional** — product truth outranks the current look; improve or replace the design system when the work calls for it.

## Accessibility & Inclusion

WCAG 2.1 AA contrast is the current engineered floor in the app token system (documented and test-gated). No additional product-specific accessibility mandate was established beyond that; keep AA as the default bar unless a later requirement raises it.
