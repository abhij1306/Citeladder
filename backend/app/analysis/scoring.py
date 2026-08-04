"""Deterministic mention/citation/domain/fanout scoring.

No LLM is used for headline metrics (invariant 9). Matching is alias-based and
transparent so every classification in the UI/exports is explainable.

Ported from the reference ``ai_visibility/scoring.py`` (B6, logic unchanged);
only the config imports are repointed at ``app.core.config.analysis`` and the
brand-identity dict shim (``project_scoring_identity``). Sentiment + average
position are deliberately NOT computed here (decision B-2, invariant 9 note) —
they need an LLM/context, so they are exposed as nullable/absent downstream.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.analysis.normalization import (
    alias_present,
    domain_matches,
    first_alias_offset,
    normalize_alias,
    normalize_domain,
)
from app.core.config.analysis import (
    AMBIGUOUS_ALIASES,
    FANOUT_FEATURE_RULES,
    PROMPT_SCORE_COMPETITIVE_WEIGHT,
    PROMPT_SCORE_OWNED_CITATION_WEIGHT,
    PROMPT_SCORE_VISIBILITY_WEIGHT,
)
from app.core.config.costs import (
    APPROVED_ROUTE_IDENTITIES,
    MICRO_USD_PER_USD,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
    PROJECTION_STATUS_PARTIAL,
    PROJECTION_STATUS_UNKNOWN,
    TOKENS_PER_MILLION,
    route_pricing_for,
)


@dataclass(frozen=True)
class CompetitorConfig:
    name: str
    aliases: tuple[str, ...]
    domains: tuple[str, ...]


def _competitor_configs(config: dict[str, Any]) -> tuple[CompetitorConfig, ...]:
    return tuple(
        CompetitorConfig(
            name=str(item.get("name") or ""),
            aliases=tuple(
                str(alias)
                for alias in ([item.get("name"), *(item.get("aliases") or [])])
                if alias
            ),
            domains=tuple(
                str(domain) for domain in (item.get("domains") or []) if domain
            ),
        )
        for item in (config.get("competitors") or [])
    )


@dataclass(frozen=True)
class ScoringConfig:
    brand_name: str
    brand_aliases: tuple[str, ...]
    owned_domains: tuple[str, ...]
    unintended_domains: tuple[str, ...]
    country_code: str = ""
    language_code: str = ""
    benchmark_mode: str = ""
    provider: str = ""
    model: str = ""
    products_services: tuple[str, ...] = field(default_factory=tuple)
    competitors: tuple[CompetitorConfig, ...] = field(default_factory=tuple)

    @classmethod
    def from_project(cls, config: dict[str, Any]) -> ScoringConfig:
        brand_name = _config_text(config, "brand_name")
        aliases = [brand_name, *(config.get("brand_aliases") or [])]
        return cls(
            brand_name=brand_name,
            brand_aliases=tuple(alias for alias in aliases if alias),
            owned_domains=tuple(config.get("owned_domains") or []),
            unintended_domains=tuple(config.get("unintended_domains") or []),
            country_code=_config_text(config, "country_code"),
            language_code=_config_text(config, "language_code"),
            benchmark_mode=_config_text(config, "benchmark_mode"),
            provider=_config_text(config, "provider"),
            model=_config_text(config, "model"),
            products_services=tuple(config.get("products_services") or []),
            competitors=_competitor_configs(config),
        )


def _config_text(config: dict[str, Any], key: str) -> str:
    return str(config.get(key) or "")


def classify_fanout(query: str) -> list[str]:
    normalized = str(query or "").lower()
    features: list[str] = []
    for feature, needles in FANOUT_FEATURE_RULES.items():
        for needle in needles:
            # Multi-word needles are substring-matched; single tokens use word
            # boundaries via surrounding spaces on a padded haystack.
            if " " in needle:
                if needle in normalized:
                    features.append(feature)
                    break
            elif f" {needle} " in f" {normalized} ":
                features.append(feature)
                break
    return features


def _entity_alias_present(
    aliases: tuple[str, ...], text: str, normalized_haystack: str
) -> bool:
    for alias in aliases:
        normalized_alias = normalize_alias(alias)
        if normalized_alias not in AMBIGUOUS_ALIASES:
            if alias_present(normalized_alias, normalized_haystack):
                return True
            continue
        if re.search(rf"\b{re.escape(alias)}\s+Australia\b", text, re.IGNORECASE):
            return True
        # A retailer-style proper noun is accepted, except common semantic uses.
        if re.search(
            rf"\b{re.escape(alias)}\b(?!\s+(?:audience|price|market|demographic))",
            text,
        ):
            return True
    return False


def _first_offset(aliases: tuple[str, ...], normalized_haystack: str) -> int | None:
    offsets = [
        offset
        for alias in aliases
        if (offset := first_alias_offset(normalize_alias(alias), normalized_haystack))
        is not None
    ]
    return min(offsets) if offsets else None


# Google grounding-redirect identity. The citation ``url``/``redirect_url`` on a
# grounded Gemini answer points at Google's redirector, not the publisher, so its
# hostname must never be taken as the citation domain.
_GOOGLE_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
_GROUNDING_REDIRECT_MARKER = "grounding-api-redirect"


def _domain_in(domain: str, targets: tuple[str, ...]) -> bool:
    return any(domain_matches(domain, target) for target in targets)


def _url_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return normalize_domain(urlparse(raw).hostname or "")
    except ValueError:
        return ""


def _is_google_redirect(value: Any) -> bool:
    """True when the URL is a Google grounding redirect, not a publisher URL.

    Matched on the PARSED host and path, never as a substring of the whole URL:
    a genuine publisher URL that merely carries one of these markers in its
    query string (``https://pub.example/a?ref=grounding-api-redirect``, or a
    tracking param echoing the redirect host) must keep its own hostname as the
    citation domain instead of being discarded as a redirect. The real shape is
    ``https://vertexaisearch.cloud.google.com/grounding-api-redirect/<token>``;
    some payloads carry the marker as a bare host.
    """
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parts = urlparse(raw)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if host == _GOOGLE_REDIRECT_HOST or host.endswith(f".{_GOOGLE_REDIRECT_HOST}"):
        return True
    if host == _GROUNDING_REDIRECT_MARKER:
        return True
    return _GROUNDING_REDIRECT_MARKER in parts.path.lower()


def citation_domain(citation: dict[str, Any]) -> str:
    """Resolve publisher identity using strongest available URL evidence."""
    resolved = _url_domain(citation.get("resolved_url"))
    if resolved:
        return resolved
    annotation_url = citation.get("redirect_url") or citation.get("url")
    direct = _url_domain(annotation_url)
    if direct and not _is_google_redirect(annotation_url):
        return direct
    return normalize_domain(citation.get("domain") or citation.get("title"))


def classify_citation(
    citation: dict[str, Any], config: ScoringConfig
) -> dict[str, Any]:
    """Annotate a raw citation dict with ownership/competitor classification."""
    domain = citation_domain(citation)
    matched_competitor = None
    for competitor in config.competitors:
        if _domain_in(domain, competitor.domains):
            matched_competitor = competitor.name
            break
    return {
        **citation,
        "domain": domain,
        "is_owned": _domain_in(domain, config.owned_domains),
        "is_unintended": _domain_in(domain, config.unintended_domains),
        "matched_competitor": matched_competitor,
    }


def score_execution(
    *,
    answer_text: str,
    search_events: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    search_used: bool,
    config: ScoringConfig,
    prompt_text: str = "",
    query_text_available: bool = True,
) -> dict[str, Any]:
    """Per-execution deterministic score."""
    normalized_answer = normalize_alias(answer_text)
    brand_mentioned = _entity_alias_present(
        config.brand_aliases, answer_text, normalized_answer
    )
    query_text = " ".join(str(event.get("query") or "") for event in search_events)
    prompt = _prompt_signals(config, prompt_text, query_text, query_text_available)
    competitors = _competitor_signals(
        config,
        answer_text,
        normalized_answer,
        query_text,
        normalize_alias(query_text),
        prompt["prompt_competitors"],
        query_text_available,
    )
    citation = _citation_signals(
        citations,
        config,
    )
    return {
        "search_used": bool(search_used),
        "search_query_count": len(search_events),
        "search_query_text_available": query_text_available,
        "brand_mentioned": brand_mentioned,
        "brand_first_offset": _first_offset(config.brand_aliases, normalized_answer),
        **prompt,
        **citation,
        **competitors,
        "fanout_features": _fanout_features(search_events),
    }


def _prompt_signals(config, prompt_text, query_text, query_text_available):
    normalized_prompt = normalize_alias(prompt_text)
    prompt_contains_brand = _entity_alias_present(
        config.brand_aliases, prompt_text, normalized_prompt
    )
    prompt_competitors = [
        competitor.name
        for competitor in config.competitors
        if _entity_alias_present(competitor.aliases, prompt_text, normalized_prompt)
    ]
    return {
        "brand_injected_in_search": _brand_injected(
            config, query_text, prompt_contains_brand, query_text_available
        ),
        "prompt_contains_brand": prompt_contains_brand,
        "prompt_contains_competitor": bool(prompt_competitors),
        "prompt_competitors": prompt_competitors,
        "prompt_class": _prompt_class(prompt_contains_brand, prompt_competitors),
    }


def _brand_injected(config, query_text, prompt_contains_brand, available):
    if not available:
        return None
    return not prompt_contains_brand and _entity_alias_present(
        config.brand_aliases, query_text, normalize_alias(query_text)
    )


def _prompt_class(prompt_contains_brand, prompt_competitors):
    if prompt_contains_brand and prompt_competitors:
        return "comparison_branded"
    if prompt_contains_brand:
        return "branded"
    if prompt_competitors:
        return "mixed"
    return "non_branded"


def _competitor_signals(
    config,
    answer_text,
    normalized_answer,
    query_text,
    query_blob,
    prompt_competitors,
    query_text_available,
):
    mentioned: list[str] = []
    injected: list[str] = []
    for competitor in config.competitors:
        if _entity_alias_present(competitor.aliases, answer_text, normalized_answer):
            mentioned.append(competitor.name)
        if query_text_available and competitor.name not in prompt_competitors:
            if _entity_alias_present(competitor.aliases, query_text, query_blob):
                injected.append(competitor.name)
    return {
        "competitors_mentioned": mentioned,
        "competitors_injected_in_search": injected,
    }


def _citation_signals(citations, config):
    classified = [classify_citation(citation, config) for citation in citations]
    owned_count = sum(1 for citation in classified if citation["is_owned"])
    qualified_owned_count = sum(
        _qualified_owned_citation(citation, config) for citation in classified
    )
    competitor_domains = _competitor_citation_domains(classified)
    return {
        "owned_domain_cited": owned_count > 0,
        "owned_citation_count": owned_count,
        "qualified_owned_citation_count": qualified_owned_count,
        "qualified_owned_cited": qualified_owned_count > 0,
        "unintended_domain_cited": any(
            citation["is_unintended"] for citation in classified
        ),
        "citation_count": len(classified),
        "competitor_domains_cited": competitor_domains,
    }


def _qualified_owned_citation(citation, config):
    if not citation["is_owned"]:
        return False
    text = " ".join(str(citation.get(key) or "") for key in ("title", "cited_text"))
    normalized = normalize_alias(text)
    return _entity_alias_present(config.brand_aliases, text, normalized) or any(
        alias_present(normalize_alias(term), normalized)
        for term in config.products_services
        if normalize_alias(term)
    )


def _competitor_citation_domains(classified):
    return sorted(
        {
            citation["matched_competitor"]
            for citation in classified
            if citation["matched_competitor"]
        }
    )


def _fanout_features(search_events):
    return sorted(
        {
            feature
            for event in search_events
            for feature in classify_fanout(str(event.get("query") or ""))
        }
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def aggregate_run(
    executions: list[dict[str, Any]], config: ScoringConfig
) -> dict[str, Any]:
    """Run-level aggregates (headline rates + stability + SOV + citations)."""
    completed = [
        execution
        for execution in executions
        if execution.get("score") and execution.get("status") == "completed"
    ]
    scores = [execution["score"] for execution in completed]
    total = len(completed)
    headline = _headline_aggregates(scores, total)
    citation = _citation_aggregates(completed, total)
    competitors = _competitor_aggregates(scores, config, total)
    token_usage = _aggregate_token_usage(completed)
    return {
        "total_completed": total,
        **headline,
        **citation,
        **competitors,
        "share_of_voice": _share_of_voice(scores, config),
        "prompt_class_counts": dict(
            Counter(score.get("prompt_class", "unknown") for score in scores)
        ),
        "per_prompt": _per_prompt_metrics(completed, config),
        "token_usage": token_usage,
        "cost": _aggregate_cost(completed, token_usage, config),
        # Roadmap metrics (decision B-2): not computed yet (no LLM for
        # headline metrics, invariant 9). Present + null so the projection shape
        # is stable and the frontend can render the columns.
        "sentiment": None,
        "avg_position": None,
    }


def _share_of_voice(
    scores: list[dict[str, Any]], config: ScoringConfig
) -> dict[str, Any]:
    """Brand-vs-competitor share of mentions across completed executions.

    Deterministic: each execution contributes one mention per entity that
    appears in its answer. SOV is that entity's mention count over the total
    mention volume (brand + all competitors). This is the rankings-table input
    for the dashboard.
    """
    brand_mentions = sum(1 for score in scores if score.get("brand_mentioned"))
    competitor_mentions = {
        competitor.name: sum(
            1
            for score in scores
            if competitor.name in (score.get("competitors_mentioned") or [])
        )
        for competitor in config.competitors
    }
    total_mentions = brand_mentions + sum(competitor_mentions.values())
    entities = {config.brand_name or "Brand": brand_mentions, **competitor_mentions}
    return {
        "total_mentions": total_mentions,
        "mention_counts": entities,
        "share": {
            name: _rate(count, total_mentions) for name, count in entities.items()
        },
    }


def _headline_aggregates(scores, total):
    mention = sum(bool(score.get("brand_mentioned")) for score in scores)
    owned = sum(bool(score.get("owned_domain_cited")) for score in scores)
    both = sum(
        bool(score.get("brand_mentioned") and score.get("owned_domain_cited"))
        for score in scores
    )
    non_branded = [
        score for score in scores if score.get("prompt_class") == "non_branded"
    ]
    query_scores = [
        score for score in non_branded if score.get("search_query_text_available", True)
    ]
    all_query_scores = [
        score for score in scores if score.get("search_query_text_available", True)
    ]
    total_queries = sum(int(score.get("search_query_count") or 0) for score in scores)
    return {
        "brand_mention_rate": _rate(mention, total),
        "owned_citation_rate": _rate(owned, total),
        "mention_to_owned_citation_conversion": _rate(both, mention),
        "brand_fanout_injection_rate": _optional_rate(
            sum(bool(score.get("brand_injected_in_search")) for score in query_scores),
            len(query_scores),
        ),
        "search_query_text_coverage_rate": _rate(len(all_query_scores), total),
        "competitor_fanout_injection_rate": _optional_rate(
            sum(
                bool(score.get("competitors_injected_in_search"))
                for score in all_query_scores
            ),
            len(all_query_scores),
        ),
        "search_use_rate": _rate(
            sum(bool(score.get("search_used")) for score in scores), total
        ),
        "avg_queries_per_execution": round(total_queries / total, 2) if total else 0.0,
        "unintended_domain_citation_rate": _rate(
            sum(bool(score.get("unintended_domain_cited")) for score in scores), total
        ),
    }


def _optional_rate(numerator, denominator):
    return _rate(numerator, denominator) if denominator else None


def _citation_aggregates(completed, total):
    counter, executions, prompts, urls = _citation_domain_counts(completed)
    top = counter.most_common(25)
    total_citations = sum(counter.values())
    annotation_share = _top_domain_share(top, total_citations)
    distinct_prompts = len({int(row.get("prompt_index", 0)) for row in completed})
    unique_url_total = len(set().union(*urls.values())) if urls else 0
    return {
        "citation_share_by_domain": annotation_share,
        "citation_annotation_share_by_domain": annotation_share,
        "domain_execution_citation_rate": {
            domain: _rate(executions[domain], total) for domain, _count in top
        },
        "domain_unique_url_share": {
            domain: _rate(len(urls.get(domain, set())), unique_url_total)
            for domain, _count in top
        },
        "domain_prompt_coverage": {
            domain: _rate(len(prompts.get(domain, set())), distinct_prompts)
            for domain, _count in top
        },
    }


def _citation_domain_counts(completed):
    counter: Counter[str] = Counter()
    executions: Counter[str] = Counter()
    prompts: dict[str, set[int]] = {}
    urls: dict[str, set[str]] = {}
    for execution in completed:
        seen: set[str] = set()
        for citation in execution.get("citations") or []:
            domain = citation_domain(citation)
            if not domain:
                continue
            counter[domain] += 1
            seen.add(domain)
            prompts.setdefault(domain, set()).add(int(execution.get("prompt_index", 0)))
            url = _citation_url(citation)
            if url:
                urls.setdefault(domain, set()).add(url)
        executions.update(seen)
    return counter, executions, prompts, urls


def _citation_url(citation):
    return str(
        citation.get("resolved_url")
        or citation.get("redirect_url")
        or citation.get("url")
        or ""
    )


def _top_domain_share(top, total_citations):
    share = {domain: _rate(count, total_citations) for domain, count in top}
    shown = sum(count for _domain, count in top)
    if total_citations > shown:
        share["Other"] = _rate(total_citations - shown, total_citations)
    return share


def _competitor_aggregates(scores, config, total):
    names = [competitor.name for competitor in config.competitors]
    return {
        "competitor_mention_rate": {
            name: _rate(
                sum(
                    name in (score.get("competitors_mentioned") or [])
                    for score in scores
                ),
                total,
            )
            for name in names
        },
        "competitor_citation_rate": {
            name: _rate(
                sum(
                    name in (score.get("competitor_domains_cited") or [])
                    for score in scores
                ),
                total,
            )
            for name in names
        },
    }


def _reported_cost_usd(usage: dict[str, Any]) -> float | None:
    """Provider-REPORTED cost for one execution, in dollars.

    Only the canonical micro-USD field is accepted. Missing or malformed data
    contributes no reported cost; it is never inferred as free.
    """
    if usage.get("provider_cost_microusd") is not None:
        try:
            return float(usage["provider_cost_microusd"]) / MICRO_USD_PER_USD
        except (TypeError, ValueError):
            return None
    return None


def _provider_reported_cost(
    completed: list[dict[str, Any]],
) -> tuple[float | None, int]:
    reported: list[float] = []
    for execution in completed:
        usage = execution.get("usage") or {}
        value = _reported_cost_usd(usage)
        if value is not None:
            reported.append(value)
    return (sum(reported) if reported else None, len(reported))


def _token_line_estimate(tokens: int, rate: int | None) -> int | None:
    """Price one token line, keeping a used unknown-rate line unknown."""
    if tokens == 0:
        return 0
    return tokens * rate if rate is not None else None


def _token_cost_estimate(
    token_usage: dict[str, int], pricing: Any | None
) -> float | None:
    token_lines = (
        _token_line_estimate(
            token_usage["uncached_input_tokens"],
            pricing.uncached_input_microusd_per_million if pricing else None,
        ),
        _token_line_estimate(
            token_usage["cached_input_tokens"],
            pricing.cached_input_microusd_per_million if pricing else None,
        ),
        _token_line_estimate(
            token_usage["output_tokens"],
            pricing.output_microusd_per_million if pricing else None,
        ),
    )
    if any(line is None for line in token_lines):
        return None
    return sum(line for line in token_lines if line is not None) / (
        TOKENS_PER_MILLION * MICRO_USD_PER_USD
    )


def _paid_list_cost_estimate(
    token_usage: dict[str, int],
    config: ScoringConfig,
    grounded_requests: int,
) -> tuple[float | None, float | None, str]:
    identity = next(
        (
            route
            for route in APPROVED_ROUTE_IDENTITIES
            if route.logical_engine == config.provider
            and route.transport_model == config.model
        ),
        None,
    )
    pricing = route_pricing_for(identity, PRICING_CATALOG_VERSION) if identity else None
    search_rate = pricing.search_fee_microusd if pricing else None
    token_estimate = _token_cost_estimate(token_usage, pricing)
    search_estimate = _search_cost_estimate(grounded_requests, search_rate)
    known = sum(value is not None for value in (token_estimate, search_estimate))
    status = _cost_estimate_status(known)
    return token_estimate, search_estimate, status


def _search_cost_estimate(
    grounded_requests: int, search_rate_microusd: int | None
) -> float | None:
    if not grounded_requests:
        return 0.0
    if search_rate_microusd is None:
        return None
    return grounded_requests * search_rate_microusd / MICRO_USD_PER_USD


def _cost_estimate_status(known_lines: int) -> str:
    if known_lines == 2:
        return PROJECTION_STATUS_COMPLETE
    if known_lines:
        return PROJECTION_STATUS_PARTIAL
    return PROJECTION_STATUS_UNKNOWN


def _aggregate_cost(
    completed: list[dict[str, Any]],
    token_usage: dict[str, int],
    config: ScoringConfig,
) -> dict[str, Any]:
    grounded_requests = sum(
        1 for execution in completed if execution["score"].get("search_used")
    )
    token_estimate, grounding_if_billable, cost_status = _paid_list_cost_estimate(
        token_usage, config, grounded_requests
    )
    reported_cost, reported_executions = _provider_reported_cost(completed)
    return {
        "currency": "USD",
        "grounded_requests": grounded_requests,
        "paid_list_token_estimate_usd": (
            round(token_estimate, 6) if token_estimate is not None else None
        ),
        "grounding_cost_if_billable_usd": (
            round(grounding_if_billable, 6)
            if grounding_if_billable is not None
            else None
        ),
        "cost_status": cost_status,
        "pricing_version": PRICING_CATALOG_VERSION,
        "provider_reported_cost_usd": (
            round(reported_cost, 6) if reported_cost is not None else None
        ),
        "provider_reported_cost_coverage": {
            "reported_executions": reported_executions,
            "total_executions": len(completed),
        },
        "free_allowance_applied": False,
        "note": (
            "Unknown official price lines remain null and are never inferred as zero."
        ),
    }


def _usage_value(usage: dict[str, Any], key: str) -> int:
    """Read one canonical usage counter; absent/malformed contributes nothing."""
    try:
        return int(usage.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _aggregate_token_usage(completed: list[dict[str, Any]]) -> dict[str, int]:
    """Sum provider token counts across completed executions.

    Reads the immutable artifact's canonical typed-usage keys. This is a SUM
    across executions, so an unknown per-execution counter contributes nothing.
    """
    uncached_input_tokens = cached_input_tokens = output_tokens = total_tokens = 0
    for e in completed:
        usage = e.get("usage") or {}
        uncached_input_tokens += _usage_value(usage, "uncached_input_tokens")
        cached_input_tokens += _usage_value(usage, "cached_input_tokens")
        output_tokens += _usage_value(usage, "output_tokens")
        total_tokens += _usage_value(usage, "total_tokens")
    return {
        "input_tokens": uncached_input_tokens + cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _per_prompt_metrics(
    completed: list[dict[str, Any]], config: ScoringConfig
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for e in completed:
        grouped.setdefault(int(e.get("prompt_index", 0)), []).append(e)

    rows: list[dict[str, Any]] = []
    for prompt_index in sorted(grouped):
        rows.append(_prompt_metric_row(prompt_index, grouped[prompt_index], config))
    return sorted(rows, key=lambda row: (-row["composite_score"], row["prompt_index"]))


def _prompt_metric_row(prompt_index, group, config):
    repetitions = len(group)
    score = _prompt_composite(group, config)
    engine_scores = _prompt_engine_scores(group, config)
    return {
        "prompt_index": prompt_index,
        "prompt_text": group[0].get("prompt_text_snapshot", ""),
        "theme": group[0].get("prompt_theme_snapshot", ""),
        "repetitions": repetitions,
        "brand_mentioned_count": score["mentioned"],
        "owned_cited_count": score["owned_raw"],
        "mention_stability": _stability(score["mentioned"], repetitions),
        "owned_stability": _stability(score["owned_raw"], repetitions),
        "visibility_rate": score["visibility"],
        "competitive_share": score["competitive"] if config.competitors else None,
        "qualified_owned_citation_rate": score["owned_rate"],
        "composite_score": score["composite"],
        "score_components": score["components"],
        "score_weights": score["weights"],
        "per_engine_scores": engine_scores,
        "cross_engine_consistency": _cross_engine_consistency(engine_scores),
    }


def _prompt_composite(group, config):
    repetitions = len(group)
    mentioned = sum(bool(item["score"].get("brand_mentioned")) for item in group)
    owned = sum(bool(item["score"].get("qualified_owned_cited")) for item in group)
    owned_raw = sum(bool(item["score"].get("owned_domain_cited")) for item in group)
    competitor_mentions = sum(
        len(item["score"].get("competitors_mentioned") or []) for item in group
    )
    visibility = _rate(mentioned, repetitions)
    owned_rate = _rate(owned, repetitions)
    competitive = _rate(mentioned, mentioned + competitor_mentions)
    components, weights = _prompt_score_parts(
        visibility, owned_rate, competitive, bool(config.competitors)
    )
    total = sum(weights.values())
    return {
        "mentioned": mentioned,
        "owned": owned,
        "owned_raw": owned_raw,
        "visibility": visibility,
        "owned_rate": owned_rate,
        "competitive": competitive,
        "components": components,
        "weights": {name: round(weight / total, 4) for name, weight in weights.items()},
        "composite": round(
            sum(components[name] * weight for name, weight in weights.items())
            / total
            * 100,
            2,
        ),
    }


def _prompt_score_parts(visibility, owned, competitive, include_competitors):
    components = {"visibility": visibility, "owned_citations": owned}
    weights = {
        "visibility": PROMPT_SCORE_VISIBILITY_WEIGHT,
        "owned_citations": PROMPT_SCORE_OWNED_CITATION_WEIGHT,
    }
    if include_competitors:
        components["competitive_position"] = competitive
        weights["competitive_position"] = PROMPT_SCORE_COMPETITIVE_WEIGHT
    return components, weights


def _prompt_engine_scores(group, config):
    engines = sorted({str(item.get("logical_engine") or "") for item in group} - {""})
    return {
        engine: _prompt_composite(
            [item for item in group if item.get("logical_engine") == engine], config
        )["composite"]
        for engine in engines
    }


def _cross_engine_consistency(engine_rates):
    if not engine_rates:
        return 0.0
    spread = max(engine_rates.values()) - min(engine_rates.values())
    return round(1.0 - spread / 100, 4)


def _stability(true_count: int, reps: int) -> float:
    if reps <= 0:
        return 0.0
    false_count = reps - true_count
    return round(max(true_count, false_count) / reps, 4)
