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
from typing import Any
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lxml_html

from app.analysis.site_health.page_types import is_question_heading
from app.analysis.site_health.structured_data import (
    parse_jsonld_blocks,
    validate_microdata_types,
)
from app.connectors.web_evidence.url_policy import registrable_domain
from app.core.config.site_health import (
    ANSWER_FIRST_MAX_HOPS,
    EXTRACTOR_VERSION,
    INLINE_SCRIPT_JAVASCRIPT_TYPES,
    LINK_KIND_ANCHOR,
    LINK_KIND_IMAGE,
    LINK_KIND_SCRIPT,
    LINK_KIND_STYLESHEET,
    site_health_settings,
)

# Bounded per-field caps so a single hostile attribute can never bloat the
# persisted facts dict.
_MAX_TITLE_CHARS = 2048
_MAX_META_CHARS = 4096
_MAX_HEADING_CHARS = 512
_MAX_HEADINGS_KEPT = 50
_MAX_URL_CHARS = 2048
_MAX_ANCHOR_TEXT_CHARS = 512
# v2 P2 (sh-extractor-2) field caps.
_MAX_AUTHOR_CHARS = 256
_MAX_DATE_CHARS = 64
_MAX_OUTBOUND_DOMAINS = 100
_MAX_DOMAIN_CHARS = 255
_MAX_HREFLANG_ALTERNATES = 50
_MAX_HREFLANG_CHARS = 35
_MAX_FIRST_ANSWER_CHARS = 512
_MAX_INLINE_SCRIPT_CHARS = 500_000

# The security response headers whose mere presence the delivery facts record.
_SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
)


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


def _text(node: Any) -> str:
    try:
        return (node.text_content() or "").strip()
    except Exception:
        return ""


def _parse_robots_directives(root: Any) -> dict[str, bool]:
    """Extract robots meta directives (noindex / nofollow) from the head.

    Reads every ``<meta name="robots">`` (and the ``googlebot`` variant),
    splitting on commas. Deterministic + case-insensitive.
    """
    noindex = False
    nofollow = False
    try:
        nodes = root.xpath(
            "//meta[translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='robots' or "
            "translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='googlebot']"
        )
    except Exception:
        nodes = []
    for node in nodes:
        content = (node.get("content") or "").lower()
        tokens = {tok.strip() for tok in content.split(",")}
        if "noindex" in tokens or "none" in tokens:
            noindex = True
        if "nofollow" in tokens or "none" in tokens:
            nofollow = True
    return {"noindex": noindex, "nofollow": nofollow}


def _meta_content(root: Any, *, name: str) -> str:
    try:
        nodes = root.xpath(
            "//meta[translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')=$n]",
            n=name.lower(),
        )
    except Exception:
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
    except Exception:
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
    except Exception:
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
        except Exception:
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


def _images(root: Any) -> dict[str, int]:
    """Count images and how many are missing a non-empty alt attribute."""
    try:
        nodes = root.xpath("//img")
    except Exception:
        nodes = []
    total = len(nodes)
    missing_alt = 0
    for node in nodes:
        alt = node.get("alt")
        if alt is None or not str(alt).strip():
            missing_alt += 1
    return {"count": total, "missing_alt": missing_alt}


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
    except Exception:
        pass
    raw = _text(node)
    text = " ".join(raw.split())[:max_chars]
    word_count = len(text.split()) if text else 0
    return {"text": text, "word_count": word_count}


def _links_and_assets(
    root: Any, *, base_host: str, max_links: int
) -> dict[str, list[dict]]:
    """Collect bounded anchors + img/script/stylesheet assets in document order.

    Each entry carries the raw ``url`` (bounded), the ``kind``, an
    ``is_internal`` heuristic (same host as the final URL when both are
    absolute), and, for anchors, the ``rel`` + bounded anchor text. Bounded by
    ``max_links`` PER kind so the persisted facts stay small.
    """
    anchors: list[dict] = []
    images: list[dict] = []
    scripts: list[dict] = []
    stylesheets: list[dict] = []

    def _internal(url: str) -> bool:
        try:
            host = urlsplit(url).hostname
        except Exception:
            return False
        if host is None:
            # A relative URL is same-origin by definition.
            return True
        return bool(base_host) and host.lower() == base_host.lower()

    try:
        for anchor in root.iter("a"):
            if len(anchors) >= max_links:
                break
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            anchors.append(
                {
                    "kind": LINK_KIND_ANCHOR,
                    "url": href[:_MAX_URL_CHARS],
                    "is_internal": _internal(href),
                    "rel": (anchor.get("rel") or "")[:128],
                    "anchor_text": _text(anchor)[:_MAX_ANCHOR_TEXT_CHARS],
                }
            )
    except Exception:
        pass

    try:
        for img in root.iter("img"):
            if len(images) >= max_links:
                break
            src = (img.get("src") or "").strip()
            if not src:
                continue
            images.append(
                {
                    "kind": LINK_KIND_IMAGE,
                    "url": src[:_MAX_URL_CHARS],
                    "is_internal": _internal(src),
                }
            )
    except Exception:
        pass

    try:
        for script in root.iter("script"):
            if len(scripts) >= max_links:
                break
            src = (script.get("src") or "").strip()
            if not src:
                continue
            scripts.append(
                {
                    "kind": LINK_KIND_SCRIPT,
                    "url": src[:_MAX_URL_CHARS],
                    "is_internal": _internal(src),
                }
            )
    except Exception:
        pass

    try:
        for link in root.iter("link"):
            if len(stylesheets) >= max_links:
                break
            rel = (link.get("rel") or "").strip().lower()
            if "stylesheet" not in rel.split():
                continue
            href = (link.get("href") or "").strip()
            if not href:
                continue
            stylesheets.append(
                {
                    "kind": LINK_KIND_STYLESHEET,
                    "url": href[:_MAX_URL_CHARS],
                    "is_internal": _internal(href),
                }
            )
    except Exception:
        pass

    return {
        "anchors": anchors,
        "images": images,
        "scripts": scripts,
        "stylesheets": stylesheets,
    }


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
    except Exception:
        raw_jsonld = []
    jsonld_facts = parse_jsonld_blocks(raw_jsonld, max_blocks=max_blocks)

    itemtypes: list[str] = []
    try:
        for node in root.xpath("//*[@itemscope][@itemtype]"):
            itemtype = (node.get("itemtype") or "").strip()
            if itemtype:
                itemtypes.append(itemtype)
    except Exception:
        itemtypes = []
    microdata_facts = validate_microdata_types(itemtypes, max_blocks=max_blocks)

    blocks = (jsonld_facts + microdata_facts)[:max_blocks]
    return {
        "blocks": blocks,
        "count": len(blocks),
        "has_json_ld": bool(jsonld_facts),
        "has_microdata": bool(microdata_facts),
        "types": sorted({b["type"] for b in blocks}),
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
    except Exception:
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


def _author_and_dates(
    root: Any, structured_data: dict[str, Any], article_meta: dict[str, str]
) -> tuple[str, dict[str, str]]:
    """Author byline + published/modified dates (bounded, precedence-ordered).

    Author precedence: JSON-LD ``author`` -> ``<meta name="author">`` ->
    ``article:author``. Date precedence: JSON-LD
    ``datePublished``/``dateModified`` -> ``article:published_time`` /
    ``article:modified_time`` -> the first ``<time datetime>``. The first
    non-empty value wins at each level (deterministic).
    """
    author = ""
    published = ""
    modified = ""
    for block in structured_data.get("blocks") or []:
        if not author:
            author = str(block.get("author") or "").strip()
        if not published:
            published = str(block.get("date_published") or "").strip()
        if not modified:
            modified = str(block.get("date_modified") or "").strip()
    if not author:
        author = _meta_content(root, name="author").strip()
    if not author:
        author = (article_meta.get("article:author") or "").strip()
    if not published:
        published = (article_meta.get("article:published_time") or "").strip()
    if not modified:
        modified = (article_meta.get("article:modified_time") or "").strip()
    if not published:
        try:
            for node in root.xpath("//time[@datetime]"):
                candidate = (node.get("datetime") or "").strip()
                if candidate:
                    published = candidate
                    break
        except Exception:
            pass
    return (
        author[:_MAX_AUTHOR_CHARS],
        {
            "published": published[:_MAX_DATE_CHARS],
            "modified": modified[:_MAX_DATE_CHARS],
        },
    )


def _outbound_domains(anchors: list[dict], *, base_host: str) -> list[str]:
    """Unique external anchor hosts (sorted, bounded).

    Reads the already-bounded anchor facts: an anchor counts as outbound when
    it is absolute, HTTP(S), and NOT same-SITE — hosts on the page's own
    registrable domain (apex, www, or any sibling subdomain) are the same
    site, never citations. Relative/anchorless URLs are same-origin by the
    link extractor's own heuristic and never count. When the page host has
    no registrable domain (e.g. an IP), falls back to exact-host matching.
    """
    base_registrable = registrable_domain(base_host) if base_host else ""
    domains: set[str] = set()
    for entry in anchors or []:
        if bool(entry.get("is_internal")):
            continue
        raw = str(entry.get("url") or "").strip()
        try:
            parts = urlsplit(raw)
        except Exception:
            continue
        host = (parts.hostname or "").lower()
        if not host or parts.scheme not in ("http", "https"):
            continue
        if base_registrable:
            if registrable_domain(host) == base_registrable:
                continue
        elif base_host and host == base_host.lower():
            continue
        domains.add(host[:_MAX_DOMAIN_CHARS])
        if len(domains) >= _MAX_OUTBOUND_DOMAINS:
            break
    return sorted(domains)


def _landmarks(root: Any) -> dict[str, bool]:
    """Presence of the main/article/nav landmark elements."""
    out = {"main": False, "article": False, "nav": False}
    for tag in out:
        try:
            out[tag] = bool(root.xpath(f"//{tag}"))
        except Exception:
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
    except Exception:
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
    except Exception:
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
        except Exception:
            continue
        alternates.append(
            {
                "hreflang": hreflang[:_MAX_HREFLANG_CHARS],
                "url": absolute[:_MAX_URL_CHARS],
            }
        )
    return alternates


def _first_answer_text(root: Any) -> str:
    """Text of the first non-empty block after the first h1/h2.

    The bounded answer-first heuristic input (spec §5.3): what an answer
    engine reads directly under the page's first heading. Empty when the
    page has no h1/h2 or no following content block.

    The fast path reads following siblings within the heading's parent. When
    the heading is wrapped in its own container (e.g.
    ``<header><h1/></header><main><p>answer</p></main>`` — no following
    siblings), a bounded document-order walk past the parent finds the first
    non-empty block-level text within ``ANSWER_FIRST_MAX_HOPS`` elements.
    """
    first_heading = None
    try:
        for node in root.iter():
            if node.tag in ("h1", "h2"):
                first_heading = node
                break
    except Exception:
        return ""
    if first_heading is None:
        return ""
    try:
        for sibling in first_heading.itersiblings():
            text = _text(sibling)
            if text:
                return " ".join(text.split())[:_MAX_FIRST_ANSWER_CHARS]
    except Exception:
        return ""
    # Container-wrapped heading: walk the elements AFTER the heading in
    # document order (bounded), skipping non-content subtrees.
    hops = 0
    seen_heading = False
    try:
        for node in root.iter():
            if node is first_heading:
                seen_heading = True
                continue
            if not seen_heading:
                continue
            hops += 1
            if hops > ANSWER_FIRST_MAX_HOPS:
                break
            if node.tag in ("script", "style", "noscript", "template"):
                continue
            text = _text(node)
            if text:
                return " ".join(text.split())[:_MAX_FIRST_ANSWER_CHARS]
    except Exception:
        return ""
    return ""


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
    except Exception:
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
        "images": {"count": 0, "missing_alt": 0},
        "body": {"text": "", "word_count": 0},
        "structured_data": {
            "blocks": [],
            "count": 0,
            "has_json_ld": False,
            "has_microdata": False,
            "types": [],
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
        "outbound_domains": [],
        "landmarks": {"main": False, "article": False, "nav": False},
        "question_heading_ratio": 0.0,
        "expand_gated_ratio": 0.0,
        "hreflang_alternates": [],
        "first_answer_text": "",
        "inline_script_chars": 0,
    }


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

    # Bound the bytes handed to the parser (defence against an oversize body
    # that slipped past the fetch cap). Use the response's declared charset
    # when present; otherwise let lxml auto-detect rather than hard-coding
    # UTF-8 (a mismatched hard-coded charset can mangle non-UTF-8 pages).
    bounded = body[: settings.max_html_bytes]
    declared_charset = _safe_parser_encoding(charset)
    parser = lxml_html.HTMLParser(
        recover=True, encoding=declared_charset, no_network=True
    )
    try:
        root = lxml_html.document_fromstring(bounded, parser=parser)
    except (etree.ParserError, ValueError):
        return facts
    if root is None:
        return facts

    facts["has_html"] = True

    try:
        title_node = next(root.iter("title"), None)
        if title_node is not None:
            facts["title"] = (_text(title_node))[:_MAX_TITLE_CHARS]
    except Exception:
        pass

    facts["meta_description"] = _meta_content(root, name="description")
    facts["robots"] = _parse_robots_directives(root)
    facts["canonical_url"] = _canonical_href(root)
    facts["open_graph"] = _meta_property_map(root, prefix="og:")
    facts["twitter"] = _meta_property_map(root, prefix="twitter:")
    # article:* OG properties (byline/dates) are a separate prefix family.
    article_meta = _meta_property_map(root, prefix="article:")
    facts["headings"] = _headings(root)
    facts["images"] = _images(root)
    facts["structured_data"] = _structured_data(
        root, max_blocks=settings.max_structured_data_blocks
    )

    base_host = ""
    try:
        base_host = urlsplit(final_url).hostname or ""
    except Exception:
        base_host = ""
    facts["links"] = _links_and_assets(
        root, base_host=base_host, max_links=settings.max_links_per_page
    )

    # v2 P2 (sh-extractor-2) fields: citability + extractability + hreflang.
    facts["author"], facts["dates"] = _author_and_dates(
        root, facts["structured_data"], article_meta
    )
    facts["outbound_domains"] = _outbound_domains(
        facts["links"]["anchors"], base_host=base_host
    )
    facts["landmarks"] = _landmarks(root)
    facts["question_heading_ratio"] = _question_heading_ratio(facts["headings"])
    facts["hreflang_alternates"] = _hreflang_alternates(root, final_url=final_url)
    facts["first_answer_text"] = _first_answer_text(root)
    # Inline-script sizing must read the tree BEFORE _body_text removes the
    # script subtrees.
    facts["inline_script_chars"] = _inline_script_chars(root)

    # Static blocking-resource heuristic: synchronous <script src> (no async/
    # defer) plus stylesheet <link>s block first render.
    blocking_scripts = 0
    try:
        for script in root.iter("script"):
            if not (script.get("src") or "").strip():
                continue
            if script.get("async") is not None or script.get("defer") is not None:
                continue
            blocking_scripts += 1
    except Exception:
        blocking_scripts = 0
    blocking_styles = len(facts["links"]["stylesheets"])
    facts["blocking_resources"] = {
        "scripts": blocking_scripts,
        "stylesheets": blocking_styles,
        "total": blocking_scripts + blocking_styles,
    }

    # Body text last (it mutates the tree by removing script/style subtrees).
    facts["body"] = _body_text(root, max_chars=settings.max_text_chars)

    # Click-to-expand gating: gated words as a fraction of the visible body
    # word count (details/aria-expanded subtrees survive _body_text's junk
    # removal, so this reads the post-body tree deliberately).
    body_words = int(facts["body"].get("word_count", 0) or 0)
    gated_words = _expand_gated_words(root)
    facts["expand_gated_ratio"] = (
        round(min(1.0, gated_words / body_words), 4) if body_words > 0 else 0.0
    )
    return facts
