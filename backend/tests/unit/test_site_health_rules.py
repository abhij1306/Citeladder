"""Unit tests for the Site Health rule evaluator (Task 5 + v2 P1/P2).

Verifies each rule maps to the right check and each outcome (pass / fail /
not_applicable / error) is produced with exact evidence + provenance, plus
the v2 P1 page-type behavior (``page_kind:<type>`` applicability tokens,
per-type thin-content minimums, weight overrides) and the v2 P2 sh-rules-2
catalog (site_root scope, per-type schema validity, citability,
extractability, hygiene, and the crawl_finalize scope's per-page exclusion).
Pure, offline.
"""

from __future__ import annotations

from app.analysis.site_health.rules import (
    evaluate_all,
    evaluate_rule,
    rule_for,
)
from app.core.config.site_health import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
    ANSWER_FIRST_MIN_WORDS,
    APPLICABILITY_CRAWL_FINALIZE,
    DIMENSION_AEO,
    DIMENSION_TECHNICAL,
    EXPAND_GATED_MAX_RATIO,
    META_DESCRIPTION_LENGTH_BAND,
    PAGE_KIND_OTHER,
    PAGE_KIND_PROFILES,
    QUESTION_HEADINGS_MIN_RATIO,
    RENDER_BLOCKING_MAX_RESOURCES,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
    SERVER_RENDERED_MIN_WORDS,
    SITE_HEALTH_RULES,
    TITLE_LENGTH_BAND,
    TTFB_WARN_MS,
    SiteHealthRule,
)

# The v1 global thin-content minimum now lives in the config-owned ``other``
# profile (identical value, so unclassified pages score exactly as before).
MIN_SUFFICIENT_WORDS = PAGE_KIND_PROFILES[PAGE_KIND_OTHER].min_sufficient_words

# The rules whose rows the finalize-writer owns: never applicable per-page.
_CRAWL_FINALIZE_RULE_IDS = {
    rule.rule_id
    for rule in SITE_HEALTH_RULES
    if rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE
}


def test_other_profile_minimum_preserves_v1_parity():
    # Pin the v1 contract: the ``other`` profile minimum must stay 100 words
    # so unclassified pages score exactly as v1 did (spec §5.2). The alias
    # above intentionally derives from config; this assertion does not.
    assert PAGE_KIND_PROFILES[PAGE_KIND_OTHER].min_sufficient_words == 100


def _html_facts(**overrides):
    """A fully healthy homepage (+ healthy site) so every per-page rule passes."""
    facts = {
        "has_html": True,
        "page_kind": "homepage",
        "title": "Acme Widgets — everything you need to know",
        "meta_description": (
            "Acme Widgets helps teams ship reliable widgets faster with "
            "fewer surprises."
        ),
        "canonical_url": "https://x.example/",
        "robots": {"noindex": False, "nofollow": False},
        "delivery": {
            "is_https": True,
            "scheme": "https",
            "final_url": "https://x.example/",
            "security_headers": {"strict-transport-security": True},
            "ttfb_ms": 120,
            "is_compressed": True,
            "content_encoding": "gzip",
        },
        "headings": {
            "h1_count": 1,
            "counts": {"h1": 1, "h2": 2},
            "h1_texts": ["Acme Widgets — everything you need to know"],
            "h2_texts": ["What are Acme widgets?", "Pricing"],
            "h3_texts": [],
        },
        "structured_data": {
            "count": 1,
            "has_json_ld": True,
            "has_microdata": False,
            "types": ["Organization"],
            "blocks": [
                {
                    "type": "Organization",
                    "syntax": "json-ld",
                    "required": ["name", "url"],
                    "present": ["name", "url"],
                    "missing": [],
                    "valid": True,
                    "name": "Acme Widgets",
                    "author": "Jane Doe",
                    "date_published": "2026-01-15",
                    "date_modified": "2026-06-01",
                    "same_as": ["https://linkedin.com/company/acme"],
                    "props_present": ["name", "url", "sameAs", "logo"],
                }
            ],
        },
        "open_graph": {"og:title": "T", "og:description": "D"},
        "body": {
            "word_count": MIN_SUFFICIENT_WORDS + 10,
            "text": "word " * (MIN_SUFFICIENT_WORDS + 10),
        },
        "author": "Jane Doe",
        "dates": {"published": "2026-01-15", "modified": "2026-06-01"},
        "outbound_domains": ["docs.example.org"],
        "question_heading_ratio": 0.5,
        "expand_gated_ratio": 0.0,
        "first_answer_text": (
            "Acme widgets are reliable little gadgets that just work for every team."
        ),
        "inline_script_chars": 0,
        "blocking_resources": {"scripts": 0, "stylesheets": 1, "total": 1},
        "site": {
            "robots": {
                "fetched": True,
                "url": "https://x.example/robots.txt",
                "status_code": 200,
                "ai_crawlers": {bot: "allow" for bot in AI_CRAWLER_BOTS},
                "sitemaps": [],
            },
            "llms_txt": {
                "fetched": True,
                "url": "https://x.example/llms.txt",
                "status_code": 200,
                "present": True,
            },
            "sitemap": {"fetched": True, "files": ["https://x.example/sitemap.xml"]},
        },
    }
    facts.update(overrides)
    return facts


def _article_facts(**overrides):
    """The healthy fixture as an ARTICLE.

    The citability/extractability rules are scoped to editorial page kinds now
    (`page_kind:article|guide|...`), so exercising them on the default homepage
    fixture would only ever assert that they are inapplicable.
    """
    return _html_facts(page_kind="article", **overrides)


def _outcome(facts, rule_id):
    rule = rule_for(rule_id)
    assert rule is not None
    return evaluate_rule(rule, facts)


# Editorial-only rules: N/A on the healthy HOMEPAGE fixture by design.
_EDITORIAL_RULE_IDS = {
    "aeo.author_present",
    "aeo.date_present",
    "aeo.outbound_citations",
    "aeo.answer_first",
    "aeo.question_headings",
}


def test_all_rules_pass_on_healthy_page():
    facts = _html_facts()
    evals = evaluate_all(facts)
    assert {e.rule_id for e in evals} == {r.rule_id for r in SITE_HEALTH_RULES}
    for e in evals:
        if e.rule_id in _CRAWL_FINALIZE_RULE_IDS | _EDITORIAL_RULE_IDS:
            # crawl_finalize rules are owned by the finalize-writer; the
            # editorial rules are scoped to article/guide/docs page kinds and
            # this fixture is a homepage.
            assert e.outcome == RULE_OUTCOME_NOT_APPLICABLE, e.rule_id
        else:
            assert e.outcome == RULE_OUTCOME_PASS, e.rule_id
    # Provenance carried through from the catalog.
    title_eval = next(e for e in evals if e.rule_id == "technical.title_present")
    assert title_eval.dimension == DIMENSION_TECHNICAL
    assert title_eval.weight == 3.0
    assert title_eval.remediation


def test_title_absent_fails():
    ev = _outcome(_html_facts(title=""), "technical.title_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["present"] is False


def test_meta_description_absent_fails():
    ev = _outcome(
        _html_facts(meta_description=""),
        "technical.meta_description_present",
    )
    assert ev.outcome == RULE_OUTCOME_FAIL


def test_canonical_absent_fails():
    ev = _outcome(_html_facts(canonical_url=""), "technical.canonical_present")
    assert ev.outcome == RULE_OUTCOME_FAIL


def test_noindex_fails_indexable():
    facts = _html_facts(robots={"noindex": True, "nofollow": False})
    ev = _outcome(facts, "technical.indexable")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["noindex"] is True


def test_http_fails_https_rule():
    facts = _html_facts(
        delivery={"is_https": False, "scheme": "http", "final_url": "http://x"}
    )
    ev = _outcome(facts, "technical.https")
    assert ev.outcome == RULE_OUTCOME_FAIL


def test_zero_or_multiple_h1_fails_single_h1():
    assert (
        _outcome(_html_facts(headings={"h1_count": 0}), "technical.single_h1").outcome
        == RULE_OUTCOME_FAIL
    )
    assert (
        _outcome(_html_facts(headings={"h1_count": 2}), "technical.single_h1").outcome
        == RULE_OUTCOME_FAIL
    )


def test_structured_data_absent_fails():
    facts = _html_facts(
        structured_data={
            "count": 0,
            "has_json_ld": False,
            "has_microdata": False,
            "types": [],
        }
    )
    ev = _outcome(facts, "aeo.structured_data_present")
    assert ev.outcome == RULE_OUTCOME_FAIL


def test_open_graph_incomplete_fails():
    ev = _outcome(_html_facts(open_graph={"og:title": "T"}), "aeo.open_graph_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["has_og_description"] is False


def test_thin_content_fails():
    ev = _outcome(
        _html_facts(page_kind=None, body={"word_count": MIN_SUFFICIENT_WORDS - 1}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["minimum"] == MIN_SUFFICIENT_WORDS


def test_has_html_rules_not_applicable_without_html():
    # A non-HTML page (has_html False) makes the has_html rules N/A but leaves
    # the "always" rules applicable.
    facts = {
        "has_html": False,
        "title": "",
        "meta_description": "",
        "canonical_url": "",
        "robots": {"noindex": False, "nofollow": False},
        "delivery": {"is_https": True, "scheme": "https", "final_url": "x"},
    }
    evals = {e.rule_id: e for e in evaluate_all(facts)}
    assert evals["technical.single_h1"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert evals["aeo.structured_data_present"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert evals["aeo.open_graph_present"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert evals["technical.thin_content"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    # "always" rules still evaluate (https passes; title fails).
    assert evals["technical.https"].outcome == RULE_OUTCOME_PASS
    assert evals["technical.title_present"].outcome == RULE_OUTCOME_FAIL


def _js_shell_facts():
    """A client-rendered shell: real markup, empty body, script-dominated.

    Modelled on the page that exposed this — 4,874 bytes of bootstrap with a
    title and meta description but zero body text and zero headings.
    """
    return _article_facts(
        headings={"h1_count": 0, "counts": {"h1": 0, "h2": 0}},
        body={"word_count": 0, "text": ""},
        inline_script_chars=1269,
        question_heading_ratio=0.0,
        outbound_domains=[],
        author="",
        dates={},
        first_answer_text="",
    )


def test_js_shell_reports_one_finding_not_a_cascade():
    """Content rules are N/A on a shell; the shell rule itself still fails.

    The crawler is HTTP-only, so a client-rendered page arrives with an empty
    body. Every content-reading rule used to "fail" on content that was never
    delivered — one page produced missing-H1 + thin-content + no-question-
    headings + no-citations + no-author + no-date as six separate findings,
    each scoring against it, for a single real problem.
    """
    evals = {e.rule_id: e for e in evaluate_all(_js_shell_facts())}

    # The one true finding, still reported at its catalog severity.
    assert evals["aeo.server_rendered_content"].outcome == RULE_OUTCOME_FAIL

    # Its derivatives are skipped, and say why.
    for rule_id in (
        "technical.single_h1",
        "technical.thin_content",
        "aeo.question_headings",
        "aeo.outbound_citations",
        "aeo.author_present",
        "aeo.date_present",
    ):
        assert evals[rule_id].outcome == RULE_OUTCOME_NOT_APPLICABLE, rule_id
        assert evals[rule_id].evidence["reason"] == "content_not_server_rendered"

    # Rules about the SERVED MARKUP are unaffected: what a non-rendering
    # crawler receives is exactly what this product is about, so a shell that
    # ships no JSON-LD is still a genuine structured-data finding.
    assert evals["aeo.structured_data_present"].outcome != RULE_OUTCOME_NOT_APPLICABLE
    assert evals["technical.title_present"].outcome == RULE_OUTCOME_PASS
    assert evals["technical.https"].outcome == RULE_OUTCOME_PASS


def test_content_rules_still_apply_to_a_server_rendered_page():
    """The gate must not swallow real findings on a normally-rendered page."""
    facts = _html_facts(headings={"h1_count": 0, "counts": {"h1": 0, "h2": 3}})
    ev = _outcome(facts, "technical.single_h1")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["h1_count"] == 0


def test_check_raising_yields_error_outcome():
    # A rule whose facts are shaped so its check raises must yield ERROR, never
    # propagate. Feed a facts dict where headings is not a dict for single_h1.
    bad = _html_facts(headings=None)
    # headings None -> `.get` on None raises inside the check.
    rule = rule_for("technical.single_h1")
    facts = dict(bad)
    facts["headings"] = 12345  # int has no .get -> AttributeError in check
    ev = evaluate_rule(rule, facts)
    assert ev.outcome == RULE_OUTCOME_ERROR
    assert "error" in ev.evidence


def test_unmapped_rule_id_yields_error():
    phantom = SiteHealthRule(
        rule_id="aeo.does_not_exist",
        rule_version="v1",
        dimension=DIMENSION_AEO,
        category="content",
        severity="low",
        weight=1.0,
        applicability_key="always",
        description="",
        remediation="",
    )
    ev = evaluate_rule(phantom, _html_facts())
    assert ev.outcome == RULE_OUTCOME_ERROR
    assert ev.evidence["error"] == "no_check_mapped"


def test_unknown_applicability_key_is_not_applicable():
    phantom = SiteHealthRule(
        rule_id="technical.title_present",
        rule_version="v1",
        dimension=DIMENSION_TECHNICAL,
        category="metadata",
        severity="low",
        weight=1.0,
        applicability_key="some_unknown_key",
        description="",
        remediation="",
    )
    ev = evaluate_rule(phantom, _html_facts())
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE


# --- v2 P1: page-type applicability / minimums / weight overrides ---------


def _page_type_rule(rule_id: str, page_kind: str, weight: float = 1.0):
    """A catalog-shaped rule scoped to one page type via the token syntax."""
    return SiteHealthRule(
        rule_id=rule_id,
        rule_version="v1",
        dimension=DIMENSION_TECHNICAL,
        category="content",
        severity="low",
        weight=weight,
        applicability_key=f"page_kind:{page_kind}",
        description="",
        remediation="",
    )


def test_page_type_token_applicable_on_matching_type():
    rule = _page_type_rule("technical.title_present", "article")
    ev = evaluate_rule(rule, _html_facts(page_kind="article"))
    # Applicable -> the real check runs (title present -> pass).
    assert ev.outcome == RULE_OUTCOME_PASS


def test_page_type_token_not_applicable_on_other_type():
    rule = _page_type_rule("technical.title_present", "article")
    ev = evaluate_rule(rule, _html_facts(page_kind="product"))
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_page_type_token_not_applicable_without_page_type_fact():
    # No facts["page_kind"] (e.g. pre-classification) -> fail-closed.
    # ``_html_facts()`` DEFAULTS page_kind to "homepage", so the key has to be
    # removed — otherwise this only re-tested the mismatched-type case above.
    rule = _page_type_rule("technical.title_present", "article")
    facts = _html_facts()
    del facts["page_kind"]
    ev = evaluate_rule(rule, facts)
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_page_type_token_unknown_type_in_facts_fail_closed():
    # A page_kind outside the config taxonomy has no profile -> fail-closed.
    rule = _page_type_rule("technical.title_present", "article")
    ev = evaluate_rule(rule, _html_facts(page_kind="not_a_real_type"))
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_page_type_token_for_unconfigured_type_fail_closed():
    # The token itself names a type with no profile entry -> fail-closed.
    rule = _page_type_rule("technical.title_present", "not_a_real_type")
    ev = evaluate_rule(rule, _html_facts(page_kind="article"))
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_thin_content_uses_per_type_minimum():
    article_min = PAGE_KIND_PROFILES["article"].min_sufficient_words
    other_min = PAGE_KIND_PROFILES[PAGE_KIND_OTHER].min_sufficient_words
    assert article_min > other_min  # the config actually differentiates
    # Between the two minimums: an article fails while `other` passes.
    facts_article = _html_facts(page_kind="article", body={"word_count": other_min})
    ev = _outcome(facts_article, "technical.thin_content")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["minimum"] == article_min
    assert ev.evidence["page_kind"] == "article"
    facts_other = _html_facts(page_kind="other", body={"word_count": other_min})
    ev_other = _outcome(facts_other, "technical.thin_content")
    assert ev_other.outcome == RULE_OUTCOME_PASS
    assert ev_other.evidence["minimum"] == other_min


def test_thin_content_without_page_type_falls_back_to_other_minimum():
    ev = _outcome(
        _html_facts(page_kind=None, body={"word_count": MIN_SUFFICIENT_WORDS}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["minimum"] == MIN_SUFFICIENT_WORDS
    assert ev.evidence["page_kind"] == "other"


def test_thin_content_homepage_minimum_is_lower():
    homepage_min = PAGE_KIND_PROFILES["homepage"].min_sufficient_words
    assert homepage_min < MIN_SUFFICIENT_WORDS
    ev = _outcome(
        _html_facts(page_kind="homepage", body={"word_count": homepage_min}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["minimum"] == homepage_min


def test_weight_override_applies_for_configured_page_type():
    override = PAGE_KIND_PROFILES["homepage"].rule_weight_overrides[
        "technical.thin_content"
    ]
    base_weight = rule_for("technical.thin_content").weight
    assert override != base_weight  # the sparse config override is real
    ev = _outcome(_html_facts(page_kind="homepage"), "technical.thin_content")
    assert ev.weight == override
    # Every other page type keeps the catalog weight.
    ev_other = _outcome(_html_facts(page_kind="other"), "technical.thin_content")
    assert ev_other.weight == base_weight
    # And a page with no page_kind fact keeps the catalog weight.
    ev_plain = _outcome(_html_facts(page_kind=None), "technical.thin_content")
    assert ev_plain.weight == base_weight


# --- v2 P2: hygiene rules ---------------------------------------------------


def test_canonical_conflict_passes_when_canonical_matches_final_url():
    ev = _outcome(_html_facts(), "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["matches_final_url"] is True


def test_canonical_conflict_normalization_variants_still_match():
    # Scheme/host case, default port, fragment, and trailing slash differences
    # are all normalized away for the comparison.
    facts = _html_facts(canonical_url="HTTPS://X.Example:443/#section")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_PASS
    facts = _html_facts(canonical_url="https://x.example")
    assert _outcome(facts, "technical.canonical_conflict").outcome == (
        RULE_OUTCOME_PASS
    )


def test_canonical_conflict_fails_on_mismatch():
    facts = _html_facts(canonical_url="https://x.example/other-page")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["matches_final_url"] is False
    assert ev.evidence["canonical_url"] == "https://x.example/other-page"
    assert ev.evidence["final_url"] == "https://x.example/"


def test_canonical_conflict_not_applicable_without_canonical():
    # The v1 presence rule owns the missing-canonical finding.
    ev = _outcome(_html_facts(canonical_url=""), "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_canonical"


def test_title_length_band():
    low, high = TITLE_LENGTH_BAND
    assert _outcome(_html_facts(), "technical.title_length_band").outcome == (
        RULE_OUTCOME_PASS
    )
    short = _outcome(_html_facts(title="x" * (low - 1)), "technical.title_length_band")
    assert short.outcome == RULE_OUTCOME_FAIL
    assert short.evidence["title_length"] == low - 1
    assert short.evidence["band"] == [low, high]
    long = _outcome(_html_facts(title="x" * (high + 1)), "technical.title_length_band")
    assert long.outcome == RULE_OUTCOME_FAIL
    # Band edges are inclusive.
    for length in (low, high):
        ev = _outcome(_html_facts(title="x" * length), "technical.title_length_band")
        assert ev.outcome == RULE_OUTCOME_PASS


def test_title_length_band_not_applicable_when_empty():
    ev = _outcome(_html_facts(title=""), "technical.title_length_band")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "empty_title"


def test_meta_description_length_band():
    low, high = META_DESCRIPTION_LENGTH_BAND
    assert (
        _outcome(_html_facts(), "technical.meta_description_length_band").outcome
        == RULE_OUTCOME_PASS
    )
    short = _outcome(
        _html_facts(meta_description="x" * (low - 1)),
        "technical.meta_description_length_band",
    )
    assert short.outcome == RULE_OUTCOME_FAIL
    assert short.evidence["description_length"] == low - 1
    assert short.evidence["band"] == [low, high]
    long = _outcome(
        _html_facts(meta_description="x" * (high + 1)),
        "technical.meta_description_length_band",
    )
    assert long.outcome == RULE_OUTCOME_FAIL


def test_meta_description_length_band_not_applicable_when_empty():
    ev = _outcome(
        _html_facts(meta_description=""), "technical.meta_description_length_band"
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "empty_meta_description"


def test_hsts_present():
    assert _outcome(_html_facts(), "technical.hsts_present").outcome == (
        RULE_OUTCOME_PASS
    )
    facts = _html_facts()
    facts["delivery"]["security_headers"] = {"strict-transport-security": False}
    ev = _outcome(facts, "technical.hsts_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["present"] is False
    assert ev.evidence["scheme"] == "https"


def test_ttfb_band():
    assert _outcome(_html_facts(), "technical.ttfb_band").outcome == (RULE_OUTCOME_PASS)

    def _with_ttfb(ttfb):
        facts = _html_facts()
        facts["delivery"]["ttfb_ms"] = ttfb
        return _outcome(facts, "technical.ttfb_band")

    assert _with_ttfb(TTFB_WARN_MS).outcome == RULE_OUTCOME_PASS
    slow = _with_ttfb(TTFB_WARN_MS + 1)
    assert slow.outcome == RULE_OUTCOME_FAIL
    assert slow.evidence["ttfb_ms"] == TTFB_WARN_MS + 1
    assert slow.evidence["threshold_ms"] == TTFB_WARN_MS
    unmeasured = _with_ttfb(None)
    assert unmeasured.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert unmeasured.evidence["reason"] == "no_ttfb_measurement"


def test_uncompressed_html():
    assert _outcome(_html_facts(), "technical.uncompressed_html").outcome == (
        RULE_OUTCOME_PASS
    )
    facts = _html_facts()
    facts["delivery"]["is_compressed"] = False
    facts["delivery"]["content_encoding"] = ""
    ev = _outcome(facts, "technical.uncompressed_html")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["is_compressed"] is False


def test_render_blocking():
    assert _outcome(_html_facts(), "technical.render_blocking").outcome == (
        RULE_OUTCOME_PASS
    )

    def _with_total(total):
        return _html_facts(
            blocking_resources={"scripts": total, "stylesheets": 0, "total": total}
        )

    assert (
        _outcome(
            _with_total(RENDER_BLOCKING_MAX_RESOURCES), "technical.render_blocking"
        ).outcome
        == RULE_OUTCOME_PASS
    )
    over = _outcome(
        _with_total(RENDER_BLOCKING_MAX_RESOURCES + 1), "technical.render_blocking"
    )
    assert over.outcome == RULE_OUTCOME_FAIL
    assert over.evidence["total"] == RENDER_BLOCKING_MAX_RESOURCES + 1
    assert over.evidence["max_allowed"] == RENDER_BLOCKING_MAX_RESOURCES


# --- v2 P2: site_root rules (facts["site"] injected by the worker) ----------


def test_site_root_rules_not_applicable_without_site_facts():
    # The worker injects facts["site"] only into the crawl root's analysis;
    # everywhere else the site_root rules stay N/A.
    facts = _html_facts(site=None)
    for rule_id in ("technical.ai_crawler_access", "aeo.llms_txt_present"):
        ev = _outcome(facts, rule_id)
        assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE, rule_id


def test_ai_crawler_access_passes_when_all_bots_allowed():
    ev = _outcome(_html_facts(), "technical.ai_crawler_access")
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["blocked"] == []
    # The bounded stance covers every configured bot.
    assert set(ev.evidence["ai_crawlers"]) == set(AI_CRAWLER_BOTS)


def test_ai_crawler_access_not_applicable_when_robots_not_fetched():
    # An unfetched robots.txt yields the fail-open all-allow stance: passing
    # a HIGH-severity signal on that would be vacuous — N/A instead.
    facts = _html_facts()
    facts["site"]["robots"]["fetched"] = False
    facts["site"]["robots"]["status_code"] = None
    ev = _outcome(facts, "technical.ai_crawler_access")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "robots_not_fetched"
    assert ev.evidence["robots_fetched"] is False
    # The stance evidence is still carried (bounded, all bots).
    assert set(ev.evidence["ai_crawlers"]) == set(AI_CRAWLER_BOTS)


def test_ai_crawler_access_fails_when_any_bot_blocked():
    facts = _html_facts()
    facts["site"]["robots"]["ai_crawlers"]["GPTBot"] = AI_CRAWLER_STANCE_BLOCK
    ev = _outcome(facts, "technical.ai_crawler_access")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["blocked"] == ["GPTBot"]
    assert ev.evidence["ai_crawlers"]["GPTBot"] == AI_CRAWLER_STANCE_BLOCK
    assert ev.evidence["robots_fetched"] is True


def test_llms_txt_present():
    assert _outcome(_html_facts(), "aeo.llms_txt_present").outcome == (
        RULE_OUTCOME_PASS
    )
    facts = _html_facts()
    facts["site"]["llms_txt"]["present"] = False
    ev = _outcome(facts, "aeo.llms_txt_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["present"] is False
    assert ev.evidence["fetched"] is True


# --- v2 P2: per-type schema validity rules ----------------------------------


def _sd(blocks: list[dict], types: list[str] | None = None) -> dict:
    """A structured_data facts dict carrying exactly ``blocks``."""
    return {
        "count": len(blocks),
        "has_json_ld": bool(blocks),
        "has_microdata": False,
        "types": types if types is not None else [b.get("type") for b in blocks],
        "blocks": blocks,
    }


def test_schema_expected_for_type_passes_with_expected_block():
    # The healthy homepage carries an Organization block (an expected type).
    ev = _outcome(_html_facts(), "aeo.schema_expected_for_type")
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["page_kind"] == "homepage"


def test_schema_expected_for_type_fails_without_expected_block():
    facts = _html_facts(
        page_kind="product",
        structured_data=_sd(
            [
                {
                    "type": "Article",
                    "syntax": "json-ld",
                    "name": "Some Post",
                    "props_present": ["headline", "author", "datePublished"],
                }
            ]
        ),
    )
    ev = _outcome(facts, "aeo.schema_expected_for_type")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["page_kind"] == "product"
    assert ev.evidence["expected_types"] == ["Product"]
    assert ev.evidence["found_types"] == ["Article"]


def test_schema_outranked_type_rules_are_not_circular():
    """A product page (classified from URL/content signals) mis-marked with
    Article markup: ``schema_expected_for_type`` owns the failure while the
    dependent validity rules are all N/A — they never double-report, and the
    expectation came from facts["page_kind"], never from the schema itself."""
    facts = _html_facts(
        page_kind="product",
        structured_data=_sd(
            [
                {
                    "type": "Article",
                    "syntax": "json-ld",
                    "name": "Some Post",
                    "props_present": ["headline", "author", "datePublished"],
                }
            ]
        ),
    )
    assert _outcome(facts, "aeo.schema_expected_for_type").outcome == (
        RULE_OUTCOME_FAIL
    )
    for rule_id in (
        "aeo.schema_required_valid",
        "aeo.schema_recommended_present",
        "aeo.schema_matches_content",
    ):
        ev = _outcome(facts, rule_id)
        assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE, rule_id
        assert ev.evidence["reason"] in (
            "no_expected_type_block",
            "no_recommended_properties",
        )


def test_schema_required_valid_passes_with_complete_block():
    ev = _outcome(_html_facts(), "aeo.schema_required_valid")
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["missing"] == []


def test_schema_required_valid_fails_and_picks_best_block():
    # Two Organization blocks: the best-annotated one decides (fewest missing).
    facts = _html_facts(
        structured_data=_sd(
            [
                {"type": "Organization", "syntax": "json-ld", "props_present": []},
                {
                    "type": "Organization",
                    "syntax": "json-ld",
                    "props_present": ["name"],
                },
            ]
        )
    )
    ev = _outcome(facts, "aeo.schema_required_valid")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["missing"] == ["url"]
    assert ev.evidence["checked_blocks"] == 2
    assert ev.evidence["required"] == ["name", "url"]


def test_schema_recommended_present():
    assert _outcome(_html_facts(), "aeo.schema_recommended_present").outcome == (
        RULE_OUTCOME_PASS
    )
    # Missing one recommended property (logo) -> low-weight fail.
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["props_present"] = ["name", "url", "sameAs"]
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_recommended_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["missing"] == ["logo"]


def test_schema_property_rules_record_microdata_shallow_extraction():
    # A microdata Product block (shallow extraction: props_present is always
    # empty) still FAILS the property rules, but the evidence records the
    # limitation so the UI can explain the finding may be fully marked up.
    microdata_block = {
        "type": "Product",
        "syntax": "microdata",
        "required": ["name", "offers"],
        "present": [],
        "missing": ["name", "offers"],
        "valid": False,
        "name": "",
        "author": "",
        "date_published": "",
        "date_modified": "",
        "same_as": [],
        "props_present": [],
    }
    facts = _html_facts(page_kind="product", structured_data=_sd([microdata_block]))
    ev = _outcome(facts, "aeo.schema_required_valid")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["extraction"] == "microdata_shallow"
    # JSON-LD blocks (full extraction) never carry the marker, even on fail.
    jsonld_block = {
        "type": "Product",
        "syntax": "json-ld",
        "name": "Widget",
        "props_present": ["name"],
    }
    facts = _html_facts(page_kind="product", structured_data=_sd([jsonld_block]))
    ev = _outcome(facts, "aeo.schema_required_valid")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert "extraction" not in ev.evidence


def test_schema_recommended_present_not_applicable_when_none_recommended():
    # ``other`` is a classification abstention, not a WebPage verdict. Schema
    # rules fail closed instead of assigning it a guessed contract.
    block = {
        "type": "WebPage",
        "syntax": "json-ld",
        "name": "Acme Widgets",
        "props_present": ["name"],
    }
    facts = _html_facts(page_kind="other", structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_recommended_present")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "other_page_kind"


def test_schema_properties_follow_the_actual_allowed_schema_type():
    article = {
        "type": "Article",
        "syntax": "json-ld",
        "name": "Install Acme",
        "props_present": ["headline", "image", "dateModified"],
    }
    guide = _html_facts(page_kind="guide", structured_data=_sd([article]))

    required = _outcome(guide, "aeo.schema_required_valid")
    recommended = _outcome(guide, "aeo.schema_recommended_present")

    assert required.outcome == RULE_OUTCOME_PASS
    assert required.evidence["schema_type"] == "Article"
    assert required.evidence["required"] == ["headline"]
    assert recommended.outcome == RULE_OUTCOME_PASS
    assert recommended.evidence["recommended"] == ["image", "dateModified"]


def test_website_does_not_receive_organization_recommendations():
    website = {
        "type": "WebSite",
        "syntax": "json-ld",
        "name": "Acme",
        "props_present": ["name", "url"],
    }
    homepage = _html_facts(structured_data=_sd([website]))

    assert _outcome(homepage, "aeo.schema_required_valid").outcome == (
        RULE_OUTCOME_PASS
    )
    recommended = _outcome(homepage, "aeo.schema_recommended_present")
    assert recommended.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert recommended.evidence["reason"] == "no_recommended_properties"


def test_schema_matches_content():
    # The healthy fixture's Organization name appears in the title.
    assert _outcome(_html_facts(), "aeo.schema_matches_content").outcome == (
        RULE_OUTCOME_PASS
    )
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["name"] = "Totally Unrelated Brand"
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_matches_content")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["matched_visible_content"] is False
    assert ev.evidence["candidates"] == ["Totally Unrelated Brand"]


def test_schema_matches_content_not_applicable_without_names():
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["name"] = ""
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_matches_content")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_schema_names"


def test_schema_rules_fail_closed_without_a_classified_page_type():
    block = {
        "type": "WebPage",
        "syntax": "json-ld",
        "name": "Acme Widgets",
        "props_present": ["name"],
    }
    facts = _html_facts(page_kind=None, structured_data=_sd([block]))
    for rule_id in (
        "aeo.structured_data_present",
        "aeo.schema_expected_for_type",
        "aeo.schema_required_valid",
        "aeo.schema_recommended_present",
        "aeo.schema_matches_content",
    ):
        evaluation = _outcome(facts, rule_id)
        assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert evaluation.evidence["reason"] == "other_page_kind"


def test_page_kind_schema_rules_preserve_the_html_guard():
    facts = _html_facts(has_html=False, page_kind="product")
    for rule_id in (
        "aeo.structured_data_present",
        "aeo.schema_expected_for_type",
        "aeo.schema_required_valid",
        "aeo.schema_recommended_present",
    ):
        evaluation = _outcome(facts, rule_id)
        assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert evaluation.evidence["reason"] == "no_html"


# --- v2 P2: citability rules -------------------------------------------------


def test_author_present():
    assert _outcome(_article_facts(), "aeo.author_present").outcome == (
        RULE_OUTCOME_PASS
    )
    ev = _outcome(_article_facts(author=""), "aeo.author_present")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["present"] is False


def test_date_present():
    assert _outcome(_article_facts(), "aeo.date_present").outcome == RULE_OUTCOME_PASS
    # Either date alone suffices.
    assert (
        _outcome(
            _article_facts(dates={"published": "2026-01-15", "modified": ""}),
            "aeo.date_present",
        ).outcome
        == RULE_OUTCOME_PASS
    )
    assert (
        _outcome(
            _article_facts(dates={"published": "", "modified": "2026-06-01"}),
            "aeo.date_present",
        ).outcome
        == RULE_OUTCOME_PASS
    )
    ev = _outcome(
        _article_facts(dates={"published": "", "modified": ""}), "aeo.date_present"
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["has_published"] is False
    assert ev.evidence["has_modified"] is False


def test_outbound_citations():
    assert _outcome(_article_facts(), "aeo.outbound_citations").outcome == (
        RULE_OUTCOME_PASS
    )
    # No outbound domains at all -> fail.
    assert (
        _outcome(_article_facts(outbound_domains=[]), "aeo.outbound_citations").outcome
        == RULE_OUTCOME_FAIL
    )
    # Social-only outbound links (incl. subdomains) do not count as citations.
    ev = _outcome(
        _article_facts(outbound_domains=["twitter.com", "m.facebook.com"]),
        "aeo.outbound_citations",
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["non_social_domain_count"] == 0
    assert ev.evidence["outbound_domain_count"] == 2


def test_organization_identity():
    # Applicable on the homepage (page_kind:homepage scope).
    ev = _outcome(_html_facts(), "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["has_organization"] is True
    assert ev.evidence["same_as_count"] == 1
    # An Organization block without sameAs fails.
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["same_as"] = []
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["same_as_count"] == 0
    # No Organization block at all fails too.
    other_block = {
        "type": "WebPage",
        "syntax": "json-ld",
        "name": "Acme Widgets",
        "props_present": ["name"],
    }
    facts = _html_facts(structured_data=_sd([other_block]))
    ev = _outcome(facts, "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["has_organization"] is False
    # Not applicable off the homepage.
    assert (
        _outcome(_html_facts(page_kind="article"), "aeo.organization_identity").outcome
        == RULE_OUTCOME_NOT_APPLICABLE
    )


# --- v2 P2: extractability rules ---------------------------------------------


def test_answer_first():
    assert _outcome(_article_facts(), "aeo.answer_first").outcome == RULE_OUTCOME_PASS
    short = _outcome(
        _article_facts(first_answer_text="Too short."), "aeo.answer_first"
    )
    assert short.outcome == RULE_OUTCOME_FAIL
    assert short.evidence["answer_word_count"] == 2
    assert short.evidence["minimum_words"] == ANSWER_FIRST_MIN_WORDS
    # Exactly at the minimum passes.
    exactly = " ".join(f"w{i}" for i in range(ANSWER_FIRST_MIN_WORDS))
    assert (
        _outcome(_article_facts(first_answer_text=exactly), "aeo.answer_first").outcome
        == RULE_OUTCOME_PASS
    )


def test_answer_first_not_applicable_without_headings():
    facts = _article_facts(
        headings={"h1_count": 0, "counts": {}, "h1_texts": [], "h2_texts": []}
    )
    ev = _outcome(facts, "aeo.answer_first")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_headings"


def test_question_headings():
    assert _outcome(_article_facts(), "aeo.question_headings").outcome == (
        RULE_OUTCOME_PASS
    )
    ev = _outcome(_article_facts(question_heading_ratio=0.0), "aeo.question_headings")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["question_heading_ratio"] == 0.0
    assert ev.evidence["minimum_ratio"] == QUESTION_HEADINGS_MIN_RATIO


def test_server_rendered_content():
    assert _outcome(_html_facts(), "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_PASS
    )
    # A JS shell: text-thin AND script-dominated -> fail.
    shell = _html_facts(
        body={"word_count": 5, "text": "tiny"}, inline_script_chars=500_000
    )
    ev = _outcome(shell, "aeo.server_rendered_content")
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["word_count"] == 5
    assert ev.evidence["inline_script_chars"] == 500_000
    # Text-thin but NOT script-dominated -> pass (not a JS-shell signature).
    thin_static = _html_facts(
        body={"word_count": 5, "text": "x" * 1000}, inline_script_chars=10
    )
    assert _outcome(thin_static, "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_PASS
    )
    # At/above the minimum word count passes regardless of script volume.
    enough = _html_facts(
        body={"word_count": SERVER_RENDERED_MIN_WORDS, "text": "tiny"},
        inline_script_chars=500_000,
    )
    assert _outcome(enough, "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_PASS
    )


def test_no_expand_gating():
    assert _outcome(_html_facts(), "aeo.no_expand_gating").outcome == (
        RULE_OUTCOME_PASS
    )
    # The boundary is inclusive: exactly at the max ratio still passes.
    assert (
        _outcome(
            _html_facts(expand_gated_ratio=EXPAND_GATED_MAX_RATIO),
            "aeo.no_expand_gating",
        ).outcome
        == RULE_OUTCOME_PASS
    )
    ev = _outcome(
        _html_facts(expand_gated_ratio=EXPAND_GATED_MAX_RATIO + 0.1),
        "aeo.no_expand_gating",
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.evidence["max_ratio"] == EXPAND_GATED_MAX_RATIO


# =========================================================================
# Page-type scoped applicability (multi-kind `page_kind:a|b|c` tokens)
# =========================================================================
# The product complaint these pin: every page kind used to be handed the same
# generic checklist, so a product page was reported for a missing author
# byline and a homepage for missing question-form headings. A rule that does
# not apply to a page kind must resolve NOT_APPLICABLE — which is a different
# statement from FAIL, and only the former keeps it out of the issue list.
_EDITORIAL_ONLY = ("aeo.author_present", "aeo.outbound_citations")


def test_editorial_citability_rules_do_not_apply_to_commercial_pages():
    for page_kind in ("product", "category", "pricing", "trust_policy", "homepage"):
        # Strip the very signals the rules look for, so a still-applicable rule
        # would FAIL rather than pass by accident.
        facts = _html_facts(
            page_kind=page_kind, author="", dates={}, outbound_domains=[]
        )
        for rule_id in _EDITORIAL_ONLY:
            outcome = _outcome(facts, rule_id)
            assert outcome.outcome == RULE_OUTCOME_NOT_APPLICABLE, (
                f"{rule_id} must not apply to a {page_kind} page"
            )


def test_editorial_citability_rules_still_evaluate_on_articles():
    facts = _html_facts(page_kind="article", author="", outbound_domains=[])
    for rule_id in _EDITORIAL_ONLY:
        assert _outcome(facts, rule_id).outcome == RULE_OUTCOME_FAIL


def test_published_date_applies_to_docs_but_not_to_a_product_page():
    missing_dates = {"dates": {}, "structured_data": {"count": 0, "blocks": []}}
    assert (
        _outcome(
            _html_facts(page_kind="docs", **missing_dates), "aeo.date_present"
        ).outcome
        == RULE_OUTCOME_FAIL
    )
    assert (
        _outcome(
            _html_facts(page_kind="product", **missing_dates), "aeo.date_present"
        ).outcome
        == RULE_OUTCOME_NOT_APPLICABLE
    )


def test_question_headings_apply_to_answer_pages_only():
    facts = _html_facts(question_heading_ratio=0.0)
    for page_kind in ("faq", "guide", "docs", "article"):
        assert (
            _outcome({**facts, "page_kind": page_kind}, "aeo.question_headings").outcome
            == RULE_OUTCOME_FAIL
        )
    for page_kind in ("homepage", "product", "category"):
        assert (
            _outcome({**facts, "page_kind": page_kind}, "aeo.question_headings").outcome
            == RULE_OUTCOME_NOT_APPLICABLE
        )


def test_multi_kind_token_still_fails_closed_on_an_unclassified_page():
    # No page kind means we could not classify the page. We do not guess which
    # checklist it should answer for.
    facts = _html_facts(page_kind=None, author="")
    assert _outcome(facts, "aeo.author_present").outcome == RULE_OUTCOME_NOT_APPLICABLE
