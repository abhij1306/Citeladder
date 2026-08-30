# Deterministic HTML + delivery fact extraction (Task 5).
#
# ``extract_page_facts`` turns one fetched page (decoded HTML bytes + the
# artifact's redacted delivery facts) into a bounded, JSON-safe dict of "page
# facts": metadata, headings, images, body text/word count, structured data,
# links/assets, and delivery/security signals. It is a PURE function (no I/O, no
# ORM) so the same input always yields the same facts (invariant 9), and every
# extraction step is guarded so a malformed/hostile page yields PARTIAL facts,
# never a crash (subplan Persistence contract).
#
# The lxml parser runs with ``no_network=True`` (never resolves an external
# DTD/entity) and JSON-LD is parsed with the stdlib loader, so there is no XML
# external-entity attack surface; defusedxml is used for any raw XML parse.
from __future__ import annotations

import codecs
import logging
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from lxml import etree
from lxml import html as lxml_html

from app.analysis.site_health.accessibility_facts import extract_accessibility_facts
from app.analysis.site_health.commerce_facts import extract_commerce_facts
from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.analysis.site_health.dom import node_text as _text
from app.analysis.site_health.fact_authorship import author_and_dates
from app.analysis.site_health.fact_entity import (
    empty_entity_signals,
    safe_entity_signals,
)
from app.analysis.site_health.fact_links import links_and_assets
from app.analysis.site_health.fact_regions import region_node_is_visible
from app.analysis.site_health.fact_signals import (
    cta_texts,
    first_answer_text,
    form_fields,
    ordered_list_steps,
    outbound_domains,
)
from app.analysis.site_health.page_kinds import is_question_heading
from app.analysis.site_health.robots_directives import (
    extract_robots_directives,
    merge_x_robots_tag,
)
from app.analysis.site_health.structured_data import (
    parse_jsonld_blocks,
    product_facts,
    validate_microdata_types,
)
from app.core.config import site_health_acquisition as site_health_config
from app.core.config.site_health_contracts import (
    EXTRACTOR_VERSION,
)
from app.core.config.site_health_rules import (
    INLINE_SCRIPT_JAVASCRIPT_TYPES,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)

# Bounded per-field caps so a single hostile attribute can never bloat the
# persisted facts dict.
_MAX_TITLE_CHARS = site_health_config.SITE_HEALTH_MAX_TITLE_CHARS
_MAX_META_CHARS = site_health_config.SITE_HEALTH_MAX_META_CHARS
_MAX_HEADING_CHARS = site_health_config.SITE_HEALTH_MAX_HEADING_CHARS
_MAX_HEADINGS_KEPT = site_health_config.SITE_HEALTH_MAX_HEADINGS_KEPT
_MAX_URL_CHARS = site_health_config.SITE_HEALTH_MAX_URL_CHARS
_MAX_ANCHOR_TEXT_CHARS = site_health_config.SITE_HEALTH_MAX_ANCHOR_TEXT_CHARS
_MAX_CTA_TEXTS = site_health_config.SITE_HEALTH_MAX_CTA_TEXTS
_MAX_CTA_TEXT_CHARS = site_health_config.SITE_HEALTH_MAX_CTA_TEXT_CHARS
_MAX_FORM_FIELDS = site_health_config.SITE_HEALTH_MAX_FORM_FIELDS
_MAX_FORM_FIELD_CHARS = site_health_config.SITE_HEALTH_MAX_FORM_FIELD_CHARS
_MAX_LINK_CONTEXT = site_health_config.SITE_HEALTH_MAX_LINK_CONTEXT
_MAX_LINK_CONTEXT_CHARS = site_health_config.SITE_HEALTH_MAX_LINK_CONTEXT_CHARS
CTA_BUTTON_ROLE_TOKENS = site_health_config.CTA_BUTTON_ROLE_TOKENS
_MAX_OUTBOUND_DOMAINS = site_health_config.SITE_HEALTH_MAX_OUTBOUND_DOMAINS
_MAX_DOMAIN_CHARS = site_health_config.SITE_HEALTH_MAX_DOMAIN_CHARS
_MAX_HREFLANG_ALTERNATES = site_health_config.SITE_HEALTH_MAX_HREFLANG_ALTERNATES
_MAX_HREFLANG_CHARS = site_health_config.SITE_HEALTH_MAX_HREFLANG_CHARS
_MAX_FIRST_ANSWER_CHARS = site_health_config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS
_MAX_INLINE_SCRIPT_CHARS = site_health_config.SITE_HEALTH_MAX_INLINE_SCRIPT_CHARS
_MAX_CONTACT_POINTS = site_health_config.SITE_HEALTH_MAX_CONTACT_POINTS
_MAX_CONTACT_VALUE_CHARS = site_health_config.SITE_HEALTH_MAX_CONTACT_VALUE_CHARS
# The security response headers whose mere presence the delivery facts record.
_SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
)

logger = logging.getLogger("app.analysis.site_health.parser")


def _safe_parser_encoding(charset: str) -> str | None:
    """Return a codec-valid encoding name, or ``None`` to auto-detect.

    A response's declared charset is arbitrary attacker-influenced input. Handed
    straight to ``lxml``'s ``HTMLParser(encoding=...)`` an unknown value raises
    ``LookupError`` at parser-construction time — outside the ``try`` guarding
    the actual parse — which would crash extraction instead of degrading to
    partial facts. Validate the name with ``codecs.lookup`` up front; if it is
    empty or unknown, return ``None`` so lxml falls back to auto-detection
    rather than raising.
    """
    normalized = str(charset or "").strip()
    if not normalized:
        return None
    try:
        codecs.lookup(normalized)
    except LookupError:
        return None
    return normalized.lower()


def _meta_content(root: Any, *, name: str) -> str:
    try:
        nodes = root.xpath(
            "//meta[translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')=$n]",
            n=name.lower(),
        )
    except DOM_ERRORS as exc:
        dom_failure("_meta_content", exc)
        return ""
    for node in nodes:
        content = (node.get("content") or "").strip()
        if content:
            return content[:_MAX_META_CHARS]
    return ""


def _meta_property_map(root: Any, *, prefix: str) -> dict[str, str]:
    """Collect ``<meta property="prefix:...">`` (OG) or name= (Twitter) tags."""
    out: dict[str, str] = {}
    try:
        nodes = root.xpath("//meta[@property or @name]")
    except DOM_ERRORS as exc:
        dom_failure("_meta_property_map", exc)
        return out
    for node in nodes:
        key = (node.get("property") or node.get("name") or "").strip().lower()
        if not key or not key.startswith(prefix):
            continue
        content = (node.get("content") or "").strip()
        if content and key not in out:
            out[key] = content[:_MAX_META_CHARS]
    return out


def _canonical_href(root: Any) -> str:
    try:
        nodes = root.xpath(
            "//link[translate(@rel,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='canonical']"
        )
    except DOM_ERRORS as exc:
        dom_failure("_canonical_href", exc)
        return ""
    for node in nodes:
        href = (node.get("href") or "").strip()
        if href:
            return href[:_MAX_URL_CHARS]
    return ""


def _headings(root: Any) -> dict[str, Any]:
    """Count h1..h6 and capture bounded h1/h2/h3 text (deterministic order)."""
    counts: dict[str, int] = {}
    h1_texts: list[str] = []
    h2_texts: list[str] = []
    h3_texts: list[str] = []
    for level in range(1, 7):
        tag = f"h{level}"
        try:
            nodes = root.xpath(f"//{tag}")
        except DOM_ERRORS as exc:
            dom_failure("_headings", exc)
            nodes = []
        counts[tag] = len(nodes)
        if level == 1:
            for node in nodes[:_MAX_HEADINGS_KEPT]:
                h1_texts.append(_text(node)[:_MAX_HEADING_CHARS])
        elif level == 2:
            for node in nodes[:_MAX_HEADINGS_KEPT]:
                h2_texts.append(_text(node)[:_MAX_HEADING_CHARS])
        elif level == 3:
            for node in nodes[:_MAX_HEADINGS_KEPT]:
                h3_texts.append(_text(node)[:_MAX_HEADING_CHARS])
    return {
        "counts": counts,
        "h1_count": counts.get("h1", 0),
        "h1_texts": h1_texts,
        "h2_texts": h2_texts,
        "h3_texts": h3_texts,
    }


def _contact_points(root: Any) -> list[dict[str, str]]:
    """Bounded declared contact points, read from ``mailto:``/``tel:`` hrefs.

    An href is an AUTHORED declaration — the site saying "reach us here". A
    regex over body text is not: it also matches an address in a testimonial, a
    placeholder in a sample form, and a partner organization's details, all of
    which would then be asserted as this project's contact information.

    Nothing here is treated as personal data to retain: these are the public
    contact points a site publishes for exactly this purpose.
    """
    points: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        for node in root.iter("a"):
            if len(points) >= _MAX_CONTACT_POINTS:
                break
            if not region_node_is_visible(node):
                continue
            href = str(node.get("href") or "").strip()
            lowered = href.casefold()
            if lowered.startswith("mailto:"):
                channel, raw = "email", href[7:]
            elif lowered.startswith("tel:"):
                channel, raw = "phone", href[4:]
            else:
                continue
            # Drop any mailto query (?subject=/&body=): it is template text,
            # not an address, and would make two links to one inbox look like
            # two different contact points. Percent-decode first — an authored
            # ``mailto:%20info@x.test`` is one inbox, and leaving the escape in
            # persists an unusable address AND a duplicate of the real one
            # (observed live on the first acceptance corpus).
            value = unquote(raw.split("?", 1)[0]).strip()[:_MAX_CONTACT_VALUE_CHARS]
            if not value:
                continue
            key = f"{channel}|{value.casefold()}"
            if key in seen:
                continue
            seen.add(key)
            points.append({"channel": channel, "value": value})
    except DOM_ERRORS as exc:
        dom_failure("_contact_points", exc)
    return points


def _link_context(anchors: list[dict]) -> list[str]:
    """Bounded internal anchor text — what this page says its neighbours are.

    Derived from the already-extracted anchors rather than a second DOM pass:
    internal anchor text is how a hub page advertises the pages it links to,
    which is what lets the classifier tell a listing from a detail page.
    """
    context: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        if len(context) >= _MAX_LINK_CONTEXT:
            break
        if not anchor.get("is_internal"):
            continue
        cleaned = " ".join(str(anchor.get("anchor_text") or "").split())[
            :_MAX_LINK_CONTEXT_CHARS
        ]
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        context.append(cleaned)
    return context


def _images(root: Any) -> dict[str, int]:
    """Distinguish absent alt text from an explicit decorative empty alt."""
    try:
        nodes = root.xpath("//img")
    except DOM_ERRORS as exc:
        dom_failure("_images", exc)
        nodes = []
    total = len(nodes)
    missing_alt = 0
    decorative_alt = 0
    for node in nodes:
        alt = node.get("alt")
        if alt is None:
            missing_alt += 1
        elif not str(alt).strip():
            decorative_alt += 1
    return {
        "count": total,
        "missing_alt": missing_alt,
        "decorative_alt": decorative_alt,
    }


def _viewport_facts(root: Any) -> dict[str, Any]:
    content = _meta_content(root, name="viewport")
    return {"declared": bool(content), "content": content}


def _body_text(root: Any, *, max_chars: int) -> dict[str, Any]:
    """Extract bounded visible body text + a whitespace-split word count.

    Script/style/noscript/template subtrees are dropped so their content never
    inflates the word count. The text is capped at ``max_chars``.
    """
    body_nodes = root.xpath("//body")
    node = body_nodes[0] if body_nodes else root
    # Drop non-content subtrees before reading text.
    try:
        for junk in node.xpath(".//script | .//style | .//noscript | .//template"):
            junk.getparent().remove(junk)
    except (etree.Error, AttributeError, TypeError, ValueError) as exc:
        # Partial-facts contract keeps the (unpruned) body text rather than
        # crashing extraction, but the reason is no longer swallowed silently
        # (ERR-6): an unpruned page inflates the word count and can mislead
        # the thin-content rule.
        logger.debug(
            "body-text junk-node removal failed; continuing with unpruned text",
            exc_info=True,
            extra={"error_type": type(exc).__name__},
        )
    raw = _text(node)
    text = " ".join(raw.split())[:max_chars]
    word_count = len(text.split()) if text else 0
    return {"text": text, "word_count": word_count}


def _structured_data(root: Any, *, max_blocks: int) -> dict[str, Any]:
    """Extract + validate JSON-LD + microdata structured-data facts."""
    raw_jsonld: list[str] = []
    try:
        for script in root.xpath(
            "//script[translate(@type,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='application/ld+json']"
        ):
            raw_jsonld.append(script.text_content() or "")
    except DOM_ERRORS as exc:
        dom_failure("_structured_data", exc)
        raw_jsonld = []
    jsonld_facts = parse_jsonld_blocks(raw_jsonld, max_blocks=max_blocks)

    itemtypes: list[str] = []
    try:
        for node in root.xpath("//*[@itemscope][@itemtype]"):
            itemtype = (node.get("itemtype") or "").strip()
            if itemtype:
                itemtypes.append(itemtype)
    except DOM_ERRORS as exc:
        dom_failure("_structured_data", exc)
        itemtypes = []
    microdata_facts = validate_microdata_types(itemtypes, max_blocks=max_blocks)

    blocks = (jsonld_facts + microdata_facts)[:max_blocks]
    return {
        "blocks": blocks,
        "count": len(blocks),
        "has_json_ld": bool(jsonld_facts),
        "has_microdata": bool(microdata_facts),
        "types": sorted({b["type"] for b in blocks}),
        "product": product_facts(blocks),
    }


def _delivery_facts(
    *,
    final_url: str,
    status_code: int | None,
    redacted_headers: dict[str, str] | None,
    http_version: str,
    ttfb_ms: int | None,
    latency_ms: int | None,
    wire_bytes: int | None,
    decoded_bytes: int | None,
) -> dict[str, Any]:
    """Derive delivery/security facts from the artifact's delivery fields.

    Pure: reads only the (already redacted) header allowlist + timing/byte
    fields the fetch produced. Records HTTPS from the final URL scheme, TTFB /
    wire/decoded bytes / HTTP version, compression + cache directives, and the
    PRESENCE of each security header (never the value).
    """
    headers = {str(k).lower(): str(v) for k, v in (redacted_headers or {}).items()}
    scheme = ""
    try:
        scheme = (urlsplit(final_url).scheme or "").lower()
    except DOM_ERRORS as exc:
        dom_failure("_delivery_facts", exc)
        scheme = ""
    content_encoding = headers.get("content-encoding", "").strip().lower()
    security_headers = {name: name in headers for name in _SECURITY_HEADERS}
    return {
        "final_url": (final_url or "")[:_MAX_URL_CHARS],
        "scheme": scheme,
        "is_https": scheme == "https",
        "status_code": status_code,
        "http_version": http_version or "",
        "ttfb_ms": ttfb_ms,
        "latency_ms": latency_ms,
        "wire_bytes": wire_bytes,
        "decoded_bytes": decoded_bytes,
        "content_encoding": content_encoding,
        "is_compressed": bool(content_encoding) and content_encoding != "identity",
        "cache_control": headers.get("cache-control", ""),
        "security_headers": security_headers,
        # Static blocking-resource heuristic: render-blocking assets are the
        # synchronous scripts + stylesheets referenced in the document. Counted
        # from the parsed facts by the caller; recorded here as a flag holder.
    }


def _landmarks(root: Any) -> dict[str, bool]:
    """Presence of the main/article/nav landmark elements."""
    out = {"main": False, "article": False, "nav": False}
    for tag in out:
        try:
            out[tag] = bool(root.xpath(f"//{tag}"))
        except DOM_ERRORS as exc:
            dom_failure("_landmarks", exc)
            out[tag] = False
    return out


def _question_heading_ratio(headings: dict[str, Any]) -> float:
    """Question-form ratio over the bounded h2 + h3 heading texts (0..1)."""
    texts = [str(t) for t in (headings.get("h2_texts") or [])]
    texts += [str(t) for t in (headings.get("h3_texts") or [])]
    if not texts:
        return 0.0
    questions = sum(1 for text in texts if is_question_heading(text))
    return round(questions / len(texts), 4)


def _expand_gated_words(root: Any) -> int:
    """Words inside click-to-expand subtrees (collapsed details / expanded=false).

    A subtree nested inside an already-counted gated subtree is skipped so
    nested gates never double-count. Bounded by the tree size already parsed.
    """
    candidates: list[Any] = []
    try:
        candidates = root.xpath(".//details[not(@open)] | .//*[@aria-expanded='false']")
    except DOM_ERRORS as exc:
        dom_failure("_expand_gated_words", exc)
        return 0
    counted: set[Any] = set()
    words = 0
    for node in candidates:
        if any(ancestor in counted for ancestor in node.iterancestors()):
            continue
        counted.add(node)
        words += len(_text(node).split())
    return words


def _hreflang_alternates(root: Any, *, final_url: str) -> list[dict[str, str]]:
    """Bounded ``<link rel="alternate" hreflang>`` annotations (absolute URLs).

    Feeds the ``crawl_finalize`` hreflang reciprocity check (spec §5.3), so
    hrefs are resolved against the page's final URL at extraction time.
    """
    alternates: list[dict[str, str]] = []
    try:
        nodes = root.xpath("//link[@hreflang]")
    except DOM_ERRORS as exc:
        dom_failure("_hreflang_alternates", exc)
        return alternates
    for node in nodes:
        if len(alternates) >= _MAX_HREFLANG_ALTERNATES:
            break
        rel_tokens = (node.get("rel") or "").lower().split()
        if "alternate" not in rel_tokens:
            continue
        hreflang = (node.get("hreflang") or "").strip()
        href = (node.get("href") or "").strip()
        if not hreflang or not href:
            continue
        try:
            absolute = urljoin(final_url or "", href)
        except DOM_ERRORS as exc:
            dom_failure("_hreflang_alternates", exc)
            continue
        alternates.append(
            {
                "hreflang": hreflang[:_MAX_HREFLANG_CHARS],
                "url": absolute[:_MAX_URL_CHARS],
            }
        )
    return alternates


def _inline_script_chars(root: Any) -> int:
    """Bounded total character count of src-less JAVASCRIPT <script> bodies.

    Only scripts that execute as JS count: an omitted ``type`` (JS per the
    HTML spec) or a JavaScript MIME in ``INLINE_SCRIPT_JAVASCRIPT_TYPES``.
    JSON-LD / importmap / template bodies are data, not code — a large
    JSON-LD block must not read as a JS shell. Read by
    ``aeo.server_rendered_content`` to tell a JS shell from real
    server-rendered content. Must run BEFORE ``_body_text`` (which removes
    script subtrees from the tree).
    """
    total = 0
    try:
        for script in root.iter("script"):
            if (script.get("src") or "").strip():
                continue
            script_type = (script.get("type") or "").strip().lower()
            if script_type and script_type not in INLINE_SCRIPT_JAVASCRIPT_TYPES:
                continue
            total += len(script.text_content() or "")
            if total >= _MAX_INLINE_SCRIPT_CHARS:
                return _MAX_INLINE_SCRIPT_CHARS
    except DOM_ERRORS as exc:
        dom_failure("_inline_script_chars", exc)
        return total
    return total


def _empty_facts() -> dict[str, Any]:
    return {
        "has_html": False,
        "title": "",
        "meta_description": "",
        "robots": {"noindex": False, "nofollow": False},
        "canonical_url": "",
        "open_graph": {},
        "twitter": {},
        "headings": {
            "counts": {},
            "h1_count": 0,
            "h1_texts": [],
            "h2_texts": [],
            "h3_texts": [],
        },
        "images": {"count": 0, "missing_alt": 0, "decorative_alt": 0},
        "accessibility": {
            "control_count": 0,
            "controls_missing_accessible_name": 0,
            "heading_levels": [],
            "heading_level_skips": 0,
            "document_language": "",
        },
        "mobile": {"viewport": {"declared": False, "content": ""}},
        "body": {"text": "", "word_count": 0},
        # Industry-role classifier facts (see the extractors above).
        "cta_text": [],
        "form_fields": [],
        "link_context": [],
        "entity": empty_entity_signals(),
        "structured_data": {
            "blocks": [],
            "count": 0,
            "has_json_ld": False,
            "has_microdata": False,
            "types": [],
            "product": product_facts([]),
        },
        "links": {
            "anchors": [],
            "images": [],
            "scripts": [],
            "stylesheets": [],
        },
        "blocking_resources": {"scripts": 0, "stylesheets": 0, "total": 0},
        # v2 P2 (sh-extractor-2) fields.
        "author": "",
        "dates": {"published": "", "modified": ""},
        "authorship": {"visible_byline": "", "visible_date": ""},
        "outbound_domains": [],
        "landmarks": {"main": False, "article": False, "nav": False},
        "ordered_list_steps": 0,
        "question_heading_ratio": 0.0,
        "expand_gated_ratio": 0.0,
        "hreflang_alternates": [],
        "first_answer_text": "",
        "inline_script_chars": 0,
        "contact_points": [],
        "commerce": {
            "breadcrumbs": [],
            "breadcrumb_links": [],
            "product_cards": [],
            "category_links": [],
            "category_role": "unknown",
            "visible_price": "",
        },
    }


def _parse_root(body: bytes, *, charset: str, settings: Any) -> Any | None:
    bounded = body[: settings.max_html_bytes]
    parser = lxml_html.HTMLParser(
        recover=True, encoding=_safe_parser_encoding(charset), no_network=True
    )
    try:
        return lxml_html.document_fromstring(bounded, parser=parser)
    except (etree.ParserError, ValueError):
        return None


def _blocking_scripts(root: Any) -> int:
    count = 0
    try:
        for script in root.iter("script"):
            if not (script.get("src") or "").strip():
                continue
            if script.get("async") is not None or script.get("defer") is not None:
                continue
            count += 1
    except DOM_ERRORS as exc:
        dom_failure("_blocking_scripts", exc)
        return 0
    return count


def _extract_document(root: Any, *, final_url: str, settings: Any) -> dict[str, Any]:
    facts = _empty_facts()
    facts["has_html"] = True
    try:
        title_node = next(root.iter("title"), None)
        if title_node is not None:
            facts["title"] = _text(title_node)[:_MAX_TITLE_CHARS]
    except DOM_ERRORS as exc:
        dom_failure("_extract_document", exc)
    facts["meta_description"] = _meta_content(root, name="description")
    facts["robots"] = extract_robots_directives(root)
    facts["canonical_url"] = _canonical_href(root)
    facts["open_graph"] = _meta_property_map(root, prefix="og:")
    facts["twitter"] = _meta_property_map(root, prefix="twitter:")
    article_meta = _meta_property_map(root, prefix="article:")
    facts["headings"] = _headings(root)
    facts["images"] = _images(root)
    facts["accessibility"] = extract_accessibility_facts(
        root, max_headings=_MAX_HEADINGS_KEPT
    )
    facts["mobile"] = {"viewport": _viewport_facts(root)}
    facts["structured_data"] = _structured_data(
        root, max_blocks=settings.max_structured_data_blocks
    )
    facts["entity"] = safe_entity_signals(root)
    try:
        base_host = urlsplit(final_url).hostname or ""
    except DOM_ERRORS as exc:
        dom_failure("_extract_document", exc)
        base_host = ""
    facts["links"] = links_and_assets(
        root, base_host=base_host, max_links=settings.max_links_per_page
    )
    facts["cta_text"] = cta_texts(root)
    facts["form_fields"] = form_fields(root)
    facts["link_context"] = _link_context(facts["links"].get("anchors") or [])
    facts["contact_points"] = _contact_points(root)
    facts["outbound_domains"] = outbound_domains(
        facts["links"]["anchors"], base_host=base_host
    )
    facts["landmarks"] = _landmarks(root)
    facts["ordered_list_steps"] = ordered_list_steps(root)
    facts["question_heading_ratio"] = _question_heading_ratio(facts["headings"])
    facts["hreflang_alternates"] = _hreflang_alternates(root, final_url=final_url)
    facts["first_answer_text"] = first_answer_text(root)
    facts["inline_script_chars"] = _inline_script_chars(root)
    blocking_scripts = _blocking_scripts(root)
    blocking_styles = len(facts["links"]["stylesheets"])
    facts["blocking_resources"] = {
        "scripts": blocking_scripts,
        "stylesheets": blocking_styles,
        "total": blocking_scripts + blocking_styles,
    }
    facts["body"] = _body_text(root, max_chars=settings.max_text_chars)
    facts["author"], facts["dates"], facts["authorship"] = author_and_dates(
        root,
        facts["structured_data"],
        article_meta,
        meta_author=_meta_content(root, name="author"),
    )
    try:
        facts["commerce"] = extract_commerce_facts(
            root, final_url=final_url, text_of=_text
        )
    except DOM_ERRORS as exc:
        dom_failure("extract_commerce_facts", exc)
    body_words = int(facts["body"].get("word_count", 0) or 0)
    gated_words = _expand_gated_words(root)
    facts["expand_gated_ratio"] = (
        round(min(1.0, gated_words / body_words), 4) if body_words > 0 else 0.0
    )
    return facts


def extract_page_facts(
    body: bytes,
    *,
    final_url: str,
    content_type: str = "",
    charset: str = "",
    status_code: int | None = None,
    redacted_headers: dict[str, str] | None = None,
    http_version: str = "",
    ttfb_ms: int | None = None,
    latency_ms: int | None = None,
    wire_bytes: int | None = None,
    decoded_bytes: int | None = None,
    settings=site_health_settings,
) -> dict[str, Any]:
    """Extract the bounded, deterministic page-facts dict for one page.

    PURE: ``body`` is the decoded HTML bytes; the remaining kwargs are the
    artifact's delivery facts. Returns a JSON-safe dict. HTML parsing is fully
    guarded — a malformed/empty page yields partial facts with ``has_html``
    reflecting whether any DOM was parsed. Never raises.
    """
    facts = _empty_facts()
    facts["extractor_version"] = EXTRACTOR_VERSION
    facts["content_type"] = (content_type or "").strip().lower()

    # Delivery facts never depend on the HTML parse succeeding.
    facts["delivery"] = _delivery_facts(
        final_url=final_url,
        status_code=status_code,
        redacted_headers=redacted_headers,
        http_version=http_version,
        ttfb_ms=ttfb_ms,
        latency_ms=latency_ms,
        wire_bytes=wire_bytes,
        decoded_bytes=decoded_bytes,
    )

    if not body:
        return facts

    root = _parse_root(body, charset=charset, settings=settings)
    if root is None:
        return facts
    facts.update(_extract_document(root, final_url=final_url, settings=settings))
    facts["extractor_version"] = EXTRACTOR_VERSION
    facts["content_type"] = (content_type or "").strip().lower()
    facts["delivery"] = _delivery_facts(
        final_url=final_url,
        status_code=status_code,
        redacted_headers=redacted_headers,
        http_version=http_version,
        ttfb_ms=ttfb_ms,
        latency_ms=latency_ms,
        wire_bytes=wire_bytes,
        decoded_bytes=decoded_bytes,
    )
    facts["robots"] = merge_x_robots_tag(
        facts.get("robots") or {},
        str((redacted_headers or {}).get("x-robots-tag") or ""),
    )
    return facts
