# Commerce Suite — M2a, M4 (Shopify), M5 (A1/A2)

> Implementation plan for the Commerce slice of
> [`docs/plans/v4-commerce-suite-m2-m5.md`](../code/abhij1306/CiteLadder/docs/plans/v4-commerce-suite-m2-m5.md),
> scoped to the approved fastest-value path. Delivered as **one combined PR** on a
> single branch.

## Scope and approved decisions

**In scope (approved):** M2a (Analyzer v2 + quiet-path shopping-surface slot) →
M5 Layer A1 (GA4 platform attribution) → M4 Shopify (catalog + orders) → M5 Layer
A2 (order-level referrer), plus the frontend for exactly those.

**Out of scope (explicitly excluded):** M2b shopping-intent fanout, M2c probe
connectors, all of M3 (Opportunities engine), BigCommerce, Google Merchant Center,
M5 Layer C / `LiftEstimate`, holdout-geo incrementality, checkout/feed write-back.

**Locked decisions (user-approved 2026-07-25):**

| # | Decision | Value |
|---|---|---|
| 1 | Scope/sequencing | Fastest-value path: M2a → A1 → Shopify orders → A2 |
| 2 | `ATTRIBUTE_DIMENSIONS` seed | `DEFAULT` + `footwear` + `outerwear` + `accessories` |
| 3 | PR delivery | Single combined PR |
| 4 | Shopify API | GraphQL Admin API `2026-07`, no REST |
| 5 | Mixed currency | Partition by ISO code; never convert or sum |
| 6 | GA4 granularity fallback | Persisted per-connection capability; labelled `session_source_medium` → `default_channel_group` |
| 7 | Commerce-health / recompute routes | Project-scoped, use `require_active_workspace` |
| 8 | Surface discovery | `available_surfaces` on the product visibility projection |
| 9 | M2a evidence identity | Stable `evidence_id` (PK-backed; UUIDv5 for JSONB attribute rows) |

## §16 build-time verifications — resolved

1. **Nested `Offer`/`AggregateRating` JSON-LD (§8.2):** not a risk —
   `_iter_jsonld_objects` recurses to depth 12 and validates any node with a known
   `@type`. Only relevant to M3, which is out of scope; recorded so a future M3
   plan need not re-derive it.
2. **Attribute-dimension seed catalog (§5.3):** a real gap the source doc missed —
   `project_product_identity` drops `Product.attributes`, so the frozen
   `Audit.configuration` carries no `category`. M2a **widens the frozen own-product
   identity first** (prerequisite task 2); this changes `Audit.configuration` shape
   and updates `test_product_shim.py`.
3. **GA4 `itemId × sessionSource` (§10.1):** cannot be verified in this sandbox (no
   GA4 credentials). The `default_channel_group` fallback template and the DTO
   granularity label are built up front, not added reactively.
4. **Shopify order referrer coverage (§10.2):** cannot be verified (no Shopify
   shop). The A2 DTO states coverage explicitly (orders with referrer/UTM evidence
   vs. total latest orders).

## Environment constraints (verification)

No real LLM provider credentials are configured (`MISTRAL_API_KEY` etc.). Any audit
run through the real pipeline fails with `auth_failure`/`parse_error`. Therefore:

- **All M2a verification uses fixture answer text and persisted
  `RawResponseArtifact` re-scoring — never a live audit run.**
- **All GA4/Shopify connector verification uses the injected
  `httpx.AsyncBaseTransport` seam** (pattern in `tests/component/test_integration_ga4.py`)
  with `httpx.MockTransport`. No OAuth/GA4/Shopify credential is used.
- **All frontend verification uses global-fetch stubs** (`lib/api/products.test.ts`
  pattern) **and MSW handlers** (`test/msw-server.ts`).
- `_seed_site_health()` has an early-return guard, so seed fixes apply only against
  a fresh DB.

## Workstreams and execution order

The work splits into four ordered backend slices plus one frontend slice. M2a is a
prerequisite for M4/M5 config (it owns `config/commerce.py`) and for the frontend
product contracts.

- **WS-A — M2a backend** (tasks A1–A8). Lands first.
- **WS-B — M4/M5 backend** (tasks B1–B5). B1 (GA4 A1) is independently verifiable
  and can start in parallel with WS-A; B2–B5 depend on B1 and on WS-A's
  `config/commerce.py`.
- **WS-C — Frontend** (tasks C1–C5). C1 (contracts) starts once WS-A and WS-B
  contracts are pinned; C2–C5 follow.

Cross-workstream contract handoffs (all land in the same combined PR):

- WS-A owns `available_surfaces`, the exact `buyer_destination_mix` /
  `competitor_co_placement` JSON shapes, and stable `evidence_id` on the product
  visibility/evidence projections (consumed by WS-C).
- WS-B owns the project-scoped `commerce/catalog-health`, `commerce/attribution`,
  `commerce/attribution/orders`, and `commerce/attribution/recompute{,/{task_id}}`
  routes using `require_active_workspace`, plus per-currency attribution rows
  (consumed by WS-C).
- WS-C consumes only persisted projections and never recomputes scoring/attribution.

---

<!-- The three workstream parts below are the authoritative task detail. -->

---


# WS-A — M2a backend (Analyzer v2 and quiet-path shopping-surface slot)

## Scope and acceptance

**Goal.** Deliver §5 Analyzer v2 metrics for own and competitor SKUs, preserve v1 reads, and land the §7.1 slot/schema boundary while shopping probes remain disabled.

**In scope.** Analyzer/scoring versions, frozen product attributes/category, price relation, attributes, merchant destinations, competitor co-placement, win rate, versioned product rows/snapshots, product API/export additions, `AuditTask.shopping_surface`, measurement-only brand isolation, empty surface gate.

**Out of scope.** M2b fanout, M2c connectors/provider routes, M3–M5, frontend work, live provider calls.

**Acceptance.** A persisted `RawResponseArtifact` can be re-scored into v2 rows without mutating v1 rows; v2 snapshots expose §5.6 metrics for own and competitor SKUs; v1 evidence falls back to `match | mismatch | null` and carries `product_analyzer_version`; measurement brand metrics/counts remain unchanged when fixture probe rows exist; the surface gate is empty.

## 1. Commerce config and version ownership [prerequisite]

### Files

- `backend/app/core/config/commerce.py` — new deterministic commerce vocabulary and gates.
- `backend/app/core/config/products.py` — bump only the existing product provenance constants.

### Changes

Add `commerce.py` with a module docstring citing invariant 1 and module-level `Final` values. Use the same declarative style as `config/products.py`; domain/scoring code must not inline these strings or limits.

Exact public declarations:

- `PRODUCT_WIN_REQUIRES_ENUMERATION: Final = True`
- `@dataclass(frozen=True) class AttributeDimension: key: str; group: str; phrases: tuple[str, ...]`
- `ATTRIBUTE_DIMENSION_GROUPS: Final[frozenset[str]] = frozenset({"characteristics", "facts", "ratings"})`
- `PRODUCT_ATTRIBUTE_WINDOW_CHARS: Final = 200`
- `CO_PLACEMENT_MAX_PAIRS: Final = 1000`
- `PRICE_RELATION_MATCH: Final = "match"`
- `PRICE_RELATION_HIGHER: Final = "higher"`
- `PRICE_RELATION_LOWER: Final = "lower"`
- `PRICE_RELATIONS: Final[frozenset[str]] = frozenset({PRICE_RELATION_MATCH, PRICE_RELATION_HIGHER, PRICE_RELATION_LOWER})`
- `MERCHANT_KIND_MARKETPLACE: Final = "marketplace"`
- `MERCHANT_KIND_RETAILER: Final = "retailer"`
- `MERCHANT_KIND_BRAND_SITE: Final = "brand_site"`
- `MERCHANT_KIND_OTHER: Final = "other"`
- `MERCHANT_KINDS: Final[frozenset[str]] = frozenset({MERCHANT_KIND_MARKETPLACE, MERCHANT_KIND_RETAILER, MERCHANT_KIND_BRAND_SITE, MERCHANT_KIND_OTHER})`
- `MERCHANT_DOMAINS: Final[dict[str, tuple[str, str]]]`, where each value is `(merchant_name, merchant_kind)`:
  - `"amazon.com": ("Amazon", "marketplace")`
  - `"ebay.com": ("eBay", "marketplace")`
  - `"etsy.com": ("Etsy", "marketplace")`
  - `"walmart.com": ("Walmart", "retailer")`
  - `"target.com": ("Target", "retailer")`
  - `"bestbuy.com": ("Best Buy", "retailer")`
- `SHOPPING_SURFACE_MEASUREMENT: Final = ""` — canonical measurement identity used by models, filters, DTO defaults, and idempotency keys.
- `SHOPPING_SURFACES: Final[dict[str, dict[str, str]]] = {}` — the disabled gate. Document the future record keys (`logical_engine`, `transport_provider`, `transport_model`) but add no entries and do not change `APPROVED_ROUTES`.
- `PRODUCT_ATTRIBUTE_EVIDENCE_NAMESPACE: Final[uuid.UUID] = uuid.UUID("73a01bbd-f974-58d4-a213-a178455bc018")` — fixed UUID5 namespace for projected attribute-evidence row identity; import `uuid` in this config module rather than embedding a namespace literal in projection code.

Seed `ATTRIBUTE_DIMENSIONS: Final[dict[str, tuple[AttributeDimension, ...]]]` with exactly `DEFAULT`, `footwear`, `outerwear`, and `accessories`. The scorer always evaluates `DEFAULT` plus the category-specific tuple; unknown/empty categories evaluate `DEFAULT` only.

| Category | Dimension | Group | Exact casefolded phrases |
|---|---|---|---|
| `DEFAULT` | `price` | `facts` | `("price", "cost", "priced at", "sale price")` |
| `DEFAULT` | `warranty` | `facts` | `("warranty", "guarantee", "coverage")` |
| `DEFAULT` | `shipping` | `facts` | `("shipping", "delivery", "ships", "free shipping")` |
| `DEFAULT` | `returns` | `facts` | `("returns", "return policy", "refund", "exchange")` |
| `DEFAULT` | `materials` | `characteristics` | `("material", "materials", "made from", "made of", "fabric")` |
| `DEFAULT` | `sizing` | `facts` | `("size", "sizes", "sizing", "size guide")` |
| `footwear` | `fit` | `ratings` | `("fit", "fits", "true to size", "runs small", "runs large")` |
| `footwear` | `comfort` | `ratings` | `("comfort", "comfortable", "cushioning", "cushioned")` |
| `footwear` | `support` | `characteristics` | `("arch support", "ankle support", "stability")` |
| `footwear` | `traction` | `characteristics` | `("traction", "grip", "outsole")` |
| `footwear` | `waterproofing` | `characteristics` | `("waterproof", "water resistant", "water-resistant")` |
| `outerwear` | `warmth` | `ratings` | `("warmth", "warm", "temperature rating")` |
| `outerwear` | `insulation` | `characteristics` | `("insulation", "insulated", "down fill", "synthetic fill")` |
| `outerwear` | `weather_protection` | `characteristics` | `("waterproof", "water resistant", "water-resistant", "windproof", "wind resistant")` |
| `outerwear` | `breathability` | `ratings` | `("breathability", "breathable", "ventilation")` |
| `outerwear` | `layering` | `facts` | `("layering", "layer", "midlayer", "shell")` |
| `accessories` | `compatibility` | `facts` | `("compatibility", "compatible with", "works with", "fits")` |
| `accessories` | `capacity` | `facts` | `("capacity", "volume", "litre", "liter")` |
| `accessories` | `dimensions` | `facts` | `("dimensions", "height", "width", "depth")` |
| `accessories` | `durability` | `ratings` | `("durability", "durable", "wear resistance")` |
| `accessories` | `weight` | `facts` | `("weight", "lightweight", "weighs")` |

In `config/products.py`, set:

- `PRODUCT_ANALYZER_VERSION: Final = "product-analysis-2"`
- `PRODUCT_SCORING_RULE_VERSION: Final = "product-scoring-v2"`

### Existing tests affected

- `backend/tests/unit/test_product_scoring.py` imports product constants and asserts exact score dictionaries; retain its v1 matching/rank coverage but add the new keys to exact expectations.
- `backend/tests/component/test_product_visibility_api.py` currently asserts only a non-empty `product_analyzer_version`; change it to the exact v2 string. `backend/tests/component/test_product_analysis_worker.py` already asserts equality with the config constants, so it follows the bump automatically — pin it to the exact v2 literals as hardening (note: it does not break on the bump; this is deliberate version-locking, not a fix for existing breakage).

## 2. Freeze attributes/category before scoring [after 1]

### Files

- `backend/app/domain/products/shim.py`
- `backend/app/analysis/product_scoring.py`
- `backend/app/domain/audits/planner.py`

### Changes

Widen `project_product_identity(project: Project) -> dict[str, Any]` before adding category-keyed extraction. Freeze each own product with exactly these keys:

`id`, `sku`, `name`, `aliases`, `variants`, `price`, `currency`, `url`, `attributes`.

Copy the complete JSON-safe `Product.attributes` bag with `dict(product.attributes or {})`; do not freeze only `category`, because the bag is already the catalog completeness identity and future deterministic dimensions must continue to read the audit-frozen value. Competitor product keys stay unchanged: `id`, `competitor_id`, `competitor_name`, `name`, `aliases`, `price`, `currency`.

Extend the frozen scorer entry to:

- `ProductEntry(..., attributes: dict[str, Any], category: str)`
- `CompetitorProductEntry(..., category: str = "")`

`ProductScoringConfig.from_project(config)` derives own `category` from `item["attributes"]["category"]`, stripped and casefolded. Competitor products use `DEFAULT` dimensions because their M1 model has no attribute bag. Also carry `owned_domains: tuple[str, ...]` from the already-frozen `project_scoring_identity()` data so merchant classification never reads live `OwnedDomain` rows.

`create_audit()` continues merging `project_scoring_identity(project)` and `project_product_identity(project)`. Add `configuration["shopping_surfaces"] = list(SHOPPING_SURFACES)`; with the locked gate this is `[]`. Do not multiply `total`, alter slot generation for probes, or create probe tasks.

### Existing tests affected

- `backend/tests/unit/test_product_shim.py` breaks on the exact own-product dict. Seed `attributes={"category": "footwear", ...}` and assert the full bag is frozen without alias folding or mutation.
- `backend/tests/unit/test_product_scoring.py` constructors and `from_project` assertions gain `attributes/category/owned_domains` expectations.
- `backend/tests/component/test_audit_planner.py` must assert `audit.configuration["shopping_surfaces"] == []` and the frozen product `attributes` bag when a catalog is present.

## 3. Versioned schema delta and model registry [after 1]

### Files

- `backend/app/models/product.py`
- `backend/app/models/analysis.py`
- `backend/app/models/audit.py`
- `backend/app/models/__init__.py`
- `backend/app/domain/audits/schemas.py`

### Changes

Apply §5.6 directly to ORM models; do not add an Alembic revision.

**`ProductResponseAnalysis`**

- Add `shopping_surface: Mapped[str] = mapped_column(String(32), default=SHOPPING_SURFACE_MEASUREMENT)`.
- Replace `uq_product_response_analysis_task(task_id)` with `uq_product_response_analysis_task_version(task_id, product_analyzer_version, product_scoring_rule_version)`. This is required by D1: a persisted v1 analysis and a new v2 re-score must coexist.
- Add `merchant_mentions` relationship with delete-orphan cascade/passive deletes, parallel to `product_mentions`.

**`ProductMention`**

- Add `price_relation: Mapped[str | None] = mapped_column(String(16), nullable=True)`.
- Add `attribute_mentions: Mapped[list] = mapped_column(JSONB, default=list)` containing only `{dimension, group, text, offset}` objects.

**`MerchantMention`** — new `merchant_mentions` table, no unique/check constraint:

- `id UUID`, primary key, `default=uuid.uuid4`
- `workspace_id UUID`, FK `workspaces.id`, `ondelete="CASCADE"`, indexed
- `audit_id UUID`, FK `audits.id`, `ondelete="CASCADE"`, indexed
- `analysis_id UUID`, FK `product_response_analyses.id`, `ondelete="CASCADE"`, indexed
- `artifact_id UUID | None`, FK `raw_response_artifacts.id`, `ondelete="SET NULL"`, nullable
- `product_id UUID | None`, FK `products.id`, `ondelete="SET NULL"`, nullable
- `competitor_product_id UUID | None`, FK `competitor_products.id`, `ondelete="SET NULL"`, nullable
- `merchant_name String(255)`
- `merchant_domain String(255)`
- `merchant_kind String(16)`
- `destination_url Text`
- `price_text String(64)`, default `""`
- `price_value Numeric(12, 2) | None`, nullable
- `price_currency String(3)`, default `""`
- `product_analyzer_version String(32)`
- `created_at DateTime(timezone=True)`

Exactly one target FK is set when written, but omit a CHECK because catalog deletion can legitimately set both to null (§5.6/D3).

**`ProductMetricSnapshot`**

- Add `win_rate: Mapped[float | None]`, nullable.
- Add `price_mismatch_rate: Mapped[float | None]`, nullable.
- Keep historical snapshots immutable. Widen both partial unique indexes so v1 and v2 snapshots coexist:
  - `uq_product_metric_snapshot_product(audit_id, product_id, product_analyzer_version, product_scoring_rule_version) WHERE product_id IS NOT NULL`
  - `uq_product_metric_snapshot_competitor_product(audit_id, competitor_product_id, product_analyzer_version, product_scoring_rule_version) WHERE competitor_product_id IS NOT NULL`
- `metrics` gains `win_rate`, `price_relation_counts`, `attribute_dimension_frequency`, `buyer_destination_mix`, `competitor_co_placement`, `per_engine`, and `per_surface`. `per_surface[surface]` contains the same aggregate shape plus nested `per_engine`; no additional snapshot row is needed per surface.
- Pin these JSONB values to the same strict shapes exposed by both visibility-entry DTOs:
  - `attribute_dimension_frequency`: `{group: {dimension: count}}`, concretely `dict[str, dict[str, int]]`; group and dimension keys are config-owned strings, counts are integers `>= 0`, an entry with no observations is `{}`, and CSV JSON serialization sorts both key levels.
  - `buyer_destination_mix`: `{"total": int >= 0, "by_kind": [{"merchant_kind": str, "count": int >= 0}], "by_domain": [{"merchant_domain": str, "merchant_name": str, "merchant_kind": str, "count": int >= 0}]}`. Sort `by_kind` by descending `count`, then `merchant_kind` ascending; sort `by_domain` by descending `count`, then `merchant_domain`, `merchant_name`, and `merchant_kind` ascending.
  - `competitor_co_placement`: `{"items": [{"competitor_product_id": UUID | null, "competitor_name": str, "product_name": str, "count": int >= 0}], "truncated": bool}`. Sort `items` by descending `count`, then casefolded `competitor_name`, casefolded `product_name`, and `str(competitor_product_id or "")` ascending. `truncated` is always present, including `false` for empty/uncapped results.

**Brand isolation model**

- Add `ResponseAnalysis.shopping_surface: String(32), default=SHOPPING_SURFACE_MEASUREMENT`. Choose this over relying only on the worker skip: `_execution_dicts()` builds per-engine denominators from `ResponseAnalysis`, and direct/retry/legacy write paths could otherwise contaminate brand metrics even when `AuditTask` queries are filtered.

**Audit slot models**

- Add `AuditTask.shopping_surface: String(32), default=SHOPPING_SURFACE_MEASUREMENT`.
- Widen `uq_audit_task_slot` to `(audit_id, prompt_index, repetition, logical_engine, shopping_surface)`.
- Add sibling `AuditShoppingSurfaceSnapshot`; do not widen `AuditEngineSnapshot`. Columns: `id UUID PK`, `audit_id UUID FK audits CASCADE/index`, `shopping_surface String(32)`, `logical_engine String(32)`, `transport_provider String(32)`, `transport_model String(255)`, `connection_id UUID | None FK provider_connections SET NULL`, `base_url String(1024) default ""`, `created_at`; unique `uq_audit_shopping_surface_snapshot_surface(audit_id, shopping_surface)`.
- Add `Audit.shopping_surface_snapshots` relationship and register/export `AuditShoppingSurfaceSnapshot` and `MerchantMention` in `models/__init__.py`. The empty gate means the planner creates no surface snapshot rows in M2a.

**DTOs**

- Add `shopping_surface: str = SHOPPING_SURFACE_MEASUREMENT` to `AuditTaskResponse`.
- Add `AuditShoppingSurfaceSnapshotResponse` and `AuditResponse.shopping_surface_snapshots` so the frozen identity has a response contract even though the default list is empty.

### Greenfield DB recreation

Use the existing bootstrap migration against a disposable DB: `cd backend && uv run alembic downgrade base && uv run alembic upgrade head` (or drop/create the disposable DB, then `upgrade head`). The test suite rebuilds `Base.metadata` in its throwaway session DB. Do not create `migrations/versions/0002_*.py` and never downgrade the developer’s non-disposable DB.

### Existing tests affected

- `backend/tests/component/test_audit_planner.py` exact slot shape and response snapshots.
- `backend/tests/component/test_audit_queue.py` queue-row fixtures/constraint expectations; set/assert measurement surface explicitly while preserving whole-queue behavior.
- `backend/tests/component/test_analysis_api.py`, `test_analysis_http.py`, and `analytics_helpers.py` direct `AuditTask`/`ResponseAnalysis` fixtures; stamp `shopping_surface=""` and update idempotency keys.
- `backend/tests/component/test_product_analysis_worker.py` snapshot uniqueness/idempotency assertions must key by entry plus current analyzer/rule version and assert v1 rows survive v2 re-score.

## 4. Analyzer v2 pure scoring [after 1, 2]

### File

- `backend/app/analysis/product_scoring.py`

### Changes

Factor the existing lines 223–234 window logic into one shared helper:

- `_line_clipped_window(text: str, offset: int, window: int) -> tuple[int, str]`

It returns the original-text absolute segment start plus the centered window clipped to the mention’s current line. `extract_price_mentions`, attribute extraction, and destination extraction all call it. Keep `_original_text_offset()` as the source mention coordinate; never use normalized offsets for context extraction.

Add these pure signatures:

- `price_relation(mentioned_value: float, mentioned_currency: str, entry: ProductEntry | CompetitorProductEntry, *, tolerance_pct: float = PRODUCT_PRICE_TOLERANCE_PCT, tolerance_abs: float = PRODUCT_PRICE_TOLERANCE_ABS) -> str | None`
- `extract_attribute_mentions(text: str, offset: int, dimensions: tuple[AttributeDimension, ...], window: int = PRODUCT_ATTRIBUTE_WINDOW_CHARS) -> list[dict[str, Any]]`
- `extract_destination_urls(text: str, offset: int, window: int = PRODUCT_ATTRIBUTE_WINDOW_CHARS) -> list[dict[str, Any]]`
- `classify_destination(url: str, *, owned_domains: tuple[str, ...]) -> dict[str, str]`

**Price direction.** Call `price_matches_catalog()` first. Return null in exactly its two unverifiable cases: absent catalog price, or both currencies present and unequal. Return `match` when its tolerance comparison is true. Otherwise return `higher` when mentioned price is above catalog and `lower` when below. Continue writing `price_matches_catalog` for compatibility.

**Attributes.** Select `ATTRIBUTE_DIMENSIONS["DEFAULT"] + ATTRIBUTE_DIMENSIONS.get(category, ())`, dedupe by dimension/group/absolute offset, match casefolded whole phrases in the original-text line-clipped window, and persist the exact matched substring plus original absolute offset. Frequency has no valence.

**Destinations.** Recognize absolute `http://`/`https://` URLs and markdown-link targets in the same line-clipped window. Sanitize every candidate with `sanitize_referral_url()` before returning it. Normalize its host, then classify in this order:

1. Any frozen `owned_domains` match via suffix-safe `domain_matches()` → `brand_site`.
2. Any `MERCHANT_DOMAINS` key match via `domain_matches()` → configured `marketplace`/`retailer` and configured display name.
3. Otherwise → `other`, with normalized host as `merchant_name`.

Deduplicate by sanitized URL. `notamazon.com` must remain `other`; a subdomain of `amazon.com` is Amazon marketplace. Reuse the first same-line price extraction as optional merchant price evidence.

**Execution score.** Extend each own/competitor signal with `price_relation`, `attribute_mentions`, and `merchant_mentions`. Keep the original `price_matches_catalog` field. Add deterministic co-placement input as the set of mentioned entry IDs per execution.

**Aggregation.** Extend `aggregate_product_run(scores, config)`:

- `win_rate`: when `PRODUCT_WIN_REQUIRES_ENUMERATION` is true, denominator is only this SKU’s mention rows with non-null `rank_position`; null when denominator is zero, `0.0` when denominator is positive and no rank is 1, otherwise rounded wins/denominator. Competitor SKUs use the same rule.
- `price_relation_counts`: count `match`, `higher`, `lower`; legacy false booleans count as `mismatch` only in mixed-version aggregation.
- `price_mismatch_rate`: `(higher + lower + legacy mismatch) / all verifiable relations`; null when no verifiable relation.
- `attribute_dimension_frequency`: exact `{group: {dimension: count}}` mapping with integer counts `>= 0`; use `{}` when no attributes are observed and stable key ordering when serialized.
- `buyer_destination_mix`: exact `{"total", "by_kind", "by_domain"}` shape from task 3. `total` counts all persisted destination observations; aggregate by kind and normalized domain, then sort `by_kind` by `(-count, merchant_kind)` and `by_domain` by `(-count, merchant_domain, merchant_name, merchant_kind)`.
- `competitor_co_placement`: for each mentioned entry, count co-occurring competitor-product IDs (exclude self), materialize the exact `{"items": [...], "truncated": bool}` shape from task 3, sort by `(-count, competitor_name.casefold(), product_name.casefold(), str(competitor_product_id or ""))`, retain at most `CO_PLACEMENT_MAX_PAIRS` items, and set `truncated` to whether additional candidate pairs were omitted. The old standalone `{"truncated": true}` sentinel is not valid.

### Existing tests affected

- `backend/tests/unit/test_product_scoring.py` exact signal/aggregate dictionaries gain fields; retain all existing v1 matching, price, rank, SOV, and determinism assertions.
- `backend/tests/component/test_product_analysis_worker.py` mention/snapshot assertions gain relation, attributes, destinations, win rate, mismatch rate, and co-placement.

## 5. Persist v2 rows and aggregate mixed versions [after 3, 4]

### Files

- `backend/app/analysis/product_service.py`
- `backend/app/workers/audit_worker.py`

### Changes

Change `analyze_task_products(session, *, task, config) -> ProductResponseAnalysis | None` idempotency to query by `(task.id, PRODUCT_ANALYZER_VERSION, PRODUCT_SCORING_RULE_VERSION)`. A v1 row no longer blocks a v2 write. Load the linked persisted `RawResponseArtifact` and score its `answer_text`; use `task.answer_text` only for legacy fixture rows with no artifact. Never call a provider.

Stamp `ProductResponseAnalysis.shopping_surface = task.shopping_surface`. Extend `_mention_row(...)` to write `price_relation` and `attribute_mentions`. Add `_merchant_rows(...) -> list[MerchantMention]` to persist one sanitized observed destination per product/competitor signal with the same analysis/artifact/version provenance and nullable live catalog FK behavior as `ProductMention`.

Change `finalize_audit_product_analysis()` to:

1. Keep the succeeded-task query unfiltered by surface; product analysis must cover measurement and future probe rows.
2. Ensure the current v2 row exists for each succeeded task.
3. Select one analysis per task for the v2 aggregate: prefer the exact current analyzer/rule pair, otherwise use the task’s v1 row. This is the mixed-version input rule; preserve all rows.
4. Build overall, per-engine, and per-surface aggregates from that selected persisted set. Surface aggregates come from `ProductResponseAnalysis.shopping_surface`; nested engine slices use both dimensions.
5. Find/update only the current-version snapshot keyed by `(entry_id, PRODUCT_ANALYZER_VERSION, PRODUCT_SCORING_RULE_VERSION)`. Never mutate a v1 snapshot.
6. Write exact selected `source_analysis_ids`/`source_artifact_ids` and the new scalar/JSON metrics.

In `_persist_success()`:

- Skip `build_scoring_config()` / `analyze_task()` and `task.score` assignment when `task.shopping_surface != SHOPPING_SURFACE_MEASUREMENT`.
- Keep `build_product_scoring_config()` / `analyze_task_products()` outside that branch so product probe evidence remains eligible.
- Keep the single commit after artifact, current analysis rows, attempts, and event.

### Existing tests affected

- `backend/tests/component/test_product_analysis_worker.py` currently drains a mocked-provider audit. Replace its M2a verification path with direct fixture `AuditTask` + persisted `RawResponseArtifact` rows and calls to `analyze_task_products()` / `finalize_audit_product_analysis()`; verify v1 row IDs remain and v2 rows/snapshots are new.
- `backend/tests/component/test_audit_worker.py` assumes every succeeded task writes brand analysis. Add explicit measurement/probe fixture assertions: probe success writes product analysis only; measurement row counts, `MetricSnapshot`, and brand `ResponseAnalysis` counts remain unchanged.

## 6. Slot identity, brand isolation, and all 13 query sites [after 3]

### Files

- `backend/app/domain/audits/planner.py`
- `backend/app/workers/audit_worker.py`
- `backend/app/analysis/service.py`
- `backend/app/domain/analysis/service.py`
- `backend/app/domain/products/visibility.py`
- `backend/app/orchestration/postgres_task_queue.py` — review-only; no filter change.

### Planner changes

Measurement slots remain `(prompt_index, engine, repetition)` because fanout/probes are excluded, but every constructed task explicitly sets `shopping_surface=SHOPPING_SURFACE_MEASUREMENT`.

Change the key to:

`f"{audit.id}:{prompt_index}:{repetition}:{engine}:{SHOPPING_SURFACE_MEASUREMENT}"`

The trailing empty segment is intentional and reserves the surface identity. `requested_count` and the max-task guard remain `len(prompts) * len(engine_list) * reps`; `SHOPPING_SURFACES` does not multiply tasks in M2a.

Eager-load `Audit.shopping_surface_snapshots` beside engine snapshots in `get_audit()`/`list_audits()`; the list is empty under the disabled gate.

### Exact 13-site audit

1. `workers/audit_worker.py:915-923` remaining non-terminal count — add `AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT`.
2. `workers/audit_worker.py:924-929` succeeded count — add the same filter before writing `audit.completed_count`.
3. `workers/audit_worker.py:930-934` total count — add the same filter before deriving `failed_count`.
4. `analysis/service.py:232-235` provider-metadata map — add the measurement filter so brand cost/token input excludes probes.
5. `analysis/service.py:277-280` defensive succeeded-task loop — add the measurement filter so finalize cannot recreate skipped brand rows.
6. `domain/analysis/service.py:245-268` brand evidence join — filter both `AuditTask.shopping_surface` and `ResponseAnalysis.shopping_surface` to measurement.
7. `domain/analysis/service.py:391-410` brand export task list — hard-filter measurement rows; default brand exports remain unchanged.
8. `domain/audits/planner.py:488-497` `list_tasks()` — change signature to `list_tasks(..., surface: str = SHOPPING_SURFACE_MEASUREMENT) -> list[AuditTask]` and filter exact surface. This powers the executions listing default; it is not a hard-coded brand-only query because callers can request a configured surface.
9. `orchestration/postgres_task_queue.py:101-124, 142/153/167/216/240/256, 290-300` claim, row transitions, and sweeper — do **not** add a surface filter. The ordinary queue must lease/heartbeat/finalize/reclaim every task identity.
10. `workers/audit_worker.py:367-370, 448-453, 598-610` task load/lock by primary key — do **not** filter; a claimed probe task must still resolve and transition.
11. `domain/audits/planner.py:524-535` whole-audit cancel — do **not** filter; cancellation terminalizes all surface tasks.
12. `analysis/product_service.py:232-243` succeeded-task product pass — do **not** hard-filter; group persisted analyses by `shopping_surface` later.
13. `domain/products/visibility.py:207-228` product evidence join — do **not** hard-filter measurement. Add an exact `surface` predicate supplied by the product endpoint, defaulting to measurement in M2a.

Also filter the initial `ResponseAnalysis` load in `analysis/service.py::_execution_dicts()` by `ResponseAnalysis.shopping_surface == SHOPPING_SURFACE_MEASUREMENT`. This is the chosen fix for the denominator question: task-only filtering does not constrain the rows used to build `per_engine`.

### Existing tests affected

- `backend/tests/component/test_audit_planner.py`: idempotency strings now end in `:`, deterministic slot tuples become `(prompt_index, repetition, logical_engine, shopping_surface)`, and default `list_tasks()` returns measurement rows.
- `backend/tests/component/test_audit_queue.py`: verify queue claim/transition/sweeper still process non-empty surfaces.
- `backend/tests/component/test_audit_worker.py`: progress/completion and brand per-engine metrics must be numerically identical with an additional terminal probe row.
- `backend/tests/component/test_analysis_api.py`: direct evidence fixtures set surface; add a probe `ResponseAnalysis` and assert it is excluded from brand evidence/denominators.
- `backend/tests/component/test_analysis_http.py`: update exact keys and assert `/audits/{id}/executions` defaults to measurement.
- `backend/tests/component/analytics_helpers.py`: stamp measurement surface on helper-created tasks/analyses so analytics fixtures remain explicit and deterministic.

## 7. Product projections and existing API routes [after 5, 6]

### Files

- `backend/app/domain/products/schemas.py`
- `backend/app/domain/products/visibility.py`
- `backend/app/api/products.py`
- `backend/app/api/audits.py`
- `backend/app/api/executions.py` — no route change; retain single-execution evidence ownership.

### Product DTOs

Add `product_analyzer_version` to every row-level derived response DTO:

- `ProductVisibilityEntry.product_analyzer_version: str`
- `CompetitorProductVisibilityEntry.product_analyzer_version: str`
- retain `ProductVisibilityResponse.product_analyzer_version`
- `ProductEvidenceItem.product_analyzer_version: str`

This avoids using only `snapshots[0]` to label potentially mixed evidence. Historical v1 responses carry their actual v1 string; v2 snapshot responses carry `product-analysis-2`.

Add visibility fields to both own and competitor entries:

- `win_rate: float | None`
- `price_mismatch_rate: float | None`
- `price_relation_counts: dict[str, int]`
- `attribute_dimension_frequency: dict[str, dict[str, int]]`, exactly `{group: {dimension: count >= 0}}`, with `{}` for no observations.
- `buyer_destination_mix: BuyerDestinationMix`, where `BuyerDestinationMix(total: int >= 0, by_kind: list[BuyerDestinationKindCount], by_domain: list[BuyerDestinationDomainCount])`, `BuyerDestinationKindCount(merchant_kind: str, count: int >= 0)`, and `BuyerDestinationDomainCount(merchant_domain: str, merchant_name: str, merchant_kind: str, count: int >= 0)` map exactly to the task 3 JSONB shape and ordering.
- `competitor_co_placement: CompetitorCoPlacement`, where `CompetitorCoPlacement(items: list[CompetitorCoPlacementItem], truncated: bool)` and `CompetitorCoPlacementItem(competitor_product_id: uuid.UUID | None, competitor_name: str, product_name: str, count: int >= 0)` map exactly to the task 3 JSONB shape and ordering.

Generalize evidence items with `evidence_kind: str` using config-owned values `product_mention`, `attribute_mention`, and `buyer_destination` (add these three constants and their frozenset to `commerce.py`). **Pin the exact projected key set** (the frontend schema is `.strict()`, so every key emitted must be declared and no undeclared key may be emitted; and every declared key must be emitted). Build on the CURRENT `ProductEvidenceItem` coordinate baseline (`domain/products/schemas.py:223-243`) so nothing the frontend already renders is dropped.

Common fields on every row (all kinds): `evidence_id`, `analysis_id`, `evidence_kind`, `audit_id`, `task_id`, `artifact_id`, `logical_engine`, `transport_model`, `prompt_text`, `prompt_index`, `repetition`, `product_analyzer_version`, `shopping_surface`, `matched_name`, `matched_sku`, `created_at`.

Product-mention fields (nullable unless noted; present on every row, null for non-`product_mention` kinds): `first_offset`, `rank_position`, `price_value`, `price_matches_catalog`, `price_relation`; `price_text` and `price_currency` (strings, `""` when absent). These are populated for `product_mention` rows from the persisted `ProductMention`.

Attribute-mention fields (nullable; null for non-`attribute_mention` kinds): `attribute_dimension`, `attribute_group`, `attribute_text`, `attribute_offset`.

Buyer-destination fields (nullable; null for non-`buyer_destination` kinds): `merchant_name`, `merchant_domain`, `merchant_kind`, `destination_url`.

Do NOT emit a top-level `mention_id` key: `ProductMention.id` already surfaces as `evidence_id` for `product_mention` rows, and `analysis_id` is present on all rows (it is also an input to the UUIDv5 tuple), so a separate `mention_id` would be an undeclared strict-schema key. Emit one base product mention item, one item per persisted `attribute_mentions` object, and one item per `MerchantMention` row.

Set stable evidence identity as follows:

- `product_mention`: `evidence_id = ProductMention.id`.
- `buyer_destination`: `evidence_id = MerchantMention.id`.
- `attribute_mention`: `evidence_id = uuid.uuid5(PRODUCT_ATTRIBUTE_EVIDENCE_NAMESPACE, f"{analysis_id}:{mention_id}:{dimension}:{offset}")`, using canonical UUID strings, the persisted config-owned dimension string, and the persisted original-text integer offset. This requires no table and returns the same UUID across repeated reads of the same persisted JSONB item.

`evidence_id` exists only for stable row identity, pagination keys, and frontend rendering keys. It never replaces `artifact_id`, `analysis_id`, or `product_analyzer_version`; provenance fields remain on every projected row under invariants 4 and 7. (`mention_id` is used only internally as an input to the UUIDv5 tuple for `attribute_mention` rows; it is not emitted as a top-level DTO key — `ProductMention.id` is already exposed as `evidence_id`.)

Add `ProductVisibilityResponse.available_surfaces: list[str]`. Build it from distinct `ProductResponseAnalysis.shopping_surface` values persisted for the selected audit, union `SHOPPING_SURFACE_MEASUREMENT`, and order measurement first followed by non-empty values ascending. Under the disabled gate it is exactly `[""]`. The client labels `""` as “Answer-engine APIs”; there is no synthetic “all surfaces” value, and omitting `?surface=` continues to select measurement rather than aggregate surfaces.

### Mixed-version projection rule

Put the read fallback in `domain/products/visibility.py`, not in ORM mutation:

- `_project_price_relation(price_relation: str | None, price_matches_catalog: bool | None) -> str | None`
- Return persisted `price_relation` when non-null.
- Otherwise return `match` for `True`, `mismatch` for `False`, and null for `None`.

For a v1 snapshot with no v2 relation counts, return an empty `price_relation_counts` and derive `price_mismatch_rate` as null when `price_accuracy_rate` is null, otherwise `round(1 - price_accuracy_rate, 4)`. The v1 `product_analyzer_version` tells clients that mismatch direction is unavailable; never infer higher/lower.

Change `_entry_metrics(snapshot, engine, surface)` to read only persisted columns/`metrics`. Default `surface` is `SHOPPING_SURFACE_MEASUREMENT`; non-empty configured surfaces read `metrics["per_surface"][surface]`, then the optional nested engine aggregate. Count `total_analyses` with the same exact `ProductResponseAnalysis.shopping_surface` filter.

### Route extensions only

- `GET /projects/{project_id}/products/visibility`: add `surface: Query(str) = SHOPPING_SURFACE_MEASUREMENT` beside `engine`.
- `GET /products/{product_id}/visibility/evidence`: add the same `surface` parameter and project the three evidence kinds.
- `GET /projects/{project_id}/products/visibility/export.csv`: add `surface`, pass it through bundle/rendering, and do not add a route.
- `GET /audits/{audit_id}/executions` in `api/audits.py`: add `surface: Query(str) = SHOPPING_SURFACE_MEASUREMENT`, pass to `list_tasks()`, and serialize `AuditTaskResponse.shopping_surface`.
- `api/executions.py` remains the single execution-detail route; no listing is added there. A probe execution ID can still be loaded by ID because site 10 is intentionally unfiltered.

Validate a requested surface against `{SHOPPING_SURFACE_MEASUREMENT, *SHOPPING_SURFACES}` and return 422 for unknown values. Tests may monkeypatch the gate with a fixture surface; shipped config stays empty.

### CSV columns

Keep existing columns and append in this exact order:

`product_analyzer_version`, `surface`, `win_rate`, `price_mismatch_rate`, `price_relation_match_count`, `price_relation_higher_count`, `price_relation_lower_count`, `price_relation_mismatch_count`, `attribute_dimension_frequency`, `buyer_destination_mix`, `competitor_co_placement`.

Serialize the three structured cells as stable JSON (`sort_keys=True`, compact separators) after applying the pinned list ordering above, so repeated reads and CSV exports are byte-stable. Keep `csv_cell()` protection for user-controlled product/SKU text and blank cells for null rates.

### Existing tests affected

- `backend/tests/component/test_product_visibility_api.py`: response exact fields, evidence shape/kinds, surface default/filter, analyzer version per item, and CSV header/order all change.
- `backend/tests/component/test_analysis_http.py`: executions list response gains `shopping_surface` and defaults to measurement.
- No new endpoint tests belong in `api/executions.py`; update only single-ID behavior to confirm a directly selected probe ID remains retrievable if it has brand evidence.

## 8. Focused test plan and fixture-only verification [after 1–7]

### New tests required by §14

1. `backend/tests/unit/test_product_scoring_v2.py`
   - Win rate: rank-1 win; ranked non-win gives `0.0`; no ranked mention gives null; a competitor-only enumeration where the SKU is absent does not enter the denominator; competitor SKU parity.
   - Price relation: exact/tolerance match, higher, lower, absent catalog price null, currency mismatch null, and compatibility bool still written.
   - Shared window: price/attribute/URL extraction use original offsets, stay on the mention line, and do not steal a neighboring list item’s evidence.
   - Attributes: each approved category plus unknown/empty category fallback; DEFAULT dimensions always included; dedupe and original absolute offsets; no sentiment/valence.
   - Destinations: owned domain, marketplace, retailer, other, sanitized credentials/fragments/query params, Amazon subdomain match, and `notamazon.com` non-match.
   - Destination mix: exact strict shape, `total`, deterministic `by_kind` and `by_domain` ordering, and byte-equal repeated aggregation.
   - Co-placement: exact `items`/always-present `truncated` shape, own/competitor counts, deterministic `(-count, name, product, id)` ordering, exact cap boundary, and over-cap `truncated=true`.
   - Determinism: repeated scoring/aggregation of identical fixture text is byte-equal.

2. `backend/tests/component/test_products_visibility_api.py`
   - Seed audit/task/artifact/product rows directly; call product analyzer/finalizer without a provider.
   - Re-score a task with a persisted v1 product analysis: v1 analysis/mention/snapshot IDs remain; v2 rows are added; current projection chooses v2.
   - Mixed selected analyses: a v1-only task plus v2 task renders `match | mismatch` fallback for legacy evidence and actual direction for v2, each with its analyzer version.
   - `?surface=` measurement default and fixture-surface slicing for visibility, evidence, totals, and export; optional `engine` intersects the selected surface; `available_surfaces == [""]` with the disabled gate and becomes measurement-first plus persisted fixture surfaces when seeded.
   - Evidence kinds include base mention, each attribute mention, and each sanitized buyer destination; assert PK-backed IDs for product/destination rows and the same UUID5 `evidence_id` for an attribute row across two projection reads.
   - Visibility entries and persisted snapshot metrics use the exact strict aggregate shapes; both aggregate lists retain deterministic ordering and `competitor_co_placement.truncated` is always present.
   - Exact CSV columns/order, null-vs-zero cells, byte-stable structured JSON cells, and formula neutralization.
   - Workspace isolation and projection-only behavior.

3. `backend/tests/component/test_audit_task_slot_surface.py`
   - Introspect `uq_audit_task_slot` columns in exact order.
   - Same audit/prompt/repetition/engine can persist measurement and fixture surface tasks; duplicate same-surface slot fails.
   - Idempotency key includes the surface segment and remains unique.
   - Planner freezes `shopping_surfaces=[]`, creates only measurement tasks/snapshots, and keeps requested count unchanged.
   - Fixture probe success produces product analysis but no brand analysis.
   - Add a probe task/analysis sharing a logical engine and prove brand overall/per-engine denominators, progress counts, evidence, and export are identical to the measurement-only baseline.
   - Executions listing defaults to measurement; explicit fixture surface lists only probe rows; queue/cancel/by-ID paths still include probes.

### Existing test updates

- `backend/tests/unit/test_product_shim.py` — exact frozen `attributes` bag/category.
- `backend/tests/unit/test_product_scoring.py` — new dataclass fields and expanded exact score dictionaries while preserving M1 cases.
- `backend/tests/component/test_audit_planner.py` — trailing surface key segment, four-part visible slot tuple, empty gate/config/snapshot list.
- `backend/tests/component/test_audit_queue.py` — explicit surface fixtures and proof that claim/transition/sweeper are not filtered.
- `backend/tests/component/test_audit_worker.py` — brand skip/progress denominator regression with fixture probe row.
- `backend/tests/component/test_analysis_api.py` — explicit measurement fixtures and brand evidence/per-engine exclusion.
- `backend/tests/component/test_analysis_http.py` — idempotency fixtures, execution surface field/default filter.
- `backend/tests/component/test_product_analysis_worker.py` — replace provider-drain M2a setup with persisted artifacts and direct re-score/finalize; assert all new rows/metrics/provenance and immutable v1 coexistence.
- `backend/tests/component/test_product_visibility_api.py` — update existing M1 projection expectations for added fields/evidence/CSV contract; leave the new plural v2 file focused on §14 mixed-version/surface cases.
- `backend/tests/component/analytics_helpers.py` — explicit measurement surfaces on direct audit/task/analysis fixtures.

### Verification constraints and commands

There are no usable LLM provider credentials in this sandbox. Do not create or drain a live audit and do not depend on `build_adapter`. All M2a scoring verification must use fixture answer text and persisted `RawResponseArtifact` rows, then call deterministic re-scoring/finalization. Planner/queue tests may create tasks but must not execute provider calls.

From `backend/`:

- `uv run pytest tests/unit/test_product_scoring.py tests/unit/test_product_scoring_v2.py tests/unit/test_product_shim.py -q`
- `uv run pytest tests/component/test_audit_task_slot_surface.py tests/component/test_product_analysis_worker.py tests/component/test_product_visibility_api.py tests/component/test_products_visibility_api.py -q`
- `uv run pytest tests/component/test_audit_planner.py tests/component/test_audit_queue.py tests/component/test_audit_worker.py tests/component/test_analysis_api.py tests/component/test_analysis_http.py -q`
- `uv run ruff check app/core/config/commerce.py app/core/config/products.py app/models/product.py app/models/analysis.py app/models/audit.py app/analysis/product_scoring.py app/analysis/product_service.py app/domain/products app/domain/audits app/workers/audit_worker.py app/analysis/service.py app/domain/analysis/service.py app/api/products.py app/api/audits.py tests/unit/test_product_scoring_v2.py tests/component/test_audit_task_slot_surface.py tests/component/test_products_visibility_api.py`
- Against a disposable DB only: `uv run alembic downgrade base && uv run alembic upgrade head`.

## Questions not answerable from the current code

None. The source doc’s executions-listing location is stale; the current owner is `api/audits.py` (`GET /audits/{audit_id}/executions`), while `api/executions.py` owns only single-ID evidence. The plan follows the verified context.
---

# WS-B — M4/M5 backend (Shopify + attribution)

## Summary

Land GA4 A1 first as an aggregate projection over new ecommerce metric rows, with a persisted per-connection fallback for incompatible item dimensions. Then extend the shipped integration framework for one read-only Shopify connection, derive catalog/feed/order facts, and add A2/unattributed projections and persisted APIs. Do not create sessions, synthetic GA4 orders, statistical allocations, `LiftEstimate`, M3 rules, or frontend code.

### Product contract

#### Users and workflows

- A workspace member connects GA4 and can read A1 revenue without Shopify.
- A workspace member connects one Shopify shop, maps it to a project through `IntegrationPropertyMapping`, and runs scheduled/on-demand syncs.
- Commerce reports read persisted snapshots and latest immutable order revisions only.

#### Acceptance criteria

- **AC1:** GA4 sync writes the source/medium ecommerce and one item ecommerce dataset, then exposes A1 revenue, transactions, AOV, and conversion rate by AI source.
- **AC2:** If the primary GA4 item dimensions receive the narrowly classified compatibility error, the same run switches to channel-group item data, persists that choice, and labels reduced granularity. Other errors do not degrade.
- **AC3:** A1 works before Shopify code or credentials exist.
- **AC4:** Shopify OAuth validates a canonical `*.myshopify.com` shop, binds it into signed and persisted state, verifies callback HMAC, encrypts the token, and stores the shop in `IntegrationConnection.account_ref`.
- **AC5:** GraphQL cursor retry/resume reads `pageCursor`/`nextPageCursor` from durable artifacts; no cursor is held only in memory.
- **AC6:** The catalog merge adopts manual rows, updates same-connection rows, emits a duplicate-SKU issue for another connection, preserves aliases/absent attributes, and never deletes absent SKUs.
- **AC7:** No customer PII survives into an import artifact, `OrderFact`, attribution row, DTO, or log.
- **AC8:** Refund/cancellation/fulfilment updates create a new order revision; all projections read the highest per-order `resync_seq`.
- **AC9:** Same-rule/version A2 reruns are idempotent and a rule-version bump can write a new link.
- **AC10:** A1 and A2 remain separate, are never summed, expose a valid/unavailable delta, and state A2 coverage.
- **AC11:** Orders without a current A2 link appear as unattributed with count, revenue, and share; no statistical allocation is generated.
- **AC12:** Cross-workspace project/connection access returns no data. Commerce/attribution routes are flat (non-path) routes under `/projects/{project_id}/commerce/...` and MUST use `require_active_workspace` (the header-resolved workspace dependency in `app/api/deps.py`) exactly like `app/api/products.py` — NOT `require_workspace_member` (which is reserved for the path-scoped `/workspaces/{workspace_id}/...` routes that take `workspace_id` from the URL path). The project is then authorized within that resolved workspace via `get_project(..., workspace_id)`, returning 404/403 cross-workspace per invariant 5.

#### Edge behavior

- Empty snapshots return empty method sections and zero counts, not fabricated rates.
- AOV and conversion rate are null when their denominator is zero or unavailable.
- Every revenue-bearing aggregate is partitioned by ISO currency. Revenue, orders, and AOV by source, surface, and product are never converted or summed across unlike currencies because the repository has no FX-rate source. Revenue delta is computed within one currency only and is null with `state=currency_unavailable` when values cannot be compared safely (A1 and A2 rows are produced per currency, so a within-currency A1-vs-A2 currency collision does not arise).
- GA4 channel-group fallback item rows have `ai_source=None` and a channel-group key. They are not guessed into an AI source.
- Shopify’s provider-permitted order-history window is reported as coverage; `read_all_orders` is not requested in this scope.
- The order API exposes only opaque fact UUIDs and sanitized line items/attribution status, never merchant order numbers or customer data.

### File structure map

- `backend/app/core/config/integrations.py` — Shopify/provider vocabulary, dataset templates, endpoint builders, paging modes, GA4 fallback capability tokens, rate limits.
- `backend/app/core/config/attribution.py` — attribution methods, namespaces, versions, source-granularity and coverage vocabularies.
- `backend/app/core/config/commerce.py` — order sanitization/retention and feed-validator vocabulary shared with the M2a-created commerce config.
- `backend/app/core/config/__init__.py` — Shopify OAuth credentials and order-hash salt.
- `backend/app/connectors/integrations/{ga4,oauth,shopify}.py` — GA4 compatibility classification, dynamic Shopify OAuth, Shopify data client.
- `backend/app/workers/integration_worker.py` — dataset-aware/cursor-aware paging, durable resume, provider derivation dispatch.
- `backend/app/domain/commerce/{sanitize,catalog,orders,feed,derive}.py` — pre-write normalization, merge policy, order revisions, feed issues, Shopify run derivation.
- `backend/app/domain/attribution/{link,snapshot,service,schemas}.py` — A2 links, A1/A2 snapshot projection, persisted reads, DTOs.
- `backend/app/domain/analytics/{enqueue,tasks}.py` and `backend/app/workers/analytics_worker.py` — attribution/retention task enqueue and dispatch.
- `backend/app/models/{integrations,product,commerce,attribution}.py` — capability state, product provenance, commerce facts, attribution rows.
- `backend/app/api/commerce.py`, `backend/app/main.py` — commerce attribution routes and router registration.
- `backend/app/models/__init__.py` — metadata registration for greenfield DB creation.

### Tasks

1. **[parallel] Ship GA4 A1 as an independently verifiable vertical slice.**

   **Config and templates**

   - In `backend/app/core/config/integrations.py` add:
     - `DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY = "ga4_ecommerce_source_medium_daily"`.
     - `DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY = "ga4_item_source_medium_daily"`.
     - `DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY = "ga4_item_channel_group_daily"` for fallback only.
     - `_GA4_ECOMMERCE_METRICS: Final = ("transactions", "purchaseRevenue", "sessions")`.
     - `_GA4_ITEM_ECOMMERCE_METRICS: Final = ("itemRevenue", "itemsPurchased")`.
     - `GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY`, `GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION = "ga4-item-attribution-1"`, `ERROR_GA4_DIMENSION_INCOMPATIBLE`, and selected-dataset/source-granularity tokens.
   - Register exact templates:
     - `IntegrationDatasetTemplate(dataset=DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY, provider=INTEGRATION_PROVIDER_GA4, api_method="runReport", dimensions=("sessionSource", "sessionMedium", "date"), metrics=_GA4_ECOMMERCE_METRICS)`.
     - `IntegrationDatasetTemplate(dataset=DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY, provider=INTEGRATION_PROVIDER_GA4, api_method="runReport", dimensions=("itemId", "sessionSource", "sessionMedium", "date"), metrics=_GA4_ITEM_ECOMMERCE_METRICS)`.
     - `IntegrationDatasetTemplate(dataset=DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY, provider=INTEGRATION_PROVIDER_GA4, api_method="runReport", dimensions=("itemId", "sessionDefaultChannelGroup", "date"), metrics=_GA4_ITEM_ECOMMERCE_METRICS)`.
   - Keep the fallback template in the registry so normalization/derivation can resolve it, but change worker template selection so exactly one item template runs. Absent or stale capability state selects the primary; persisted fallback state selects only the fallback.

   **Attribution config**

   - Add `backend/app/core/config/attribution.py` with module-level `Final` constants:
     - `ATTRIBUTION_METHOD_ORDER_REFERRER = "order_referrer"`.
     - `ATTRIBUTION_METHOD_GA4_PLATFORM = "ga4_platform_attributed"`.
     - `ATTRIBUTION_METHODS` containing those two values.
     - Re-export/import `CONFIDENCE_EXACT`, `CONFIDENCE_HEURISTIC`, and `CONFIDENCE_BUCKETS` from `core/config/analytics.py`; do not duplicate their literals.
     - `ATTRIBUTION_ANALYZER_VERSION = "attribution-analysis-1"`.
     - `ATTRIBUTION_FORMULA_VERSION = "attribution-formula-1"`.
     - `ATTRIBUTION_MIN_SAMPLE = CORRELATION_MIN_SAMPLE` to follow the existing analytics floor; no statistical estimate consumes it in this scope.
     - `ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC = "deterministic"` and `ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL = "statistical"`.
     - `ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM = "session_source_medium"`, `ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP = "default_channel_group"`, and the vocabulary set.
     - Delta states `comparable`, `currency_unavailable`, and `method_unavailable` (exactly these three, matching the frontend `attributionDeltaStateSchema`); statistical state `not_offered`.

   **Capability persistence and GA4 connector**

   - In `backend/app/models/integrations.py`, add `IntegrationConnection.dataset_capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)`. Store only non-secret provider capability state, for example the selected item dataset, source granularity, reason token, and capability version.
   - In `backend/app/connectors/integrations/ga4.py`:
     - Change template resolution to `def _ga4_template(dataset: str, dimensions: Sequence[str]) -> IntegrationDatasetTemplate`, validating both dataset id and dimensions.
     - **Currency source (resolves the A1 currency gap).** A GA4 property is single-currency, and the Data API `runReport` response carries that code at `metadata.currencyCode`. Read it on every ecommerce report response and persist it on the sanitized page `payload` as `currency_code` (top-level, beside `rows`/`rowCount`); do NOT add the `currencyCode` report dimension (that would change `dimension_key` identity and explode the row cardinality). `build_a1_projection` reads `currency_code` from the artifact payload (falling back to the persisted `IntegrationMetricRow` page metadata) so every A1 source/surface/product row carries its ISO currency. Because a GA4 property is single-currency, A1 yields exactly one currency partition per project; the `currency` field is **required** (non-null) on available A1 rows. This is the only currency source for A1 — `shop.currencyCode` cannot be used because A1 ships before Shopify (AC3).
     - Add `Ga4DimensionCompatibilityError(Ga4ApiError)`.
     - Raise it only for the primary item dataset when HTTP 400’s capped provider detail explicitly identifies an incompatible dimension/metric combination. Authentication, rate limit, malformed response, and generic 400 errors retain existing behavior.
   - In `backend/app/workers/integration_worker.py`:
     - Add `dataset` to `_DataClient.query_search_analytics(...)` and pass `template.dataset` to every connector.
     - Change `_provider_datasets` to accept `_RunContext`/capabilities and omit the unselected item candidate.
     - Wrap the primary item call in a narrow fallback path. Before falling back, assert no artifact for the primary item dataset exists in the run. Persist fallback state under an `IntegrationConnection` row lock, then page the fallback in the same run. A changed capability version retries the primary on a future run.
     - Do not catch `Ga4DimensionCompatibilityError` in the broad provider-error path before the fallback handler.

   **A1 model, task, projection, and API**

   - Add `backend/app/models/attribution.py::AttributionSnapshot`:
     - UUID `id`.
     - `workspace_id` FK `workspaces.id` `CASCADE`.
     - `project_id` FK `projects.id` `CASCADE`.
     - `window_start Date`, `window_end Date`, `granularity String(8)`, `metrics JSONB`.
     - `source_link_ids JSONB`, `source_order_fact_ids JSONB`, `source_metric_row_ids JSONB`, `source_snapshot_ids JSONB`, all nullable provenance arrays.
     - `analyzer_version String(64)`, `formula_version String(64)`, `created_at DateTime(timezone=True)`.
     - `UNIQUE(project_id, window_start, window_end, granularity)` named `uq_attribution_snapshot_window`.
   - Register `AttributionSnapshot` in `backend/app/models/__init__.py`. Greenfield policy: add no Alembic revision; recreate the local/test DB from `Base.metadata` and run the schema bootstrap check.
   - In `backend/app/core/config/analytics.py`, add `ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT = "attribution_snapshot"` to `ANALYTICS_TASK_KINDS`.
   - In `backend/app/domain/analytics/enqueue.py`, add `enqueue_attribution_snapshot_refresh(session, *, workspace_id, project_id, window_start, window_end, resync_seq, priority=0) -> UUID | None` through `_enqueue_window_snapshot_refresh`.
   - **Change `enqueue_post_sync_projections(...)` to be dataset-aware.** Note: today it is NOT dataset-aware — it enqueues referral ingest for every artifact plus a traffic refresh per window without selecting `dataset` (`domain/analytics/enqueue.py`). This task changes that behavior. Select `dataset` in the artifact query and route by it. The mapping is **additive and many-to-many** — do NOT re-partition the 8 existing datasets; preserve every trigger that exists today (the existing dataset→chain sets are the source of truth, `config/traffic.py`):
     - `TRAFFIC_GA4_REFERRAL_DATASETS = {ga4_referrer_daily, ga4_source_medium_daily}` → referral ingest (GA4-only; GSC is not referral).
     - `TRAFFIC_CONSUMED_DATASETS = {gsc_page, gsc_query, ga4_channel, ga4_source_medium, ga4_landing}` → traffic refresh. Note `ga4_source_medium_daily` feeds **both** referral ingest and traffic refresh today — keep both triggers; do not file it under only one chain. `ga4_landing_daily` feeds traffic only (do not newly route it to referral). `bing_page_daily`/`bing_query_daily` keep their existing (traffic) chain.
     - The three GA4 ecommerce datasets (source/medium + both item templates) → **one attribution snapshot refresh per distinct window/revision, and nothing else** (they are not referral, not traffic).
     - The two Shopify datasets (`shopify.products`, `shopify.orders`) → commerce derive only (Task 3); no referral/traffic/attribution-snapshot enqueue from the artifact itself (A2 link/snapshot enqueue happens via the order link task in Task 4).
     - Net effect: ecommerce-only artifacts do not increase referral or traffic task counts, and no existing dataset loses a trigger it has today.
   - Add `backend/app/domain/attribution/snapshot.py`:
     - `metric_row_not_superseded` is reused from `domain/analytics/ingest.py` for latest GA4 revisions.
     - `build_a1_projection(rows: Sequence[IntegrationMetricRow], products_by_sku: Mapping[str, UUID]) -> A1Projection` classifies source/medium via `classify_referral_signals(utm_source=..., utm_medium=...)` and computes currency-partitioned transactions, purchase revenue, sessions, AOV, and conversion rate. Every revenue-bearing source/surface/product row carries its ISO currency; unlike currencies are never combined.
     - Primary item rows resolve `itemId -> Product.sku`; fallback rows resolve the SKU but group by channel group with `ai_source=None`.
     - `refresh_attribution_snapshot(session_factory, task) -> None` parses the window with `payload_window`, reads latest rows in bounded batches, and upserts every configured analytics granularity with `ON CONFLICT DO UPDATE` on the snapshot unique tuple, mirroring `domain/analytics/snapshot.py::_upsert_snapshot`.
     - Persist top-level `metrics["deterministic"]["a1"]`; persist `metrics["statistical"] = {"state": "not_offered", "allocations": []}`.
   - Register the executor in `backend/app/workers/analytics_worker.py::EXECUTORS`.
   - Add `backend/app/domain/attribution/schemas.py` and `service.py` with an A1-capable `CommerceAttributionResponse`. Method summaries use the exact frontend-consumed field names: `method`, `state` (`available | no_data | not_connected`), `source_granularity` (required `session_source_medium | default_channel_group` on available A1 rows; null on A2 rows and on any non-available row — see S2 below), `currency` (required three-char ISO on every available revenue-bearing row), `coverage_rate` (nullable), `totals`, `by_ai_source` source rows, and `by_product` product rows. Null denominators remain null.
   - Add `backend/app/api/commerce.py` with `GET /projects/{project_id}/commerce/attribution?from=&to=&granularity=`. Use `require_active_workspace`, call `get_project` with `workspace_id` first, and read only `AttributionSnapshot`. Register the router in `backend/app/main.py`.

   **Tests and affected existing tests**

   - Add `backend/tests/unit/test_attribution_config.py` and `backend/tests/unit/test_attribution_snapshot.py` for template metrics, classifier mapping, null denominators, SKU mapping, fallback channel-group labeling, no guessed AI source, latest revision, and empty statistical namespace.
   - Add A1 cases to `backend/tests/component/test_attribution_api.py`: GA4-only response, reduced-granularity label, cross-workspace 404, empty snapshot, and no provider call at read time.
   - Update `backend/tests/unit/test_integrations_config.py` exact provider/template/metric/registry assertions.
   - Update `backend/tests/component/test_integration_ga4.py` exact `_GA4_DATASETS`, call/artifact counts, per-template metric assertions, primary success, narrowly matched fallback, persisted future-run selection, capability-version reprobe, and generic-400 no-fallback cases. Use `httpx.MockTransport`; no credentials.
   - Update `backend/tests/component/test_integration_derivation.py`, `test_integration_worker.py`, `test_analytics_queue.py`, `test_post_sync_chain.py`, `test_analytics_snapshot.py`, `test_llm_analytics_api.py`, `backend/tests/unit/test_analytics_config.py`, and `test_traffic_projection.py` where exact dataset/task vocabularies or counts are asserted.

2. **[after 1] Add the GraphQL-only Shopify OAuth and durable cursor transport foundation.**

   **Locked API decision**

   - Use Shopify Admin GraphQL API only. CiteLadder is a greenfield new app, so there is no REST compatibility or fallback path in connector, config, tests, or documentation.

   **Provider/OAuth config**

   - In `backend/app/core/config/integrations.py` add:
     - `INTEGRATION_PROVIDER_SHOPIFY = "shopify"`, `INTEGRATION_TRANSPORT_SHOPIFY = "shopify_oauth"`, and provider/transport mapping entries.
     - `INTEGRATION_OAUTH_SCOPES[shopify_oauth] = ("read_products", "read_orders")`; do not request write scopes or `read_all_orders`.
     - Dynamic authorize/token path templates `/admin/oauth/authorize` and `/admin/oauth/access_token`; Shopify revoke URL is empty/local disconnect.
     - `SHOPIFY_SHOP_DOMAIN_PATTERN`, `normalize_shopify_shop_domain(value: str) -> str`, `is_shopify_shop_domain(host: str) -> bool`, and URL builders that interpolate only a validated canonical shop host.
     - `SHOPIFY_ADMIN_API_VERSION: Final[str] = "2026-07"` and `SHOPIFY_ADMIN_GRAPHQL_PATH: Final[str] = "/admin/api/{version}/graphql.json"`. Build `https://{shop}.myshopify.com/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json` only after shop-host validation; connector code never owns the version literal.
     - Add a NEW constant `INTEGRATION_OAUTH_REFRESHABLE: Final[dict[str, bool]] = {"google_oauth": True, "microsoft_oauth": True, "shopify_oauth": False}` (this mapping does not exist today — `config/integrations.py` currently has only the authorize/token/revoke URL and scope maps). `IntegrationWorker._fresh_access_token` (`integration_worker.py`) currently treats `token_expires_at=None` as near-expiry and would fail a Shopify offline token with "grant has no refresh token"; update it to consult `INTEGRATION_OAUTH_REFRESHABLE` and return a non-refreshable transport's access token directly instead of attempting a refresh.
     - `DATASET_SHOPIFY_PRODUCTS = "shopify.products"`, `DATASET_SHOPIFY_ORDERS = "shopify.orders"` and templates with `provider=shopify`, `api_method="ShopifyProducts"|"ShopifyOrders"`, empty report dimensions/metrics, and `paging_mode="cursor"`.
     - Paging-mode vocabulary `offset|cursor`; add `paging_mode: str = "offset"` to `IntegrationDatasetTemplate`.
     - Shopify request-rate and page-size settings under `IntegrationSettings`; all values remain config-owned.
   - In `backend/app/core/config/__init__.py`, add env-backed `integration_shopify_client_id`, `integration_shopify_client_secret`, and `order_hash_salt`. Include the salt in `_check_secret_defaults` outside dev/test.
   - Add those env keys to `infra/docker/.env.example`; no token appears there.

   **Signed shop state and callback validation**

   - In `backend/app/models/integrations.py`, add `IntegrationOAuthState.provider_account_ref: Mapped[str] = mapped_column(String(255), default="")`.
   - Extend `backend/app/core/security.py::create_oauth_state(..., provider_account_ref: str | None = None)` to sign the canonical shop host when present.
   - In `backend/app/api/integrations.py`, add optional `shop` to the start route. Require it only for Shopify, normalize/validate it before calling the domain service, and pass all callback query parameters needed for HMAC verification.
   - In `backend/app/domain/integrations/service.py`:
     - Extend `start_connect(..., provider_account_ref: str = "") -> str`; persist and sign the shop.
     - Extend state verification/consumption to require signed claim, persisted value, and callback `shop` to match exactly.
     - Verify Shopify callback HMAC-SHA256 with `integration_shopify_client_secret` over canonical query parameters excluding `hmac`, using constant-time comparison, before code exchange.
     - Extend `_attach_connections(..., provider_account_ref="")` so Shopify sets `IntegrationConnection.account_ref` to the canonical shop; Google/Microsoft behavior is unchanged.
   - In `backend/app/connectors/integrations/oauth.py`:
     - Add the Shopify credential branch.
     - Change `IntegrationOAuthClient`/`build_oauth_client` to accept `provider_account_ref` and resolve dynamic Shopify token URLs through the validated builder.
     - Use Shopify’s code-exchange form. Treat a Shopify offline token with no expiry/refresh token as usable; update `IntegrationWorker._fresh_access_token` to return it directly when the transport is non-refreshable instead of treating `token_expires_at=None` as near expiry.
   - In `backend/app/connectors/integrations/_http.py`, replace exact-set-only host checking with `is_approved_integration_host`: fixed hosts remain exact matches; a dynamic host passes only `is_shopify_shop_domain`. Do not add an unrestricted wildcard/suffix check.
   - In `backend/app/domain/integrations/mappings.py`, add a Shopify branch that requires `property_ref == connection.account_ref` after canonicalization, rather than comparing the `myshopify.com` host to the project’s custom `OwnedDomain`. Project/workspace validation and the one-active-owner index remain unchanged.

   **Shared cursor protocol and resume**

   - Keep `workers/integration_worker.py:106-136` unchanged: Shopify implements the shipped `query_search_analytics(*, access_token, property_ref, dimensions, start_date, end_date, start_row) -> page` method and returns only `payload`, `rows`, and `raw_row_count`.
   - Add `_DatasetResume(start_row: int, page_cursor: str | None, complete: bool)` below the existing protocols and change `_dataset_resume` to read durable artifact snapshots. Do not add cursor fields to `_ClientPage` or `_DataClient`.
   - For a `paging_mode="cursor"` template, the worker restores the resume cursor through a narrow optional connector capability `ShopifyClient.set_page_cursor(cursor: str | None) -> None` before invoking the unchanged query method. `ShopifyClient` sends that value as GraphQL variable `after`; `start_row` remains the worker’s logical page offset and is not translated into a Shopify offset.
   - The Shopify page’s sanitized `payload` includes normalized `pageInfo`. After each call the worker validates `hasNextPage`/`endCursor`, persists `pagingMode`, `pageCursor`, and `nextPageCursor` in `query_snapshot`, and injects the next cursor into the client before the next unchanged-protocol call. Resume after process restart comes only from the latest immutable artifact.
   - Cursor datasets finish when `hasNextPage` is false; `hasNextPage=true` requires a non-empty `endCursor` and otherwise fails as malformed provider data. Offset datasets retain the existing `raw_row_count < sync_page_size` termination rule.

   **Shopify connector**

   - Add `backend/app/connectors/integrations/shopify.py` with `ShopifyApiError`, frozen `ShopifyPage(payload, rows, raw_row_count)`, `ShopifyClient`, `set_page_cursor`, and `build_shopify_client(*, transport=None)`.
   - Validate `property_ref` before every request; POST to the config-built GraphQL endpoint with `X-Shopify-Access-Token`; use `RequestPacer`, config timeout/rate limits, `assert_approved_url`, and the injected `httpx.AsyncBaseTransport` seam. Treat top-level GraphQL `errors` as provider failures even on HTTP 200, without persisting their unrestricted payload.
   - Pin the `shopify.products` outer-page operation and selection set as **config-owned query text** (invariant 1 is absolute — no GraphQL query text as a connector module constant):
     - `query ShopifyProducts($first: Int!, $after: String, $query: String!, $variantFirst: Int!) { shop { currencyCode } products(first: $first, after: $after, sortKey: UPDATED_AT, query: $query) { pageInfo { hasNextPage endCursor } nodes { id title handle description vendor productType status onlineStoreUrl updatedAt variants(first: $variantFirst) { pageInfo { hasNextPage endCursor } nodes { id title sku barcode price inventoryQuantity updatedAt } } } } }`.
     - Build `$query` from the sync window with `updated_at:>=<start> updated_at:<=<end>`. Normalize one safe catalog row per variant; use `shop.currencyCode` for the variant-price currency.
     - If a product’s nested `variants.pageInfo.hasNextPage` is true, exhaust it before returning the outer worker page with `query ShopifyProductVariants($id: ID!, $first: Int!, $after: String) { product(id: $id) { variants(first: $first, after: $after) { pageInfo { hasNextPage endCursor } nodes { id title sku barcode price inventoryQuantity updatedAt } } } }`. Pace every continuation call and reject malformed nested pageInfo; do not truncate variants silently.
   - Pin the `shopify.orders` operation and selection set:
     - `query ShopifyOrders($first: Int!, $after: String, $query: String!, $lineItemFirst: Int!) { orders(first: $first, after: $after, sortKey: UPDATED_AT, query: $query) { pageInfo { hasNextPage endCursor } nodes { id createdAt updatedAt cancelledAt currencyCode currentTotalPriceSet { shopMoney { amount currencyCode } } displayFinancialStatus displayFulfillmentStatus customerJourneySummary { ready firstVisit { landingSiteUrl: landingPage referrerUrl referralCode source sourceDescription sourceType utmParameters { campaign content medium source term } } lastVisit { landingSiteUrl: landingPage referrerUrl referralCode source sourceDescription sourceType utmParameters { campaign content medium source term } } } lineItems(first: $lineItemFirst) { pageInfo { hasNextPage endCursor } nodes { id sku quantity currentQuantity originalUnitPriceSet { shopMoney { amount currencyCode } } } } } } }`.
     - Build `$query` only from `updated_at:>=<start> updated_at:<=<end>`; do not add financial or fulfillment filters, so open, closed, cancelled, refunded, and fulfilled revisions remain eligible. `updatedAt` drives re-ingest of refunds/cancellations/fulfilment changes.
     - The GraphQL alias `landingSiteUrl: landingPage` gives the sanitizer the §10.2 key while using Shopify’s current `CustomerVisit.landingPage` field. When `customerJourneySummary.ready` is true, normalize `lastVisit` when present and fall back to `firstVisit`; otherwise record explicit unavailable journey coverage and do not guess.
     - Exhaust nested line-item pages before returning the outer order page using `query ShopifyOrderLineItems($id: ID!, $first: Int!, $after: String) { order(id: $id) { lineItems(first: $first, after: $after) { pageInfo { hasNextPage endCursor } nodes { id sku quantity currentQuantity originalUnitPriceSet { shopMoney { amount currencyCode } } } } } }`; never truncate order revenue allocation silently.
   - Both operations use `first: N, after: $cursor`. The connector performs only structural normalization: it returns `pageInfo { hasNextPage endCursor }` and one structurally-typed row per outer node. For **products** (no PII — title/handle/vendor/type/price/sku/barcode) the connector's normalized catalog rows are already safe and the worker persists them directly. For **orders** the connector returns structurally-normalized-but-RAW order nodes and the **worker** runs `sanitize_order_payload` (see Task 3) to produce the `SanitizedOrder` payload before the immutable artifact write — the connector never sanitizes and never imports `app.domain.*`. `raw_row_count` is the number of outer product/order nodes before row validation; `rows` contains only structurally normalized rows.
   - Register `_shopify_client_builder` in `INTEGRATION_CLIENT_BUILDERS` and add `ShopifyApiError` to the worker’s provider-error tuple.
   - Add a provider-specific GraphQL connection probe such as `query ShopifyConnectionProbe { shop { id } }`; do not reuse the Google GSC probe.

   **Tests and affected existing tests**

   - Add Shopify OAuth unit/component coverage in `backend/tests/unit/test_integrations_oauth.py` and `backend/tests/component/test_integrations_oauth_api.py`: domain normalization, hostile suffix rejection, signed/persisted shop mismatch, HMAC rejection, encrypted token, account ref, no refresh attempt, and no secret in DTO/event/log.
   - Add `backend/tests/component/test_integration_shopify.py` with `httpx.MockTransport`: exact endpoint/version/header, products/orders selection variables, two GraphQL cursor pages, exact `endCursor` replay, worker restart/resume from artifact state, `hasNextPage=false` completion, malformed/missing outer or nested `pageInfo`, HTTP-200 GraphQL errors, 429 retry classification, unauthorized token, and unapproved host rejection.
   - Update `backend/tests/unit/test_integrations_config.py`, `backend/tests/component/test_integration_worker.py`, `test_integration_dispatcher.py`, `test_integrations_api.py`, `test_integrations_mappings_api.py`, and `test_integrations_models.py` for the new provider, transport, state column, protocol fields, and dispatcher coverage.

3. **[after 2] Derive Shopify catalog, feed issues, and immutable sanitized order revisions.**

   **Commerce config and models**

   - Extend the M2a-owned `backend/app/core/config/commerce.py`; do not create a second commerce config owner. Add:
     - `ORDER_SANITIZE_VERSION = "order-sanitize-1"`, `ORDER_RETENTION_DAYS = 90`, `ORDER_REF_HASH_HEX_LENGTH = 64`, and bounded retention batch size.
     - `ORDER_ATTRIBUTION_KEY_ALLOWLIST` for sanitized `landing_url`, `referrer_url`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, and `source_name`.
     - `ORDER_LINE_ITEM_KEYS` for `sku`, `quantity`, `unit_price`; product IDs are added after SKU resolution.
     - Feed-rule version/severity vocabularies and rule ids for missing SKU, missing GTIN/MPN, missing availability, catalog-price divergence, and `feed.duplicate_sku_across_connections`. Do not add M3’s `stale_catalog_data`, `ai_channel_ineligible`, or `entity_inconsistency` rules. The spec §9.3 "platform AI-eligibility verdict" feed source is explicitly **out of scope** here: it arrives with GMC (excluded) and Shopify's native Agentic Commerce Dashboard is not a read API we consume in this slice — record this as a deliberate exclusion, not an omission.
     - `SHOPIFY_PLATFORM_ATTRIBUTE_KEYS` and price-divergence tolerance; aliases are never in the platform-owned set.
   - In `backend/app/core/config/products.py`, add `PRODUCT_ORIGIN_SYNCED = "synced"` to `PRODUCT_ORIGINS`.
   - In `backend/app/models/product.py`, add:
     - `connection_id UUID`, nullable FK `integration_connections.id` with `SET NULL`, indexed.
     - `external_item_ref String(255)`, default `""`.
     - `last_seen_sync_run_id UUID`, nullable FK `integration_sync_runs.id` with `SET NULL`, indexed.
     - Keep `uq_product_project_sku` unchanged.
   - Add `backend/app/models/commerce.py::OrderFact` with §9.4 columns:
     - UUID `id`; `workspace_id` FK `workspaces.id` `CASCADE`; `project_id` FK `projects.id` `CASCADE`.
     - Same-workspace composite `connection_id` FK to `integration_connections` with `CASCADE`.
     - `provider String(16)`, `order_ref_hash String(64)`, `resync_seq Integer`, `occurred_at DateTime(timezone=True)`, `currency String(3)`, `total_amount Numeric(12,2)`.
     - `line_items JSONB`, `attribution_keys JSONB`, `source_artifact_id UUID`, `importer_version String(64)`, `order_sanitize_version String(64)`, `created_at`.
     - Same-workspace composite `source_artifact_id` FK to `integration_import_artifacts` with `CASCADE`.
     - `UNIQUE(connection_id, order_ref_hash, resync_seq)` and `UNIQUE(workspace_id, id)` for scoped child FKs.
     - No customer/order-number/address/email/phone/IP/payment columns.
   - Add `FeedIssue` in the same model module:
     - UUID `id`; workspace/project `CASCADE`; same-workspace connection and sync-run `CASCADE`.
     - `external_item_ref String(255)`, nullable `product_id` FK `products.id` `SET NULL`, `rule_id String(64)`, `severity String(16)`, `evidence JSONB`.
     - Same-workspace `source_artifact_id` FK `CASCADE`, `importer_version String(64)`, `created_at`.
   - Register both models in `backend/app/models/__init__.py`; no Alembic revision under the greenfield policy.

   **Pre-persistence sanitizer**

   - Add `backend/app/domain/commerce/sanitize.py`:
     - Frozen `SanitizedOrder` contains only `order_ref_hash`, occurrence/update timestamps, currency, net/current total, allowlisted non-PII order-state evidence, sanitized line items, and attribution keys.
     - `hash_order_ref(raw_order_id: object) -> str` uses HMAC-SHA256 with `settings.order_hash_salt` and returns 64 hex chars.
     - `sanitize_order_payload(raw: Mapping[str, object]) -> SanitizedOrder` constructs a new allowlisted object; it never copies then deletes fields.
     - Reuse `sanitize_referral_url` for landing/referrer URLs. Parse UTM values only from the sanitized landing URL and explicit allowlisted fields.
     - Normalize line items to SKU/current quantity/unit price and safe refund/fulfilment state needed to detect revisions; discard names, gift messages, customer, tax/address, and arbitrary properties.
   - The immutable artifact stores only `SanitizedOrder` dictionaries. A second validation in order derivation rejects unexpected keys; raw provider JSON is never persisted. **Dependency-direction note:** sanitization must run before the immutable artifact write, so the sanitizer cannot live only in `app/domain/*` (today connectors import only config + `_http`; the direction is worker/domain → connector). To avoid a connector→domain layering inversion, place the order sanitizer in `backend/app/domain/commerce/sanitize.py` BUT keep it free of any `app.domain` / `app.models` imports (pure function over mappings + config), and have the **worker** (`integration_worker.py`) call it on each connector-returned raw page to build the sanitized payload — the connector returns raw provider rows, the worker sanitizes. This preserves the existing dependency direction (worker/domain → connector) while still guaranteeing sanitize-before-immutable-write. Do NOT have `connectors/integrations/shopify.py` import `app.domain.commerce.sanitize`.

   **Catalog/feed/order derivation**

   - Add `backend/app/domain/commerce/catalog.py` with table-driven `merge_catalog_row(session, *, mapping, connection, run, artifact, row) -> CatalogMergeResult` keyed by `(project_id, sku)`:
     - Manual/no-connection: set `origin=synced`, set provenance, overwrite name/price/currency/url/variants and present platform attributes, preserve aliases, and merge old attributes so keys absent from feed survive.
     - Synced/same connection: same platform-field update and preservation behavior.
     - Synced/different connection: no Product mutation; emit `feed.duplicate_sku_across_connections` with both connection ids and the SKU in evidence.
     - Absent from the feed: no delete and no update. Staleness remains inferable by comparing `last_seen_sync_run_id` to the latest successful catalog run; no M3 stale rule is emitted.
     - Treat each Shopify variant with a non-empty SKU as one `Product` row; `external_item_ref` is the opaque variant id. Missing-SKU variants emit a `FeedIssue` and do not create an unstable catalog identity.
   - Add `backend/app/domain/commerce/feed.py::validate_feed_row(...) -> tuple[FeedFinding, ...]` for only the in-scope deterministic rules. Every issue carries sanitized evidence, product/artifact/run provenance, importer version, and no customer data.
   - Add `backend/app/domain/commerce/orders.py`:
     - Resolve line-item `product_id` by `(project_id, sku)`; unresolved SKU stays null.
     - Allocate `OrderFact.resync_seq = max(existing)+1` per `(connection_id, order_ref_hash)` while the integration worker already holds the connection row lock. Do not copy the run-window sequence because overlapping windows can share it.
     - Insert one new fact for each order returned by a later sync, including refund/cancellation/fulfilment revisions. The sanitized artifact retains non-PII order-state evidence; attribution uses net/current amount and current line-item quantities.
     - Add `order_fact_not_superseded()` as the SQL `NOT EXISTS` max-sequence predicate and use it in every projection/read.
   - Add `backend/app/domain/commerce/derive.py::derive_shopify_run(session, *, run, connection, artifacts) -> DerivedCommerceRun`. Resolve the active mapping through `resolve_active_mapping`, split product/order datasets, run catalog/feed/order derivation, and return project/artifact/fact counts.
   - In `backend/app/workers/integration_worker.py::_finalize_success`, dispatch Shopify artifacts to `derive_shopify_run`; existing metric providers keep `derive_run`. Both remain inside the owner-gated terminal transaction and call the post-sync enqueue hook last.

   **Retention**

   - Add `ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP = "order_retention_sweep"`, enqueue helper, and `run_order_retention_sweep(session_factory, task) -> None` in `domain/commerce/orders.py`.
   - Mirror the referral sweep’s workspace scope, bounded commits, and cooperative cancellation. Delete superseded/expired `AttributionLink` rows through FK cascade with their `OrderFact`; do not delete GA4 metric rows. Include a deterministic `sweep_key` in the idempotency key.

   **Tests and affected existing tests**

   - Add `backend/tests/unit/test_feed_validators.py` for every in-scope rule and source-absent no-issue behavior.
   - Add `backend/tests/unit/test_order_sanitize.py` with hostile nested customer/email/address/phone/IP/note/payment fields. Assert none survives the worker-sanitized payload (the connector returns raw order nodes; the worker sanitizes), `line_items`, `attribution_keys`, model columns, or DTO shapes; assert URL credentials/fragments/non-allowlisted params are removed and order hash is opaque/stable.
   - Add `backend/tests/component/test_catalog_sync_merge.py` for all four §9.2 rows, alias preservation, absent-attribute preservation, missing SKU, deterministic variant identity, duplicate issue, provenance, and never-delete behavior.
   - Add `backend/tests/component/test_order_resync_seq.py` for overlapping windows, refund revision, cancellation/fulfilment revision, per-order monotonic sequence, immutable prior rows, and latest-only read.
   - Extend `backend/tests/component/test_integration_shopify.py` through claim → sanitized artifact → catalog/feed/order derivation; inspect the persisted artifact to prove raw PII never lands.
   - **Expose the new provenance fields on the product DTO (mandatory, not conditional).** The frontend `productSchema` (`.strict()`) requires these as required keys, so extend `ProductResponse` and `product_to_response` in `backend/app/domain/products/schemas.py` to always include `connection_id: UUID | None`, `external_item_ref: str | None`, and `last_seen_sync_run_id: UUID | None` (null for unbound manual/imported products), and narrow `origin` to the `manual | imported | synced` enum now that `synced` exists. Without this, every product list/get fails frontend strict validation. Ensure no token/PII fields are added.
   - Update `backend/tests/component/test_products_api.py` and `backend/tests/unit/test_product_schemas.py` for the three new required-nullable fields and the narrowed `origin` enum; ensure no token/PII fields are added.

4. **[after 3] Add A2 links, combined snapshots, unattributed reads, and order drill-down.**

   **Models and queue wiring**

   - Extend `backend/app/models/attribution.py` with `AttributionLink`:
     - UUID `id`; workspace/project FKs `CASCADE`.
     - `order_fact_id UUID` with a same-workspace composite FK to `order_facts` and `CASCADE`.
     - `method String(24)`, `confidence String(16)`, `matched_rule_id String(64)`, `rule_version String(64)`, `analyzer_version String(64)`, `evidence_refs JSONB`.
     - `revenue_amount Numeric(12,2)`, `currency String(3)`, `created_at`.
     - `UNIQUE(order_fact_id, matched_rule_id, rule_version)` named `uq_attribution_link_order_rule_version`.
   - Add `ANALYTICS_TASK_KIND_ATTRIBUTION_LINK = "attribution_link"`; register `run_attribution_link` and the order-retention executor in `workers/analytics_worker.py::EXECUTORS`.
   - Add `enqueue_attribution_link(session, *, workspace_id, project_id, sync_run_id, rule_version=AI_REFERRAL_RULE_VERSION, priority=0) -> UUID | None`. Include rule/analyzer versions in its idempotency key so a rule bump can reprocess the same source run.
   - Update `enqueue_post_sync_projections` so Shopify order artifacts enqueue one link task per sync run. Catalog artifacts enqueue no attribution work. Link completion enqueues attribution snapshot refresh for the source run window/revision.

   **Link and combined snapshot projection**

   - Add `backend/app/domain/attribution/link.py`:
     - `_link_values(order: OrderFact) -> dict | None` calls `classify_referral_signals` over the sanitized referrer host/UTM values in `attribution_keys`.
     - A match writes `method=order_referrer`, the classifier’s confidence/rule id, `AI_REFERRAL_RULE_VERSION`, `ATTRIBUTION_ANALYZER_VERSION`, fact/artifact evidence refs, and order revenue/currency.
     - No match writes no link; the order remains deterministically unattributed.
     - `run_attribution_link` reads only latest facts for the sync run, inserts with `ON CONFLICT DO NOTHING` on the unique tuple, then enqueues the window snapshot in the same commit.
   - Extend `backend/app/domain/attribution/snapshot.py`:
     - Read latest `OrderFact` revisions and only links at the current rule/analyzer versions.
     - Build `metrics.deterministic.a2` as separate ISO-currency partitions by AI source, surface, and product id from safe line items; every revenue-bearing row includes `currency`. Compute AOV only within one currency and only when order count is nonzero. Never convert or sum unlike currencies. Do not claim a conversion rate because A2 has no session denominator.
     - Build explicit coverage: total latest orders, orders with referrer/UTM evidence, linked AI orders, unattributed orders, evidence coverage rate, attributed share, and source window/horizon.
     - Build `unattributed` count/revenue/share as separate currency partitions from latest orders without a current link.
     - Keep `a1` and `a2` sibling objects. Add per-currency `delta` rows with order/revenue differences only when comparable; never create a combined total or a cross-currency total.
     - Stamp exact `source_link_ids`, `source_order_fact_ids`, `source_metric_row_ids`, source snapshot ids, analyzer version, and formula version on every upsert.

   **Persisted APIs and DTOs**

   - Extend `backend/app/domain/attribution/schemas.py` with strict, explicit response models:
     - `AttributionMethodSummary`, `AttributionSourceRow`, `AttributionProductRow`, `AttributionCoverage`, `AttributionDelta`, `UnattributedSummary`, `AttributionStatisticalMetrics`, and `CommerceAttributionResponse`.
     - `source_granularity` describes only A1's GA4 source dimension. It is required and exactly `session_source_medium` or `default_channel_group` **on available A1 summaries**; it is **null** on A2 summaries and on any summary whose `state` is not `available` (the frontend schema makes it nullable — see the S2 contract note). Every revenue-bearing source/surface/product/unattributed/delta row requires a three-character ISO `currency`; denominator-derived metrics remain nullable.
     - `statistical.state` is `not_offered` and `allocations` is empty in this scope.
     - `AttributionOrderRow` exposes fact UUID, occurrence, safe line items, amount/currency, attribution state, method, AI source, confidence, and rule version. It does not expose `order_ref_hash` or source payload.
     - `AttributionOrdersPage(items, next_cursor)` uses a bounded keyset cursor built with the shared `encode_keyset_cursor` / `decode_keyset_cursor` helpers (`domain/traffic/service.py`) — the same "bind all filters, 400 on tamper" convention the traffic surface already uses (invariant 2 — reuse, don't reinvent).
   - In `backend/app/domain/attribution/service.py`:
     - `get_commerce_attribution(...) -> CommerceAttributionResponse` loads the exact/latest snapshot tuple and returns an empty contract when absent.
     - `get_attribution_orders(..., source: str | None, attribution_state: str | None, from_date, to_date, cursor) -> AttributionOrdersPage` pages latest facts joined to current-version links only. Cursor signatures bind all filters; tampered/replayed-different-filter cursors return 400.
   - In `backend/app/api/commerce.py`, add `GET /projects/{project_id}/commerce/attribution/orders`. Keep `require_active_workspace`, authorize the project before reads, map invalid windows/source/state to 422 and invalid cursors to 400.

   **Tests and affected existing tests**

   - Add `backend/tests/unit/test_attribution_link.py`: referrer priority, UTM fallback, unmatched order, exact/heuristic propagation, same-version idempotency, rule-version new row, latest-order-only selection, and no session join.
   - Complete `backend/tests/component/test_attribution_api.py`: A1-only, A2-only, both side by side, no summed total field, comparable and unavailable deltas, per-currency behavior, fallback label, explicit coverage, unattributed share, statistical `not_offered`, latest refund revision, safe order DTO, cursor filter binding, and cross-workspace 404.
   - Update `backend/tests/component/test_analytics_queue.py` for all declared task kinds and executor coverage; update `test_post_sync_chain.py`, `test_integration_ga4.py`, `test_integration_shopify.py`, `test_analytics_snapshot.py`, and `backend/tests/unit/test_analytics_config.py` for the new chain/counts.

5. **[after 4] Own the frontend-consumed catalog-health and attribution-recompute routes.**

   This task closes the B1 handoff gap: WS-C consumes `GET …/commerce/catalog-health`, `POST …/commerce/attribution/recompute`, and `GET …/commerce/attribution/recompute/{task_id}`, but no earlier task builds them. All routes use `require_active_workspace` (flat-route convention) and authorize the project within the resolved workspace via `get_project(..., workspace_id)`.

   **Catalog-health projection and route**

   - Add `backend/app/domain/commerce/schemas.py` and extend `backend/app/domain/commerce/service.py` (create if needed) with `get_catalog_health(session, *, workspace_id, project_id) -> CommerceCatalogHealth`. Read only persisted rows: the project's bound `IntegrationConnection`s (via `IntegrationPropertyMapping`), each connection's latest `IntegrationSyncRun` (status, window, row count, `error_code`, `completed_at`, `last_synced_at`), and per-product feed health derived from the latest `FeedIssue` rows + `Product.last_seen_sync_run_id`. Match products to health by `product_id`, never by mutable name.
   - Response DTO exactly matches the frontend `commerceCatalogHealthSchema`: `{ project_id, connections: [{ connection_id, provider: "shopify", label, account_ref, grant_status, last_synced_at, latest_sync: { sync_run_id, connection_id, status, window_start, window_end, row_count, error_code, completed_at } | null }], products: [{ product_id: UUID | null, connection_id, external_item_ref, sync_run_id, status: healthy | warning | error | unavailable, highest_severity: info | warning | error | null, issue_count, rule_ids: string[], last_seen_in_feed: bool }], generated_at: str | null }`. A synced product with no feed row reports `status=unavailable`; an unbound product is simply absent (the frontend renders `Not feed-bound`).
   - Add `GET /projects/{project_id}/commerce/catalog-health` to `backend/app/api/commerce.py`.

   **Attribution recompute enqueue + status**

   - The shared `enqueue_attribution_snapshot_refresh` dedupes on idempotency key `(task_kind, project_id, window_start, window_end, resync_seq)` and returns `None` when a matching task already exists. A manual recompute for an already-projected window at the current `resync_seq` therefore has no new task to return — resolve this explicitly. The existing `_next_resync_seq` path (`domain/integrations/sync.py`) is scoped `(connection_id, sync_kind, window)` over `IntegrationSyncRun` under a connection row lock — a manual recompute has no connection and writes no sync run, so that path does NOT apply. Specify the manual sequence precisely:
     - Add `enqueue_attribution_recompute(session, *, workspace_id, project_id, window_start, window_end, priority=0) -> UUID`.
     - **Sequence storage/scope:** the manual revision is scoped `(project_id, window_start, window_end)` and computed as `COALESCE(MAX(resync_seq), -1) + 1` over the project's persisted attribution-snapshot **tasks** (the `analytics_tasks` rows for `task_kind=attribution_snapshot` matching the project + window), NOT over `IntegrationSyncRun` and NOT over the snapshot row. Because automatic refreshes also persist their `resync_seq` on the same task rows, this MAX is taken over the union of automatic + manual revisions for the window, so a manual recompute can never collide with a future automatic refresh for the same window (the automatic refresh reads the latest persisted metric rows regardless of which task revision rebuilt the snapshot; the snapshot itself is a `ON CONFLICT (project_id, window, granularity) DO UPDATE` upsert, so later writes win).
     - **Concurrency:** allocate the sequence under the project's row lock (`SELECT ... FOR UPDATE` on the `projects` row) in the same transaction as the task insert, so two concurrent POSTs serialize and each gets a distinct sequence. If, despite serialization, the insert loses an idempotency race (returns `None` from the underlying enqueue helper), fall back to returning the **pre-existing** task's UUID rather than failing — the endpoint contract is "always returns a task UUID the client can poll."
     - Recompute means "rebuild the projection from the latest persisted metric rows/facts," never a provider re-call.
   - `POST /projects/{project_id}/commerce/attribution/recompute` accepts an optional `{ from, to }` window (default = latest synced window; the refresh upserts every configured granularity, so no per-granularity recompute is accepted), enqueues via the helper, and returns `{ task_id, project_id, status, error_code, updated_at, completed_at }` matching `attributionRecomputeSchema`.
   - `GET /projects/{project_id}/commerce/attribution/recompute/{task_id}` reads that analytics task's persisted status. `attributionTaskStatusSchema` is exactly `queued | leased | running | retry_wait | succeeded | failed | cancelled` (the queue status vocabulary). Authorize the task's `project_id`/`workspace_id` before returning; cross-workspace → 404. Do NOT add a generic cross-domain `/analytics-tasks/{task_id}` route.

   **Tests**

   - Add `backend/tests/component/test_commerce_catalog_health_api.py`: bound/unbound/absent product health, latest-sync selection, `error_code` on failed runs, cross-workspace 404, no provider call at read time.
   - Add recompute cases to `backend/tests/component/test_attribution_api.py`: POST enqueues one task and returns a task id even for an already-projected window (fresh manual `resync_seq`); GET returns the task status lifecycle; invalid window → 422; cross-workspace GET → 404.

### Testing

- Run focused backend tests from `backend/`:
  - `uv run pytest tests/unit/test_integrations_config.py tests/unit/test_integrations_oauth.py tests/unit/test_attribution_config.py tests/unit/test_attribution_snapshot.py tests/unit/test_feed_validators.py tests/unit/test_order_sanitize.py tests/unit/test_attribution_link.py -q`
  - `uv run pytest tests/component/test_integration_ga4.py tests/component/test_integration_shopify.py tests/component/test_catalog_sync_merge.py tests/component/test_order_resync_seq.py tests/component/test_attribution_api.py tests/component/test_analytics_queue.py tests/component/test_post_sync_chain.py -q`
  - Run the affected existing integration/analytics/traffic/product tests listed per task.
- Run `uv run ruff check .`.
- Recreate the greenfield test database from model metadata and run the repository’s schema/bootstrap check; do not add an Alembic revision.
- All connector/OAuth coverage uses injected `httpx.MockTransport`. No GA4, Shopify, OAuth, or LLM credential is required or used.

### Dependency rationale

- Task 1 is self-contained and must land first to satisfy the A1-before-Shopify requirement.
- Task 2 establishes the locked GraphQL-only OAuth/paging/artifact-safety path.
- Task 3 depends on sanitized Shopify artifacts and durable paging.
- Task 4 depends on immutable latest-revision `OrderFact` rows and extends the A1 snapshot rather than creating a second report path.
- Task 5 owns the frontend-consumed catalog-health and recompute routes; it depends on the Task 3 feed/provenance rows and the Task 4 attribution snapshot/task machinery.

### Open questions

None. Shopify Admin GraphQL `2026-07`, ISO-currency partitioning, and the persisted GA4 fallback/granularity contract are locked for this scope.


---

# WS-C — Frontend (Commerce workspace)

## Product specification

### Goals and success criteria

Grow `/products` into one Commerce workspace with three URL-addressable tabs: Catalog, Visibility, and Attribution. Keep the existing route and product drill-down, consume persisted projections only, and preserve null as unavailable (`—`) rather than coercing it to zero.

Success means:

- Catalog labels manual/imported/synced origin, shows feed health per SKU, and shows the bound Shopify connection’s current or latest sync state.
- Visibility adds win rate, v2 price direction, attribute frequency, buyer destinations, competitor co-placement, and engine × surface slicing.
- Mixed-version evidence never infers direction from v1 data; a v1 mismatch reads `Direction unavailable`.
- `/products/[productId]` displays product mentions, attribute mentions, and sanitized buyer destinations in the existing bounded evidence explorer.
- Attribution compares A1 and A2 without summing them, shows `A1 − A2`, unattributed orders/share, source and SKU metrics, and the GA4 fallback state.
- Navigation says Commerce while the href remains `/products`.

### Users and workflow

Commerce operators use Catalog to inspect catalog/feed state, Visibility to inspect AI answer evidence, and Attribution to compare platform-attributed and order-referrer revenue. Product names continue linking to the evidence drill-down. Date range, granularity, and recompute stay local to Attribution; run, engine, surface, and export stay local to Visibility.

### User-visible labels

- A1 method: `A1 · GA4 platform-attributed`
- A2 method: `A2 · Shopify order referrer`
- Delta: `Delta · A1 − A2`
- Statistical namespace badge/card title: `Statistical estimate`
- Reduced GA4 item fallback: `Reduced GA4 granularity · item revenue is grouped by default channel instead of AI source.`
- Insufficient statistical sample: `Insufficient data · no estimate is available for this window.` and metric value `—`
- Unattributed summary: `Unattributed · {orders} orders ({share}) have no referrer evidence.`
- v1 price mismatch: `Direction unavailable`
- Null metric: `—`

### Non-goals

No Opportunities tab, M2b/M2c controls, BigCommerce/GMC UI, checkout/feed write-back, or M5 Layer C lift panel. Do not add a shared Commerce-wide toolbar, new visual primitives, or new design tokens.

### Constraints and edge cases

- A1 and A2 are cross-checks. Never add their revenue, orders, AOV, or conversion values.
- Unattributed orders stay unattributed because no session join key exists.
- Attribution is partitioned by ISO currency. Never convert currencies, never sum unlike currencies, and render one complete block per currency; this repository has no FX-rate source.
- `insufficient_data` requires null estimate values.
- Unknown or absent `?tab=` still selects Catalog.
- Only the active tab’s queries run.
- Evidence remains newest-first with default limit 100 and backend maximum 500.
- A selected run with no product metrics keeps its run selector reachable.
- Surface and engine filters intersect; export receives both.
- Matrix and breakdown meaning cannot depend on color.
- Deliver all approved backend and frontend scope in one combined PR; do not split this frontend slice into a separate PR.

## Architecture decisions

- Keep local panel toolbars. Catalog has no analytical filters; Visibility and Attribution have unrelated filter state. The shared `visibility-toolbar.tsx` pattern is not useful here because hidden tabs do not share controls.
- Keep `lib/products/use-products-screen.ts` as the screen orchestration owner and move Catalog query ownership there so every tab has explicit `enabled` behavior.
- Keep product v2 contracts in `lib/api/products.ts`; add domain owners `lib/api/commerce.ts` and `lib/api/attribution.ts` as required by §11. `lib/api/index.ts` remains a transport-free compatibility facade.
- Reuse `Table`, `TablePagination`, `Badge`, `Donut`, `TrendChart`, cards, alerts, dropdowns, skeletons, and existing semantic token classes.
- Deterministic metrics use standard cards plus explicit A1/A2 method badges. `metrics.statistical.allocations`, when `state=available`, uses a separate warning-treated card titled `Statistical estimate`; it is excluded from deterministic totals, delta, and headline trends.

## Locked cross-workstream contracts

These frontend-driven backend additions land in the same combined PR and are owned by the corresponding backend workstream:

- Add `GET /projects/{project_id}/commerce/catalog-health`, `POST /projects/{project_id}/commerce/attribution/recompute`, and `GET /projects/{project_id}/commerce/attribution/recompute/{task_id}` in `backend/app/api/commerce.py`, with DTO/service support in `backend/app/domain/commerce/{schemas,service}.py` and `backend/app/domain/attribution/{schemas,service}.py`. Every route uses `require_active_workspace` (the flat header-resolved dependency used by `app/api/products.py`, NOT the path-scoped `require_workspace_member`), authorizes the project within that resolved workspace via `get_project(..., workspace_id)`, and returns cross-workspace 403/404 per invariant 5. Do not add a generic cross-domain `/analytics-tasks/{task_id}` route.
- Add `ProductVisibilityResponse.available_surfaces: list[str]` in `backend/app/domain/products/schemas.py` and populate it from persisted projection identities in `backend/app/domain/products/visibility.py`. Include `""` for measurement and persisted configured surface ids; the frontend does not read `Audit.configuration`.
- Replace open-ended M2a `buyer_destination_mix` and `competitor_co_placement` DTO dictionaries with the exact shapes below. Add stable `evidence_id` to every projected evidence item.
- Return AttributionSnapshot currency partitions under `metrics.deterministic.a1`, `metrics.deterministic.a2`, `metrics.deterministic.delta`, and `metrics.deterministic.unattributed`. Every revenue/AOV-bearing row carries its ISO currency. The backend never converts or aggregates unlike currencies.

## Contract inventory

All response objects below are `.strict()`. All `id`, `*_id`, and ID arrays use the local `uuid()` helper. Dates/timestamps remain strings, matching current API conventions. No token, customer name/email/address, merchant order number, raw order payload, or unsanitized URL is accepted.

### Existing product contract additions

Change `productSchema.origin` from an open string to `productOriginSchema` (`manual | imported | synced`) and add:

| Field | Shape | Nullability |
|---|---|---|
| `connection_id` | UUID | nullable; null for unbound manual/imported products |
| `external_item_ref` | string | nullable |
| `last_seen_sync_run_id` | UUID | nullable |

`productVisibilityEntrySchema` and `competitorProductVisibilityEntrySchema` each add:

| Field | Shape | Nullability |
|---|---|---|
| `product_analyzer_version` | string | required |
| `win_rate` | number | nullable |
| `price_mismatch_rate` | number | nullable |
| `price_relation_counts` | strict partial object `{ match: int, higher: int, lower: int, mismatch: int }` | required; `{}` is valid for v1 |
| `attribute_dimension_frequency` | record(group, record(dimension, non-negative int)) | required |
| `buyer_destination_mix` | `buyerDestinationMixSchema` | required |
| `competitor_co_placement` | `competitorCoPlacementSchema` | required |

Exact nested schemas:

- `buyerDestinationKindSchema`: `marketplace | retailer | brand_site | other`.
- `buyerDestinationMixSchema`: `{ total: non-negative int, by_kind: [{ merchant_kind, count }], by_domain: [{ merchant_domain: string, merchant_name: string, merchant_kind, count }] }`.
- `competitorCoPlacementSchema`: `{ items: [{ competitor_product_id: UUID | null, competitor_name: string, product_name: string, count: non-negative int }], truncated: boolean }`.
- `productVisibilitySchema` adds required `available_surfaces: string[]`. The measurement surface is represented by `""`; the UI labels it `Answer-engine APIs`. Do not offer `All surfaces`: the M2a route defines omission as the measurement slice, not an all-surface aggregate. This field is a frontend-driven backend addition owned by the M2a workstream.

`ProductEvidenceParams`, `getProductVisibility`, and `exportCsvUrl` add `surface?: string`; the products visibility query key normalizes `surface || 'measurement'` so omitted and explicit-empty measurement requests share one cache entry.

Generalize `productEvidenceItemSchema` with:

- Required common fields: `evidence_id: UUID`, `analysis_id: UUID`, `evidence_kind: product_mention | attribute_mention | buyer_destination`, existing audit/task/artifact/engine/prompt coordinates, `product_analyzer_version: string`, `shopping_surface: string`, `matched_name`, `matched_sku`, and `created_at`.
- Product-mention fields: `first_offset`, `rank_position`, `price_value`, `price_matches_catalog`, and `price_relation` are nullable; `price_text` and `price_currency` are strings.
- Attribute fields: `attribute_dimension`, `attribute_group`, `attribute_text`, and `attribute_offset` are nullable.
- Destination fields: `merchant_name`, `merchant_domain`, `merchant_kind`, and `destination_url` are nullable.
- Backend returns one stable UUID `evidence_id` per projected row: use `ProductMention.id` for `product_mention`, `MerchantMention.id` for `buyer_destination`, and derive JSONB-backed `attribute_mention` ids with UUIDv5 from the canonical tuple `(analysis_id, mention_id, dimension, offset)` under one fixed config-owned namespace. The same persisted evidence therefore produces the same id across reads without adding an attribute table. React keys use `evidence_id` and must never fall back to array index.

### Commerce health contract

Add these schemas and inferred types:

- `feedHealthStatusSchema`: `healthy | warning | error | unavailable`.
- `feedIssueSeveritySchema`: `info | warning | error`.
- `commerceSyncSummarySchema`: `{ sync_run_id: UUID, connection_id: UUID, status: integrationSyncRunStatusSchema, window_start: string, window_end: string, row_count: int, error_code: string, completed_at: string | null }`.
- `commerceConnectionSummarySchema`: `{ connection_id: UUID, provider: "shopify", label: string, account_ref: string, grant_status: integrationGrantStatusSchema, last_synced_at: string | null, latest_sync: commerceSyncSummarySchema | null }`.
- `productFeedHealthSchema`: `{ product_id: UUID | null, connection_id: UUID, external_item_ref: string, sync_run_id: UUID, status: feedHealthStatusSchema, highest_severity: feedIssueSeveritySchema | null, issue_count: non-negative int, rule_ids: string[], last_seen_in_feed: boolean }`.
- `commerceCatalogHealthSchema`: `{ project_id: UUID, connections: commerceConnectionSummarySchema[], products: productFeedHealthSchema[], generated_at: string | null }`; use an array because catalog rows can be bound to different connection IDs.

`commerceApi.getCatalogHealth(projectId, options?)` reads `GET /projects/{id}/commerce/catalog-health` and validates this schema. `commerceKeys.catalogHealth(projectId)` is `['commerce','catalog-health',projectId]`.

This route and DTO are a frontend-driven backend addition. The commerce backend workstream adds the project-scoped route and persisted projection using `require_active_workspace`; the frontend does not compose health by fetching unscoped task resources.

### Attribution contract

Reuse `snapshotGranularitySchema` (`day | week | month`) and the existing AI-source string vocabulary. Add:

- `attributionMethodSchema`: `ga4_platform_attributed | order_referrer`.
- `attributionDataStateSchema`: `available | no_data | not_connected`.
- `attributionSourceGranularitySchema`: `session_source_medium | default_channel_group` — mirrors the backend `ATTRIBUTION_SOURCE_GRANULARITY_*` vocabulary exactly. `default_channel_group` is the reduced GA4 item fallback. Do NOT define a separate `source_medium | channel_group | order_referrer` enum: granularity describes only A1's GA4 source dimension; A2's `order_referrer` identity is already carried by `attributionMethodSchema`, not by this field.
- `attributionMetricSetSchema`: `{ currency: three-character string | null, revenue: number | null, orders: int | null, average_order_value: number | null, sessions: int | null, conversion_rate: number | null }`; refine it so non-null revenue or AOV requires non-null currency.
- `attributionSourceRowSchema`: `{ ai_source: string, currency: three-character string, metrics: attributionMetricSetSchema }`.
- `attributionProductRowSchema`: `{ product_id: UUID | null, sku: string, name: string, ai_source: string | null, source_label: string, currency: three-character string, revenue: number | null, orders: int | null }`; `ai_source` is null and `source_label` carries the default-channel label when GA4 item granularity is reduced.
- `attributionMethodMetricsSchema`: `{ method, state, source_granularity: attributionSourceGranularitySchema | null, reduced_granularity: boolean, currency: three-character string | null, coverage_rate: number | null, totals: attributionMetricSetSchema, by_ai_source: attributionSourceRowSchema[], by_product: attributionProductRowSchema[] }`. `source_granularity` is non-null (`session_source_medium | default_channel_group`) on available A1 rows and **null** on A2 rows and on any row whose `state` is not `available` — the backend producer contract agrees (it is only meaningful for A1's GA4 source dimension). Refine: when `method=ga4_platform_attributed` and `state=available`, `source_granularity` must be non-null. `currency` is non-null on every `state=available` row (every available revenue-bearing row carries its ISO currency) and **null** on rows whose `state` is `no_data`/`not_connected` when no response ever yielded `metadata.currencyCode`; refine to require non-null `currency` when `state=available`, mirroring the `attributionMetricSetSchema` refine precedent. The backend emits null `currency` on unavailable rows when no currency is known. Each element is one method/currency partition. For every represented currency the backend returns one A1 and one A2 row; an unavailable method uses `no_data` or `not_connected` with null metrics rather than a fabricated zero.
- `attributionDeltaStateSchema`: `comparable | method_unavailable | currency_unavailable`.
- `attributionDeltaSchema`: `{ currency: three-character string, state: attributionDeltaStateSchema, revenue: number | null, orders: int | null, average_order_value: number | null, conversion_rate: number | null }`; values are backend-projected A1 minus A2 and may be negative. Non-`comparable` rows carry null metric values.
- `unattributedMetricsSchema`: `{ currency: three-character string, orders: int, order_share: number | null, revenue: number | null }`.
- `statisticalAllocationRowSchema`: `{ ai_source: string, currency: three-character string, estimated_revenue: number | null, estimated_orders: number | null, estimated_share: number | null }`.
- `attributionStatisticalSchema`: `{ state: not_offered | available | insufficient_data, sample_size: int | null, allocations: statisticalAllocationRowSchema[] }`; require empty allocations for `not_offered`, and require every estimate field to be null for `insufficient_data`.
- `attributionDeterministicSchema`: `{ a1: attributionMethodMetricsSchema[], a2: attributionMethodMetricsSchema[], delta: attributionDeltaSchema[], unattributed: unattributedMetricsSchema[] }`.
- `attributionMetricsSchema`: `{ deterministic: attributionDeterministicSchema, statistical: attributionStatisticalSchema }`.
- `attributionSnapshotSchema`: `{ project_id: UUID, window_start: string, window_end: string, granularity, metrics: attributionMetricsSchema, source_link_ids: UUID[], source_order_fact_ids: UUID[], source_metric_row_ids: UUID[], source_snapshot_ids: UUID[], formula_version: string, analyzer_version: string, created_at: string | null }`.

The UI builds the currency selector/order from the union of ISO codes in `metrics.deterministic.a1`, `a2`, `delta`, and `unattributed`, then renders one complete block per currency. It pairs A1/A2 only within the same code, never derives a cross-currency total, and never computes delta in the browser. Unavailable method rows render their backend `no_data`/`not_connected` state, not a zero value. GA4 channel-group fallback product rows retain `ai_source=null` and their persisted `source_label`.

Add recompute schemas:

- `attributionTaskStatusSchema`: `queued | leased | running | retry_wait | succeeded | failed | cancelled`.
- `attributionRecomputeSchema`: `{ task_id: UUID, project_id: UUID, status: attributionTaskStatusSchema, error_code: string, updated_at: string, completed_at: string | null }`.

`attributionApi.getSnapshot(projectId, { from?, to?, granularity? }, options?)` reads the §10.6 attribution route with `withQuery/definedQuery`. `recompute(projectId)` posts to `/projects/{id}/commerce/attribution/recompute`, and `getRecompute(projectId, taskId)` reads `/projects/{id}/commerce/attribution/recompute/{taskId}`. The two recompute routes are frontend-driven backend additions owned by the attribution backend workstream and use the same project/workspace authorization as the snapshot read.

`attributionKeys` contains:

- `all: ['attribution']`
- `snapshot(projectId, filters): ['attribution','snapshot',projectId,filters]`
- `recompute(projectId, taskId): ['attribution','recompute',projectId,taskId]`

## File structure map

### Frontend-driven backend additions

- `backend/app/api/commerce.py` — add project-scoped catalog-health and attribution recompute/status routes with `require_active_workspace`.
- `backend/app/domain/commerce/{schemas,service}.py` — add the persisted catalog-health projection and exact response DTO.
- `backend/app/domain/attribution/{schemas,service}.py` — add recompute enqueue/status DTOs and per-currency attribution response rows.
- `backend/app/domain/products/{schemas,visibility}.py` — add `available_surfaces`, exact destination/co-placement DTO shapes, and stable evidence ids.
- `backend/tests/component/test_attribution_api.py`, `backend/tests/component/test_product_visibility_api.py`, and the commerce-health API component test owned by the M4 backend slice — cover project/workspace authorization, exact DTOs, per-currency rows, surface metadata, deterministic UUIDv5 evidence identity, and no provider call on reads.

### Modified

- `frontend/lib/api/schemas.ts` — product v2, commerce health, attribution, and task schemas.
- `frontend/lib/api/products.ts` — surface query/export and generalized evidence contracts.
- `frontend/lib/api/types.ts` — inferred product/commerce/attribution types.
- `frontend/lib/api/query-keys/products.ts` — surface-aware visibility key.
- `frontend/lib/api/query-keys.ts` — Commerce and Attribution namespace re-exports.
- `frontend/lib/api/index.ts` — transport-free exports/spreads for new domain modules.
- `frontend/lib/products/catalog.ts` — three-tab model, labels, and null-safe commerce formatters.
- `frontend/lib/products/use-products-screen.ts` — active-tab query enablement, surface state, and attribution orchestration.
- `frontend/components/products/products-screen.tsx` — three-panel composition.
- `frontend/components/products/products-tabs.tsx` — three-tab comments/ARIA label while preserving keyboard behavior.
- `frontend/components/products/catalog-panel.tsx` — receives active Catalog queries and combines product/health rows.
- `frontend/components/products/catalog-table.tsx` — origin, feed-health, and sync-state cells.
- `frontend/components/products/product-visibility-panel.tsx` — surface control and v2 panels.
- `frontend/components/products/product-evidence-table.tsx` — evidence-kind rendering.
- `frontend/components/layout/nav-items.ts` — Products label to Commerce; href unchanged.

### New

- `frontend/lib/api/commerce.ts` — catalog-health transport owner.
- `frontend/lib/api/attribution.ts` — attribution snapshot/recompute transport owner.
- `frontend/lib/api/query-keys/commerce.ts` — catalog-health key namespace.
- `frontend/lib/api/query-keys/attribution.ts` — snapshot/task key namespace.
- `frontend/lib/products/attribution.ts` — range options, display-only method labels, metric formatting, and no-sum view projection.
- `frontend/components/products/surface-filter-dropdown.tsx` — measurement/configured surface selector.
- `frontend/components/products/attribute-frequency-panel.tsx` — grouped frequency table.
- `frontend/components/products/buyer-destination-breakdown.tsx` — donut plus complete text legend/table.
- `frontend/components/products/competitor-co-placement-matrix.tsx` — semantic matrix table.
- `frontend/components/products/attribution-panel.tsx` — Attribution toolbar, states, and composition.
- `frontend/components/products/attribution-method-comparison.tsx` — A1/A2/delta/unattributed cards.
- `frontend/components/products/attribution-source-table.tsx` — per-source deterministic metrics.
- `frontend/components/products/attribution-product-table.tsx` — paged per-SKU revenue.
- `frontend/components/products/statistical-allocation-card.tsx` — optional Layer B treatment only; no lift UI.

## Implementation tasks

### 1. Contract owners and strict schemas [parallel]

Update `frontend/lib/api/schemas.ts`, `frontend/lib/api/products.ts`, `frontend/lib/api/types.ts`, `frontend/lib/api/query-keys/products.ts`, `frontend/lib/api/query-keys.ts`, and `frontend/lib/api/index.ts`; add `frontend/lib/api/commerce.ts`, `frontend/lib/api/attribution.ts`, `frontend/lib/api/query-keys/commerce.ts`, and `frontend/lib/api/query-keys/attribution.ts`.

- Add the exact schema inventory above, all `.strict()`, and infer all exported response types from zod.
- Extend product visibility/evidence/export query parameters with `surface` and include it in cache keys and CSV URL generation.
- Add same-origin Commerce health and Attribution transports using `apiClient`, `strictValidate`, `withQuery`, and `definedQuery`; keep the facade transport-free.
- Coordinate the project-scoped catalog-health/recompute routes, `available_surfaces`, exact M2a nested DTOs, UUIDv5 attribute evidence ids, and per-currency attribution rows with the named backend owners in the same combined PR.
- Reject PII/secret drift through strict schemas. Do not add catch-and-ignore validation paths.
- Keep nullability exactly as specified so absent metrics remain unavailable.

Existing tests that break: `frontend/lib/api/products.test.ts`, `frontend/lib/api/schemas.test.ts`, `frontend/lib/products/products-lib.test.ts`, and every strict product fixture in component tests. Add `frontend/lib/api/commerce.test.ts` and `frontend/lib/api/attribution.test.ts` using global fetch stubs, matching existing `products.test.ts`.

Test expectations:

- Paths and optional query strings are exact; surface participates in visibility/evidence/export requests.
- Numeric IDs, extra token/PII keys, absent required metric namespaces, and wrong nullability fail loud.
- v1 `{}` relation counts parse; null rates remain null.
- Attribution parses per-currency A1, A2, delta, unattributed, reduced granularity, `not_offered`, and `insufficient_data` without constructing a combined or cross-currency metric.
- Generalized evidence parses stable UUID ids; attribute fixtures use the backend’s deterministic UUIDv5 output and UI tests key rows only by `evidence_id`.

### 2. Three-tab shell and query orchestration [after 1]

Update `frontend/lib/products/catalog.ts`, `frontend/lib/products/use-products-screen.ts`, `frontend/components/products/products-screen.tsx`, `frontend/components/products/products-tabs.tsx`, and `frontend/components/products/catalog-panel.tsx`; add `frontend/lib/products/attribution.ts`.

- Change `ProductsTab` to `catalog | visibility | attribution`; append Attribution to `PRODUCTS_TABS`; retain Catalog default for missing/invalid query values.
- **Nested sub-tabs (approved design — see `designs/design-plan.json`).** Visibility and Attribution each get a second-level segmented tablist rendered directly under their local toolbar, reusing the existing `components/ui/segmented.tsx` primitive (the same control `products-tabs.tsx` uses for the top-level tabs) — no new primitive. Only ONE nested panel renders at a time. Nested sub-tab state is local React state per parent tab (defaulting to the first sub-tab); it is NOT mirrored in the URL (only the top-level `?tab=` is). Define the sub-tab id vocabularies in `lib/products/catalog.ts` / `lib/products/attribution.ts`:
  - Visibility: `overview | attributes | destinations | co-placement` (default `overview`).
  - Attribution: `overview | by-source | by-product` (default `overview`).
- In `ProductsScreen`, instantiate Catalog, Visibility, and Attribution query hooks with `enabled` flags based on the active tab, then render only one panel.
- Move `useCatalogQueries` invocation out of `CatalogPanel` so `productsApi.list` and `commerceApi.getCatalogHealth` are disabled when Catalog is inactive.
- Extend `useProductVisibilityQueries` with `surface`; pass engine and surface to the request/key/export. Preserve selected-run fallback behavior.
- Add `useAttributionQueries` with range/granularity state, snapshot query, recompute mutation, and task query. Reuse the existing shared analytics range/granularity module `frontend/lib/analytics/options.ts` (`AnalyticsRange`, `RANGE_OPTIONS`, `rangeToWindow`, `AnalyticsGranularity`, `GRANULARITY_OPTIONS`) — the same framework-free options the `/analytics` and `/traffic` surfaces already use — rather than duplicating date math or the visibility trend's `run|week|month` vocabulary.
- Preserve one rendered `tabpanel` (top-level AND nested), roving tab index, automatic activation, focus transfer, arrow wraparound, Home/End, visible focus, and horizontal scrolling on both tablist levels.

Existing tests that break: `frontend/components/products/products-screen.test.tsx` and `frontend/lib/products/products-lib.test.ts`.

Test expectations:

- `?tab=attribution` renders Attribution; invalid values render Catalog.
- ArrowRight from Visibility reaches Attribution; End reaches Attribution; ArrowRight from Attribution wraps to Catalog.
- Exactly one top-level tab/panel is active and mounted.
- Only the active tab’s query functions are enabled; tab changes preserve URL sync.
- The Visibility and Attribution sub-tablists render under their toolbars; exactly one nested panel is mounted per parent tab; nested keyboard navigation (Arrow/Home/End, roving tabindex) works; nested selection is local state and does not change the URL.

### 3. Catalog health and navigation slice [after 2]

Update `frontend/components/products/catalog-panel.tsx`, `frontend/components/products/catalog-table.tsx`, and `frontend/components/layout/nav-items.ts`.

- Join `commerceCatalogHealth.products` to catalog rows by `product_id`; never match by mutable display name. A synced product with no health row displays `Feed health unavailable`; unbound products display `Not feed-bound`.
- Replace raw origin text with explicit neutral/status badges: `Manual`, `CSV import`, `Synced feed`.
- Add Feed health and Sync columns. Health badges include text (`Healthy`, `N warnings`, `N errors`, `Unavailable`) and may expose rule IDs in a tooltip. Sync renders the existing run-status badge vocabulary plus last-synced/completed timestamp; failed state includes non-secret `error_code`.
- For every connection whose `latest_sync` is active, use `useQueries` to poll its existing integration sync detail every 3,000 ms with `isActiveSyncRun`/`SYNC_RUN_POLL_MS`. Stop each query on terminal state, then invalidate `queryKeys.commerce.catalogHealth(projectId)`, `queryKeys.products.list(projectId)`, and the relevant integration namespace. Do not poll terminal rows.
- Change only the nav label from Products to Commerce; keep `/products` and product drill-down paths.

Existing tests that break: `frontend/components/products/catalog-table.test.tsx`, `frontend/components/layout/sidebar-nav.test.tsx`, `frontend/lib/api/products.test.ts`, and strict product fixtures in `frontend/lib/api/schemas.test.ts`.

Test expectations:

- Manual, imported, synced, healthy, warning/error, unavailable, and unbound rows have explicit text.
- Active sync polls at 3,000 ms; terminal status stops polling and invalidates product/health keys.
- Null connection/provenance does not crash or imply a feed error.
- Sidebar expects Commerce at href `/products`.

### 4. Visibility v2 and evidence slice [after 2]

Update `frontend/components/products/product-visibility-panel.tsx`, `frontend/components/products/product-evidence-table.tsx`, and `frontend/lib/products/catalog.ts`; add `frontend/components/products/surface-filter-dropdown.tsx`, `attribute-frequency-panel.tsx`, `buyer-destination-breakdown.tsx`, and `competitor-co-placement-matrix.tsx`.

- Add Surface beside Run and Engine. Label `""` as `Answer-engine APIs`; use backend-provided configured labels/ids verbatim. Keep export on the right and include both engine and surface. The Run/Engine/Surface/Export toolbar stays ABOVE the nested sub-tablist and slices all four sub-panels.
- Distribute the Visibility content across the nested sub-tabs (see Task 2); do NOT stack all panels vertically:
  - `overview` (default): summary cards + own Product rankings table + Competitor products table.
  - `attributes`: `AttributeFrequencyPanel` (full width).
  - `destinations`: `BuyerDestinationBreakdown` (donut + full merchant table).
  - `co-placement`: `CompetitorCoPlacementMatrix` (full width) + truncation notice.
- Add Win rate and Price relation columns to own and competitor tables (in the `overview` sub-tab). Render win-rate null as `—`. Render relation-count badges for `Match`, `Higher`, `Lower`; for an analyzer-v1 row with `mismatch > 0`, render `Direction unavailable`, never Higher/Lower.
- Aggregate the selected projection’s row-level `attribute_dimension_frequency`, `buyer_destination_mix`, and `competitor_co_placement` for display only by adding persisted counts; do not re-score evidence. Put pure projection helpers in `lib/products/catalog.ts` and preserve backend `truncated` if any row is truncated.
- `AttributeFrequencyPanel` uses a semantic table grouped by group/dimension and integer frequency.
- `BuyerDestinationBreakdown` uses `Donut` for kind shares and a visible domain legend/table with name, kind, count, and share. Its `aria-label` names every segment and percentage.
- `CompetitorCoPlacementMatrix` uses `Table` with explicit row and column headers and visible numeric cells; add a truncation notice when `truncated=true`. Color may reinforce values but never carry them alone.
- Generalize evidence rows by `evidence_kind`: product mention retains rank/price/relation; attribute mention displays dimension, group, exact text, and offset; buyer destination displays merchant, kind, sanitized URL, and optional price. Add surface to the evidence query key/request. Keep limit 100 and truncation notice.
- **Product drill-down (`/products/[productId]`) evidence sub-tabs.** Replace the single unified evidence table with a nested segmented tablist (same `segmented.tsx` primitive, local state defaulting to `mentions`, not in the URL): `mentions | attributes | destinations`. Only one evidence panel renders at a time. `mentions` keeps the existing columns (Engine, Prompt, Rank, Price mentioned, vs catalog, Offset, Execution link); `attributes` shows Engine, Prompt, Dimension, Group, exact matched Text, Offset; `destinations` shows Engine, Prompt, Merchant, Kind badge, sanitized destination URL, optional price. Each panel keeps the 100-row limit and truncation notice; nulls render `—`.

Existing tests that break: `frontend/components/products/product-visibility-panel.test.tsx`, `frontend/lib/products/products-lib.test.ts`, `frontend/lib/api/products.test.ts`, and `frontend/lib/api/schemas.test.ts`. Add `frontend/components/products/product-evidence-table.test.tsx`; add focused tests beside each new panel or cover them through `product-visibility-panel.test.tsx` if kept as pure children.

Test expectations:

- Surface and engine both participate in key/request/export.
- v1 mismatch reads `Direction unavailable`; v2 Higher/Lower render only from persisted counts.
- Null win/mismatch metrics render `—`, not `0`.
- Matrix has row/column header semantics and numeric accessible names.
- Donut legend and ARIA summary state segment names and percentages.
- Every evidence kind renders only its applicable fields; destination URL is already sanitized and opens safely; truncation remains visible.

### 5. Attribution vertical slice [after 2]

Add `frontend/components/products/attribution-panel.tsx`, `attribution-method-comparison.tsx`, `attribution-source-table.tsx`, `attribution-product-table.tsx`, and `statistical-allocation-card.tsx`.

- `AttributionPanel` owns a local Range dropdown, day/week/month segmented control, and Recompute button — all ABOVE the nested sub-tablist, slicing every sub-panel. Reuse the analytics/traffic toolbar empty/error/skeleton patterns and the shared `lib/analytics/options.ts` range/granularity options (see Task 2).
- Distribute the Attribution content across the nested sub-tabs (see Task 2); do NOT stack everything vertically:
  - `overview` (default): A1 and A2 method cards side by side (never merged), the Delta card, the Unattributed card, the reduced-granularity alert (when applicable), and — only when `metrics.statistical.state=available` — the `Statistical estimate` card with its warning treatment.
  - `by-source`: the per-`ai_source` deterministic table (full width).
  - `by-product`: the per-SKU product table + `TablePagination` (full width).
- For each ISO code discovered in `metrics.deterministic.*`, render A1 and A2 method cards side by side with the exact labels above. Each card shows revenue, orders, AOV, and conversion; null values use `—`. Method `state` drives no-data/not-connected copy.
- Render the backend delta in its own card labelled `Delta · A1 − A2`. Do not calculate or render `A1 + A2`; no helper, summary card, chart series, or table footer may combine methods.
- Show unattributed copy directly under A2 using persisted order count/share. A null share is `—`, not `0%`.
- Render `by_ai_source` (in `by-source`) as a deterministic table and `by_product` (in `by-product`) with `TablePagination`; preserve unresolved `product_id=null` rows as plain SKU/name rows. Do not use `TrendChart` in this scope because the exact DTO has no persisted time buckets; never synthesize a trend from totals. If the backend later adds nullable persisted buckets, use `TrendChart` so null remains a visible/announced gap.
- When A1 `reduced_granularity=true`, show the exact reduced-granularity alert. Item rows grouped by `item_default_channel_group` must not be relabelled as per-AI-source data.
- If `metrics.statistical.state=available`, render its allocations only in `StatisticalAllocationCard` with existing warning semantic classes and title `Statistical estimate`. For `state=insufficient_data`, render the exact insufficient-data copy and all estimates as `—`; for `state=not_offered`, render no statistical card. Never merge this namespace into deterministic cards, delta, or tables.
- Recompute posts once, stores the returned task id, and polls only that task every 3,000 ms while status is queued/leased/running/retry_wait. Terminal status stops polling and invalidates `queryKeys.attribution.snapshot(projectId, currentFilters)`; failed/cancelled remains explicit and retains the current snapshot.

Add `frontend/components/products/attribution-panel.test.tsx` with `renderWithProviders`, shared `mswServer`, and per-test handlers. Add pure formatter/projection tests in `frontend/lib/products/attribution.test.ts`.

Test expectations:

- A1/A2 labels and backend delta render; no A1+A2 value or combined total exists.
- Revenue, orders, AOV, conversion, source rows, SKU rows, and unattributed copy use persisted values.
- ISO currency blocks remain separate; fixtures with USD and EUR prove there is no cross-currency total, conversion, or delta.
- Reduced-granularity alert appears only for the fallback state.
- Null metrics and insufficient estimates render `—`; statistical values never appear in deterministic totals.
- Recompute polls at 3,000 ms, stops at terminal status, and invalidates only the relevant Attribution namespace/filter.

## Testing and final verification

No GA4, Shopify, OAuth, or LLM credentials are configured in this environment. Automated frontend verification uses only global `fetch` stubs for API-contract tests, following `frontend/lib/api/products.test.ts`, and per-test MSW handlers through `frontend/test/msw-server.ts` for component/query tests. Do not call live providers or execute a live audit/sync. Manual UI verification, if performed, uses seeded or fixture-backed persisted responses only.

Run from `frontend/`:

1. `pnpm test -- lib/api/products.test.ts lib/api/commerce.test.ts lib/api/attribution.test.ts lib/api/schemas.test.ts`
2. `pnpm test -- lib/products/products-lib.test.ts lib/products/attribution.test.ts components/products/products-screen.test.tsx components/products/catalog-table.test.tsx components/products/product-visibility-panel.test.tsx components/products/product-evidence-table.test.tsx components/products/attribution-panel.test.tsx components/layout/sidebar-nav.test.tsx`
3. `pnpm lint`
4. `pnpm check:policy`
5. `pnpm build`

Final integration verification:

- Open `/products`, `/products?tab=visibility`, `/products?tab=attribution`, and `/products/[productId]`; verify back/forward URL tab state and keyboard navigation.
- Verify narrow-width horizontal tab scrolling, table overflow, visible focus, and no color-only status/matrix/donut meaning.
- Verify one active tab produces only its own network requests.
- Verify no request bypasses same-origin `/api/v1`, no response schema accepts PII/secrets, and no frontend helper recomputes backend attribution/scoring.

## Acceptance mapping

- Catalog feed origin/health/sync: Tasks 1 and 3.
- Three tabs, URL state, active-query isolation, Commerce nav: Tasks 2 and 3.
- Visibility v2, mixed-version label, surface slicing, evidence kinds: Tasks 1, 2, and 4.
- A1/A2/delta/source/SKU/unattributed/reduced-granularity behavior: Tasks 1, 2, and 5.
- Deterministic/statistical separation and insufficient-data behavior: Tasks 1 and 5.
- Polling and accessibility: Tasks 2–5 plus final verification.
