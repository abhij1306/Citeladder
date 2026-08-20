"""Strong-evidence indexing-intent resolution for Site Health rules."""

from __future__ import annotations

from typing import Any
from urllib.parse import SplitResult, urlsplit

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)


def _split_compare_url(raw: str) -> tuple[SplitResult, int | None] | None:
    try:
        parts = urlsplit(raw)
        try:
            port = parts.port
        except ValueError:
            port = None
    except ValueError:
        # ``urlsplit`` raises only ValueError, and only on a genuinely
        # unparseable URL (a bad IPv6 literal, a non-numeric port). Anything
        # else out of here is a bug and must not be turned into "no URL".
        return None
    return parts, port


def _compare_netloc(scheme: str, host: str, port: int | None) -> str:
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    return f"{host}:{port}" if port is not None and not default_port else host


def _compare_path(path: str) -> str:
    normalized = path or ""
    while len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized or "/"


def normalized_url_for_compare(url: str) -> str:
    """Canonical-vs-final comparison form; never crawler identity."""
    raw = str(url or "").strip()
    parsed = _split_compare_url(raw)
    if parsed is None:
        return raw.lower()
    parts, port = parsed
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return raw.lower()
    out = f"{scheme}://{_compare_netloc(scheme, host, port)}{_compare_path(parts.path)}"
    if parts.query:
        return f"{out}?{parts.query}"
    return out


def _canonical_intent(
    facts: dict[str, Any], evidence: dict[str, Any]
) -> tuple[str, str] | None:
    canonical = str(facts.get("canonical_url") or "").strip()
    if not canonical:
        return None
    final_url = str((facts.get("delivery") or {}).get("final_url") or "")
    same = normalized_url_for_compare(canonical) == normalized_url_for_compare(
        final_url
    )
    evidence["canonical_url"] = canonical[:2048]
    evidence["canonical_matches_final_url"] = same
    return ("intended_index" if same else "intended_exclude"), "canonical_declaration"


def _resolve_intent(facts: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, str]:
    explicit = str(facts.get("indexing_policy") or "").strip().lower()
    if explicit in {"index", "exclude"}:
        intent = "intended_index" if explicit == "index" else "intended_exclude"
        return intent, "explicit_user_policy"
    canonical = _canonical_intent(facts, evidence)
    if canonical is not None:
        return canonical
    if facts.get("sitemap_member") is True:
        return "intended_index", "sitemap_membership"
    robots = str(facts.get("robots_indexing_policy") or "").strip().lower()
    if robots in {"index", "exclude"}:
        intent = "intended_index" if robots == "index" else "intended_exclude"
        return intent, "robots_evidence"
    return "unknown", "insufficient_evidence"


def evaluate_indexability(facts: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Classify ``noindex`` from strong evidence and preserve uncertainty."""
    robots = facts.get("robots") or {}
    noindex = bool(robots.get("noindex"))
    evidence: dict[str, Any] = {
        "noindex": noindex,
        "nofollow": bool(robots.get("nofollow")),
    }
    if not noindex:
        return RULE_OUTCOME_PASS, evidence
    intent, source = _resolve_intent(facts, evidence)
    evidence.update({"indexing_intent": intent, "intent_source": source})
    if intent == "intended_exclude":
        evidence["reason"] = "intentional_non_indexing"
        return RULE_OUTCOME_NOT_APPLICABLE, evidence
    return RULE_OUTCOME_FAIL, evidence
