# Evaluation corpora

Evaluation corpora prove that CiteLadder acquires, understands, analyzes, generates, and verifies
without depending on live customer sites or model behavior in CI.

## Evidence versus labels

External tools can provide a technical baseline for facts they actually observe—URLs, media types,
status codes, redirects, metadata, headings, links, images, canonicals, directives, and structured
data. They are not semantic ground truth for industry role, entity identity, current/historical
state, answer quality, journey support, or business priority.

Each evaluation therefore separates:

1. source artifacts or sanitized derived fixtures;
2. external technical expectations;
3. reviewed semantic labels;
4. expected deterministic findings;
5. expected content briefs and validation;
6. expected before/after verification.

## Activation rule

An industry profile cannot move from `foundation` to `validated_candidate` until it has:

- representative labelled HTML and document fixtures;
- expected page kinds and industry roles;
- expected entities/assertions/relations, including unknown and conflict cases;
- expected questions, sections, schema/trust/journey gaps;
- at least one FAQ-first generation fixture with allowed and prohibited claims;
- a modified after-state that proves recrawl verification;
- deterministic replay with no live provider dependency.
