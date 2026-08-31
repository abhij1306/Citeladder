"""Unit tests for the Site Health page-fact parser + structured-data helpers.

Pure, offline: local HTML byte fixtures only (no live internet). Covers full
fact extraction, malformed/partial pages, the bounded limits, delivery/security
facts, and JSON-LD / microdata validation against the config schema map.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.analysis.site_health import fact_source_support
from app.analysis.site_health.dom import node_text, xpath
from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.structured_data import (
    parse_jsonld_blocks,
    validate_microdata_types,
)
from app.core.config.site_health_acquisition import (
    SITE_HEALTH_MAX_CTA_TEXT_CHARS,
    SITE_HEALTH_MAX_CTA_TEXTS,
    SITE_HEALTH_MAX_HEADINGS_KEPT,
)
from app.core.config.site_health_contracts import (
    EXTRACTOR_VERSION,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)

_FULL_PAGE = b"""
<html lang="en">
  <head>
    <title>Acme Widgets</title>
    <meta name="description" content="Best widgets on the web.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="https://acme.example.com/widgets">
    <meta property="og:title" content="Acme Widgets">
    <meta property="og:description" content="Buy widgets">
    <meta name="twitter:card" content="summary">
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
    assert facts["robots"]["noindex"] is False
    assert facts["robots"]["nofollow"] is False
    assert facts["robots"]["nosnippet"] is False
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


def test_availability_requires_commerce_context() -> None:
    unrelated = _facts(b"<html><body>Support is available worldwide.</body></html>")
    assert unrelated["commerce"]["visible_availability"] == ""

    purchasable = _facts(
        b"<html><body>This item is available for purchase.</body></html>"
    )
    assert purchasable["commerce"]["visible_availability"] == "available for purchase"


def test_accessibility_viewport_and_snippet_facts_are_distinct() -> None:
    facts = _facts(
        b'<html lang="en"><head><meta name="robots" content="nosnippet">'
        b'<meta name="viewport" content="width=device-width"></head><body>'
        b'<h1>Title</h1><h3>Skipped</h3><img src="a.png" alt="">'
        b'<img src="b.png"><label for="email">Email</label>'
        b'<input id="email"><input id="missing"></body></html>',
        redacted_headers={"x-robots-tag": "max-snippet:0"},
    )
    assert facts["robots"]["nosnippet"] is True
    assert facts["robots"]["max_snippet"] == 0
    assert facts["images"] == {"count": 2, "missing_alt": 1, "decorative_alt": 1}
    assert facts["accessibility"]["controls_missing_accessible_name"] == 1
    assert facts["accessibility"]["heading_level_skips"] == 1
    assert facts["accessibility"]["document_language"] == "en"
    assert facts["mobile"]["viewport"]["declared"] is True


def test_header_robots_directives_survive_an_empty_body() -> None:
    facts = _facts(
        b"",
        redacted_headers={
            "X-Robots-Tag": "googlebot: noindex, nofollow, max-snippet:0"
        },
    )

    assert facts["has_html"] is False
    assert facts["robots"]["noindex"] is True
    assert facts["robots"]["nofollow"] is True
    assert facts["robots"]["max_snippet"] == 0


def test_robots_merge_preserves_bounded_meta_facts_and_restrictive_snippet() -> None:
    filler = ",".join(f"a-directive-{index:02d}" for index in range(40))
    facts = _facts(
        (
            '<html><head><meta name="robots" content="'
            f'{filler},noindex,max-snippet:-1,max-snippet:50">'
            "</head><body></body></html>"
        ).encode(),
        redacted_headers={"x-robots-tag": "max-snippet:0"},
    )

    assert len(facts["robots"]["directives"]) == 32
    assert facts["robots"]["noindex"] is True
    assert facts["robots"]["max_snippet"] == 0


def test_accessible_names_resolve_labelledby_and_native_buttons() -> None:
    facts = _facts(
        b'<html><body><span id="valid">Search</span><span id="empty"></span>'
        b'<input aria-labelledby="valid"><input aria-labelledby="missing">'
        b'<input aria-labelledby="empty"><button>Save</button><button></button>'
        b"</body></html>"
    )

    assert facts["accessibility"]["control_count"] == 5
    assert facts["accessibility"]["controls_missing_accessible_name"] == 3


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


def test_extractor_version_is_sh_extractor_13():
    # sh-extractor-1 includes targeted visible byline/date facts while retaining
    # the explicit breadcrumb relationship URLs of v12.
    assert EXTRACTOR_VERSION == "sh-extractor-1"
    assert _facts(_V2_PAGE)["extractor_version"] == "sh-extractor-1"


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


# --- the VISIBLE byline and date ---------------------------------------------
#
# Every source above this point is markup. A properly attributed article --
# the byline printed where a reader looks for it -- reported no author and no
# date, so author/date readiness checks failed it. Those rules ask
# whether the page tells a reader who wrote this and when; answering only from
# markup asked a different question.


def test_visible_byline_and_date_are_read_when_no_markup_declares_them():
    # Whitespace between block elements, as authored HTML has: the body
    # text is a flat string, so the byline needs a word boundary in front
    # of it to be found.
    body = (
        b"<html><body><article> "
        b"<h1>Choosing between oiled and lacquered oak</h1> "
        b'<p class="byline">By Ruth Ellery, 14 March 2026</p> '
        b"<p>The finish on an oak table decides how it ages.</p> "
        b"</article></body></html>"
    )
    facts = _facts(body)
    assert facts["author"] == "By Ruth Ellery"
    assert facts["dates"]["published"] == "14 March 2026"
    assert facts["authorship"] == {
        "visible_byline": "By Ruth Ellery",
        "visible_date": "14 March 2026",
        "visible_profile_url": "",
        "declared_author": "",
        "declared_author_source": "",
    }


def test_day_first_dates_are_recognised():
    # "14 March 2026" is the ordinary written form across Britain and Europe.
    # Only ISO and month-first were matched, so those articles read as undated.
    for written in (b"2 February 2026", b"11 Mar 2026", b"March 14, 2026"):
        body = (
            b'<html><body><p class="publication-date">Published '
            + written
            + b"</p></body></html>"
        )
        assert _facts(body)["dates"]["published"] != "", written


def test_declared_markup_still_outranks_the_visible_byline():
    # Precedence is unchanged: the visible scan is the LAST fallback, so a
    # page that declares its author keeps the declared value.
    body = (
        b"<html><head>"
        b'<meta name="author" content="Meta Author">'
        b"</head><body>"
        b'<p class="byline">By Someone Else, 14 March 2026</p>'
        b"</body></html>"
    )
    assert _facts(body)["author"] == "Meta Author"


def test_a_date_inside_json_ld_is_not_a_visible_date():
    # Script bodies are stripped before the visible scan, so a date that only
    # exists inside markup cannot be reported as printed on the page. Here the
    # block declares no datePublished, so nothing should be found.
    body = (
        b"<html><body>"
        b'<script type="application/ld+json">'
        b'{"@context":"https://schema.org","@type":"Article",'
        b'"headline":"H","somethingElse":"2 February 2026"}'
        b"</script>"
        b"<p>Body text with no date at all.</p>"
        b"</body></html>"
    )
    assert _facts(body)["dates"]["published"] == ""


def test_an_unlabelled_content_date_is_not_a_publication_date():
    body = (
        b"<html><body><article><h1>History</h1>"
        b"<p>The organization was founded on 2 February 2026.</p>"
        b"</article></body></html>"
    )
    facts = _facts(body)
    assert facts["dates"]["published"] == ""
    assert facts["authorship"]["visible_date"] == ""


def test_visible_authorship_is_not_limited_to_the_body_text_prefix():
    filler = b"<p>Background material without a date. </p>" * 100
    body = (
        b"<html><body><article><h1>A long article</h1>"
        + filler
        + b'<p class="byline">By Ruth Ellery, published 2 February 2026</p>'
        + b"</article></body></html>"
    )
    facts = _facts(body)
    assert facts["author"] == "By Ruth Ellery"
    assert facts["dates"]["published"] == "2 February 2026"


def test_ordered_navigation_is_not_procedural_content():
    body = (
        b"<html><body><nav><ol><li>One</li><li>Two</li><li>Three</li></ol></nav>"
        b"<p>Short primary content.</p></body></html>"
    )
    assert _facts(body)["ordered_list_steps"] == 0


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


# --- PR4 page-owned content and collection evidence -------------------------


def test_page_owned_content_facts_are_distinct_and_exclude_chrome_modules() -> None:
    facts = _facts(
        b"""
        <html><body>
          <nav><h2>Browse documentation</h2></nav>
          <main>
            <h1>Enterprise Search</h1>
            <p class="byline">By Ana</p>
            <p>Acme Search provides answer discovery for support teams so they
               resolve cases faster.</p>
            <a class="cta" href="/demo">Book a demo</a>
            <h2>What is enterprise search?</h2>
            <p>Enterprise search gives teams one place to find trusted answers
               quickly.</p>
            <section aria-label="Related articles">
              <article><h3>Related one</h3><a href="/one">One</a></article>
              <article><h3>Related two</h3><a href="/two">Two</a></article>
              <article><h3>Related three</h3><a href="/three">Three</a></article>
            </section>
          </main>
          <footer><h2>Company links</h2></footer>
        </body></html>
        """
    )

    lead = (
        "Acme Search provides answer discovery for support teams so they "
        "resolve cases faster."
    )
    assert facts["editorial_lead"] == lead
    assert facts["direct_answer"] == (
        "Enterprise search gives teams one place to find trusted answers quickly."
    )
    assert facts["entity_proposition"] == {
        "identity": "Enterprise Search",
        "proposition": lead,
        "provider": "Acme Search",
        "named_capability": "answer discovery",
        "audience_or_outcome": "support teams so they resolve cases faster",
        "next_action": "/demo",
    }
    assert facts["primary_heading_outline"] == [
        {"level": 1, "text": "Enterprise Search"},
        {"level": 2, "text": "What is enterprise search?"},
    ]
    # The document-wide Web Fundamentals heading facts intentionally retain
    # chrome/module headings; only the page-owned outline is scoped.
    assert facts["headings"]["h2_texts"] == [
        "Browse documentation",
        "What is enterprise search?",
        "Company links",
    ]
    assert facts["headings"]["h3_texts"] == [
        "Related one",
        "Related two",
        "Related three",
    ]


def test_collection_evidence_binds_affordances_to_one_bounded_container() -> None:
    long_control_text = "x" * (SITE_HEALTH_MAX_CTA_TEXT_CHARS + 40)
    body = f"""
        <html><body><main>
          <h1>Products</h1>
          <div class="toolbar">
            <output aria-controls="products" role="status">
              8 results {long_control_text}
            </output>
            <select name="sort" aria-controls="products">
              <option>Featured</option><option>Newest</option>
            </select>
            <button name="filter" aria-controls="products">
              Filter {long_control_text}
            </button>
          </div>
          <section id="products" aria-label="Products">
            <article><a href="/p/a">A</a></article>
            <article><a href="/p/b">B</a></article>
            <article><a href="/p/c">C</a></article>
            <article><a href="/p/d">D</a></article>
            <article><a href="/p/e">E</a></article>
            <article><a href="/p/f">F</a></article>
          </section>
        </main></body></html>
    """
    facts = _facts(body.encode())
    listing = facts["entity"]["listing"]
    evidence = listing["collection_evidence"]

    assert listing["largest_card_list_size"] == 6
    assert listing["distinct_card_list_targets"] == 6
    assert listing["has_result_count"] is True
    assert listing["has_sort_control"] is True
    assert listing["has_filter_control"] is True
    assert evidence["container"] == {
        "tag": "section",
        "label": "Products",
        "item_count": 6,
        "distinct_targets": 6,
    }
    assert evidence["affordances"] == [
        {
            "class": "result_count",
            "relation": "targets",
            "text": f"8 results {long_control_text}"[:SITE_HEALTH_MAX_CTA_TEXT_CHARS],
        },
        {
            "class": "sort",
            "relation": "targets",
            "text": "Featured Newest",
        },
        {
            "class": "filter",
            "relation": "targets",
            "text": f"Filter {long_control_text}"[:SITE_HEALTH_MAX_CTA_TEXT_CHARS],
        },
    ]
    assert all(
        set(item) == {"class", "relation", "text"}
        and len(item["text"]) <= SITE_HEALTH_MAX_CTA_TEXT_CHARS
        for item in evidence["affordances"]
    )
    assert set(evidence) == {"container", "affordances"}
    assert set(evidence["container"]) == {
        "tag",
        "label",
        "item_count",
        "distinct_targets",
    }


def test_semantic_pagination_navigation_binds_to_collection() -> None:
    facts = _facts(
        b"""
        <html><body><main>
          <h1>Products</h1>
          <section id="products" aria-label="Products">
            <article><a href="/p/a">A</a></article>
            <article><a href="/p/b">B</a></article>
            <article><a href="/p/c">C</a></article>
            <article><a href="/p/d">D</a></article>
            <article><a href="/p/e">E</a></article>
            <article><a href="/p/f">F</a></article>
          </section>
          <nav aria-label="Pagination" aria-controls="products">
            <a href="?page=2" rel="next">Next</a>
          </nav>
        </main></body></html>
        """
    )

    listing = facts["entity"]["listing"]
    assert listing["has_pagination"] is True
    assert {
        (item["class"], item["relation"])
        for item in listing["collection_evidence"]["affordances"]
    } == {("pagination", "targets"), ("pagination", "adjacent")}


def test_recommendation_cards_and_unrelated_controls_have_empty_evidence() -> None:
    facts = _facts(
        b"""
        <html><body><main>
          <h1>Research note</h1>
          <output role="status">13 products</output>
          <select name="sort"><option>Newest</option><option>Oldest</option></select>
          <section class="related-products" aria-label="Related products">
            <article><a href="/p/a">A</a></article>
            <article><a href="/p/b">B</a></article>
            <article><a href="/p/c">C</a></article>
            <article><a href="/p/d">D</a></article>
            <article><a href="/p/e">E</a></article>
            <article><a href="/p/f">F</a></article>
          </section>
        </main></body></html>
        """
    )
    listing = facts["entity"]["listing"]

    assert listing["largest_card_list_size"] == 6
    assert listing["distinct_card_list_targets"] == 6
    assert listing["has_result_count"] is False
    assert listing["has_sort_control"] is False
    assert listing["has_filter_control"] is False
    assert listing["collection_evidence"] == {
        "container": {
            "tag": "",
            "label": "",
            "item_count": 0,
            "distinct_targets": 0,
        },
        "affordances": [],
    }


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"", "application/pdf"),
        (
            b"<html><body><div id='app'></div>"
            b"<script src='/app.js'></script></body></html>",
            "text/html",
        ),
    ],
)
def test_page_owned_facts_have_stable_empty_shapes(
    body: bytes, content_type: str
) -> None:
    facts = _facts(body, content_type=content_type)

    assert facts["editorial_lead"] == ""
    assert facts["direct_answer"] == ""
    assert facts["entity_proposition"] == {
        "identity": "",
        "proposition": "",
        "provider": "",
        "named_capability": "",
        "audience_or_outcome": "",
        "next_action": "",
    }
    assert facts["primary_heading_outline"] == []
    assert facts["entity"]["listing"]["collection_evidence"] == {
        "container": {
            "tag": "",
            "label": "",
            "item_count": 0,
            "distinct_targets": 0,
        },
        "affordances": [],
    }


def test_nested_navigation_inside_main_cannot_become_a_collection() -> None:
    facts = _facts(
        b"""
        <html><body><main>
          <h1>Research note</h1>
          <nav aria-label="Browse results">
            <output role="status">6 results</output>
            <select name="sort">
              <option>Newest</option><option>Oldest</option>
            </select>
            <article><a href="/r/1">One</a></article>
            <article><a href="/r/2">Two</a></article>
            <article><a href="/r/3">Three</a></article>
            <article><a href="/r/4">Four</a></article>
            <article><a href="/r/5">Five</a></article>
            <article><a href="/r/6">Six</a></article>
          </nav>
          <p>This page explains one research observation in detail.</p>
        </main></body></html>
        """
    )

    assert facts["entity"]["listing"]["collection_evidence"] == {
        "container": {
            "tag": "",
            "label": "",
            "item_count": 0,
            "distinct_targets": 0,
        },
        "affordances": [],
    }
    assert classify("https://acme.example.test/research-note", facts).page_kind != (
        "category"
    )


def test_page_owned_scans_apply_caps_after_filtering_navigation() -> None:
    ignored_headings = "".join(
        "<h2>Navigation heading</h2>" for _ in range(SITE_HEALTH_MAX_HEADINGS_KEPT + 5)
    )
    ignored_links = "".join(
        f"<a href='/ignored/{index}'>Read item {index}</a>"
        for index in range(SITE_HEALTH_MAX_CTA_TEXTS * 4 + 5)
    )
    body = f"""
        <html><body><main>
          <nav>{ignored_headings}{ignored_links}</nav>
          <h1>Enterprise Search</h1>
          <p>Acme Search provides answer discovery for support teams.</p>
          <h2>What is enterprise search?</h2>
          <p>Enterprise search gives teams one place to find trusted
             answers.</p>
          <a class="cta" href="/demo">Book a demo</a>
        </main></body></html>
    """

    facts = _facts(body.encode())

    assert facts["direct_answer"] == (
        "Enterprise search gives teams one place to find trusted answers."
    )
    assert facts["entity_proposition"]["next_action"] == "/demo"


def test_standalone_cta_marked_paragraph_is_not_the_editorial_lead() -> None:
    facts = _facts(
        b"""
        <html><body><main>
          <h1>Enterprise Search</h1>
          <p class="cta">Book a demo to explore enterprise search today.</p>
          <p>Acme Search provides answer discovery for support teams
             worldwide.</p>
        </main></body></html>
        """
    )

    assert facts["editorial_lead"] == (
        "Acme Search provides answer discovery for support teams worldwide."
    )


def test_freshness_context_is_derived_from_identity_without_using_dates() -> None:
    versioned = _facts(
        b"<html><head><title>API v2 migration guide</title></head>"
        b"<body><main><h1>API version 2 migration</h1></main></body></html>",
        final_url="https://acme.example.com/docs/migration",
    )
    dated_only = _facts(
        b"<html><head><title>API migration guide</title>"
        b"<meta property='article:published_time' content='2026-01-15'></head>"
        b"<body><main><h1>API migration guide</h1></main></body></html>",
        final_url="https://acme.example.com/docs/migration",
    )

    assert versioned["freshness_context"] == {
        "required": True,
        "reasons": ["explicit_year_or_version_identity"],
    }
    assert dated_only["dates"]["published"] == "2026-01-15"
    assert dated_only["freshness_context"] == {"required": False, "reasons": []}


def test_news_route_requires_freshness_without_a_date_signal() -> None:
    facts = _facts(
        b"<html><head><title>Product update</title></head>"
        b"<body><main><h1>Product update</h1></main></body></html>",
        final_url="https://acme.example.com/news/product-update",
    )

    assert facts["freshness_context"] == {
        "required": True,
        "reasons": ["changelog_or_news_route"],
    }


def test_bare_source_word_does_not_attach_a_generic_external_link() -> None:
    facts = _facts(
        b"<html><body><main><h1>Implementation details</h1>"
        b"<p>View the <a href='https://github.com/acme/project'>"
        b"source on GitHub</a>.</p>"
        b"</main></body></html>"
    )

    assert facts["source_support"]["attached_sources"] == []
    assert facts["source_support"]["ambiguous_source_count"] == 1


def test_explicit_source_attribution_attaches_an_external_link() -> None:
    facts = _facts(
        b"<html><body><main><h1>Research summary</h1>"
        b"<p>Source: <a href='https://data.example.org/report'>Example dataset</a>.</p>"
        b"</main></body></html>"
    )

    assert facts["source_support"]["attached_sources"] == [
        {
            "url": "https://data.example.org/report",
            "domain": "data.example.org",
            "source_name": "Example dataset",
            "relationship": "nearby_attribution",
        }
    ]


def test_source_support_dom_setup_failure_returns_zero_facts(monkeypatch) -> None:
    def fail_primary_region(_root):
        raise ValueError("malformed DOM")

    monkeypatch.setattr(fact_source_support, "primary_region", fail_primary_region)

    assert (
        fact_source_support.extract_source_support_facts(
            object(), final_url="https://acme.example.com/report"
        )
        == fact_source_support.empty_source_support_facts()
    )


def test_malformed_source_authority_preserves_prior_sources(monkeypatch) -> None:
    real_urlsplit = fact_source_support.urlsplit

    class MalformedAuthority:
        scheme = "https"

        @property
        def hostname(self):
            raise ValueError("malformed authority")

    def guarded_urlsplit(url):
        if url == "https://bad.example.test/report":
            return MalformedAuthority()
        return real_urlsplit(url)

    monkeypatch.setattr(fact_source_support, "urlsplit", guarded_urlsplit)
    facts = _facts(
        b"<html><body><main><h1>Research summary</h1>"
        b"<p>Source: <a href='https://data.example.org/report'>Dataset</a>.</p>"
        b"<p>Source: <a href='https://bad.example.test/report'>Broken</a>.</p>"
        b"</main></body></html>"
    )

    assert facts["source_support"]["attached_sources"] == [
        {
            "url": "https://data.example.org/report",
            "domain": "data.example.org",
            "source_name": "Dataset",
            "relationship": "nearby_attribution",
        }
    ]
