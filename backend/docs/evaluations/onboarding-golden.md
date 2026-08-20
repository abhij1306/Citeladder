# Onboarding golden evaluation

This corpus is the repeatable acceptance check for the location-aware onboarding
research and prompt portfolio. It is intentionally isolated from production
onboarding: its known-brand competitor sets are a test oracle, never facts to
silently insert into a customer workspace.

The five cases are:

- Flipkart — India
- Best&Less — Australia
- Feedonomics — United States (chosen explicitly instead of a vague global market)
- Canva — Australia (chosen explicitly instead of a vague global market)
- Puma — India

For every case, validate candidate competitors with `evaluate_competitors` and
the proposed prompt set with `evaluate_portfolio` from
`evaluations.onboarding_golden`.

The deterministic gate requires exactly ten prompts: five neutral
`market_visibility` prompts and five unbranded `brand_relevant` prompts grounded
in verified offerings. It rejects duplicates, any tracked brand or competitor
name, absence of the selected market, and missing known product/service or
buyer-use-case coverage.

`evaluate_with_nvidia` is an optional qualitative pass. It reads `NVIDIA_API_KEY`
only at execution time and returns a skipped result when absent, so no test or
CI job performs an unrequested network call. It defaults to NVIDIA's
OpenAI-compatible chat-completions endpoint and
`meta/llama-3.1-8b-instruct`; callers can override only for evaluation
through `ONBOARDING_EVAL_NVIDIA_ENDPOINT` and `ONBOARDING_EVAL_NVIDIA_MODEL`.

Production onboarding uses the independently configured default agent. A live
three-run Best&Less contract check selected Mistral Small 4
(`mistral-small-2603`): all three responses parsed with exactly ten prompts and
five competitor candidates. NVIDIA Llama 3.1 8B passed one of three runs, Groq
GPT-OSS 20B passed one of three, and Bedrock Nova Micro passed two of three but
produced weak competitor matches.

Run the offline gate from `backend/`:

```powershell
uv run pytest tests/unit/test_onboarding_golden_eval.py -q
```

The implementation milestone will run this corpus against real onboarding
outputs, then record the deterministic and optional NVIDIA-review results.

## 2026-08-04 implementation result

The production fallback generator and production portfolio evaluator passed all
five market-specific cases: Flipkart India, Best&Less Australia, Feedonomics
United States, Canva Australia, and Puma India (5/5; exact 5 market + 5
brand-relevant prompts, all unbranded, with required market/product/use-case coverage). The application
model remains an optional enhancement: provider errors or malformed structured
output take the same validated fallback path instead of blocking onboarding.

The onboarding resolver also reached the supplied local test corpus without a
scraping vendor: Books to Scrape, Web Scraping Dev, Puma India, and Practice
Software Testing all resolved; content-poor pages degraded to review warnings.
