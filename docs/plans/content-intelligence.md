# Content Intelligence

> **Status:** active owner and plan for content strategy, generation, review,
> and verification.

## Ownership

Content Intelligence owns:

- content inventory and strategy snapshots;
- immutable briefs and bounded context packages;
- provider-neutral generation attempts;
- automatic validation and revision revalidation;
- explicit save/discard and publication-claim transitions;
- later site/demand verification.

It extends the existing content queue and result models. It does not add a
parallel generator, fact store, review inbox, or autonomous publisher.

Site Health supplies persisted page inventory, page kinds, rule evidence, and a
source snapshot identity. Demand Intelligence supplies optional observed query,
journey, behavior, and visibility evidence.

## Current flow

```text
Site Health snapshot + optional Demand snapshot
  -> ContentStrategySnapshot
  -> ContentBrief
  -> TaskContextPackage
  -> ContentGenerationAttempt
  -> ContentValidation
  -> user revision + revalidation
  -> save/discard or publication claim
  -> later ContentVerification
```

Every row is workspace/project scoped and carries exact source IDs plus the
relevant strategy, brief, context, skill, validator, provider, and model
versions.

## Grounding boundary

The former Site Intelligence knowledge assertions were deleted during Site
Health simplification. The current `_brief_evidence` adapter therefore returns
explicit empty `allowed_facts`, `prohibited_claims`, and `source_refs`.

That state is truthful but not evidence grounding. Do not weaken validators or
invent facts from page summaries to hide it. The next product slice must choose
one bounded replacement source, define its provenance and conflict behavior,
and add acceptance fixtures before factual generation can be described as
grounded.

## Generation and validation

- Provider adapters receive only the frozen context package.
- Attempts are append-only; retries create new attempts.
- Model output cannot change Site Health or Demand metrics.
- Citations must resolve to a source included in the context package.
- Blocking unsupported or regulated claims prevent save at the API and UI.
- Generated FAQ schema is derived from the reviewed visible FAQ, never the
  other way around.

## User decisions

The user may generate, edit, save, discard, and claim publication. No external
CMS publication happens autonomously. A publication claim is an observation to
verify later, not proof that the content is live or correct.

## Verification

A later compatible Site Health snapshot may show whether required visible
elements and rule outcomes changed. Optional aligned Demand evidence may show
later movement. Verification remains descriptive unless the product has a
separate causal design; generated content never marks itself successful.

## Next gated slice

Choose the replacement grounding source. Acceptance requires:

1. immutable source references with workspace authorization;
2. explicit allowed/prohibited claim derivation;
3. conflict, unavailable, stale, and historical states;
4. bounded context selection and omission reporting;
5. deterministic fixtures proving unsupported claims are blocked;
6. no new generic knowledge store unless existing owners are proven
   insufficient.
