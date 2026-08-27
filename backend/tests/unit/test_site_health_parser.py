"""Unit tests for the Site Health page-fact parser + structured-data helpers.

Pure, offline: local HTML byte fixtures only (no live internet). Covers full
fact extraction, malformed/partial pages, the bounded limits, delivery/security
facts, and JSON-LD / microdata validation against the config schema map.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.analysis.site_health.dom import node_text, xpath
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.structured_data import (
    parse_jsonld_blocks,
    validate_microdata_types,
)
from app.core.config.site_health_contracts import (
    EXTRACTOR_VERSION,
)
from app.core.config.site_health_rules import (
    ANSWER_FIRST_MAX_HOPS,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)

_FULL_PAGE = b"""
<html>
  <head>
    <title>Acme Widgets</title>
    <meta name="description" content="Best widgets on the web.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="https://acme.example.com/widgets">
    <meta property="og:title" content="Acme Widgets">
    <meta property="og:description" content="Buy widgets">
    <meta name="twitter:card" content="summary">
    <link rel="stylesheet" href="/styles.css">
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Organization",
       "name":"Acme","url":"https://acme.example.com"}
    </script>
  </head>
  <body>
    <h1>Acme Widgets</h1>
    <h2>Section one</h2>
    <h2>Section two</h2>
    <p>Widgets are great. We sell many widgets to many happy customers.</p>
    <img src="/a.png" alt="a picture">
    <img src="/b.png">
    <a href="https://acme.example.com/about" rel="nofollow">About</a>
    <a href="https://external.org/x">External</a>
    <a href="#frag">skip</a>
    <script src="/app.js"></script>
    <script src="/async.js" async></script>
  </body>
</html>
"""


def _facts(body: bytes, **kwargs):
    defaults: dict[str, Any] = dict(
        final_url="https://acme.example.com/widgets",
        content_type="text/html",
        status_code=200,
        redacted_headers={
            "content-encoding": "gzip",
            "cache-control": "max-age=60",
            "strict-transport-security": "max-age=31536000",
            "content-security-policy": "default-src 'self'",
        },
        http_version="HTTP/2",
        ttfb_ms=42,
        latency_ms=90,
        wire_bytes=1234,
        decoded_bytes=4567,
    )
    defaults.update(kwargs)
    return extract_page_facts(body, **defaults)


def test_full_page_extraction():
    facts = _facts(_FULL_PAGE)
    assert facts["has_html"] is True
    assert facts["title"] == "Acme Widgets"
    assert facts["meta_description"] == "Best widgets on the web."
    assert facts["robots"] == {"noindex": False, "nofollow": False}
    assert facts["canonical_url"] == "https://acme.example.com/widgets"
    assert facts["open_graph"]["og:title"] == "Acme Widgets"
    assert facts["open_graph"]["og:description"] == "Buy widgets"
    assert facts["twitter"]["twitter:card"] == "summary"
    assert facts["headings"]["h1_count"] == 1
    assert facts["headings"]["counts"]["h2"] == 2
    assert facts["images"]["count"] == 2
    assert facts["images"]["missing_alt"] == 1
    assert facts["body"]["word_count"] > 0
    assert "widgets" in facts["body"]["text"].lower()
    assert facts["extractor_version"] == EXTRACTOR_VERSION


def test_structured_data_extraction_and_validation():
    facts = _facts(_FULL_PAGE)
    sd = facts["structured_data"]
    assert sd["count"] == 1
    assert sd["has_json_ld"] is True
    assert "Organization" in sd["types"]
    block = sd["blocks"][0]
    assert block["type"] == "Organization"
    assert block["valid"] is True
    assert set(block["present"]) == {"name", "url"}


def test_jsonld_type_array_keeps_every_recognized_type():
    body = b"""
    <html><head><title>Widget guide</title>
      <script type="application/ld+json">
        {
          "@type": ["UnregisteredExtension", "Article", "HowTo"],
          "headline": "Widget guide",
          "name": "Widget guide",
          "author": {"name": "Jane Doe"},
          "datePublished": "2026-08-11",
          "step": [{"name": "Start"}]
        }
      </script>
    </head><body><h1>Widget guide</h1></body></html>
    """
    structured_data = _facts(body)["structured_data"]

    assert structured_data["types"] == ["Article", "HowTo"]
    assert [block["type"] for block in structured_data["blocks"]] == [
        "Article",
        "HowTo",
    ]


def test_links_and_assets_classification():
    facts = _facts(_FULL_PAGE)
    links = facts["links"]
    # Fragment + external anchors: fragment dropped, external kept but external.
    anchor_urls = [a["url"] for a in links["anchors"]]
    assert "https://acme.example.com/about" in anchor_urls
    assert "https://external.org/x" in anchor_urls
    assert not any("#frag" in u for u in anchor_urls)
    internal = {a["url"]: a["is_internal"] for a in links["anchors"]}
    assert internal["https://acme.example.com/about"] is True
    assert internal["https://external.org/x"] is False
    assert [a["rel"] for a in links["anchors"] if "about" in a["url"]] == ["nofollow"]
    assert len(links["scripts"]) == 2
    assert len(links["stylesheets"]) == 1
    # One sync script blocks; async does not; one stylesheet blocks.
    assert facts["blocking_resources"]["scripts"] == 1
    assert facts["blocking_resources"]["stylesheets"] == 1
    assert facts["blocking_resources"]["total"] == 2


def test_delivery_and_security_facts():
    facts = _facts(_FULL_PAGE)
    delivery = facts["delivery"]
    assert delivery["is_https"] is True
    assert delivery["scheme"] == "https"
    assert delivery["http_version"] == "HTTP/2"
    assert delivery["ttfb_ms"] == 42
    assert delivery["wire_bytes"] == 1234
    assert delivery["decoded_bytes"] == 4567
    assert delivery["content_encoding"] == "gzip"
    assert delivery["is_compressed"] is True
    assert delivery["cache_control"] == "max-age=60"
    sh = delivery["security_headers"]
    assert sh["strict-transport-security"] is True
    assert sh["content-security-policy"] is True
    assert sh["x-frame-options"] is False


def test_noindex_robots_directive():
    body = (
        b"<html><head><title>x</title>"
        b'<meta name="robots" content="noindex, nofollow"></head>'
        b"<body><h1>x</h1></body></html>"
    )
    facts = _facts(body)
    assert facts["robots"]["noindex"] is True
    assert facts["robots"]["nofollow"] is True


def test_http_final_url_not_https():
    facts = _facts(_FULL_PAGE, final_url="http://acme.example.com/widgets")
    assert facts["delivery"]["is_https"] is False
    assert facts["delivery"]["scheme"] == "http"


def test_empty_body_yields_partial_facts():
    facts = _facts(b"")
    assert facts["has_html"] is False
    assert facts["title"] == ""
    assert facts["structured_data"]["count"] == 0
    # Delivery facts still computed from the artifact fields.
    assert facts["delivery"]["is_https"] is True


def test_malformed_html_never_crashes():
    # ``<title>`` must be closed: it is RCDATA per HTML5, so an unclosed title
    # swallows the rest of the document as text (behavior that differs across
    # libxml2 versions). The rest stays malformed on purpose.
    body = b"<html><head><title>Broken</title><body><h1>hi</h1><a href='/x'>"
    facts = _facts(body)
    # lxml's recover parser tolerates it and still yields facts.
    assert facts["has_html"] is True
    assert facts["title"] == "Broken"
    assert facts["headings"]["h1_count"] == 1


def test_dom_read_failure_is_logged_while_an_empty_page_is_silent(caplog):
    """An extraction error and a genuinely empty page must not look alike.

    Both produce an empty fact bucket, and before sh-extractor-8 that was the
    whole story: a broken traversal was swallowed with ``except Exception:
    pass``, so the rules scored a parser bug as "this page has no CTAs".
    The bucket still fails open — but the failure now leaves a record, and an
    empty page still leaves none.
    """
    empty_page = b"<html><head><title>t</title></head><body></body></html>"

    with caplog.at_level(logging.DEBUG, logger="app.analysis.site_health.dom"):
        facts = _facts(empty_page)
    # A real page with nothing in it: empty results, and nothing to report.
    assert facts["has_html"] is True
    assert caplog.records == []

    # Now make one traversal raise the way a hostile document or an internal
    # bug would. The task still completes with partial facts...
    class _Exploding:
        def __getattr__(self, name):
            raise AttributeError(name)

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="app.analysis.site_health.dom"):
        assert node_text(_Exploding()) == ""
        assert xpath(_Exploding(), "//a") == []

    # ...and both failures are attributable to the operation that failed.
    assert len(caplog.records) == 2
    operations = [record.operation for record in caplog.records]
    assert operations == ["node_text", "xpath://a"]
    assert all(record.error_type == "AttributeError" for record in caplog.records)
    assert all(record.exc_info is not None for record in caplog.records)


def test_dom_errors_does_not_swallow_a_programming_error():
    """Fail-open covers bad HTML, not bad code.

    A ``KeyError`` or ``RuntimeError` from a traversal is a defect; catching
    it would hide the bug behind an empty fact bucket, which is exactly the
    failure mode sh-extractor-8 exists to remove.
    """

    class _Bug:
        def text_content(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        node_text(_Bug())


def test_malformed_jsonld_block_skipped_but_others_kept():
    body = (
        b"<html><head><title>x</title>"
        b'<script type="application/ld+json">{ not json }</script>'
        b'<script type="application/ld+json">'
        b'{"@type":"WebSite","name":"S","url":"https://s.example"}'
        b"</script></head><body><h1>x</h1></body></html>"
    )
    facts = _facts(body)
    sd = facts["structured_data"]
    assert sd["count"] == 1
    assert sd["blocks"][0]["type"] == "WebSite"
    assert sd["blocks"][0]["valid"] is True


def test_multiple_h1_counted():
    body = (
        b"<html><head><title>x</title></head>"
        b"<body><h1>one</h1><h1>two</h1></body></html>"
    )
    facts = _facts(body)
    assert facts["headings"]["h1_count"] == 2


def test_link_bound_enforced(monkeypatch):
    # Build a page with more anchors than the configured bound.
    limit = site_health_settings.max_links_per_page
    anchors = "".join(
        f'<a href="https://acme.example.com/p{i}">l</a>' for i in range(limit + 25)
    )
    body = (
        f"<html><head><title>x</title></head><body>{anchors}</body></html>"
    ).encode()
    facts = _facts(body)
    assert len(facts["links"]["anchors"]) == limit


def test_structured_data_block_bound_enforced():
    blocks = [
        '{"@type":"Organization","name":"n","url":"https://u.example"}'
        for _ in range(site_health_settings.max_structured_data_blocks + 5)
    ]
    facts = parse_jsonld_blocks(
        blocks, max_blocks=site_health_settings.max_structured_data_blocks
    )
    assert len(facts) == site_health_settings.max_structured_data_blocks


def test_text_bound_enforced():
    long_text = "word " * 5000
    body = (
        f"<html><head><title>x</title></head><body><p>{long_text}</p></body></html>"
    ).encode()
    facts = extract_page_facts(
        body,
        final_url="https://x.example/",
        content_type="text/html",
        settings=site_health_settings,
    )
    assert len(facts["body"]["text"]) <= site_health_settings.max_text_chars


def test_jsonld_missing_required_property_invalid():
    facts = parse_jsonld_blocks(['{"@type":"Article","headline":"H"}'], max_blocks=10)
    assert len(facts) == 1
    assert facts[0]["type"] == "Article"
    assert facts[0]["valid"] is False
    assert "author" in facts[0]["missing"]
    assert "datePublished" in facts[0]["missing"]


def test_jsonld_graph_and_type_url_normalization():
    payload = (
        '{"@context":"https://schema.org","@graph":['
        '{"@type":"http://schema.org/WebPage","name":"P"},'
        '{"@type":["Organization"],"name":"O","url":"https://o.example"}]}'
    )
    facts = parse_jsonld_blocks([payload], max_blocks=10)
    types = {f["type"] for f in facts}
    assert types == {"WebPage", "Organization"}


def test_jsonld_preserves_explicit_architecture_relationship_urls():
    payload = """{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "item": {"@id": "/shop"}},
        {"@type": "ListItem", "position": 2, "item": "https://x.test/p"}
      ],
      "isPartOf": {"@id": "https://x.test/help"}
    }"""
    (block,) = parse_jsonld_blocks([payload], max_blocks=10)
    assert block["breadcrumb_items"] == ["/shop", "https://x.test/p"]
    assert block["is_part_of_url"] == "https://x.test/help"


def test_unrecognized_jsonld_type_ignored():
    facts = parse_jsonld_blocks(['{"@type":"UnknownThing","name":"x"}'], max_blocks=10)
    assert facts == []


def test_microdata_validation():
    facts = validate_microdata_types(
        ["https://schema.org/Product", "https://schema.org/Nope"],
        max_blocks=10,
    )
    assert len(facts) == 1
    assert facts[0]["type"] == "Product"
    assert facts[0]["syntax"] == "microdata"
    assert facts[0]["valid"] is False


# --- charset handling (handoff finding 5) ---------------------------------


def test_bogus_charset_falls_back_and_never_crashes():
    # An arbitrary/unknown declared charset must NOT crash extraction: it is
    # validated away (codecs.lookup fails) and lxml auto-detects instead. The
    # parser still returns the page facts.
    facts = _facts(_FULL_PAGE, charset="totally-not-a-real-charset")
    assert facts["title"] == "Acme Widgets"
    assert facts["extractor_version"] == EXTRACTOR_VERSION


def test_empty_charset_auto_detects():
    facts = _facts(_FULL_PAGE, charset="")
    assert facts["title"] == "Acme Widgets"


def test_valid_declared_charset_is_honored():
    # A Latin-1 page whose non-ASCII byte must be decoded with the declared
    # charset (not UTF-8) to yield the correct title character.
    body = ("<html><head><title>Caf\u00e9</title></head><body>x</body></html>").encode(
        "latin-1"
    )
    facts = _facts(body, charset="ISO-8859-1")
    assert facts["title"] == "Caf\u00e9"


# --- v2 P2 (sh-extractor-2): citability / extractability / hreflang fields ---

_V2_PAGE = b"""
<html>
  <head>
    <title>Acme Widgets Guide</title>
    <meta name="author" content="Meta Author">
    <meta property="article:published_time" content="2026-01-15T10:00:00Z">
    <meta property="article:modified_time" content="2026-06-01T10:00:00Z">
    <link rel="alternate" hreflang="en" href="https://acme.example.com/widgets">
    <link rel="alternate" hreflang="fr" href="/fr/widgets">
    <link rel="stylesheet" href="/styles.css">
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Article",
       "headline":"Acme Widgets Guide",
       "author":{"@type":"Person","name":"JSONLD Author"},
       "datePublished":"2026-01-10","dateModified":"2026-05-30"}
    </script>
  </head>
  <body>
    <nav><a href="/nav">nav</a></nav>
    <main>
      <article>
        <h1>Acme Widgets Guide</h1>
        <p>Widgets are reliable little gadgets that just work for everyone.</p>
        <h2>What are widgets?</h2>
        <p>Answer text here.</p>
        <h2>Installation</h2>
        <h3>Do widgets work offline?</h3>
        <a href="https://docs.example.org/setup">Docs</a>
        <a href="https://external.org/x">External</a>
        <a href="https://docs.example.org/api">Docs API</a>
      </article>
    </main>
    <script>var appState = {"boot": true};</script>
    <script src="/app.js"></script>
  </body>
</html>
"""


def test_extractor_version_is_sh_extractor_12():
    # sh-extractor-12 also freezes explicit breadcrumb relationship URLs.
    # while retaining the DOM
    # traversal failure boundary.
    assert EXTRACTOR_VERSION == "sh-extractor-12"
    assert _facts(_V2_PAGE)["extractor_version"] == "sh-extractor-12"


def test_visible_breadcrumb_links_preserve_resolvable_urls():
    facts = _facts(
        b"""<html><body><main>
        <nav aria-label="Breadcrumb">
          <a href="/">Home</a><a href="/products">Products</a>
          <span>Widget</span>
        </nav></main></body></html>"""
    )
    assert facts["commerce"]["breadcrumbs"] == ["Home", "Products", "Widget"]
    assert facts["commerce"]["breadcrumb_links"] == [
        {"url": "https://acme.example.com/", "title": "Home"},
        {"url": "https://acme.example.com/products", "title": "Products"},
    ]


def test_breadcrumb_label_limit_does_not_discard_later_parent_links():
    labels = b"".join(f"<span>Label {index}</span>".encode() for index in range(16))
    facts = _facts(
        b"<html><body><nav aria-label='Breadcrumb'>"
        + labels
        + b"<a href='/parent'>Parent</a></nav></body></html>"
    )

    assert len(facts["commerce"]["breadcrumbs"]) == 16
    assert facts["commerce"]["breadcrumb_links"] == [
        {"url": "https://acme.example.com/parent", "title": "Parent"}
    ]


# --- sh-extractor-3: industry-role classifier facts -------------------------

_ROLE_FACTS_PAGE = b"""
<html><body>
  <h1>Admissions</h1>
  <a href="/apply" class="btn btn-primary">Apply Now</a>
  <a href="/prospectus" role="button">Download prospectus</a>
  <a href="/about">About the school</a>
  <a href="https://other.test/x">External partner</a>
  <button>Enquire</button>
  <form>
    <label for="pn">Parent Name</label><input id="pn" name="parent_name">
    <input name="grade" placeholder="Grade applying for">
    <textarea aria-label="Questions for us"></textarea>
    <input type="hidden" name="csrf" value="secret-token">
    <input type="submit" value="Submit Enquiry">
  </form>
</body></html>
"""


def test_cta_text_keeps_button_affordances_and_drops_navigation():
    facts = _facts(_ROLE_FACTS_PAGE, final_url="https://school.test/admissions")
    # Buttons, submit inputs, and button-like anchors qualify; a plain
    # navigation anchor does not, or the real CTAs would be drowned out.
    assert facts["cta_text"] == [
        "Apply Now",
        "Download prospectus",
        "Enquire",
        "Submit Enquiry",
    ]


def test_form_fields_capture_labels_never_values():
    facts = _facts(_ROLE_FACTS_PAGE, final_url="https://school.test/admissions")
    assert facts["form_fields"] == [
        "Parent Name",
        "Grade applying for",
        "Questions for us",
    ]
    # Hidden fields and any typed value stay out of the evidence entirely.
    assert "secret-token" not in str(facts)


def test_link_context_is_internal_anchor_text_only():
    facts = _facts(_ROLE_FACTS_PAGE, final_url="https://school.test/admissions")
    assert facts["link_context"] == [
        "Apply Now",
        "Download prospectus",
        "About the school",
    ]
    assert "External partner" not in facts["link_context"]


def test_role_facts_are_empty_for_a_page_without_them():
    facts = _facts(b"<html><body><p>Just prose.</p></body></html>")
    assert facts["cta_text"] == []
    assert facts["form_fields"] == []
    assert facts["link_context"] == []


def test_h3_texts_and_question_heading_ratio():
    facts = _facts(_V2_PAGE)
    headings = facts["headings"]
    assert headings["h3_texts"] == ["Do widgets work offline?"]
    # h2 ("What are widgets?", "Installation") + h3 ("Do widgets work
    # offline?"): 2 questions out of 3 headings.
    assert facts["question_heading_ratio"] == round(2 / 3, 4)


def test_author_and_dates_jsonld_wins_over_meta():
    facts = _facts(_V2_PAGE)
    # JSON-LD author/datePublished outrank the meta tags.
    assert facts["author"] == "JSONLD Author"
    assert facts["dates"] == {"published": "2026-01-10", "modified": "2026-05-30"}


def test_author_and_dates_meta_fallbacks():
    body = (
        b"<html><head>"
        b'<meta name="author" content="Meta Author">'
        b'<meta property="article:published_time" content="2026-01-15T10:00:00Z">'
        b"</head><body><p>text</p></body></html>"
    )
    facts = _facts(body)
    assert facts["author"] == "Meta Author"
    assert facts["dates"]["published"] == "2026-01-15T10:00:00Z"
    assert facts["dates"]["modified"] == ""


def test_dates_time_element_fallback():
    body = (
        b"<html><body><p>text</p>"
        b'<time datetime="2026-03-01">March 2026</time>'
        b"</body></html>"
    )
    facts = _facts(body)
    assert facts["dates"]["published"] == "2026-03-01"


def test_outbound_domains_sorted_deduped_external_only():
    facts = _facts(_V2_PAGE)
    # Relative /nav is same-origin; the two docs.example.org links dedupe.
    assert facts["outbound_domains"] == ["docs.example.org", "external.org"]


def test_outbound_domains_exclude_same_registrable_domain():
    # www / apex / sibling subdomains of the page's own site are the SAME
    # site, never citations — only genuinely external hosts count.
    body = (
        b"<html><body><p>x</p>"
        b'<a href="https://www.example.com/y">www subdomain</a>'
        b'<a href="https://example.com/z">apex</a>'
        b'<a href="https://blog.example.com/w">sibling subdomain</a>'
        b'<a href="https://external.org/x">external</a>'
        b"</body></html>"
    )
    facts = _facts(body, final_url="https://example.com/widgets")
    assert facts["outbound_domains"] == ["external.org"]
    # And from the www host's perspective, apex is same-site too.
    facts = _facts(body, final_url="https://www.example.com/widgets")
    assert facts["outbound_domains"] == ["external.org"]


def test_landmarks_detected():
    facts = _facts(_V2_PAGE)
    assert facts["landmarks"] == {"main": True, "article": True, "nav": True}
    assert _facts(b"<html><body><p>x</p></body></html>")["landmarks"] == {
        "main": False,
        "article": False,
        "nav": False,
    }


def test_hreflang_alternates_resolved_absolute():
    facts = _facts(_V2_PAGE)
    assert facts["hreflang_alternates"] == [
        {"hreflang": "en", "url": "https://acme.example.com/widgets"},
        {"hreflang": "fr", "url": "https://acme.example.com/fr/widgets"},
    ]


def test_first_answer_text_is_first_block_after_first_heading():
    facts = _facts(_V2_PAGE)
    assert facts["first_answer_text"] == (
        "Widgets are reliable little gadgets that just work for everyone."
    )
    # No heading -> no answer text.
    assert _facts(b"<html><body><p>x</p></body></html>")["first_answer_text"] == ""


def test_first_answer_text_container_wrapped_heading():
    # Regression (review MAJOR-1): an h1 wrapped in its own container has no
    # following siblings — the bounded document-order walk past the parent
    # must still find the answer block.
    body = (
        b"<html><body>"
        b"<header><h1>Widget Guide</h1></header>"
        b"<main><p>The answer paragraph lives right here.</p></main>"
        b"</body></html>"
    )
    assert _facts(body)["first_answer_text"] == (
        "The answer paragraph lives right here."
    )


def test_first_answer_text_walk_skips_script_subtrees():
    # The document-order walk never returns script/style bodies as "answers".
    body = (
        b"<html><body>"
        b"<header><h1>Widget Guide</h1></header>"
        b"<script>var notAnAnswer = true;</script>"
        b"<main><p>Real answer text after the script.</p></main>"
        b"</body></html>"
    )
    assert _facts(body)["first_answer_text"] == ("Real answer text after the script.")


def test_first_answer_text_hop_bound_gives_up():
    # More elements than the config hop bound between the wrapped heading and
    # the first content block -> empty (bounded, deterministic).
    empties = "<div></div>" * (ANSWER_FIRST_MAX_HOPS + 2)
    body = (
        b"<html><body><header><h1>Widget Guide</h1></header>"
        + empties.encode()
        + b"<main><p>Too far away to be the answer.</p></main></body></html>"
    )
    assert _facts(body)["first_answer_text"] == ""


def test_inline_script_chars_count_srcless_scripts_only():
    # Only the src-less <script> body counts; the src script contributes 0.
    body = (
        b"<html><body><p>x</p>"
        b"<script>var a = 1;</script>"
        b'<script src="/x.js"></script>'
        b"</body></html>"
    )
    assert _facts(body)["inline_script_chars"] == len("var a = 1;")
    assert _facts(b"<html><body><p>x</p></body></html>")["inline_script_chars"] == 0
    # The richer page's inline JS app script counts exactly — its JSON-LD
    # block is data, not JS, and contributes nothing.
    assert _facts(_V2_PAGE)["inline_script_chars"] == len(
        'var appState = {"boot": true};'
    )


def test_inline_script_chars_skip_non_js_types():
    # JSON-LD / importmap / template bodies never count; JS MIME types and
    # type-less scripts do.
    body = (
        b"<html><body><p>x</p>"
        b'<script type="application/ld+json">{"@type":"WebPage","name":"x"}</script>'
        b'<script type="importmap">{"imports":{}}</script>'
        b"<script>var js = 1;</script>"
        b'<script type="module">export const m = 1;</script>'
        b'<script type="text/javascript">var tj = 1;</script>'
        b"</body></html>"
    )
    expected = len("var js = 1;") + len("export const m = 1;") + len("var tj = 1;")
    assert _facts(body)["inline_script_chars"] == expected


def test_expand_gated_ratio_counts_collapsed_subtrees():
    body = (
        b"<html><body>"
        b"<p>visible words one two three four five six seven eight</p>"
        b"<details><p>gated alpha beta gamma</p></details>"
        b"</body></html>"
    )
    facts = _facts(body)
    # 4 gated words out of 13 body words (the visible <p> and the details
    # text concatenate without a separator in the body text, merging
    # "eight"+"gated" into one word).
    assert facts["body"]["word_count"] == 13
    assert facts["expand_gated_ratio"] == round(4 / 13, 4)
    # Nothing gated -> 0.0.
    assert _facts(b"<html><body><p>x y</p></body></html>")["expand_gated_ratio"] == 0.0


def test_expand_gated_ratio_never_double_counts_nested_gates():
    body = (
        b"<html><body>"
        b"<p>visible words one two three four five six seven eight</p>"
        b'<div aria-expanded="false"><p>gated alpha beta gamma</p>'
        b"<details><p>nested delta epsilon</p></details></div>"
        b"</body></html>"
    )
    facts = _facts(body)
    # The outer div's text is counted ONCE (its own concatenated text merges
    # "gamma"+"nested" -> 6 gated words); the nested details adds nothing —
    # double-counting it would push the ratio to 9/15.
    assert facts["body"]["word_count"] == 15
    assert facts["expand_gated_ratio"] == round(6 / 15, 4)


# --- v2 P2 (sh-extractor-2): structured-data recognition + enrichment --------


def test_newly_recognized_type_kept_with_empty_required_contract():
    # Service is recognized by the P2 set but carries no v1 required contract.
    blocks = parse_jsonld_blocks(
        ['{"@type":"Service","name":"Consulting","provider":"Acme"}'],
        max_blocks=10,
    )
    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "Service"
    assert block["required"] == []
    assert block["missing"] == []
    assert block["valid"] is True
    # Enrichment still lands.
    assert block["name"] == "Consulting"
    assert "name" in block["props_present"]


def test_jsonld_enrichment_name_author_dates_same_as():
    blocks = parse_jsonld_blocks(
        [
            '{"@type":"Organization","name":"Acme","url":"https://acme.example",'
            '"author":[{"@type":"Person","name":"First Author"}],'
            '"datePublished":"2026-01-10","dateModified":"2026-05-30",'
            '"sameAs":["https://twitter.com/acme","https://linkedin.com/acme"]}'
        ],
        max_blocks=10,
    )
    block = blocks[0]
    assert block["name"] == "Acme"
    # list-of-dicts author collapses to the first resolvable name.
    assert block["author"] == "First Author"
    assert block["date_published"] == "2026-01-10"
    assert block["date_modified"] == "2026-05-30"
    assert block["same_as"] == [
        "https://twitter.com/acme",
        "https://linkedin.com/acme",
    ]


def test_jsonld_name_falls_back_to_headline():
    payload = (
        '{"@type":"Article","headline":"The Headline","author":"A","datePublished":"D"}'
    )
    blocks = parse_jsonld_blocks([payload], max_blocks=10)
    assert blocks[0]["name"] == "The Headline"


def test_props_present_supports_dotted_offer_paths():
    blocks = parse_jsonld_blocks(
        [
            '{"@type":"Product","name":"Widget",'
            '"offers":{"@type":"Offer","price":"9.99","priceCurrency":"USD"}}'
        ],
        max_blocks=10,
    )
    props = blocks[0]["props_present"]
    assert "name" in props
    assert "offers" in props
    assert "offers.price" in props
    assert "offers.priceCurrency" in props
    # Sorted + bounded to the config path set.
    assert props == sorted(props)


def test_microdata_blocks_carry_empty_enrichment_fields():
    blocks = validate_microdata_types(
        ["https://schema.org/Organization"], max_blocks=10
    )
    assert len(blocks) == 1
    block = blocks[0]
    assert block["name"] == ""
    assert block["author"] == ""
    assert block["date_published"] == ""
    assert block["date_modified"] == ""
    assert block["same_as"] == []
    assert block["props_present"] == []
