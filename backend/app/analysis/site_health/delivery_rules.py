"""Deterministic checks for HTTP delivery and automated-consumer access."""

from __future__ import annotations

from collections.abc import Callable

from app.analysis.site_health.rule_scope import server_render_signals
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
    SEARCH_CITATION_CRAWLER_BOTS,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_rules import TTFB_WARN_MS


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_SATISFIED if condition else RULE_OUTCOME_MISSING


def _check_https(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    is_https = bool(delivery.get("is_https"))
    return _pass_fail(is_https), {
        "scheme": delivery.get("scheme", ""),
        "final_url": delivery.get("final_url", ""),
        "is_https": is_https,
    }


def _check_hsts_present(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    security = delivery.get("security_headers") or {}
    present = bool(security.get("strict-transport-security"))
    return _pass_fail(present), {
        "present": present,
        "scheme": delivery.get("scheme", ""),
    }


def _check_ttfb_band(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    ttfb = delivery.get("ttfb_ms")
    if ttfb is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_ttfb_measurement"}
    ttfb_ms = int(ttfb)
    return _pass_fail(ttfb_ms <= TTFB_WARN_MS), {
        "ttfb_ms": ttfb_ms,
        "threshold_ms": TTFB_WARN_MS,
    }


def _check_uncompressed_html(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    compressed = bool(delivery.get("is_compressed"))
    return _pass_fail(compressed), {
        "content_encoding": delivery.get("content_encoding", ""),
        "is_compressed": compressed,
    }


def _check_ai_crawler_access(facts: dict) -> tuple[str, dict]:
    site = facts.get("site") or {}
    robots = site.get("robots") or {}
    stance = robots.get("ai_crawlers") or {}
    bounded_stance = {bot: stance.get(bot, "") for bot in AI_CRAWLER_BOTS}
    if not robots.get("fetched"):
        # The stance is the fail-open default (robots.txt unfetchable): a
        # PASS would be vacuous for a HIGH-severity signal. N/A instead.
        return RULE_OUTCOME_NOT_APPLICABLE, {
            "reason": "robots_not_fetched",
            "robots_fetched": False,
            "ai_crawlers": bounded_stance,
        }
    blocked = [
        bot for bot in AI_CRAWLER_BOTS if stance.get(bot) == AI_CRAWLER_STANCE_BLOCK
    ]
    return _pass_fail(not blocked), {
        "robots_fetched": True,
        "ai_crawlers": bounded_stance,
        "blocked": blocked,
    }


def _check_search_crawler_access(facts: dict) -> tuple[str, dict]:
    robots = (facts.get("site") or {}).get("robots") or {}
    stance = robots.get("ai_crawlers") or {}
    if not robots.get("fetched"):
        return RULE_OUTCOME_NOT_APPLICABLE, {
            "reason": "robots_not_fetched",
            "crawler_role": "search_citation",
        }
    blocked = [
        bot
        for bot in SEARCH_CITATION_CRAWLER_BOTS
        if stance.get(bot) == AI_CRAWLER_STANCE_BLOCK
    ]
    return _pass_fail(not blocked), {
        "crawler_role": "search_citation",
        "checked": list(SEARCH_CITATION_CRAWLER_BOTS),
        "blocked": blocked,
    }


def _check_snippet_access(facts: dict) -> tuple[str, dict]:
    robots = facts.get("robots") or {}
    nosnippet = bool(robots.get("nosnippet"))
    max_snippet = robots.get("max_snippet")
    blocked = nosnippet or max_snippet == 0
    return _pass_fail(not blocked), {
        "nosnippet": nosnippet,
        "max_snippet": max_snippet,
        "directives": list(robots.get("directives") or ())[:32],
    }


def _check_llms_txt_present(facts: dict) -> tuple[str, dict]:
    site = facts.get("site") or {}
    llms = site.get("llms_txt") or {}
    present = bool(llms.get("present"))
    return _pass_fail(present), {
        "fetched": bool(llms.get("fetched")),
        "present": present,
        "url": str(llms.get("url") or "")[:2048],
    }


_SOFT_ERROR_PHRASES = ("page not found", "404 not found", "does not exist")


def _check_soft_error(facts: dict) -> tuple[str, dict]:
    status_code = (facts.get("delivery") or {}).get("status_code")
    headings = facts.get("headings") or {}
    title_and_h1 = [str(facts.get("title") or ""), *(headings.get("h1_texts") or ())]
    normalized = {value.strip().casefold() for value in title_and_h1 if value}
    matched = next(
        (
            phrase
            for phrase in _SOFT_ERROR_PHRASES
            if any(phrase in value for value in normalized)
        ),
        "",
    )
    soft_error = status_code == 200 and bool(matched)
    return _pass_fail(not soft_error), {
        "status_code": status_code,
        "matched_error_phrase": matched,
    }


def _check_server_rendered_content(facts: dict) -> tuple[str, dict]:
    is_shell, evidence = server_render_signals(facts)
    return _pass_fail(not is_shell), evidence


DELIVERY_CHECKS: dict[str, Callable[[dict], tuple[str, dict]]] = {
    "technical.https": _check_https,
    "technical.hsts_present": _check_hsts_present,
    "technical.ttfb_band": _check_ttfb_band,
    "technical.uncompressed_html": _check_uncompressed_html,
    "technical.ai_crawler_access": _check_ai_crawler_access,
    "search.crawler_access": _check_search_crawler_access,
    "search.snippet_access": _check_snippet_access,
    "aeo.llms_txt_present": _check_llms_txt_present,
    "technical.soft_error": _check_soft_error,
    "aeo.server_rendered_content": _check_server_rendered_content,
}
