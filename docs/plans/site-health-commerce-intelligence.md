# Site Health, Commerce Intelligence, and AI Presence Upgrade

## Summary and Preflight

- Create `feature/site-health-commerce-intelligence` in a separate worktree from `origin/main`; never switch the current dirty checkout.
- Save this plan, review it against concurrent changes, and confirm the implementation still has the documented owners and contracts before writing application code.
- Document the comprehensive page-type issue catalog and revised crawler policy before implementing crawler behavior.
- Preserve the automatic 10-page production crawl. Advanced count, upload, crawl-mode, and page-type controls remain development-only; future tier behavior is documented but not implemented.
- Deliver competitor catalog comparison last, after crawling, Commerce discovery, product intelligence, and scoring are stable.

## 1. Documentation and Greenfield Schema

- Reconcile `Agents.md` with the existing pre-deployment policy: one rebuildable `0001_initial` baseline.
- Fold the concurrent `0002_grounded_visibility_greenfield` schema into `0001_initial` during integration and remove `0002`. Do not disturb the concurrent agent’s untracked file in the shared checkout.
- Update Site Health, invariants, backend/frontend architecture, Commerce, design, README, and AWS hosting documentation. Remove the stale prohibition on curl-cffi, impersonation, and external acquisition.
- Add a comprehensive page-type analysis matrix to the canonical Site Health documentation:
  - Types: homepage, product, category/listing, service, local location, article, guide/how-to, comparison, FAQ, docs/support, pricing, about/contact, case study/review, trust/policy, and other.
  - Rule families: crawlability/indexability, AI crawler access, metadata, delivery/security, content structure, citability/trust, links/media, structured-data presence, required/recommended properties, and visible/schema consistency.
  - Each page type receives explicit expected schema types, required and recommended properties, applicability, severity, evidence, and remediation.
- Replace user-facing “Technical” with “Web Fundamentals.” Retain the internal API token `technical`.

## 2. Value-Aware Site Health

### URL admission and selection

- Introduce a config-owned URL value classifier before any fetch task is created.
- Hard-exclude login, registration, account/profile, admin, cart, checkout, payment, order confirmation, wishlist, and equivalent localized paths.
- Exclude search, filter/facet/sort combinations, tag/author archives, pagination duplicates, feeds, print/share pages, tracking URLs, preview URLs, attachments, and non-HTML assets.
- Apply exclusions consistently to roots, redirects, links, sitemaps, uploads, recrawls, and manual selections. Hard exclusions cannot be overridden.
- Return safe exclusion reason codes and aggregate skipped counts; excluded URLs never invoke a transport.
- Prioritize root and explicit selections, then products, comparison/service/local pages, category/pricing, article/guide/FAQ/docs, and finally trust/ambiguous pages.
- Freeze admission policy, page-value classifier, and page-type classifier versions in each crawl configuration.

### Crawl modes and UI

- Extend crawl creation with:
  - `input_mode: auto | exact_urls | discovery_seeds`
  - `requested_page_limit`
  - `seed_urls`
  - `page_types`
  - existing include/exclude globs and deterministic seed
- Add a bounded CSV/text/JSON URL preview endpoint returning accepted rows, duplicates, hard exclusions, out-of-scope entries, and row-level errors.
- Build a guided flow: enter domain/URLs or upload → inspect candidates grouped by page type/value → select URLs/types → confirm budget → crawl.
- Exact mode follows only accepted URLs. Seed mode expands through admissible links and sitemaps.
- Production retains automatic 10-page behavior. Development configuration unlocks all controls. Document future Tier 2 increased limits, Tier 3 page-type selection, and crawl-limit add-ons without changing current billing logic.

### Fetch ladder

- Refactor acquisition behind one transport protocol:
  1. Secure `httpx`.
  2. curl-cffi when configured challenge/block or low-content evidence appears.
  3. ScraperAPI when curl-cffi remains blocked or unusable.
- Preserve robots handling, SSRF controls, manual redirect validation, TLS verification, byte/time limits, host pacing, and no-raw-HTML persistence.
- curl-cffi uses `trust_env=False`, manual redirects, and pinned validated resolution. If pinned-IP verification fails on a supported platform, disable that rung and proceed to ScraperAPI.
- ScraperAPI uses server-only configuration and secret redaction. Raw HTML is used for Site Health; render, premium, and geo features activate only through frozen config rules.
- Persist transport, rung, trigger, impersonation profile, ScraperAPI options/request ID, and versions on append-only attempts and successful artifacts.
- Update AWS documentation for the secret, worker access, NAT egress, credit usage, latency, fallback errors, cost ceilings, and rotation.

## 3. Page-Type Analysis, Guidance, and History

- Strengthen deterministic classification using URL, sitemap, visible content, metadata, structured data, and commerce signals. Persist the winning type, alternatives, confidence, conflicts, and classifier version.
- Product analysis includes `Product`/`Offer`, SKU/GTIN/brand, price/currency/availability, variants, ratings, shipping/returns where present, and visible/schema parity.
- Other page types use their documented schema/content profiles; ambiguous pages explain why they remained `other`.
- Expand Site Health → Opportunity mappings for every documented schema and content rule.
- Redesign the Opportunity drawer around:
  - What was found.
  - Affected page and page type.
  - Exact bounded evidence.
  - Why it matters.
  - Recommended improvements.
  - Expected schema and missing properties.
  - Collapsed provenance details.
- Add development-enabled on-demand tailored guidance:
  - `POST /opportunities/{id}/guidance`
  - latest and history reads
  - immutable `OpportunityGuidance` records containing source IDs, bounded input snapshot/hash, findings, recommendations, prompt/model/provider versions, and timestamps
  - regeneration creates a new record; idempotency prevents duplicates
- Guidance is unavailable to trial/Tier 1 in the documented production policy and never changes detection, priority, or scores.
- Replace repeated issue-history rows with rule-grouped history:
  - current state
  - occurrence count
  - first/last seen
  - new, continuing, and resolved transitions
  - collapsed crawl timeline
  - “Since previous crawl” summary
- Derive history exclusively from persisted crawl evidence.

## 4. Guided Commerce and Product Conversations

- Replace Products navigation with:
  - **Discover:** domains/URLs/CSV, candidate discovery and selection.
  - **Catalog:** own and competitor catalog management and completeness.
  - **AI Conversations:** what prompts and answer engines discuss about each product.
  - **Market Intelligence:** external competitor products, offers, prices, and availability.
- Add versioned Commerce discovery runs/tasks/artifacts/candidates using the shared Postgres queue.
- Use ScraperAPI raw/rendered acquisition for arbitrary product pages and supported structured/Google Shopping endpoints where applicable.
- Match candidates deterministically using GTIN/SKU/model first, then configured brand/name/variant evidence. Persist confidence and match reasons; LLM output cannot establish identity.
- Add `discovered` catalog origin and source-candidate/artifact provenance. Preserve manual edits and audit catalog freezing.
- Extend product snapshot metrics with:
  - prompt coverage by product
  - frozen prompt text/theme/intent
  - conversation themes
  - mention and rank distribution
  - discussed attributes
  - price claims and accuracy
  - buyer destinations
  - competitor co-mentions and comparisons
- Do not infer sentiment or attribute valence deterministically.

## 5. AI Presence Index and Momentum

### Non-commerce projects

Use the selected cross-industry formula:

- 30% brand mention rate
- 20% normalized share of voice
- 20% owned citation rate
- 30% Web Fundamentals

### Commerce projects

When Commerce is configured and has sufficient product evidence:

- 25% Brand Visibility, internally composed from 60% brand mention rate and 40% normalized share of voice
- 30% Product Presence
- 20% Web Fundamentals
- 15% owned citation rate
- 10% Opportunity Execution

Product Presence is:

- 40% product share of voice
- 25% product prompt/mention coverage
- 20% normalized rank performance
- 15% verifiable price accuracy

Opportunity Execution is `resolved / (open + in_progress + resolved)` from the latest comparable opportunity snapshot; dismissed items are excluded and no opportunities produces `null`, not a free 100.

### Projection behavior

- Score per project/brand; no workspace portfolio rollup.
- Missing components are renormalized, while the response exposes coverage and labels incomplete scores provisional.
- Momentum is the latest score minus the earliest comparable score in the trailing 30 days; return `null` with fewer than two comparable points.
- Comparability requires the same commerce/non-commerce formula, component coverage, and compatible analyzer/rule/formula versions.
- Return component scores, weights, coverage, source snapshot IDs, versions, and comparability metadata.
- Show resolved opportunities as timeline annotations as well as the explicit Commerce execution component.
- All calculations project persisted evidence; no provider call occurs in dashboard or trend reads.

## 6. Final Slice: Competitor Catalog Comparison

Implement this only after the preceding slices pass acceptance tests.

- Allow competitor catalog creation through:
  - crawling competitor domains/category/product URLs
  - selecting discovered candidates
  - CSV or JSON upload with preview and row-level validation
  - existing manual competitor-product CRUD
- Persist immutable import/crawl artifacts and reviewed candidate provenance.
- Expand competitor product records with variants, identifiers, attributes, availability, extraction freshness, and source linkage.
- Deterministically match own and competitor products using:
  1. GTIN/UPC/EAN
  2. manufacturer part/model number plus brand
  3. normalized product family and variant identity
  4. configured title/attribute similarity
- Require review for ambiguous matches; never overwrite an accepted mapping silently.
- Provide side-by-side comparison for:
  - matched/unmatched catalog coverage
  - price and availability
  - variants and identifiers
  - attribute completeness and differences
  - product schema readiness
  - crawl freshness
  - AI conversation SOV, mentions, rank, attributes, and buyer destinations
- Store versioned comparison snapshots with source artifact/catalog IDs, matcher version, confidence, and truncation metadata.
- Keep uploaded, crawled, and AI-conversation evidence visibly distinguished.

## Public Interface Changes

- Site Health crawl-mode, page-limit, seed-URL, page-type, upload-preview, exclusion, and acquisition-provenance contracts.
- Rule-grouped issue-history response.
- Opportunity guidance create/latest/history endpoints.
- Commerce discovery run/task/candidate/accept endpoints.
- Product conversation and Product Presence metrics.
- Competitor catalog upload/crawl/matching/comparison endpoints.
- Dashboard AI Presence Index, formula kind, Momentum, components, coverage, versions, and trend points.
- Register all new coded failures in the shared error envelope.

## Verification and Acceptance

- Prove forbidden transactional/authentication URLs never enqueue or call any transport.
- Test value ranking, provisional/final classification, page-type filtering, exact/seed modes, upload normalization, and frozen replay.
- Test httpx → curl-cffi → ScraperAPI transitions, pinned-IP safety, redirects, redaction, limits, and provenance.
- Maintain a fixture matrix for every page type and documented schema/content rule.
- Verify production automatic-10 behavior and development-only advanced controls.
- Test guidance eligibility, bounded inputs, immutable regeneration, idempotency, and metric isolation.
- Test grouped issue transitions without repeated-looking history.
- Test both score formulas, Commerce activation, Product Presence, Opportunity Execution, missing-component renormalization, version boundaries, and Momentum.
- Test competitor crawl/upload parity, deterministic matching, ambiguous review, comparisons, freshness, and workspace isolation.
- Run focused backend/frontend suites, lint, frontend build, same-origin browser flows, disposable database reset, `alembic upgrade head`, `alembic check`, and assert that `0001_initial.py` is the only migration revision.

## Assumptions

- Commerce scoring activates only when a project has an accepted product catalog and sufficient ProductMetricSnapshot evidence; otherwise the cross-industry formula applies.
- CiteLadder is still pre-production, so resetting development databases and rebuilding the single baseline is authorized.
- The ScraperAPI credential remains server-only and is never returned or logged.
- No customer-specific names, branding, or logic are introduced.
