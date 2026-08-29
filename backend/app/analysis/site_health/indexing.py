"""Strong-evidence indexing-intent resolution for Site Health rules."""

from __future__ import annotations

from typing import Any
from urllib.parse import SplitResult, parse_qsl, urlencode, urljoin, urlsplit

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_rules import TRACKING_QUERY_PARAMS


def _split_compare_url(raw: str) -> tuple[SplitResult, int | None] | None:
    """``(parts, port)`` for a parseable URL, or None when it is not one.

    ``urlsplit`` is lazy about the port: it succeeds on
    ``https://x.example:notaport/`` and only raises when ``.port`` is read.
    Catching that and substituting ``None`` made a malformed authority look
    like a clean one -- the port simply vanished, so
    ``https://x.example:99999/a`` normalized to ``https://x.example/a`` and
    compared EQUAL to the page it was supposed to be a broken canonical for.

    An unreadable port means the URL did not parse, and it is reported as such.
    """
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        # ``urlsplit`` and ``.port`` raise only ValueError, and only on a
        # genuinely unparseable URL (a bad IPv6 literal, a non-numeric or
        # out-of-range port). Anything else out of here is a bug and must not
        # be turned into "no URL".
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


def _compare_query(query: str) -> str:
    """Drop campaign/click parameters before comparing two URLs.

    A page reached from a newsletter or an ad arrives with the tracking
    parameters still on its final URL while its canonical is, correctly, the
    clean address. Comparing the query verbatim made every one of those visits
    a canonical conflict -- a finding about how the crawler arrived, not about
    the page.

    Only the config-owned tracking set is dropped. Every other parameter is
    preserved, because a parameter that genuinely selects different content is
    exactly what a canonical is resolving.
    """
    if not query:
        return ""
    pairs = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_PARAMS
    ]
    return urlencode(pairs)


def resolve_canonical(canonical: str, final_url: str) -> str:
    """Absolute form of a declared canonical, resolved against the page URL.

    ``_canonical_href`` deliberately records what the page DECLARED, and a
    relative ``<link rel="canonical" href="/contact-us">`` is both legal and
    common. Comparing that raw value against an absolute final URL could never
    match, so every page using a relative canonical looked like a conflict --
    and, worse, ``_canonical_intent`` read the same non-match as evidence that
    the page was deliberately excluded from indexing, which suppressed a real
    noindex defect.

    Resolution happens here, at the comparison boundary, rather than in the
    extractor: the declared value stays the persisted fact, and both consumers
    of that fact resolve it identically. Mirrors ``_hreflang_alternates``,
    which already resolves against ``final_url``.
    """
    raw = str(canonical or "").strip()
    if not raw:
        return ""
    try:
        return urljoin(str(final_url or ""), raw)
    except ValueError:
        # Same narrow contract as ``_split_compare_url``: an unresolvable
        # value is returned as declared rather than silently becoming "no
        # canonical".
        return raw


def canonical_origin(url: str) -> str:
    """The URL origin -- scheme, host AND port -- or "" when unparseable.

    The port is part of an origin, and dropping it made
    ``https://x.example:444/a`` compare equal to ``https://x.example/a``. Those
    are different origins, so a canonical handing indexing authority across
    them read as ordinary same-origin consolidation and passed silently.

    Default ports normalize away via ``_compare_netloc``, so ``:443`` on HTTPS
    stays equal to no port at all -- the same rule
    ``normalized_url_for_compare`` already applies, which is what kept the two
    comparisons disagreeing with each other.
    """
    parsed = _split_compare_url(str(url or "").strip())
    if parsed is None:
        return ""
    parts, port = parsed
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return ""
    return f"{scheme}://{_compare_netloc(scheme, host, port)}"


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
    query = _compare_query(parts.query)
    if query:
        return f"{out}?{query}"
    return out


def _canonical_intent(
    facts: dict[str, Any], evidence: dict[str, Any]
) -> tuple[str, str] | None:
    declared = str(facts.get("canonical_url") or "").strip()
    if not declared:
        return None
    final_url = str((facts.get("delivery") or {}).get("final_url") or "")
    canonical = resolve_canonical(declared, final_url)
    if not canonical_origin(canonical):
        # An unparseable canonical is not evidence of intent in either
        # direction. Before ports were validated it silently compared EQUAL to
        # the page and read as intended_index; treating it as a mismatch
        # instead would swing it to intended_exclude and suppress a real
        # noindex defect. It is simply no canonical evidence, so precedence
        # falls through to sitemap membership and robots.
        evidence["canonical_url"] = canonical[:2048]
        evidence["canonical_unparseable"] = True
        return None
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
