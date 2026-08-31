# CiteLadder Onboarding Discovery v7 and GMI Cloud Cutover

> **Superseded in part.** The evidence-first onboarding research in this plan
> shipped and remains current. The GMI Cloud / MiniMax M3 application-model
> cutover was later reverted: the default agent and content generation both
> run on Mistral, and no GMI code path remains. A later runtime simplification
> also moved topic selection from discovery into asynchronous completion,
> required evidence references and explicit business-model classification for
> every competitor, reused the resolved homepage, and bounded identity evidence
> across first-party and external sources. Kept as a historical record; current
> behavior is documented in `docs/backend-architecture.md`.

**Status:** Implemented
**Branch:** `feat/onboarding-discovery-v7-gmi`
**Authority:** This plan replaces the ChatGPT implementation report. Runtime
code, tests, and current architecture documents remain authoritative once the
work ships.

## Reliability amendment (brand-discovery-v8)

> The GMI Cloud statements in this section are historical. They describe the
> amendment as written while the GMI cutover was still in place; see the
> supersession notice above for the current state.

Onboarding identity and competitor qualification now share a three-attempt
structured-response repair loop. Requests carry explicit allowed
evidence-reference IDs; a schema or deterministic reference rejection supplies
bounded contract feedback without response bodies or evidence text instead of
repeating the same prompt. Retryable provider failures honor `Retry-After` or
config-owned exponential backoff while non-retryable failures still degrade
immediately. The shared application gateway selects native strict JSON Schema
automatically for Mistral and prompt-carried JSON-object mode for hosts without
a verified guarantee — at the time of writing, GMI Cloud.
Identity and competitor prompt versions advance to v2; all original evidence
gates and persisted provider/model provenance remain unchanged.

## Outcome

Implement evidence-first onboarding research and make GMI Cloud MiniMax M3 the
active application model for onboarding, topic and prompt generation, Content,
Growth Agent, and Commerce. Measurement engines remain separate. Mistral stays
available as a dormant Content fallback.

The onboarding research pipeline becomes:

```text
bounded first-party evidence
  -> Keenable identity corroboration
  -> JSON-mode identity + competitive signature
  -> deterministic brand-neutral competitor searches
  -> retrieved candidate domains and evidence
  -> JSON-mode candidate qualification
  -> deterministic hard gates and existing domain verification
  -> persisted review projection and immutable research snapshot
```

There is no frontend redesign, Site Health change, database migration, new
queue, recursive crawler, embedding store, or autonomous research loop.

## Implementation

### Provider cutover

- Add host-bound `GMICLOUD_API_KEY` resolution to the default application-model
  gateway. Configure GMI with `GMICLOUD_BASE_URL` and `GMICLOUD_MODEL`, and use
  JSON-object mode for structured workflows.
- Add `gmi` to Content's provider configuration. Replace the Mistral-specific
  Content transport with one provider-neutral OpenAI-compatible transport that
  retains correct `gmi`/`mistral` provenance and the existing retry/attempt
  lifecycle.
- Keep Mistral selectable as a fallback. Do not change answer-engine
  measurement providers.
- Treat schemas as application contracts: include the schema in the prompt,
  validate every response with Pydantic, validate evidence/candidate references
  deterministically, retry within the existing bounded call budget, and degrade
  explicitly. Native strict JSON Schema is not assumed.

Capability verification on 2026-08-26 found that GMI Cloud documents
`response_format: {"type":"json_object"}` for chat completions, while MiniMax's
own text API documents native `json_schema` output only for `MiniMax-Text-01`,
not its M-series models. CiteLadder therefore rejects strict-schema mode for a
GMI endpoint and uses JSON-object mode plus prompt-carried schema, Pydantic
validation, reference checks, and bounded retry. Revisit only after GMI
documents and tests model-specific strict-schema support for MiniMax M3.

- [GMI Cloud LLM API reference](https://docs.gmicloud.ai/inference-engine/api-reference/llm-api-reference)
- [MiniMax text API reference](https://platform.minimax.io/docs/api-reference/text-post)

### Keenable connector and policy

- Add narrow authenticated `search` and `fetch` operations with typed parsing,
  provider-error classification, six-second timeouts, and secret-safe logging.
- Use canonical `KEENABLE_API_KEY` and `https://api.keenable.ai`; the key is sent
  only through `X-API-Key`.
- Config owns three identity searches, four identity fetches, four competitor
  searches, at most two reformulations, 24 candidate domains, ten candidate
  fetches, concurrency five, and a hard 24-operation budget.
- Keenable failure degrades valid onboarding and does not trigger repeated
  whole-discovery retries.

### Evidence-first onboarding

- Preserve the existing homepage plus at most four selected first-party pages.
- Split identity synthesis from competitor discovery. Identity returns the
  existing public `DiscoveryProfile`, an internal `CompetitiveSignature`, a
  ready/insufficient/conflicting status, and field evidence references. It does
  not return competitors.
- Construct four competitor searches from the signature; the first three are
  brand-neutral. Candidate domains must originate from retrieved URLs.
- Normalize registrable domains, remove the owned domain and configured noise,
  deduplicate, prefer official-looking results, and fetch bounded evidence for
  the strongest candidates.
- Qualification returns verdicts for input candidate IDs only. Direct admission
  requires the same core problem, same buyer, a credible substitute, and
  non-irrelevant geography. Delivery and positioning affect deterministic
  ranking but are not universal exclusions.
- Reuse existing `resolve_site()` validation, reference-host protections,
  service/product guard, concurrency, and deeper-pool-before-truncation. Return
  fewer than five when fewer than five defensible direct competitors exist.
- Keep offering harvest, topic selection, confirmation, initial portfolio
  creation, and manual competitor editing unchanged.

### Persistence and contracts

- Bump discovery/research/prompt versions for v7.
- Persist profile, signature, competitors, verdicts, topics, offerings, bounded
  evidence manifest, warnings, and per-phase provider/model/prompt provenance in
  the existing immutable `BrandResearchSnapshot`.
- Keep public onboarding DTOs and the database schema unchanged. New warning
  states are `external_research_unavailable`, `external_research_no_results`,
  `conflicting_evidence`, existing `research_degraded`, and
  `competitors_not_found`.
- Preserve workspace authorization, ready-discovery idempotency, queue leases,
  side-effect-free reads, and the zero-`SiteCrawl` completion contract.

## Verification

- Mock-transport tests cover GMI and retained Mistral configuration, payloads,
  provenance, errors, and secret redaction.
- Keenable unit tests cover request contracts, parsing, budgets, auth,
  rate-limit/server/timeout failures, and no secret/body leakage.
- Identity and competitor tests cover query construction, evidence budgets,
  conflict/insufficient states, candidate-universe enforcement, hard gates,
  deterministic ranking, and no weak padding.
- Component tests cover the successful two-call research path, every degraded
  provider path, immutable snapshot provenance, duplicate worker delivery,
  workspace isolation, unchanged queue behavior, and zero Site Health crawls.
- Add frozen obscure-brand evidence for TempPro, Lanhtropy, NOOE,
  Authenticity50, Atomicwork, Facets, Loop Health, Airtribe, Kalungi, and Kodo.
  Release gates are at least 9/10 defensible identities, Precision@5 at least
  0.80 where five direct peers exist, no non-retrieved domains, no broad-sector
  fallback over stronger niche evidence, and the Lanhtropy linen-womenswear
  regression.
- Complete with `./scripts/check.ps1`, `./scripts/test.ps1`, `git diff --check`,
  `git diff --stat`, and `git diff --name-status`.

## Configuration defaults

- `GMICLOUD_BASE_URL=https://api.gmi-serving.com/v1`
- `GMICLOUD_MODEL=MiniMaxAI/MiniMax-M3`
- `DEFAULT_AGENT_STRUCTURED_OUTPUT_MODE=prompt_json`
- `CONTENT_PROVIDER=gmi`
- Keenable limits are runtime bounds, not product entitlements.
