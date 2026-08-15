# Content Intelligence

> **Status:** shipped authority for bounded content generation.

Delivery sequencing and the Act → Improve / Verify product contract are owned by
[`citeladder-aeo-product-rebuild.md`](citeladder-aeo-product-rebuild.md).

Content owns one generation workflow. A user supplies an instruction and may
link an Opportunity. Before enqueue, `domain/content/grounding.py` freezes one
authorized, bounded envelope; the worker rebuilds provider messages only from
that immutable request material.

```text
confirmed BrandProfile facts + exact crawl-observed fragments
  -> frozen GroundingEnvelope
  -> queued ContentGeneration
  -> append-only provider attempts
  -> result, history, feedback, retry, or regeneration
```

## Grounding envelope

The v1 envelope records `status` (`included`, `unavailable`, or `conflicting`),
`version`, `allowed_facts`, `prohibited_claims`, `source_refs`, `omissions`, and
the selected/omitted/character budget. Every allowed fact has a stable fact ID,
field, value, claim class, review state, limitations, and source-reference IDs.
Every source reference records its source kind and exact persisted source ID,
field or bounded fragment, observed time, origin, review state, and applicable
extractor/content-hash provenance.

Only BrandProfile values whose review state is `confirmed` or `edited` become
allowed business facts. Crawl fragments are labelled `crawl_observed` and
`observed_untrusted`; they support terminology, tone, structure, or an explicit
“the current site says” attribution, never verified business truth. The v1
selector is deterministic and lexical; it adds no embeddings or vector store.

Numeric, pricing, policy, regulated, date, safety, and identity claims are
prohibited without an exact matching confirmed fact. Distinct confirmed values
for one claim class make the envelope `conflicting`; all facts in that class are
removed and the provider is instructed to omit the claim. An unavailable
envelope is still frozen and the UI labels the output an ungrounded draft.

`message_builder.build_messages()` accepts only `GroundingEnvelope`; the former
direct `WebsiteContext` adapter and wire contract are deleted.
`website_context.py` remains an internal bounded crawl-fragment selector used by
the grounding owner. Envelope validation rejects an allowed fact whose source ID
is absent. Provider output source markers use
`[[source:<source_ref_id>]]`; the worker rejects markers not present in the
frozen envelope.

Content does not own strategy snapshots, inventory copies, briefs, validation
state machines, revisions, publication claims, or later verification. No
autonomous publishing is permitted. Reads never acquire or repair evidence;
retries reuse the exact envelope, while regeneration freezes a new one.
