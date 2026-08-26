# CiteLadder Onboarding Discovery v7 — Evidence-First Identity and Competitor Discovery

**Status:** Implementation proposal after static audit of `abhij1306/Citeladder` `main` on 2026-08-26
**Scope:** Brand/domain understanding and initial competitor suggestions during onboarding only
**Explicitly out of scope:** Site Health crawler and analysis, Commerce Suite catalog discovery, prompt/topic redesign, frontend redesign, frontier-model adoption

---

## 1. Executive decision

Replace the current single-pass onboarding research step with an evidence-first, search-backed pipeline:

```text
resolve site
  -> bounded first-party fetch (existing: homepage + <=4 useful pages)
  -> Keenable identity corroboration
  -> small structured model: business identity + competitive signature
  -> Keenable brand-neutral competitor discovery
  -> Keenable evidence fetch for candidate domains
  -> small structured model: candidate qualification/ranking
  -> existing current-domain verification
  -> existing topic selection
  -> existing onboarding review
```

The key change is **where facts and competitors come from**:

- Keenable retrieves factual evidence and candidate domains.
- The application model reconciles ambiguity and classifies bounded evidence.
- The model must not invent competitor names/domains from memory.
- Site Health remains completely unchanged.

This should be implemented without a new database table, new queue, vector DB, embeddings, recursive crawler, agent loop, or frontier model.

### Normal runtime target

A typical onboarding should use roughly:

- 3 Keenable identity searches
- up to 4 Keenable identity fetches
- 1 small-model identity call
- 4 Keenable competitor searches
- up to 10 Keenable candidate fetches
- 1 small-model candidate qualification call
- existing domain resolution for final survivors

Typical total: **15–21 Keenable operations and 2 small structured model calls**, with a hard configurable Keenable cap of 24 operations per discovery.

The authenticated Keenable API currently supports `POST /v1/search` and `GET /v1/fetch` with `X-API-Key`. Do not integrate the MCP/plugin interface into the backend.

---

## 2. Audit of the shipped implementation

### 2.1 Existing flow

The current onboarding research owner is:

`backend/app/domain/projects/onboarding/research.py`

Current `research_brand()` behavior is effectively:

```text
collect_brand_evidence()
  -> ONE structured research-model call
       -> DiscoveryProfile
       -> competitor suggestions
  -> verify model-generated competitor domains/scores
  -> harvest first-party offerings
  -> separate topic-selection pass
```

The topic split is correct and must remain. The remaining problem is that **business identity and competitor generation are still coupled inside the same model call**.

### 2.2 First-party evidence is already appropriately lightweight

`backend/app/domain/projects/brand_evidence.py` already does the right thing for onboarding:

- canonicalizes the website;
- fetches the homepage;
- selects at most four high-signal internal commercial/offering pages;
- uses the secure `connectors/web_evidence` acquisition boundary;
- has a bounded total timeout;
- caches and single-flights requests;
- degrades instead of failing onboarding for ordinary evidence-fetch failures.

**Keep this.** It is not a Site Health crawl and should not be replaced by Keenable.

Do not expand onboarding into sitemap/internal-link crawling.

### 2.3 Current competitor generation is model-memory-first

`ResearchEnvelope` currently contains both:

- `profile`
- `competitors`

`_model_research()` therefore asks the application model to establish the niche and nominate market participants at the same time. The later verification stage can reject bad candidates, but it cannot recover the best candidates that the model never nominated.

This is the main architectural precision limit.

### 2.4 Current verification is useful but not sufficient

The existing verifier is worth retaining for domain safety and reachability:

- excludes known reference/research hosts from domain adoption;
- rejects owned domain reuse;
- resolves candidate sites;
- verifies a deeper pool before truncating to the final cap;
- keeps deterministic domain normalization.

However, current semantic admission depends heavily on four model-generated floats:

- product substitutability
- customer/use-case overlap
- geographic relevance
- question visibility

and `_is_peer_company()` ultimately delegates to `same_business_class()`.

`same_business_class()` currently separates service-like businesses from non-service businesses. It deliberately treats combinations such as `b2b_saas`/`marketplace` and `d2c_product`/`retail` as the same broad class. This is a useful safety check against agency-vs-platform errors, but it is **not a niche classifier** and should not be expected to identify the best competitors.

### 2.5 Existing schemas are already rich enough

`backend/app/domain/projects/discovery_schemas.py` already carries:

- open-vocabulary `category`
- category aliases/terms/options
- products/services
- jobs-to-be-done
- target audience / buyer type
- business model and secondary models
- market scope
- buyer register / roles
- price tier
- confidence

Do not add a commerce-specific taxonomy or giant new industry tree. The missing concept can be an **internal competitive signature**, derived from these fields plus corroborating evidence.

### 2.6 Existing persistence can hold the new provenance

`backend/app/models/discovery.py` already has:

- one durable `BrandDiscoveryTask` queue row;
- JSONB `BrandDiscovery` projections;
- immutable `BrandResearchSnapshot` with `extracted_fields`, `evidence`, `warnings`, provider/model and method.

This is sufficient for v7.

**Do not add a migration/table.** Store the new competitive signature, Keenable evidence manifest, and candidate verdicts inside the existing immutable research snapshot JSON.

### 2.7 Existing completion contract already keeps Site Health separate

`backend/tests/component/test_brand_discovery_completion.py` explicitly verifies that completing onboarding does **not** start a Site Health crawl.

Preserve that contract.

### 2.8 Existing evaluation corpus is biased toward recognizable brands

`backend/evaluations/onboarding_*` and `backend/tests/unit/test_onboarding_golden_eval.py` contain useful regression cases, but many are established brands (Flipkart, Canva, Puma, Zoho, etc.). That is not sufficient for the failure mode being fixed here.

Add a frozen obscure-brand identity/competitor regression set rather than replacing the existing corpus.

---

## 3. Empirical basis for the change

A Keenable test was run across 10 lower/medium-recognition businesses, four commerce and six other sectors:

| Brand | Narrowest defensible identity found | Why it matters |
|---|---|---|
| TempPro | wireless/smart meat thermometers and temperature tools | recent rebrand/expansion can make model priors too broad or stale |
| Lanhtropy | contemporary women's natural-linen apparel | direct homepage extraction initially suggested leather goods; external official/independent evidence corrected it |
| NOOE | premium designer workspace accessories and stationery | homepage is design/ethos-heavy; external evidence clarifies the actual product category |
| Authenticity50 | American-made bedding/home textiles | qualifier such as Made-in-USA materially changes the competitive set |
| Atomicwork | AI-native/agentic IT service management and employee support | spans several adjacent software categories |
| Facets | infrastructure control plane/internal developer platform | hybrid platform + managed services creates category ambiguity |
| Loop Health | employer health benefits combining group insurance + preventive healthcare | one resolved niche search surfaced credible peers such as Plum/Nova/ekincare |
| Airtribe | live cohort-based professional tech/product upskilling | delivery format and audience matter more than broad `EdTech` |
| Kalungi | outsourced B2B SaaS marketing department/fractional CMO + execution | buyer receives a service/team, not software |
| Kodo | spend management/intake-to-pay/procurement workflow platform | product evolution makes remembered classifications risky |

The critical regression is **Lanhtropy**: one external identity search found the company's own About page and independent evidence that corrected a misleadingly broad/wrong first read. A bigger model is not the systematic fix; corroborating evidence is.

The second observed pattern is that once the niche is correctly resolved, competitor search becomes much easier. Broad/incorrect identity caused generic market-report results; specific identity produced useful peer sets.

---

## 4. Target architecture

### Phase A — Resolve site and collect first-party evidence

**Owner:** existing `brand_evidence.py`

No behavioral expansion. Continue reading the homepage plus at most four selected first-party pages.

Output should be converted into bounded evidence items with stable local refs such as:

```text
fp-1, fp-2, fp-3 ...
```

Keep page URL, title, role and bounded text. Do not send raw unbounded HTML to the model.

### Phase B — Keenable identity corroboration

Add a new provider-neutral backend connector, recommended path:

`backend/app/connectors/keenable.py`

It should expose two narrow operations:

```python
async def search(query: str, *, site: str | None = None, max_results: int, snippet_max_length: int) -> SearchResponse
async def fetch(url: str, *, live: bool, max_chars: int) -> FetchResponse
```

Do not expose arbitrary Keenable options to domain code. Config owns limits.

Run **three searches concurrently**:

1. **Official-site identity search**
   - `site=<owned domain>`
   - semantic query asking for About/company/products/services/customers/how the offering is delivered.

2. **Independent company identity search**
   - include brand name + domain in the natural-language query;
   - ask for independent descriptions of what the company sells, customer, business model and location/market.

3. **Market-context identity search**
   - ask for pages describing the company's category, positioning, use cases and alternatives.

Then select at most four high-value URLs for Keenable fetch:

- prefer official About/product/service pages not already captured first-party;
- then credible independent company/profile/context sources;
- exclude social/search/reference noise via the existing research-domain policy plus any new config-owned source rules.

Do not use Keenable's optional extraction prompt in production. Retrieve ordinary snippets/markdown and let CiteLadder's configured small model perform the only semantic synthesis. This keeps the model boundary inspectable.

For official pages where currentness matters, `live=true` is allowed. If live content is unusably thin and an indexed copy exists, fall back to the indexed version and preserve which mode produced the evidence.

### Phase C — Small-model identity synthesis

Split the existing research envelope.

Introduce internal models in the onboarding owner (or a focused sibling module):

```python
class CompetitiveSignature(BaseModel):
    category: str
    buyer: str
    core_job: str
    delivery_model: str
    market_context: str
    qualifiers: list[str]          # max 5
    adjacent_categories: list[str] # max 3
    search_terms: list[str]        # bounded

class IdentityResearchEnvelope(BaseModel):
    status: Literal["ready", "insufficient_evidence", "conflicting_evidence"]
    profile: DiscoveryProfile
    signature: CompetitiveSignature
    field_evidence_refs: dict[str, list[str]]
```

The model receives:

- first-party evidence refs/text;
- Keenable evidence refs/snippets/fetched markdown;
- user-supplied market/industry hints;
- existing allowed facet vocabularies.

The system instruction must require:

- use supplied evidence as the source of factual identity claims;
- conflicting evidence must be surfaced, not silently reconciled;
- output the narrowest buyer-facing category that is defensible;
- do not generate competitors;
- do not broaden to a sector when stronger niche evidence exists;
- do not let model prior override current evidence;
- `field_evidence_refs` may reference only supplied evidence IDs.

Deterministically validate all returned refs. Reject/retry an envelope that cites nonexistent evidence.

Keep the existing `DiscoveryProfile` public shape. Do not add commerce-only fields.

### Phase D — Build competitor queries deterministically

Do **not** call another model to write search queries.

Construct four parallel search queries from `CompetitiveSignature`:

1. primary category + buyer + core job + primary market, explicitly requesting providers/brands/companies and official sites;
2. delivery model + category + buyer;
3. category + strongest 1–2 qualifiers + market;
4. supplementary alternatives query using the brand name, but rank target-owned and publisher results below brand-neutral candidate results.

The first three queries should be brand-neutral. This prevents a company's own SEO comparison pages from dominating discovery.

Use up to 12–15 results per query initially. Merge and deduplicate by registrable domain.

If fewer than 8 viable candidate domains remain after deterministic filtering, allow up to two additional reformulations. This is a bounded fallback, not an agent loop.

### Phase E — Deterministic candidate-domain admission

A competitor candidate must originate from a Keenable result URL. **The model may not introduce a new competitor name/domain.**

Before any model call:

- normalize registrable domains;
- remove owned domains;
- remove duplicate domains;
- remove known social/reference/search hosts;
- down-rank obvious publisher/article URLs;
- prefer root/shallow official-looking results;
- cap the candidate pool (recommended 24).

Comparison articles may remain supporting evidence, but a company mentioned only inside a third-party snippet does not become a competitor until a Keenable search resolves that company to its own candidate domain.

This rule is important: retrieval produces the candidate universe; the model only judges it.

### Phase F — Fetch candidate evidence

Choose up to 10 strongest/most ambiguous candidate domains for evidence fetch, concurrently under a semaphore.

For each candidate retain:

- candidate ID (`cand-1`, etc.);
- domain;
- originating search result title/snippet/query ref;
- fetched official page title/content when available;
- acquired/published timestamp when available;
- fetch mode (`indexed`/`live`);
- evidence refs.

Do not deep-crawl candidate sites.

One homepage or one strong product/service/About page is sufficient for onboarding qualification.

### Phase G — Small-model competitor qualification

Use one structured call over the bounded candidate set.

Recommended internal contract:

```python
class CandidateVerdict(BaseModel):
    candidate_id: str
    decision: Literal["direct", "adjacent", "exclude"]
    same_core_problem: bool
    same_buyer: bool
    credible_substitute: bool
    geography: Literal["match", "partial", "irrelevant", "unknown"]
    delivery_overlap: Literal["match", "partial", "mismatch", "unknown"]
    positioning_overlap: Literal["high", "medium", "low", "unknown"]
    product_substitutability: float
    customer_use_case_overlap: float
    geographic_relevance: float
    question_visibility: float
    confidence: float
    evidence_refs: list[str]
    reasoning: str

class CompetitorQualificationEnvelope(BaseModel):
    verdicts: list[CandidateVerdict]
```

The existing four floats are retained for backward-compatible telemetry/output, **not as the primary admission gate**.

Hard direct-competitor admission requires:

```text
same_core_problem == true
same_buyer == true
credible_substitute == true
geography != irrelevant
```

`delivery_overlap` and `positioning_overlap` influence ranking but should not be universal hard gates; a different channel/delivery model can still compete for the same purchase decision.

Deterministic post-validation must ensure:

- every verdict references an input `candidate_id`;
- every evidence ref exists;
- no new candidate/domain/name appears in model output;
- `direct` cannot survive failed hard gates.

Then convert survivors back into the existing `DiscoveryCompetitorSuggestion` shape for the public onboarding response.

Persist the full internal verdicts in the immutable research snapshot.

### Phase H — Reuse existing current-domain verification

Refactor, do not delete, the existing `_verify_competitors()` / domain resolution logic.

Retain:

- owned-domain exclusion;
- reference-host protection;
- `resolve_site()` current-domain validation;
- verification concurrency;
- deeper pool then truncate behavior;
- `_is_peer_company()` as a coarse secondary safety guard.

Change the admission logic so `_verified_competitor()` no longer relies on `min(four_float_scores) >= floor` as the core semantic gate. Semantic admission already happened via the evidence-backed verdict.

### Phase I — Topic selection remains unchanged

After profile and competitors are settled, continue:

```text
harvest_offerings(first-party pages)
  -> select_topics(...)
```

Do not feed external competitor pages into the brand's offering harvest.

Do not redesign portfolio/prompt generation as part of this change.

---

## 5. File-level implementation plan

### 5.1 New connector

**Add:** `backend/app/connectors/keenable.py`

Responsibilities only:

- authenticated REST calls;
- request/response parsing;
- provider errors;
- no business/niche logic;
- no prompt generation;
- no persistence.

Authenticated API contract at implementation time:

```text
POST https://api.keenable.ai/v1/search
X-API-Key: <secret>
Content-Type: application/json

GET https://api.keenable.ai/v1/fetch
X-API-Key: <secret>
```

Search fields needed:

```text
query
site (optional)
max_results
snippet_max_length
```

Response evidence needed:

```text
title
url
description
snippet
published_at
acquired_at
```

Fetch fields needed:

```text
url
live
max
```

Do not add a dependency on Keenable MCP.

### 5.2 Configuration

**Modify:** `backend/app/core/config/brand_discovery.py`

Add config-owned settings (names may follow existing project conventions):

```text
KEENABLE_API_KEY                       secret, optional/degraded when absent
KEENABLE_BASE_URL                      default https://api.keenable.ai
identity_search_count                  default 3
identity_search_max_results            default 10
identity_fetch_max_pages               default 4
competitor_search_count                default 4
competitor_search_max_results          default 15
competitor_candidate_cap               default 24
competitor_fetch_max_pages             default 10
keenable_snippet_max_chars             default 1500
keenable_fetch_max_chars               default 6000
keenable_concurrency                    default 5
keenable_request_timeout_seconds        default 6
keenable_total_call_cap                 default 24
```

Treat these as initial bounded defaults, not product entitlements.

The authenticated Keenable service currently documents a 10 requests/second organization limit, so keep application concurrency below that (recommended 5) and let HTTP/provider errors degrade safely.

Add new version constants:

```text
BRAND_DISCOVERY_VERSION = "brand-discovery-v7"
BRAND_IDENTITY_PROMPT_VERSION = "brand-identity-v1"
BRAND_COMPETITOR_QUALIFICATION_VERSION = "brand-competitor-qualification-v1"
KEENABLE_RESEARCH_VERSION = "keenable-research-v1"
```

### 5.3 Research orchestration

**Refactor:** `backend/app/domain/projects/onboarding/research.py`

Prefer extracting focused siblings rather than making this already-large module larger:

Recommended:

```text
onboarding/identity_research.py
onboarding/competitor_research.py
onboarding/research_evidence.py
```

`research.py` should remain orchestration and result assembly.

Target shape:

```python
async def research_brand(...):
    first_party = await _site_evidence(site)

    external_identity = await research_identity_evidence(...)
    identity = await synthesize_identity(first_party, external_identity, ...)

    competitor_evidence = await discover_competitor_candidates(identity.signature, ...)
    qualified = await qualify_competitor_candidates(identity, competitor_evidence)
    verified = await verify_competitors(qualified, ...)

    harvest = harvest_offerings(first_party.pages, ...)
    topics = await select_topics(...)

    return ResearchResult(...)
```

### 5.4 Research prompt

**Modify:** `_discovery_research_system_prompt()` or split it into two prompt owners in `core/config/brand_discovery.py`.

The identity prompt must no longer contain a `COMPETITORS` section.

The competitor prompt must never be allowed to produce arbitrary company names. It receives candidate IDs and returns verdicts for those IDs only.

### 5.5 Schemas

**Prefer internal Pydantic schemas** for `CompetitiveSignature`, evidence items, and candidate verdicts.

Keep `DiscoveryProfile` and the public onboarding DTO stable unless a concrete UI need appears.

Keep `DiscoveryCompetitorSuggestion` stable. Convert the internal verdict into its existing:

- qualification floats;
- reasoning;
- confidence;
- evidence URLs;
- business model where confidently resolved.

Do not expose all internal evidence/verdict fields to the frontend in v7.

### 5.6 Persistence

**Modify:** `backend/app/domain/projects/onboarding/service.py`

Update snapshot method from the current `commercial_pages+structured_model` to a versioned method such as:

```text
first_party+keenable+structured_models
```

Persist into `BrandResearchSnapshot.extracted_fields`:

```json
{
  "profile": {},
  "competitive_signature": {},
  "competitors": [],
  "competitor_verdicts": [],
  "topics": [],
  "offerings": [],
  "model_calls": [
    {"phase": "identity", "provider": "...", "model": "...", "prompt_version": "..."},
    {"phase": "competitor_qualification", "provider": "...", "model": "...", "prompt_version": "..."}
  ]
}
```

Persist a bounded evidence manifest in the snapshot containing the first-party and Keenable source refs actually used.

No new DB column/table is needed.

### 5.7 Model transport

Current onboarding uses `create_model_gateway()` and benefits from its structured JSON-schema interface. Preserve that structured-output behavior in v7.

Do **not** switch onboarding blindly to `connectors/discovery_models`, because that package is currently wired to content settings and its Mistral client is a general text-generation client rather than the current onboarding JSON-schema seam.

Two acceptable implementation options:

1. **Minimal v7:** keep `create_model_gateway()` and configure the application's default compatible endpoint/model to the intended small model.
2. **Preferred isolation if the default agent may use a different model:** add an onboarding-specific configuration wrapper while reusing the same structured `ModelGateway` transport contract.

Do not duplicate the HTTP model client merely to get a separate env var.

The runtime requirement is a small/low-cost model with structured JSON support; no frontier model is required by the feature.

### 5.8 Frontend

No frontend redesign is required.

The current UI already allows:

- category correction;
- buyer/market confirmation;
- competitor selection/removal;
- manual competitor addition/domain edit.

Do not add new compulsory onboarding questions in v7.

A separate “regenerate competitors after manual category correction” interaction can be considered later; it is not necessary for the initial accuracy fix and would add a new user-triggered research lifecycle/API.

---

## 6. Failure/degradation contract

Onboarding reliability is more important than any one external provider.

Implement explicit states:

| Condition | Required behavior |
|---|---|
| valid site, first-party page fetch thin | continue using Keenable corroboration |
| Keenable not configured | continue first-party/model-only with `external_research_unavailable` warning |
| Keenable request failure/timeout | degrade; do not fail a valid onboarding |
| Keenable returns zero useful results | `external_research_no_results`, distinct from provider failure |
| external sources conflict with first-party evidence | identity status `conflicting_evidence`; prefer current official evidence where defensible, otherwise lower confidence |
| identity model unavailable | preserve current deterministic fallback profile behavior; no invented competitors |
| competitor search yields no candidates | return profile + no competitors + `competitors_not_found` |
| qualification model unavailable | do not promote unqualified retrieved candidates; return no competitors/degraded warning |
| candidate domain fails current `resolve_site()` | skip candidate and continue deeper pool |
| fewer than five valid competitors exist | return fewer than five; never pad with weak candidates |

Do not turn an external-research outage into repeated full queue retries unless the failure is explicitly classified as a required blocking dependency in the future.

---

## 7. Evidence/provenance requirements

The change must preserve CiteLadder's hard invariants:

1. External search/fetch evidence is observation, not automatically truth.
2. Every model judgement has provider/model/prompt version.
3. Model output must cite bounded supplied evidence refs.
4. A competitor can only come from the retrieved candidate universe.
5. Search result URL/domain normalization is deterministic code.
6. Unsupported/conflicting fields remain low-confidence/unknown rather than invented.
7. Read endpoints remain persisted projections and never call Keenable/model providers.
8. Keenable keys never enter logs, DTOs, snapshots or error text.

Do not rename historical `secure_crawler` capture-method values as part of this implementation. Although that name is imprecise for onboarding's bounded first-party fetch, changing persisted provenance vocabulary is unnecessary churn for v7. New external evidence can use new capture methods such as:

```text
external_search
external_fetch
```

with `provider="keenable"`.

---

## 8. Tests Codex must add/update

### 8.1 Connector unit tests

Add tests for `connectors/keenable.py` using `httpx.MockTransport`:

- API key is only in `X-API-Key`;
- correct search body and fetch query params;
- search response parsing;
- malformed response -> provider error/empty according to contract;
- 401/403 non-retryable auth classification;
- 429/5xx retryable classification where appropriate;
- timeout/connection errors;
- no response body or secret logged.

### 8.2 Identity-research unit tests

Test deterministic query construction and evidence selection:

- exactly three default identity queries;
- official query uses site restriction;
- duplicate URLs collapse;
- first-party pages are not fetched again unnecessarily;
- independent source selection excludes configured noise;
- evidence and text budgets are enforced;
- invalid model evidence refs reject the result;
- conflict state remains distinct from insufficient evidence.

### 8.3 Competitor-research unit tests

Add tests that prove:

- first three competitor queries do not include the brand name;
- candidate domains originate only from Keenable result URLs;
- owned domain is removed;
- duplicate/subdomain variants normalize correctly;
- reference/social/publisher noise is excluded/down-ranked;
- model cannot introduce `cand-999` or a new domain;
- `direct` fails if same core problem, same buyer, or credible substitute is false;
- geography `irrelevant` excludes;
- delivery mismatch alone does not universally exclude;
- fewer than five strong candidates returns fewer than five;
- no weak padding.

Update the existing research-helper tests so service-vs-product peer checks remain as a **secondary** guard rather than the primary semantic qualification mechanism.

### 8.4 Component tests

Extend `tests/component/test_brand_discovery_worker.py` / focused discovery component coverage with mocked Keenable + model boundaries:

1. first-party + Keenable + two model calls -> ready discovery;
2. Keenable unavailable -> ready but degraded, not failed;
3. Keenable zero results -> distinct warning;
4. qualification model failure -> profile persists, competitors empty;
5. evidence/verdicts are persisted in one `BrandResearchSnapshot`;
6. duplicate worker delivery does not rerun a ready discovery;
7. current queue lease/retry/finalization behavior remains unchanged;
8. completion still creates zero `SiteCrawl` rows.

### 8.5 Obscure-brand frozen evaluation set

Add a deterministic fixture set under `backend/evaluations/`, e.g.:

```text
onboarding_identity_competitor_cases.py
```

Do not make CI call live Keenable. Freeze bounded first-party + Keenable search/fetch evidence captured for the evaluation cases.

Minimum initial cases:

```text
TempPro
Lanhtropy
NOOE
Authenticity50
Atomicwork
Facets
Loop Health
Airtribe
Kalungi
Kodo
```

Required regression assertions should focus on defensible category identity and competitor precision, not exact prose.

Critical hard regression:

```text
Lanhtropy must not resolve to generic "leather goods" when the frozen evidence
contains its official About evidence identifying its natural-linen womenswear focus.
```

Other useful category expectations:

```text
TempPro       -> meat/wireless cooking thermometers (broader precision tools may be secondary)
NOOE          -> designer workspace accessories/stationery
Authenticity50-> American-made bedding/home textiles
Atomicwork    -> IT service management/employee-support platform
Facets        -> infrastructure control plane/internal developer platform
Loop Health   -> employer health benefits + group insurance/preventive care
Airtribe      -> live cohort professional tech/product upskilling
Kalungi       -> outsourced/fractional B2B SaaS marketing function
Kodo          -> spend management/intake-to-pay/procurement workflows
```

For competitor evaluation, use an **acceptable set** rather than one exact ordered list. A credible direct competitor outside a hand-written top five should not fail solely due to rank variance.

Suggested release gates (targets to validate, not claims about current measured performance):

- identity category correct/narrowly defensible on >= 9/10 frozen obscure cases;
- Competitor Precision@5 >= 0.80 across cases where >=5 direct competitors exist;
- zero competitor domains not present in retrieval evidence;
- zero broad-sector fallback when stronger niche evidence is present;
- Lanhtropy regression passes.

Keep the existing established-brand golden corpus too; v7 must not regress it.

---

## 9. Validation mapping and repository gates

Because this touches `backend/app/domain/projects/**` and `backend/app/core/config/**`, ensure `scripts/validation.json` maps any new connector/research files to the relevant onboarding tests. Do not evade the existing selector.

At implementation completion, from repository root run exactly the repository-owned gates:

```powershell
.\scripts\check.ps1
.\scripts\test.ps1
```

If a new config mapping is required, add it honestly to `scripts/validation.json`.

No migration should be required. If Codex nevertheless changes ORM schema, it must follow the repository's pre-launch single-baseline policy (`0001_initial.py`) and verify from an empty disposable DB with Alembic upgrade/check.

---

## 10. Implementation sequence

Implement in this order to keep the change reviewable:

### Slice 1 — Keenable connector + config

- add authenticated REST connector;
- add bounded settings/call budget;
- tests with mock transport;
- no onboarding behavior change yet.

### Slice 2 — Identity corroboration + identity-only model envelope

- preserve existing first-party fetch;
- add three Keenable searches and selected fetches;
- split competitors out of `ResearchEnvelope`;
- produce `CompetitiveSignature`;
- update snapshot provenance;
- add Lanhtropy-style regression fixture.

### Slice 3 — Search-backed competitor candidates

- deterministic brand-neutral query builder;
- retrieved-domain candidate pool;
- normalization/dedupe/exclusions;
- candidate evidence fetch.

### Slice 4 — Candidate qualification + existing domain verification

- structured `CandidateVerdict` call;
- hard semantic gates;
- deterministic ranking;
- convert to existing public competitor DTO;
- reuse current `resolve_site` verification.

### Slice 5 — Evaluation + documentation

- add obscure-brand frozen eval;
- run existing established-brand golden eval;
- update active backend/onboarding architecture documentation where the shipped research method changes;
- bump versions.

Do not combine this with unrelated onboarding UI, prompt-generation, Site Health, or Commerce Suite work.

---

## 11. Non-goals / explicit prohibitions

Codex must **not** do any of the following for this feature:

- modify or replace Site Health crawler/acquisition;
- start Site Health during onboarding;
- add sitemap or recursive crawling to onboarding;
- use Keenable as Site Health truth;
- add a vector database or embeddings;
- add an autonomous research agent/loop;
- add a commerce-specific business taxonomy;
- ask a frontier model to compensate for weak evidence;
- let the model invent competitor names/domains;
- create a new queue or Redis dependency;
- create a new database table without a demonstrated need;
- pad the competitor list to five;
- remove the user's ability to edit/add competitors;
- weaken existing provenance, workspace or queue contracts.

---

## 12. Definition of done

The implementation is complete when all of the following are true:

- [ ] Initial business identity uses first-party evidence plus bounded Keenable corroboration.
- [ ] The identity model no longer generates competitors.
- [ ] Competitor candidates originate from Keenable-retrieved domains only.
- [ ] The first three competitor searches are brand-neutral.
- [ ] Candidate evidence is fetched before final semantic qualification.
- [ ] The normal path uses two bounded small structured-model calls.
- [ ] No frontier model is required.
- [ ] Existing domain verification and reference-host protections remain.
- [ ] External-provider failures degrade a valid onboarding rather than fail it.
- [ ] One immutable `BrandResearchSnapshot` records profile, signature, evidence, verdicts and model versions.
- [ ] No Site Health code or lifecycle behavior changes.
- [ ] No new DB table/queue is introduced.
- [ ] Existing established-brand golden tests continue to pass.
- [ ] New 10-brand obscure regression set meets the agreed identity/competitor gates.
- [ ] `Lanhtropy` resolves to its evidence-backed linen-womenswear niche, not generic leather goods.
- [ ] `scripts/validation.json` covers new production files.
- [ ] `./scripts/check.ps1` and `./scripts/test.ps1` pass under the repository's Windows workflow.

---

## 13. Final architecture

```text
                     ONBOARDING ONLY

User domain
   |
   v
resolve_site()
   |
   +--> collect_brand_evidence() -----------------------+
   |    homepage + <=4 first-party pages               |
   |                                                    |
   +--> Keenable identity search x3 (parallel)          |
        + selected fetch <=4                            |
                                                        v
                                      Identity model (small, structured)
                                                        |
                                                        v
                                          DiscoveryProfile
                                          CompetitiveSignature
                                                        |
                                                        v
                                      deterministic search-query builder
                                                        |
                                                        v
                                  Keenable competitor search x4 (parallel)
                                                        |
                                                        v
                              normalize/dedupe/filter candidate domains
                                                        |
                                                        v
                                  Keenable candidate fetch <=10 (parallel)
                                                        |
                                                        v
                                 Qualification model (small, structured)
                                                        |
                                                        v
                                    deterministic hard gates + ranking
                                                        |
                                                        v
                                        existing resolve_site verification
                                                        |
                                                        v
                                             best <=5 competitors
                                                        |
                 +--------------------------------------+----------------+
                 |                                                       |
                 v                                                       v
      existing offering harvest                              immutable research snapshot
                 |
                 v
      existing topic selection
                 |
                 v
        existing user review

SITE HEALTH remains a completely separate crawler/source-of-truth pipeline.
```

This is the smallest architectural change that addresses the measured failure mode: **obscure companies need corroborated identity before competitor retrieval, and competitors should be retrieved from the web rather than generated from model memory.**
