# Industry Pack Authority Pointer

The executable industry knowledge definitions no longer live in this planning directory.

The single canonical authority is:

- [`../../../backend/app/core/config/industry_packs/README.md`](../../../backend/app/core/config/industry_packs/README.md) — catalog layout, exact registry, maturity, loading, classification, sources, safety, and validation;
- [`../../../backend/app/core/config/industry_packs/registry.json`](../../../backend/app/core/config/industry_packs/registry.json) — exact active pack IDs, versions, files, aliases, maturity, and content hashes;
- [`../../../backend/app/core/config/industry_packs/schema/industry-pack.schema.json`](../../../backend/app/core/config/industry_packs/schema/industry-pack.schema.json) — normative pack schema;
- [`../../../backend/app/core/config/industry_packs/validate.py`](../../../backend/app/core/config/industry_packs/validate.py) — canonical offline validator;
- [`../codex-site-intelligence-wiring-handoff.md`](../codex-site-intelligence-wiring-handoff.md) — next production persistence and runtime-wiring slice.

This directory intentionally contains no YAML/JSON pack definitions, registry, schema copy,
validator, extension contract, or evaluation contract. Reintroducing those files would create a
competing authority and should fail repository hygiene validation.

From `backend/`, validate the canonical catalog with:

```bash
uv run python -m app.core.config.industry_packs.validate
```

The catalog library is implemented. Current Site Health still classifies and scores the generic
`page_type`; pack selection and persisted `industry_role` remain a separate gated implementation
slice.
