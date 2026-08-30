"""Frozen crawl policy and admission decisions."""

from __future__ import annotations

from collections.abc import Callable

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    CLASSIFIER_VERSION,
    EXTRACTOR_VERSION,
    RULE_CATALOG_VERSION,
    SCORING_VERSION,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    DISCOVERY_MODE_SAMPLE,
    INPUT_MODE_AUTO,
    URL_ADMISSION_POLICY_VERSION,
)
from app.core.config.site_health_runtime import site_health_settings


def is_sample_mode(runtime) -> bool:
    return runtime.discovery_mode == DISCOVERY_MODE_SAMPLE


def frozen_configuration(
    *,
    root_registrable_domain: str,
    include_globs: list[str],
    exclude_globs: list[str],
    runtime,
    input_mode: str = INPUT_MODE_AUTO,
    requested_page_limit: int | None = None,
    seed_urls: list[str] | None = None,
    page_kinds: list[str] | None = None,
) -> dict:
    settings = site_health_settings
    configuration = {
        "discovery_mode": runtime.discovery_mode,
        "sample_mode": is_sample_mode(runtime),
        "count_disclosure": bool(runtime.count_disclosure),
        "sample_url_limit": int(runtime.sample_url_limit),
        "monitored_url_limit": int(runtime.monitored_url_limit),
        "discovery_url_cap": runtime.discovery_url_cap,
        "resolved_registry_revision": runtime.resolved_registry_revision,
        "resolved_entitlement_lifecycle_version": int(
            runtime.resolved_entitlement_lifecycle_version
        ),
        "root_registrable_domain": root_registrable_domain,
        "include_globs": include_globs,
        "exclude_globs": exclude_globs,
        "url_admission_policy_version": URL_ADMISSION_POLICY_VERSION,
        "page_kind_classifier_version": CLASSIFIER_VERSION,
        "page_profile_rule_version": RULE_CATALOG_VERSION,
        "input_mode": input_mode,
        "requested_page_limit": requested_page_limit,
        "max_discovery_urls": settings.max_discovery_urls,
        "max_analysis_urls": settings.max_analysis_urls,
        "seed_urls": list(seed_urls or []),
        "page_kinds": list(page_kinds or []),
        "max_frontier_urls": settings.max_frontier_urls,
        "max_crawl_depth": settings.max_crawl_depth,
        "admission_batch_size": settings.admission_batch_size,
        "global_concurrency": settings.global_concurrency,
        "per_host_concurrency": settings.per_host_concurrency,
        "per_host_delay_seconds": settings.per_host_delay_seconds,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "max_redirects": settings.max_redirects,
        "max_response_wire_bytes": settings.max_response_wire_bytes,
        "max_response_decoded_bytes": settings.max_response_decoded_bytes,
        "max_attempts": settings.max_attempts,
        "extractor_version": EXTRACTOR_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "scoring_version": SCORING_VERSION,
    }
    if input_mode == INPUT_MODE_AUTO:
        entitlement_limit = int(
            runtime.sample_url_limit
            if is_sample_mode(runtime)
            else runtime.monitored_url_limit
        )
        configuration[AUTOMATIC_MONITOR_LIMIT_KEY] = min(
            int(requested_page_limit or 0), entitlement_limit
        )
    return configuration


def admit_seed_urls(
    seed_urls: list[str],
    *,
    root_domain: str,
    includes: list[str],
    excludes: list[str],
    error: Callable[[str, str], Exception],
) -> list[str]:
    accepted: list[str] = []
    seen: set[str] = set()
    for raw in seed_urls:
        decision = classify_url_admission(
            raw,
            root_registrable_domain=root_domain,
            include_globs=includes,
            exclude_globs=excludes,
        )
        if not decision.accepted or not decision.canonical_url:
            raise error(
                "seed URL is not admissible",
                decision.reason_code or "invalid_crawl_request",
            )
        if decision.canonical_url not in seen:
            seen.add(decision.canonical_url)
            accepted.append(decision.canonical_url)
    return accepted
