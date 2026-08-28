# AEO opportunity loop evaluation — 2026-08-28

## Scope and evidence

This sanitized development evaluation uses deterministic repository fixtures,
not a live provider run. The input corpus covers usable citation-bearing
answers, repeated citations across answers, duplicate citations within one
answer, failed answers, no-citation answers, unknown domains, competitor-owned
domains, and unavailable entity assessment. No customer text, provider secret,
or raw third-party response is included.

Versions: `grounded-analysis-v4`, `entity-assessment-1`, `opp-analyzer-7`,
`opp-rules-8`, `opp-formula-3`, `source-taxonomy-2`,
`opportunity-source-mix-1`, `opportunity-content-handoff-1`, and
`implementation-verifier-2`.

## Coverage and observed routing

The fixture projection deduplicates each canonical domain once per answer and
counts repeat use across eligible analyzed answers. It preserves Owned,
Competitive evidence, and Earned as observational source classes while routing
Competitive evidence to the Owned action path. Failed and citation-free
answers remain explicit in coverage and do not fabricate zero source usage.

## Representative top actions

1. Improve an Owned comparison page for the high-value decision prompt where a
   competitor was explicitly recommended.
2. Prepare one Earned editorial inclusion brief for the recurring independent
   domain, grouped across affected prompts rather than duplicated per prompt.
3. Improve an Owned content page for the persisted gap supported by competitive
   citation evidence.

Ordering is deterministic from severity, frozen buyer-stage/intent value,
visibility-gap strength, entity recommendation strength, source usage, and
competitor evidence. Exact factors and source IDs remain on the Opportunity.

## Abstentions and limitations

- Unknown third-party sources stay `other_third_party` and do not become an
  Earned task without a configured eligible class.
- Missing citations and failed analysis do not establish source absence.
- An unusable or ambiguous entity assessment is `unavailable`, never `absent`.
- Provider, model/retrieval, prompt-cohort, locale, or repetition mismatch makes
  the visibility verification leg `non_comparable`.
- Missing post-action analytics remains `not_run`; missing baseline evidence is
  `unavailable`; an observed numeric zero remains `observed_zero`.
- Later movement is descriptive. Overlapping implementation declarations are
  listed and no movement is attributed to CiteLadder.

Automated fixtures are the authority for positive and boundary behavior. A
live citation-bearing project read-through remains a release/demo operation
when approved provider access and sanitized project data are available.
