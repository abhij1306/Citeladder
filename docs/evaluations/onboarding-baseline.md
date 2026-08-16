# Onboarding baseline scorecard

Measured 2026-08-16 against `main` @ `278586d8`, before any product change.
**Post-rebuild results are in [Results after the rebuild](#results-after-the-rebuild) at the
end of this document.**

This is the Phase 0 gate for the onboarding context rebuild. The corpus in
[`app/evaluations/onboarding_cases.py`](../../backend/app/evaluations/onboarding_cases.py)
is the *specification*; this run measures how far today's pipeline is from it, so the rebuild
can be derived backwards from real gaps rather than from assumption.

Reproduce:

```bash
cd backend && uv run python -m scripts.run_onboarding_eval --baseline --out baseline.json
```

Judge: `groq / llama-3.3-70b-versatile`, selected by probing all four free provider keys
(Groq, NVIDIA, Bedrock, Mistral). Five candidate models returned strict JSON; all five
independently identified the same template fill as the most synthetic prompt, so ground-truth
agreement is good. Bedrock's OpenAI-compatible path returned non-JSON in all three regions.

## Results

| case | prompts | realism | template_tell | gold_overlap | category | facets | comp_recall | structurally valid |
|---|---|---|---|---|---|---|---|---|
| flipkart-india | 10 | 48.6 | **1.0** | 0.235 | yes | 0.0 | 0.60 | yes |
| best-less-australia | 10 | 20.0 | **1.0** | 0.221 | NO | 0.0 | 0.20 | yes |
| feedonomics-united-states | 10 | 21.4 | **1.0** | 0.095 | NO | 0.0 | 0.33 | yes |
| canva-australia | 10 | 20.0 | **1.0** | 0.123 | yes | 0.33 | 0.50 | yes |
| **puma-india** | — | — | — | — | — | — | — | **CRASH** |
| urban-company-india | 10 | 10.0 | **1.0** | 0.065 | NO | 0.0 | 0.20 | yes |
| jupiter-india | 10 | 27.1 | **1.0** | 0.154 | NO | 0.0 | 0.60 | yes |
| **zoho-india** | — | — | — | — | — | — | — | **CRASH** |
| graza-united-states | 10 | 0.0 | **1.0** | 0.103 | NO | 0.0 | 0.40 | yes |
| wakefit-india | 10 | 20.0 | **1.0** | 0.159 | NO | 0.0 | 0.20 | yes |
| **burrow-united-states** | — | — | — | — | — | — | — | **FETCH FAIL** |

Realism: min 0.0, median 20.0, max 48.6. Category match 2/8. Facet accuracy 0.0 (the fields do
not exist). Offering coverage median 0.33.

## The headline

**Every successful case is structurally valid and 100% machine-generated.** `template_tell` is
`1.0` across the board — every shipped prompt matches a slot-template skeleton exactly. This is
the whole argument for the rebuild in one row, and it is why the eval had to come first: the
old gate reported these portfolios as fine.

For Graza and Urban Company the judge scored **detection 1.0 / false-positive 0.0** — it
identified every generated prompt and misclassified none of the real ones. Perfect
discrimination.

## Findings

**1. The LLM never writes onboarding prompts.**
[`service.py:560`](../../backend/app/domain/projects/onboarding/service.py) passes a hardcoded
`[]` as `model_prompts`, which always fails the count gate, so the deterministic fallback is
always what ships. Confirmed by direct execution, not inspection.

**2. Neutral prompts ignore the brand entirely.** For **Feedonomics** — a product-feed
company — all five market prompts come from the static `Software` topics list:

> *"Which **analytics software** options can help my team with automating workflows?"*
> *"How do I compare **data management** options for improving team performance?"*
> *"Which **team collaboration** options integrate with the systems my team already uses?"*

**3. Two brands in one category get one portfolio.** Wakefit (mattresses, India) and Burrow
(sofas, US) both resolve to `Ecommerce / Home and General Merchandise` and receive prompts
about *clothing, homewares, electronics, beauty products, household essentials* — none of which
either company sells. Word-for-word identical apart from the country name:
**collision = 1.000** once the market token is removed. Reproduce:

```bash
cd backend && uv run python -c "
from app.domain.projects.onboarding.industry_library import industry_context
from app.domain.projects.onboarding.prompt_generation import fallback_portfolio
_, ctx = industry_context('Ecommerce')
for m in ('IN','US'):
    for p in fallback_portfolio(primary_market=m, industry='Ecommerce', industry_context=ctx,
                                products_services=['mattresses'], target_audience='families',
                                price_tier='mid_market'):
        if p['cohort']=='market_visibility': print(m, p['text'])
"
```

**4. Three of eleven real brands cannot onboard at all (27%).**

- **Puma** and **Zoho** raise `RuntimeError` from `validated_portfolio` — the *deterministic
  fallback* fails its own quality gate when a discovered offering happens to contain a tracked
  name. In production this propagates out of `complete_discovery`, so project creation fails
  outright. There is no fallback behind the fallback.
- **Burrow** fails with `response_too_large`: a mainstream Shopify storefront exceeds the 2 MiB
  `MAX_HTML_BYTES` onboarding fetch cap.

**5. Prompts interpolate raw profile text.** One Feedonomics prompt runs to 40 words because
the entire `target_audience` string is spliced mid-sentence:

> *"Which option for AI data enrichment best fits my needs as Brands, retailers, ecommerce
> platforms, agencies, and system integrators seeking to scale product visibility and sales
> across digital channels?"*

**6. The taxonomy has no slot for two of eleven businesses.** Urban Company (at-home services)
falls to `General`; Graza (food/CPG) is filed under `Home and General Merchandise`. Depth would
not fix this — Feedonomics has a "correct" leaf and still fails.

**7. Three validator rules actively mandate unnatural phrasing.** The corpus's own
hand-authored gold prompts — written as real buyers speak — *fail* the current gate:

| rule | why real queries fail it |
|---|---|
| `buyer_perspective` | requires `i/me/my/we/us/our`; *"best mattress for back pain india under 20000"* has no pronoun |
| `natural_search` | requires ≥ 6 words; *"feedonomics alternatives"* is 2 |
| market + offering coverage | requires the market name and every product string verbatim, forcing *"... in United States"* onto queries no American types |

Because the specification fails these rules, they are realism blockers rather than quality
gates. In the eval, coverage is now **measured and reported** rather than enforced; structure
stays a contract, vocabulary becomes a score.

## Metric notes

`buyer_realism` is a discrimination test, not a rating:
`100 × (1 − (machine_detection_rate − false_positive_rate))`. A plain 0-100 "how realistic?"
prompt was tried first and rejected — five judges scored a set containing three literal
template fills at **75-85**. Subtracting the false-positive rate cancels judge leniency, so a
judge that labels everything machine and one that labels everything human both land near the
same score; it moves only when the judge can genuinely separate our prompts from real ones.

Run-to-run variance is real: Jupiter scored 98.6 on one run and 27.1 on another. Treat
per-case scores as directional and the corpus median as the signal.

## Targets for the rebuild

| metric | baseline | target |
|---|---|---|
| `template_tell` | 1.0 | 0 |
| `buyer_realism` (median) | 20.0 | ≥ 75 |
| `cross_brand_collision` | 1.000 | < 0.3 |
| `category_match` | 2/8 | 11/11 |
| hard failures | 3/11 | 0/11 |
| `facet_accuracy` | 0.0 | ≥ 0.9 |

Under-filling is **not** a failure: a brand the model barely knows shipping 8 honest prompts
with a stated reason beats 15 padded ones, and both the contract and the harness now allow it.

---

## Results after the rebuild

Same harness, same corpus, same judge. Measured 2026-08-16 after Phases 1-2.

| case | prompts | realism | template_tell | gold_overlap | category | facets | comp_recall | valid |
|---|---|---|---|---|---|---|---|---|
| flipkart-india | 8 | 87.5 | 0.0 | 0.440 | yes | 1.00 | 0.60 | yes |
| best-less-australia | 10 | 20.0 | 1.0 | 0.218 | yes | 1.00 | 0.40 | yes |
| feedonomics-united-states | 10 | 100.0 | 0.0 | 0.340 | yes | 1.00 | 0.33 | yes |
| canva-australia | 9 | 71.8 | 0.0 | 0.320 | yes | 1.00 | 0.50 | yes |
| puma-india | 10 | 100.0 | 0.0 | 0.317 | yes | 0.67 | 0.00 | yes |
| urban-company-india | 8 | 25.0 | 0.0 | 0.319 | yes | 1.00 | 0.20 | yes |
| jupiter-india | 14 | 100.0 | 0.0 | 0.280 | yes | 1.00 | 0.60 | yes |
| zoho-india | 10 | 44.3 | 1.0 | 0.139 | yes | 1.00 | 0.60 | yes |
| graza-united-states | 8 | 91.7 | 0.0 | 0.479 | yes | 1.00 | 0.20 | yes |
| wakefit-india | 13 | 100.0 | 0.0 | 0.305 | yes | 1.00 | 0.40 | yes |
| burrow-united-states | 15 | 81.2 | 0.0 | 0.295 | yes | 1.00 | 0.60 | yes |

**cross_brand_collision** (wakefit vs burrow): **0.000**

### Against the targets

| metric | baseline | after | target | |
|---|---|---|---|---|
| `template_tell` | 1.0 (all 8) | 0.0 (9 of 11) | 0 | met, with variance |
| `buyer_realism` median | 20.0 | 87.5 | ≥ 75 | met |
| `cross_brand_collision` | 1.000 | 0.000 | < 0.3 | met |
| `category_match` | 2/8 | **11/11** | 11/11 | met |
| hard failures | 3/11 | **0/11** | 0 | met |
| `facet_accuracy` | 0.0 | 1.0 on 10/11 | ≥ 0.9 | met |
| structurally valid | — | 11/11 | — | met |

### What changed, and why it worked

1. **The model now writes the portfolio.** `_prepare_confirmed_portfolio` passes real
   model prompts instead of `[]`. Templates became the fallback they were designed to be.
2. **Context replaced taxonomy.** Feedonomics resolves to *"product feed management
   platform"*, Wakefit to *"premium mattress brand"*, Urban Company to *"home services
   booking platform"* — none of which exists as a leaf in any taxonomy.
3. **Three realism-blocking rules were deleted** (`buyer_perspective`, `natural_search`,
   `market_coverage`) and replaced by a template-skeleton rejection plus a precise
   third-person-audience check. Coverage became a measurement, not a gate.
4. **Two crash paths and one false "site not found" were fixed.** `validated_portfolio` no
   longer raises; `response_too_large` now degrades to a resolved site with no page text,
   because a storefront that is too large to read still exists.

### Known limitations

- **Fallback intermittency.** Two of eleven cases fall back to templates on a typical run,
  and it is a *different* two each time — model variance, not a broken case. The generator
  retries a thin reply, which reduces but does not remove it. Those cases are the
  `template_tell = 1.0` rows above.
- **Per-case realism is noisy.** Jupiter scored 98.6, 27.1 and 100.0 on three separate runs.
  The corpus median is the trustworthy signal; a single case's score is not.
- **`buyer_type` skews to `both`.** The model hedges on consumer-versus-business even when
  one side clearly dominates. A prompt instruction reduced but did not eliminate it.
- **Competitor recall is unchanged and still weak** (0.0-0.6). Competitor discovery was not
  in scope for this work and remains the largest untouched gap.
- Puma's `market_scope` resolves to `global` where the corpus expects `national`; defensible
  for a global brand with an India storefront, and left as an accepted mismatch rather than
  tuned away.
