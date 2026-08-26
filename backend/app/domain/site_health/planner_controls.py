"""Validation and normalization of crawl request controls."""

from __future__ import annotations

from collections.abc import Callable

from app.core.config.site_health_crawl_policy import INPUT_MODE_AUTO, INPUT_MODES
from app.core.config.site_health_runtime import site_health_settings
from app.core.config.site_health_taxonomy import PAGE_KINDS


def _advanced_requested(mode: str, seeds: list[str], page_kinds: list[str]) -> bool:
    return mode != INPUT_MODE_AUTO or bool(seeds) or bool(page_kinds)


def advanced_controls_requested(
    mode: str, seeds: list[str], page_kinds: list[str]
) -> bool:
    return _advanced_requested(mode, seeds, page_kinds)


def _page_limit(
    requested: int | None,
    *,
    error: Callable[[str, str], Exception],
) -> int:
    limit = (
        requested
        if requested is not None
        else site_health_settings.automatic_page_limit
    )
    maximum = (
        site_health_settings.max_advanced_requested_page_limit
        if site_health_settings.advanced_controls_enabled
        else site_health_settings.max_requested_page_limit
    )
    if limit <= 0 or limit > maximum:
        raise error(
            "requested_page_limit is outside the allowed range",
            "discovery_limit_exceeded",
        )
    return int(limit)


def resolve_controls(
    *,
    input_mode: str | None,
    requested_page_limit: int | None,
    seed_urls: list[str] | None,
    page_kinds: list[str] | None,
    error: Callable[[str, str], Exception],
) -> tuple[str, int, list[str], list[str]]:
    mode = input_mode or INPUT_MODE_AUTO
    seeds = list(seed_urls or [])
    selected_types = list(page_kinds or [])
    if mode not in INPUT_MODES:
        raise error("unknown input_mode", "invalid_crawl_request")
    if len(seeds) > site_health_settings.max_seed_urls:
        raise error("too many seed_urls", "invalid_crawl_request")
    if any(value not in PAGE_KINDS for value in selected_types):
        raise error("unknown page kind", "invalid_crawl_request")
    if (
        _advanced_requested(mode, seeds, selected_types)
        and not site_health_settings.advanced_controls_enabled
    ):
        raise error(
            "advanced crawl controls are unavailable",
            "advanced_controls_unavailable",
        )
    if mode == "exact_urls" and not seeds:
        raise error("exact_urls requires seed_urls", "invalid_crawl_request")
    return mode, _page_limit(requested_page_limit, error=error), seeds, selected_types
