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

import pytest

from app.analysis.site_health.rules import (
    creates_issue,
    evaluate_all,
    evaluate_rule,
    rule_for,
)
from app.analysis.site_health.scoring import score_analysis
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
)
from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    DIMENSION_AEO,
    DIMENSION_TECHNICAL,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_family_profile import CAPABILITY_FAMILY_MANIFEST
from app.core.config.site_health_measurement import expected_checkpoints
from app.core.config.site_health_rule_types import (
    COMPOSITE_THRESHOLD_ALL_REQUIRED,
    COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE,
    FINDING_CLASS_ADVISORY,
    FINDING_CLASS_DEFECT,
    FINDING_CLASS_DIAGNOSTIC,
    KIND_EVIDENCE_CLASSES,
    KIND_EVIDENCE_TRIGGERED,
    RULE_SCOPE_CLUSTER,
    RULE_SCOPE_GRAPH,
    RULE_SCOPE_PAGE,
    RULE_SCOPE_SITE,
    SCORE_ROLE_AEO,
    SCORE_ROLE_WEB_FUNDAMENTALS,
    CompositeAtom,
    CompositeContract,
    SiteHealthRule,
    validate_triggered_rule_links,
)
from app.core.config.site_health_rules import (
    ANSWER_FIRST_MIN_WORDS,
    META_DESCRIPTION_LENGTH_BAND,
    QUESTION_HEADINGS_MIN_RATIO,
    SERVER_RENDERED_MIN_WORDS,
    SITE_HEALTH_RULES,
    TITLE_LENGTH_BAND,
    TTFB_WARN_MS,
)
from app.core.config.site_health_taxonomy import (
    MIN_MEANINGFUL_WORDS,
    PAGE_KIND_PROFILES,
)

# The rules whose rows the finalize-writer owns: never applicable per-page.
_CRAWL_FINALIZE_RULE_IDS = {
    rule.rule_id
    for rule in SITE_HEALTH_RULES
    if rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE
}


def _html_facts(**overrides):
    """A fully healthy homepage (+ healthy site) so every per-page rule passes."""
    facts = {
        "has_html": True,
        "page_kind": "homepage",
        # Classification confidence is retained as display metadata only.
        "page_kind_evidence": {"tier": "structural", "confidence": "high"},
        "title": "Acme Widgets — everything you need to know",
        "meta_description": (
            "Acme Widgets helps teams ship reliable widgets faster with "
            "fewer surprises."
        ),
        "canonical_url": "https://x.example/",
        "robots": {"noindex": False, "nofollow": False},
        "images": {"count": 0, "missing_alt": 0, "decorative_alt": 0},
        "accessibility": {
            "control_count": 0,
            "controls_missing_accessible_name": 0,
            "heading_levels": [1, 2, 2],
            "heading_level_skips": 0,
            "document_language": "en",
        },
        "mobile": {"viewport": {"declared": True, "content": "width=device-width"}},
        "links": {
            "anchors": [{"url": "/about", "anchor_text": "About", "is_internal": True}],
            "images": [],
            "scripts": [],
            "stylesheets": [],
        },
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
                    "url": "https://x.example/",
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
            "word_count": MIN_MEANINGFUL_WORDS + 10,
            "text": "word " * (MIN_MEANINGFUL_WORDS + 10),
        },
        "author": "Jane Doe",
        "authorship": {
            "declared_author": "Jane Doe",
            "declared_author_source": "json_ld",
            "visible_byline": "Jane Doe",
            "visible_date": "2026-01-15",
            "visible_profile_url": "https://x.example/authors/jane-doe",
        },
        "dates": {"published": "2026-01-15", "modified": "2026-06-01"},
        "freshness_context": {"required": False, "reasons": []},
        "source_support": {
            "primary_content_available": True,
            "research_sensitive": False,
            "context_reasons": [],
            "attached_sources": [],
            "ambiguous_source_count": 0,
            "invalid_source_count": 0,
        },
        "question_heading_ratio": 0.5,
        "direct_answer": (
            "Acme widgets are reliable little gadgets that just work for every team."
        ),
        "editorial_lead": (
            "Acme widgets are reliable little gadgets that just work for every team."
        ),
        "entity_proposition": {
            "identity": "Acme Widgets",
            "proposition": (
                "Acme widgets are reliable little gadgets that just work for "
                "every team."
            ),
            "provider": "Acme Widgets",
            "named_capability": "Reliable widgets",
            "audience_or_outcome": "Every team",
            "next_action": "Learn more",
        },
        "primary_heading_outline": [
            {"level": 1, "text": "Acme Widgets — everything you need to know"},
            {"level": 2, "text": "What are Acme widgets?"},
            {"level": 2, "text": "Pricing"},
        ],
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
    if "headings" in overrides and "primary_heading_outline" not in overrides:
        headings = facts.get("headings") or {}
        facts["primary_heading_outline"] = [
            *(
                {"level": 1, "text": str(text)}
                for text in headings.get("h1_texts") or ()
            ),
            *(
                {"level": 2, "text": str(text)}
                for text in headings.get("h2_texts") or ()
            ),
            *(
                {"level": 3, "text": str(text)}
                for text in headings.get("h3_texts") or ()
            ),
        ]
    return facts


def test_measurement_registry_covers_every_page_kind_and_checkpoint() -> None:
    from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER, PAGE_KINDS

    readiness_ids = {
        checkpoint_id
        for family in CAPABILITY_FAMILY_MANIFEST
        for checkpoint_id in family.checkpoint_ids
    }
    for page_kind in PAGE_KINDS:
        checkpoints = expected_checkpoints(
            page_kind, (), {"is_site_root": page_kind == "homepage"}
        )
        assert set(checkpoints) <= readiness_ids
    assert "aeo.schema_expected_for_type" not in expected_checkpoints(PAGE_KIND_OTHER)


def test_missing_expected_structure_is_a_determinate_failure() -> None:
    facts = _html_facts(page_kind="faq")
    facts["headings"] = {"h1_count": 1, "counts": {"h1": 1}, "h1_texts": ["FAQ"]}
    facts["primary_heading_outline"] = [{"level": 1, "text": "FAQ"}]
    evaluation = _outcome(facts, "aeo.question_headings")
    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.expected_profile_membership is True
    assert evaluation.score_roles == ("aeo_readiness",)


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
    "aeo.visible_attribution",
    "aeo.content_date_present",
    "aeo.editorial_lead_present",
    "aeo.source_support_present",
    "aeo.answer_first",
    "aeo.question_headings",
}


def test_all_rules_pass_on_healthy_page():
    facts = _html_facts()
    evals = evaluate_all(facts)
    assert {e.rule_id for e in evals} == {r.rule_id for r in SITE_HEALTH_RULES}
    for evaluation in evals:
        if not evaluation.display_applicability:
            assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE, evaluation.rule_id
        else:
            assert evaluation.outcome == RULE_OUTCOME_SATISFIED, evaluation.rule_id
    # Provenance carried through from the catalog.
    title_eval = next(e for e in evals if e.rule_id == "technical.title_present")
    assert title_eval.dimension == DIMENSION_TECHNICAL
    assert title_eval.weight == 3.0
    assert title_eval.remediation


def test_title_absent_fails():
    ev = _outcome(_html_facts(title=""), "technical.title_present")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["present"] is False


def test_meta_description_absent_fails():
    ev = _outcome(
        _html_facts(meta_description=""),
        "technical.meta_description_present",
    )
    assert ev.outcome == RULE_OUTCOME_MISSING


def test_canonical_absent_fails():
    ev = _outcome(_html_facts(canonical_url=""), "technical.canonical_present")
    assert ev.outcome == RULE_OUTCOME_MISSING


def test_form_name_evidence_includes_bounded_control_descriptors() -> None:
    ev = _outcome(
        _html_facts(
            accessibility={
                "control_count": 3,
                "controls_missing_accessible_name": 1,
                "controls_missing_accessible_name_descriptors": [
                    {
                        "tag": "input",
                        "type": "email",
                        "id": "contact",
                        "name": "email",
                        "ordinal": 2,
                    }
                ],
                "heading_levels": [1, 2],
                "heading_level_skips": 0,
                "document_language": "en",
            }
        ),
        "web.accessibility_form_names",
    )

    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence == {
        "control_count": 3,
        "missing_accessible_name": 1,
        "missing_control_descriptors": [
            {
                "tag": "input",
                "type": "email",
                "id": "contact",
                "name": "email",
                "ordinal": 2,
            }
        ],
    }


def test_heading_evidence_distinguishes_full_document_and_primary_content() -> None:
    web = _outcome(
        _html_facts(
            accessibility={
                "control_count": 0,
                "controls_missing_accessible_name": 0,
                "heading_levels": [1, 3],
                "heading_level_skips": 1,
                "document_language": "en",
            }
        ),
        "web.accessibility_heading_order",
    )
    aeo = _outcome(
        _html_facts(
            primary_heading_outline=[
                {"level": 1, "text": "Title"},
                {"level": 3, "text": "Details"},
            ]
        ),
        "aeo.heading_hierarchy",
    )

    assert web.outcome == RULE_OUTCOME_MISSING
    assert web.evidence["skips"] == [{"from": 1, "to": 3, "scope": "full_document"}]
    assert aeo.outcome == RULE_OUTCOME_MISSING
    assert aeo.evidence["skips"] == [{"from": 1, "to": 3, "scope": "primary_content"}]


def test_full_document_heading_skip_evidence_scans_beyond_displayed_levels() -> None:
    levels = [1] * 64 + [3]
    web = _outcome(
        _html_facts(
            accessibility={
                "control_count": 0,
                "controls_missing_accessible_name": 0,
                "heading_levels": levels,
                "heading_level_skips": 1,
                "document_language": "en",
            }
        ),
        "web.accessibility_heading_order",
    )

    assert web.evidence["heading_levels"] == levels[:64]
    assert web.evidence["skips"] == [{"from": 1, "to": 3, "scope": "full_document"}]


def test_empty_primary_outline_does_not_invent_a_skipped_transition() -> None:
    evaluation = _outcome(
        _html_facts(primary_heading_outline=[]),
        "aeo.heading_hierarchy",
    )

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence == {"levels": [], "skips": []}


def test_noindex_fails_indexable():
    facts = _html_facts(robots={"noindex": True, "nofollow": False})
    ev = _outcome(facts, "technical.indexable")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["noindex"] is True


def test_http_fails_https_rule():
    facts = _html_facts(
        delivery={"is_https": False, "scheme": "http", "final_url": "http://x"}
    )
    ev = _outcome(facts, "technical.https")
    assert ev.outcome == RULE_OUTCOME_MISSING


def test_zero_or_multiple_h1_fails_single_h1():
    assert (
        _outcome(_html_facts(headings={"h1_count": 0}), "technical.single_h1").outcome
        == RULE_OUTCOME_MISSING
    )
    assert (
        _outcome(_html_facts(headings={"h1_count": 2}), "technical.single_h1").outcome
        == RULE_OUTCOME_MISSING
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
    assert ev.outcome == RULE_OUTCOME_MISSING


def test_open_graph_incomplete_fails():
    ev = _outcome(_html_facts(open_graph={"og:title": "T"}), "aeo.open_graph_present")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["has_og_description"] is False


def test_thin_content_fails_on_an_empty_page():
    ev = _outcome(
        _html_facts(page_kind=None, body={"word_count": MIN_MEANINGFUL_WORDS - 1}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["minimum"] == MIN_MEANINGFUL_WORDS


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
    # A supported document is successful inventory evidence, not a broken page.
    # These three were "always" rules, so a PDF was reported as missing a
    # <title>, a meta description and a canonical -- three metadata defects
    # about markup the format does not have.
    assert evals["technical.title_present"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert evals["technical.meta_description_present"].outcome == (
        RULE_OUTCOME_NOT_APPLICABLE
    )
    assert evals["technical.canonical_present"].outcome == RULE_OUTCOME_NOT_APPLICABLE
    # Delivery-level "always" rules still evaluate: they read the response,
    # not the markup.
    assert evals["technical.https"].outcome == RULE_OUTCOME_SATISFIED
    assert evals["technical.indexable"].outcome == RULE_OUTCOME_SATISFIED


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
        authorship={
            "declared_author": "",
            "declared_author_source": "",
            "visible_byline": "",
            "visible_date": "",
            "visible_profile_url": "",
        },
        dates={},
        freshness_context={"required": True, "reasons": ["time_bound_report"]},
        source_support={
            "primary_content_available": False,
            "research_sensitive": True,
            "context_reasons": ["time_bound_report"],
            "attached_sources": [],
            "ambiguous_source_count": 0,
            "invalid_source_count": 0,
        },
        direct_answer="",
    )


def test_js_shell_reports_one_finding_not_a_cascade():
    """Content rules are N/A on a shell; the shell rule itself still fails.

    The crawler is HTTP-only, so a client-rendered page arrives with an empty
    body. Content-reading rules must not report missing evidence that could not
    be inspected; the rendering diagnostic owns that observable limitation.
    """
    evals = {e.rule_id: e for e in evaluate_all(_js_shell_facts())}

    # The one true finding, still reported at its catalog severity.
    assert evals["aeo.server_rendered_content"].outcome == RULE_OUTCOME_MISSING

    # Its derivatives are skipped, and say why.
    for rule_id in (
        "technical.single_h1",
        "technical.thin_content",
        "aeo.source_support_present",
        "aeo.visible_attribution",
        "aeo.content_date_present",
    ):
        assert evals[rule_id].outcome == RULE_OUTCOME_NOT_APPLICABLE, rule_id
        assert evals[rule_id].evidence["reason"] == "content_not_server_rendered"

    # Rules about the SERVED MARKUP are unaffected: what a non-rendering
    # crawler receives is exactly what this product is about, so a shell that
    # ships no JSON-LD is still a genuine structured-data finding.
    assert evals["aeo.structured_data_present"].outcome != RULE_OUTCOME_NOT_APPLICABLE
    assert evals["technical.title_present"].outcome == RULE_OUTCOME_SATISFIED
    assert evals["technical.https"].outcome == RULE_OUTCOME_SATISFIED
    # Skipped too, but for a different reason: the shell fixture is an article
    # and question headings are asked of FAQ pages only.
    assert evals["aeo.question_headings"].outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_content_rules_still_apply_to_a_server_rendered_page():
    """The gate must not swallow real findings on a normally-rendered page."""
    facts = _html_facts(headings={"h1_count": 0, "counts": {"h1": 0, "h2": 3}})
    ev = _outcome(facts, "technical.single_h1")
    assert ev.outcome == RULE_OUTCOME_MISSING
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
    assert ev.reason_code == "check_error"
    assert ev.score_roles == ()
    assert ev.score_applicability is False
    assert ev.expected_profile_membership is True


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
    assert ev.reason_code == "no_check_mapped"
    assert ev.readiness_dimension == ""


def test_unknown_applicability_key_is_unknown_not_semantic_na():
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
    assert ev.outcome == RULE_OUTCOME_UNKNOWN
    assert ev.reason_code == "unknown_applicability"


def test_rule_scope_defaults_validate_and_match_current_owners() -> None:
    default = SiteHealthRule(
        rule_id="technical.title_present",
        rule_version="1",
        dimension=DIMENSION_TECHNICAL,
        category="metadata",
        severity="low",
        weight=1.0,
        applicability_key="always",
        description="",
        remediation="",
    )
    assert default.scope == RULE_SCOPE_PAGE
    with pytest.raises(ValueError, match="Unsupported rule scope"):
        SiteHealthRule(
            rule_id="technical.title_present",
            rule_version="1",
            dimension=DIMENSION_TECHNICAL,
            category="metadata",
            severity="low",
            weight=1.0,
            applicability_key="always",
            description="",
            remediation="",
            scope="unknown",
        )
    assert rule_for("technical.ai_crawler_access").scope == RULE_SCOPE_SITE
    assert rule_for("search.crawler_access").scope == RULE_SCOPE_SITE
    assert rule_for("aeo.llms_txt_present").scope == RULE_SCOPE_SITE
    assert rule_for("technical.sitemap_orphan").scope == RULE_SCOPE_CLUSTER
    assert rule_for("technical.hreflang_conflict").scope == RULE_SCOPE_CLUSTER
    assert rule_for("architecture.orphan_pages").scope == RULE_SCOPE_GRAPH
    assert (
        rule_for("architecture.duplicate_metadata_in_page_kind").scope
        == RULE_SCOPE_CLUSTER
    )
    assert _outcome(_html_facts(), "technical.title_present").scope == RULE_SCOPE_PAGE


def test_composite_contract_marks_all_structurally_inapplicable_atoms_not_applicable():
    contract = CompositeContract(
        atoms=(
            CompositeAtom(
                name="variant",
                required=False,
                condition="page_trait:has_variants",
            ),
        ),
        threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED,
    )
    atoms = [
        contract.atom_detail("variant", satisfied=False, evidence=False, page_traits=())
    ]
    assert atoms[0]["outcome"] == RULE_OUTCOME_NOT_APPLICABLE
    assert contract.outcome_for(atoms) == RULE_OUTCOME_NOT_APPLICABLE


def test_composite_threshold_controls_optional_atom_failure():
    atom = CompositeAtom(name="optional", required=False)
    all_required = CompositeContract(
        atoms=(atom,), threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED
    )
    all_applicable = CompositeContract(
        atoms=(atom,), threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE
    )
    failed = [
        all_required.atom_detail(
            "optional", satisfied=False, evidence=False, page_traits=()
        )
    ]
    assert all_required.outcome_for(failed) == RULE_OUTCOME_SATISFIED
    assert all_applicable.outcome_for(failed) == RULE_OUTCOME_PARTIAL


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
    assert ev.outcome == RULE_OUTCOME_SATISFIED


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


def test_length_alone_never_decides_a_page_is_bad():
    """The per-kind ladder is gone: 40 for a homepage up to 300 for an article.

    Segmenting by kind beat one global threshold, but the premise underneath
    was still that length proves substance. A 150-word article is short; it is
    not defective, and the analyzer has no way to tell the difference.
    """
    short_but_real = {"word_count": MIN_MEANINGFUL_WORDS + 1, "text": "word " * 30}
    for page_kind in ("article", "guide", "comparison", "docs", "other"):
        ev = _outcome(
            _html_facts(page_kind=page_kind, body=short_but_real),
            "technical.thin_content",
        )
        assert ev.outcome == RULE_OUTCOME_SATISFIED, page_kind
        assert ev.evidence["minimum"] == MIN_MEANINGFUL_WORDS


def test_thin_content_without_page_type_falls_back_to_other():
    ev = _outcome(
        _html_facts(page_kind=None, body={"word_count": MIN_MEANINGFUL_WORDS}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["minimum"] == MIN_MEANINGFUL_WORDS
    assert ev.evidence["page_kind"] == "other"


def test_a_listing_page_is_sufficient_because_it_lists():
    """25 words over 60 products is an excellent category page.

    Below the floor a page can still prove itself structurally. This is the
    only thing the per-kind knowledge is used for now, and it can only ever
    ADD a way to pass -- nothing here fails a page the floor would have passed.
    """
    almost_empty = {"word_count": 5, "text": "Women dresses sorted by"}
    listing = _outcome(
        _html_facts(page_kind="category", page_traits=["listing"], body=almost_empty),
        "technical.thin_content",
    )
    assert listing.outcome == RULE_OUTCOME_SATISFIED
    assert listing.evidence["structurally_sufficient"] is True
    # Same page kind, same word count, no listing: genuinely empty.
    empty = _outcome(
        _html_facts(page_kind="category", page_traits=[], body=almost_empty),
        "technical.thin_content",
    )
    assert empty.outcome == RULE_OUTCOME_MISSING
    assert empty.evidence["structurally_sufficient"] is False


def test_a_commercial_page_is_sufficient_because_it_shows_a_price():
    almost_empty = {"word_count": 6, "text": "Ilkley Refectory Table 1240"}
    priced = _outcome(
        _html_facts(
            page_kind="product",
            body=almost_empty,
            entity={"product": {"has_primary_price": True}},
        ),
        "technical.thin_content",
    )
    assert priced.outcome == RULE_OUTCOME_SATISFIED
    assert priced.evidence["structural_signal"] == "price"


def test_a_contact_or_about_page_proves_itself_either_way():
    # The two halves of the bundled kind have different evidence, and either
    # one is enough: a contact page hands over a way to reply, an about page
    # identifies the entity.
    almost_empty = {"word_count": 4, "text": "Northgate Joinery Leeds"}
    for traits in (["contact_intent"], ["about_intent"]):
        ev = _outcome(
            _html_facts(
                page_kind="about_contact", page_traits=traits, body=almost_empty
            ),
            "technical.thin_content",
        )
        assert ev.outcome == RULE_OUTCOME_SATISFIED, traits


def test_structural_sufficiency_only_ever_adds_a_pass():
    # A kind with no structural signal is judged on the floor alone, which is
    # the correct answer rather than a gap.
    ev = _outcome(
        _html_facts(page_kind="article", page_traits=[], body={"word_count": 200}),
        "technical.thin_content",
    )
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert "structural_signal" not in ev.evidence


def test_thin_content_weight_is_reduced_on_a_homepage():
    # Emptiness matters less on the one page whose job is to route visitors
    # elsewhere, so the weight override survives the threshold removal.
    ev = _outcome(
        _html_facts(page_kind="homepage", body={"word_count": MIN_MEANINGFUL_WORDS}),
        "technical.thin_content",
    )
    assert ev.weight == 1.0
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["minimum"] == MIN_MEANINGFUL_WORDS


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
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["self_canonical"] is True


def test_canonical_conflict_normalization_variants_still_match():
    # Scheme/host case, default port, fragment, and trailing slash differences
    # are all normalized away for the comparison.
    facts = _html_facts(canonical_url="HTTPS://X.Example:443/#section")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    facts = _html_facts(canonical_url="https://x.example")
    assert _outcome(facts, "technical.canonical_conflict").outcome == (
        RULE_OUTCOME_SATISFIED
    )


def test_a_same_origin_cross_canonical_is_not_a_conflict():
    """Consolidating one URL onto another is what rel=canonical is FOR.

    The old rule failed every canonical that was not the page own final URL,
    so a sorted listing pointing at its parent -- the textbook use -- became a
    defect. It also contradicted ``_canonical_intent``, which reads the very
    same condition as evidence the page is deliberately excluded: one module
    called it a mistake while the other called it an intention.
    """
    facts = _html_facts(canonical_url="https://x.example/other-page")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["self_canonical"] is False
    assert ev.evidence["reason"] == "intentional_consolidation"
    assert ev.evidence["canonical_url"] == "https://x.example/other-page"
    assert ev.evidence["final_url"] == "https://x.example/"


def test_tracking_parameters_are_not_a_canonical_conflict():
    # Reached from a newsletter: the tracking parameter describes how the
    # crawler arrived, not the page.
    facts = _html_facts(
        canonical_url="https://x.example/post",
        delivery={
            **_html_facts()["delivery"],
            "final_url": "https://x.example/post?utm_source=newsletter",
        },
    )
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["self_canonical"] is True


def test_a_relative_canonical_resolves_before_comparing():
    # A relative canonical href is legal and common. The declared value is
    # recorded raw, so comparing it against an absolute final URL could never
    # match and every such page looked like a conflict.
    facts = _html_facts(canonical_url="/")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["self_canonical"] is True
    assert ev.evidence["declared_canonical"] == "/"
    assert ev.evidence["canonical_url"] == "https://x.example/"


def test_canonical_to_another_origin_fails():
    facts = _html_facts(canonical_url="https://other.example/page")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["problem"] == "cross_origin_canonical"


def test_unresolvable_canonical_fails():
    facts = _html_facts(canonical_url="javascript:void(0)")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["problem"] == "invalid_canonical"


def test_a_different_port_is_a_different_origin():
    """An origin is scheme, host AND port.

    Dropping the port made ``https://x.example:444/a`` compare equal to
    ``https://x.example/a``, so a canonical handing indexing authority across
    two origins read as ordinary same-origin consolidation and passed. It also
    disagreed with ``normalized_url_for_compare``, which has always kept the
    port -- the two comparisons in one rule contradicted each other.
    """
    facts = _html_facts(canonical_url="https://x.example:444/")
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["problem"] == "cross_origin_canonical"


def test_a_default_port_is_still_the_same_origin():
    # :443 on HTTPS is the same origin as no port at all, the same rule
    # normalized_url_for_compare already applies.
    ev = _outcome(
        _html_facts(canonical_url="https://x.example:443/"),
        ("technical.canonical_conflict"),
    )
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["self_canonical"] is True


@pytest.mark.parametrize(
    "canonical",
    [
        "https://x.example:notaport/",
        "https://x.example:99999/",
    ],
)
def test_an_unreadable_port_makes_the_canonical_invalid(canonical):
    """``urlsplit`` is lazy about the port and only raises when it is read.

    Swallowing that and substituting None made the port vanish, so a malformed
    authority normalized to a clean one and compared EQUAL to the page it was
    a broken canonical for -- passing as self-canonical.
    """
    ev = _outcome(_html_facts(canonical_url=canonical), "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["problem"] == "invalid_canonical"


def test_an_unparseable_canonical_is_not_intent_evidence():
    """It is not evidence in either direction, so precedence falls through.

    Before the port was validated this compared equal to the page and read as
    intended_index. Treating the mismatch as intent instead would swing it to
    intended_exclude and suppress the noindex defect entirely, which is the
    worse of the two errors -- so it yields no canonical evidence at all.
    """
    ev = _outcome(
        _html_facts(
            robots={"noindex": True, "nofollow": False},
            canonical_url="https://x.example:notaport/",
            sitemap_member=True,
        ),
        "technical.indexable",
    )
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["canonical_unparseable"] is True
    assert ev.evidence["intent_source"] == "sitemap_membership"


def test_canonical_to_a_different_hreflang_alternate_fails():
    # A page in an hreflang cluster must canonicalise to ITSELF; pointing at a
    # sibling language tells the two systems opposite things.
    facts = _html_facts(
        canonical_url="https://x.example/fr/",
        hreflang_alternates=[
            {"hreflang": "en", "url": "https://x.example/"},
            {"hreflang": "fr", "url": "https://x.example/fr/"},
        ],
    )
    ev = _outcome(facts, "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["problem"] == "hreflang_canonical_conflict"


def test_same_language_hreflang_canonical_is_intentional_consolidation():
    facts = _html_facts(
        canonical_url="https://x.example/products/linen-shirt",
        delivery={
            **_html_facts()["delivery"],
            "final_url": ("https://x.example/collections/sale/products/linen-shirt"),
        },
        hreflang_alternates=[
            {
                "hreflang": "x-default",
                "url": "https://x.example/products/linen-shirt",
            },
            {
                "hreflang": "en-US",
                "url": "https://x.example/products/linen-shirt",
            },
            {
                "hreflang": "fr-FR",
                "url": "https://x.example/fr/products/linen-shirt",
            },
        ],
    )

    ev = _outcome(facts, "technical.canonical_conflict")

    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["reason"] == "intentional_consolidation"
    assert ev.evidence["canonical_hreflang_languages"] == ["x-default", "en-us"]
    assert ev.evidence["document_language"] == "en"


def test_hreflang_canonical_abstains_without_document_language():
    facts = _html_facts(
        canonical_url="https://x.example/fr/",
        hreflang_alternates=[
            {"hreflang": "fr", "url": "https://x.example/fr/"},
        ],
        accessibility="malformed persisted evidence",
    )

    ev = _outcome(facts, "technical.canonical_conflict")

    assert ev.outcome == RULE_OUTCOME_UNKNOWN
    assert ev.evidence["reason"] == "document_language_unavailable"


def test_canonical_conflict_not_applicable_without_canonical():
    # The v1 presence rule owns the missing-canonical finding.
    ev = _outcome(_html_facts(canonical_url=""), "technical.canonical_conflict")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_canonical"


def test_indexability_uses_strong_intent_evidence_in_precedence_order():
    explicit = _outcome(
        _html_facts(
            robots={"noindex": True, "nofollow": False},
            indexing_policy="exclude",
            canonical_url="https://x.example/",
            sitemap_member=True,
        ),
        "technical.indexable",
    )
    assert explicit.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert explicit.finding_class == FINDING_CLASS_DEFECT
    assert explicit.evidence["intent_source"] == "explicit_user_policy"

    canonical_exclude = _outcome(
        _html_facts(
            robots={"noindex": True, "nofollow": False},
            canonical_url="https://x.example/preferred",
            sitemap_member=True,
        ),
        "technical.indexable",
    )
    assert canonical_exclude.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert canonical_exclude.evidence["intent_source"] == "canonical_declaration"

    sitemap_index = _outcome(
        _html_facts(
            robots={"noindex": True, "nofollow": False},
            canonical_url="",
            sitemap_member=True,
        ),
        "technical.indexable",
    )
    assert sitemap_index.outcome == RULE_OUTCOME_MISSING
    assert sitemap_index.finding_class == FINDING_CLASS_DEFECT
    assert sitemap_index.severity == "critical"


def test_unknown_noindex_intent_preserves_rule_metadata_without_a_missing_outcome():
    result = _outcome(
        _html_facts(
            robots={"noindex": True, "nofollow": False},
            canonical_url="",
            sitemap_member=False,
        ),
        "technical.indexable",
    )
    assert result.outcome == RULE_OUTCOME_UNKNOWN
    assert result.finding_class == FINDING_CLASS_DEFECT
    assert result.severity == "critical"
    assert result.evidence == {
        "noindex": True,
        "nofollow": False,
        "indexing_intent": "unknown",
        "intent_source": "insufficient_evidence",
        "reason": "insufficient_evidence",
    }


def test_title_length_band():
    low, high = TITLE_LENGTH_BAND
    assert _outcome(_html_facts(), "technical.title_length_band").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    short = _outcome(_html_facts(title="x" * (low - 1)), "technical.title_length_band")
    assert short.outcome == RULE_OUTCOME_MISSING
    assert short.finding_class == FINDING_CLASS_ADVISORY
    assert short.expected_profile_membership is True
    assert short.score_applicability is False
    assert short.score_roles == ()
    assert short.evidence["title_length"] == low - 1
    assert short.evidence["band"] == [low, high]
    long = _outcome(_html_facts(title="x" * (high + 1)), "technical.title_length_band")
    assert long.outcome == RULE_OUTCOME_MISSING
    # Band edges are inclusive.
    for length in (low, high):
        ev = _outcome(_html_facts(title="x" * length), "technical.title_length_band")
        assert ev.outcome == RULE_OUTCOME_SATISFIED


def test_title_length_band_not_applicable_when_empty():
    ev = _outcome(_html_facts(title=""), "technical.title_length_band")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "empty_title"


def test_meta_description_length_band():
    low, high = META_DESCRIPTION_LENGTH_BAND
    assert (
        _outcome(_html_facts(), "technical.meta_description_length_band").outcome
        == RULE_OUTCOME_SATISFIED
    )
    short = _outcome(
        _html_facts(meta_description="x" * (low - 1)),
        "technical.meta_description_length_band",
    )
    assert short.outcome == RULE_OUTCOME_MISSING
    assert short.finding_class == FINDING_CLASS_ADVISORY
    assert short.evidence["description_length"] == low - 1
    assert short.evidence["band"] == [low, high]
    long = _outcome(
        _html_facts(meta_description="x" * (high + 1)),
        "technical.meta_description_length_band",
    )
    assert long.outcome == RULE_OUTCOME_MISSING


def test_meta_description_length_band_not_applicable_when_empty():
    ev = _outcome(
        _html_facts(meta_description=""), "technical.meta_description_length_band"
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "empty_meta_description"


def test_web_fundamentals_defect_is_scored_and_creates_an_issue():
    facts = _html_facts()
    facts["images"]["missing_alt"] = 1

    evaluation = _outcome(facts, "web.accessibility_image_alt")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.weight == 2.0
    assert evaluation.score_roles == (SCORE_ROLE_WEB_FUNDAMENTALS,)
    assert creates_issue(evaluation) is True

    scores = score_analysis(evaluate_all(facts), page_kind="homepage")
    assert scores.web_fundamentals_score is not None
    assert scores.web_fundamentals_score < 100


def test_non_scoring_advisory_does_not_create_an_issue():
    evaluation = _outcome(_html_facts(title="short"), "technical.title_length_band")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.finding_class == FINDING_CLASS_ADVISORY
    assert evaluation.score_roles == ()
    assert creates_issue(evaluation) is False


def test_hsts_present():
    assert _outcome(_html_facts(), "technical.hsts_present").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    facts = _html_facts()
    facts["delivery"]["security_headers"] = {"strict-transport-security": False}
    ev = _outcome(facts, "technical.hsts_present")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["present"] is False
    assert ev.evidence["scheme"] == "https"


def test_ttfb_band():
    assert _outcome(_html_facts(), "technical.ttfb_band").outcome == (
        RULE_OUTCOME_SATISFIED
    )

    def _with_ttfb(ttfb):
        facts = _html_facts()
        facts["delivery"]["ttfb_ms"] = ttfb
        return _outcome(facts, "technical.ttfb_band")

    assert _with_ttfb(TTFB_WARN_MS).outcome == RULE_OUTCOME_SATISFIED
    slow = _with_ttfb(TTFB_WARN_MS + 1)
    assert slow.outcome == RULE_OUTCOME_MISSING
    assert slow.evidence["ttfb_ms"] == TTFB_WARN_MS + 1
    assert slow.evidence["threshold_ms"] == TTFB_WARN_MS
    unmeasured = _with_ttfb(None)
    assert unmeasured.outcome == RULE_OUTCOME_UNKNOWN
    assert unmeasured.reason_code == "no_ttfb_measurement"


def test_uncompressed_html():
    assert _outcome(_html_facts(), "technical.uncompressed_html").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    facts = _html_facts()
    facts["delivery"]["is_compressed"] = False
    facts["delivery"]["content_encoding"] = ""
    ev = _outcome(facts, "technical.uncompressed_html")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["is_compressed"] is False


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
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["blocked"] == []
    # The bounded stance covers every configured bot.
    assert set(ev.evidence["ai_crawlers"]) == set(AI_CRAWLER_BOTS)


def test_ai_crawler_access_unknown_when_robots_not_fetched():
    # An unfetched robots.txt yields the fail-open all-allow stance: passing
    # a HIGH-severity signal on that would be vacuous — unknown instead.
    facts = _html_facts()
    facts["site"]["robots"]["fetched"] = False
    facts["site"]["robots"]["status_code"] = None
    ev = _outcome(facts, "technical.ai_crawler_access")
    assert ev.outcome == RULE_OUTCOME_UNKNOWN
    assert ev.evidence["reason"] == "robots_not_fetched"
    assert ev.evidence["robots_fetched"] is False
    # The stance evidence is still carried (bounded, all bots).
    assert set(ev.evidence["ai_crawlers"]) == set(AI_CRAWLER_BOTS)


def test_ai_crawler_access_fails_when_any_bot_blocked():
    facts = _html_facts()
    facts["site"]["robots"]["ai_crawlers"]["GPTBot"] = AI_CRAWLER_STANCE_BLOCK
    ev = _outcome(facts, "technical.ai_crawler_access")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["blocked"] == ["GPTBot"]
    assert ev.evidence["ai_crawlers"]["GPTBot"] == AI_CRAWLER_STANCE_BLOCK
    assert ev.evidence["robots_fetched"] is True


def test_llms_txt_present():
    assert _outcome(_html_facts(), "aeo.llms_txt_present").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    facts = _html_facts()
    facts["site"]["llms_txt"]["present"] = False
    ev = _outcome(facts, "aeo.llms_txt_present")
    assert ev.outcome == RULE_OUTCOME_MISSING
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
    assert ev.outcome == RULE_OUTCOME_SATISFIED
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
    assert ev.outcome == RULE_OUTCOME_MISSING
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
        RULE_OUTCOME_MISSING
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
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["missing"] == []


def test_schema_required_valid_uses_the_bound_primary_entity() -> None:
    facts = _html_facts(
        structured_data=_sd(
            [
                {
                    "type": "Organization",
                    "syntax": "json-ld",
                    "schema_id": "#unrelated",
                    "url": "https://other.example/",
                    "props_present": ["name", "url"],
                },
                {
                    "type": "Organization",
                    "syntax": "json-ld",
                    "schema_id": "#primary",
                    "url": "https://x.example/",
                    "props_present": ["url"],
                },
            ]
        )
    )

    evaluation = _outcome(facts, "aeo.schema_required_valid")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.evidence["missing"] == ["name"]
    assert evaluation.evidence["checked_blocks"] == 1
    assert evaluation.evidence["required"] == ["name", "url"]


def test_schema_recommended_present():
    assert _outcome(_html_facts(), "aeo.schema_recommended_present").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    # Missing one recommended property (logo) -> low-weight fail.
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["props_present"] = ["name", "url", "sameAs"]
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_recommended_present")
    assert ev.outcome == RULE_OUTCOME_MISSING
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
    assert ev.outcome == RULE_OUTCOME_MISSING
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
    assert ev.outcome == RULE_OUTCOME_MISSING
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


def test_generic_article_schema_does_not_self_certify_a_procedural_guide():
    article = {
        "type": "Article",
        "syntax": "json-ld",
        "name": "Install Acme",
        "props_present": ["headline", "image", "dateModified"],
    }
    guide = _html_facts(
        page_kind="guide",
        page_traits=["procedural"],
        structured_data=_sd([article]),
    )

    expected = _outcome(guide, "aeo.schema_expected_for_type")
    required = _outcome(guide, "aeo.schema_required_valid")

    assert expected.outcome == RULE_OUTCOME_MISSING
    assert expected.reason_code == "expected_schema_absent"
    assert required.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert required.reason_code == "no_expected_type_block"


def test_website_does_not_receive_organization_recommendations():
    website = {
        "type": "WebSite",
        "syntax": "json-ld",
        "name": "Acme",
        "props_present": ["name", "url"],
    }
    homepage = _html_facts(structured_data=_sd([website]))

    assert _outcome(homepage, "aeo.schema_required_valid").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    recommended = _outcome(homepage, "aeo.schema_recommended_present")
    assert recommended.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert recommended.evidence["reason"] == "no_recommended_properties"


def test_schema_matches_content():
    # The healthy fixture's Organization name appears in the title.
    assert _outcome(_html_facts(), "aeo.schema_matches_content").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["name"] = "Totally Unrelated Brand"
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_matches_content")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["matched_visible_content"] is False
    assert ev.evidence["candidates"] == ["Totally Unrelated Brand"]


def test_schema_content_match_rejects_one_generic_shared_token():
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["name"] = "Widget Pro"
    facts = _html_facts(
        title="Pro",
        headings={"h1_count": 1, "counts": {"h1": 1}, "h1_texts": ["Pro"]},
        structured_data=_sd([block]),
    )
    assert _outcome(facts, "aeo.schema_matches_content").outcome == RULE_OUTCOME_MISSING


def test_schema_matches_content_not_applicable_without_names():
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["name"] = ""
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.schema_matches_content")
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_schema_names"


def _product_schema_facts(blocks: list[dict]) -> dict:
    facts = _html_facts(
        page_kind="product",
        structured_data=_sd(blocks),
    )
    facts["delivery"]["final_url"] = "https://x.example/products/acme"
    facts["canonical_url"] = "https://x.example/products/acme"
    facts["title"] = "Acme Widget"
    facts["headings"]["h1_texts"] = ["Acme Widget"]
    return facts


def test_unrelated_nested_schema_nodes_do_not_activate_primary_entity_contracts() -> (
    None
):
    facts = _product_schema_facts(
        [
            {
                "type": "Article",
                "syntax": "json-ld",
                "schema_id": "#article",
                "main_entity_id": "#other-product",
                "url": "https://x.example/articles/widget-roundup",
                "props_present": ["headline", "mainEntity"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#other-product",
                "url": "https://other.example/products/other",
                "name": "Other Product",
                "props_present": ["name", "offers"],
            },
            {
                "type": "BreadcrumbList",
                "syntax": "json-ld",
                "schema_id": "#breadcrumbs",
                "main_entity_id": "#other-product",
                "props_present": ["itemListElement"],
            },
        ]
    )

    expected = _outcome(facts, "aeo.schema_expected_for_type")
    required = _outcome(facts, "aeo.schema_required_valid")

    assert expected.outcome == RULE_OUTCOME_MISSING
    assert expected.reason_code == "expected_schema_other_document"
    assert required.outcome != RULE_OUTCOME_SATISFIED


def test_unbound_primary_schema_candidates_are_ambiguous_not_satisfied() -> None:
    facts = _product_schema_facts(
        [
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#one",
                "name": "One",
                "props_present": ["name", "offers"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#two",
                "name": "Two",
                "props_present": ["name", "offers"],
            },
        ]
    )

    evaluation = _outcome(facts, "aeo.schema_expected_for_type")

    assert evaluation.outcome == RULE_OUTCOME_UNKNOWN
    assert evaluation.reason_code == "ambiguous_primary_schema_entity"


def test_unique_corroborated_schema_candidate_resolves_duplicate_declarations() -> None:
    facts = _product_schema_facts(
        [
            {
                "type": "WebPage",
                "syntax": "json-ld",
                "schema_id": "#page",
                "main_entity_id": "#product",
                "url": "https://x.example/products/acme",
                "props_present": ["mainEntity", "url"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#duplicate",
                "main_entity_of_page_id": "#page",
                "name": "Acme Widget",
                "props_present": ["name", "offers"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#product",
                "main_entity_of_page_id": "#page",
                "url": "https://x.example/products/acme",
                "name": "Acme Widget",
                "props_present": ["name", "offers"],
            },
        ]
    )

    evaluation = _outcome(facts, "aeo.schema_expected_for_type")

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence["primary_schema_type"] == "Product"


def test_relative_canonical_binds_schema_entity_to_resolved_document_url() -> None:
    facts = _product_schema_facts(
        [
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#canonical-product",
                "url": "https://x.example/products/acme",
                "name": "Acme Widget",
                "props_present": ["name", "offers"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#other-product",
                "url": "https://x.example/products/other",
                "name": "Other Widget",
                "props_present": ["name", "offers"],
            },
        ]
    )
    facts["delivery"]["final_url"] = "https://x.example/products/current"
    facts["canonical_url"] = "/products/acme"

    evaluation = _outcome(facts, "aeo.schema_expected_for_type")

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence["primary_schema_type"] == "Product"


def test_conflicting_primary_schema_evidence_normalizes_to_unknown() -> None:
    facts = _product_schema_facts(
        [
            {
                "type": "WebPage",
                "syntax": "json-ld",
                "schema_id": "#page",
                "main_entity_id": "#declared",
                "url": "https://x.example/products/acme",
                "props_present": ["mainEntity", "url"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#declared",
                "main_entity_of_page_id": "#page",
                "url": "https://x.example/products/other",
                "name": "Declared Product",
                "props_present": ["name", "offers"],
            },
            {
                "type": "Product",
                "syntax": "json-ld",
                "schema_id": "#visible",
                "url": "https://x.example/products/acme",
                "name": "Acme Widget",
                "props_present": ["name", "offers"],
            },
        ]
    )

    evaluation = _outcome(facts, "aeo.schema_expected_for_type")

    assert evaluation.outcome == RULE_OUTCOME_UNKNOWN
    assert evaluation.reason_code == "conflicting_schema_entities"


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


# --- semantic evidence, attribution, and freshness contracts -----------------


def _source_support_facts(**overrides):
    support = {
        "primary_content_available": True,
        "research_sensitive": True,
        "context_reasons": ["comparison"],
        "attached_sources": [],
        "ambiguous_source_count": 0,
        "invalid_source_count": 0,
    }
    support.update(overrides)
    return _html_facts(page_kind="comparison", source_support=support)


def test_generic_external_link_does_not_earn_source_support() -> None:
    facts = _source_support_facts()
    facts["links"]["anchors"] = [
        {
            "url": "https://research.example/report",
            "anchor_text": "External report",
            "is_internal": False,
            "region": "main",
        }
    ]

    evaluation = _outcome(facts, "aeo.source_support_present")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.reason_code == "source_support_absent"


@pytest.mark.parametrize(
    "relationship",
    [
        "references_section",
        "methodology_section",
        "citation_marker",
        "nearby_attribution",
    ],
)
def test_bounded_source_relationships_satisfy_support(relationship: str) -> None:
    facts = _source_support_facts(
        attached_sources=[
            {
                "url": "https://research.example/report",
                "domain": "research.example",
                "source_name": "Independent Research Group",
                "relationship": relationship,
            }
        ]
    )

    evaluation = _outcome(facts, "aeo.source_support_present")

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.reason_code == ""


def test_ambiguous_and_unavailable_source_evidence_remain_distinct_unknowns() -> None:
    ambiguous = _outcome(
        _source_support_facts(ambiguous_source_count=1),
        "aeo.source_support_present",
    )
    unavailable = _outcome(
        _source_support_facts(primary_content_available=False),
        "aeo.source_support_present",
    )

    assert ambiguous.outcome == RULE_OUTCOME_UNKNOWN
    assert ambiguous.reason_code == "ambiguous_source_attachment"
    assert unavailable.outcome == RULE_OUTCOME_UNKNOWN
    assert unavailable.reason_code == "primary_content_unavailable"


def test_invalid_source_relationship_is_a_determinate_defect() -> None:
    evaluation = _outcome(
        _source_support_facts(invalid_source_count=1),
        "aeo.source_support_present",
    )

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.reason_code == "invalid_source_relationship"


def _attribution_facts(**authorship):
    return _article_facts(
        author="",
        authorship={
            "declared_author": "",
            "declared_author_source": "",
            "visible_byline": "",
            "visible_date": "",
            "visible_profile_url": "",
            **authorship,
        },
    )


def test_visible_named_attribution_and_declared_metadata_are_distinct_atoms() -> None:
    complete = _outcome(
        _attribution_facts(
            visible_byline="Jane Doe",
            visible_profile_url="https://x.example/authors/jane-doe",
            declared_author="Jane Doe",
            declared_author_source="json_ld",
        ),
        "aeo.visible_attribution",
    )
    metadata_only = _outcome(
        _attribution_facts(
            declared_author="Jane Doe",
            declared_author_source="json_ld",
        ),
        "aeo.visible_attribution",
    )
    visible_unlinked = _outcome(
        _attribution_facts(visible_byline="Jane Doe"),
        "aeo.visible_attribution",
    )
    absent = _outcome(_attribution_facts(), "aeo.visible_attribution")

    assert complete.outcome == RULE_OUTCOME_SATISFIED
    assert metadata_only.outcome == RULE_OUTCOME_PARTIAL
    assert metadata_only.reason_code == "declared_attribution_only"
    assert visible_unlinked.outcome == RULE_OUTCOME_SATISFIED
    assert visible_unlinked.reason_code == ""
    assert absent.outcome == RULE_OUTCOME_MISSING
    assert absent.reason_code == "visible_attribution_absent"


@pytest.mark.parametrize(
    "dates",
    [
        {"published": "2026-01-15", "modified": ""},
        {"published": "", "modified": "2026-06-01"},
    ],
)
def test_independently_required_freshness_accepts_either_date(dates: dict) -> None:
    evaluation = _outcome(
        _article_facts(
            dates=dates,
            freshness_context={"required": True, "reasons": ["time_bound_report"]},
        ),
        "aeo.content_date_present",
    )

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED


def test_required_freshness_stays_expected_when_date_is_missing() -> None:
    evaluation = _outcome(
        _article_facts(
            dates={"published": "", "modified": ""},
            freshness_context={"required": True, "reasons": ["time_bound_report"]},
        ),
        "aeo.content_date_present",
    )

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.reason_code == "freshness_signal_missing"
    assert evaluation.expected_profile_membership is True


def test_date_presence_alone_cannot_activate_freshness() -> None:
    evaluation = _outcome(
        _article_facts(
            dates={"published": "2026-01-15", "modified": ""},
            freshness_context={"required": False, "reasons": []},
        ),
        "aeo.content_date_present",
    )

    assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert evaluation.reason_code == "freshness_context_irrelevant"


def _company_profile_facts(**overrides):
    facts = _html_facts(
        page_kind="about_contact",
        page_traits=["about_intent", "company_profile_intent"],
        body={
            "word_count": 40,
            "text": (
                "Acme provides workflow software for operations teams. "
                "Our platform combines planning and reporting in one operating system. "
                "Acme was founded in 2012."
            ),
        },
        primary_content_text=(
            "Acme provides workflow software for operations teams. "
            "Our platform combines planning and reporting in one operating system. "
            "Acme was founded in 2012."
        ),
        entity_proposition={
            "identity": "Acme",
            "provider": "Acme",
            "named_capability": "workflow software",
            "audience_or_outcome": "operations teams",
            "proposition": "Acme provides workflow software for operations teams.",
            "next_action": "",
        },
    )
    facts.update(overrides)
    return facts


def test_company_entity_completeness_is_one_weighted_issue_checkpoint() -> None:
    rule = rule_for("aeo.company_entity_completeness")
    assert rule is not None
    strong = evaluate_rule(rule, _company_profile_facts())
    assert strong.outcome == RULE_OUTCOME_SATISFIED
    assert not creates_issue(strong)
    assert strong.checkpoint_family == "visible_attribution"
    assert strong.evidence["normalized_score"] == 1.0

    partial_facts = _company_profile_facts()
    partial_facts["body"] = {
        "word_count": 30,
        "text": "Acme provides workflow software for operations teams.",
    }
    partial_facts["primary_content_text"] = (
        "Acme provides workflow software for operations teams."
    )
    partial = evaluate_rule(rule, partial_facts)
    assert partial.outcome == RULE_OUTCOME_PARTIAL
    assert creates_issue(partial)
    assert partial.evidence["normalized_score"] == 0.65
    assert partial.description
    assert rule.display_label == "Company entity information incomplete"


def test_company_entity_completeness_excludes_specialized_company_pages() -> None:
    rule = rule_for("aeo.company_entity_completeness")
    assert rule is not None
    facts = _company_profile_facts(page_traits=["about_intent"])
    evaluation = evaluate_rule(rule, facts)
    assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert not creates_issue(evaluation)


def test_company_entity_internal_credit_controls_authority_score() -> None:
    rule = rule_for("aeo.company_entity_completeness")
    assert rule is not None
    facts = _company_profile_facts()
    facts["body"] = {
        "word_count": 30,
        "text": "Acme provides workflow software for operations teams.",
    }
    facts["primary_content_text"] = (
        "Acme provides workflow software for operations teams."
    )
    evaluation = evaluate_rule(rule, facts)
    scores = score_analysis(
        [evaluation],
        page_kind="about_contact",
        page_traits=("company_profile_intent",),
    )
    authority = next(
        row for row in scores.readiness_dimensions if row.key == "authority"
    )
    assert authority.score == 65.0
    assert authority.earned_points == 0.325
    assert authority.determinate_points == 0.5


def test_organization_identity():
    # Applicable on the homepage (page_kind:homepage scope).
    ev = _outcome(_html_facts(), "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["has_organization"] is True
    assert ev.evidence["complete_identity_count"] == 1
    # An Organization block without its URL fails.
    block = dict(_html_facts()["structured_data"]["blocks"][0])
    block["url"] = ""
    facts = _html_facts(structured_data=_sd([block]))
    ev = _outcome(facts, "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["complete_identity_count"] == 0
    # No Organization block at all fails too.
    other_block = {
        "type": "WebPage",
        "syntax": "json-ld",
        "name": "Acme Widgets",
        "props_present": ["name"],
    }
    facts = _html_facts(structured_data=_sd([other_block]))
    ev = _outcome(facts, "aeo.organization_identity")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["has_organization"] is False
    for schema_type in ("LocalBusiness", "ContactPage"):
        facts = _html_facts(
            structured_data=_sd(
                [{"type": schema_type, "name": "Acme", "url": "https://x.example"}]
            )
        )
        assert (
            _outcome(facts, "aeo.organization_identity").outcome
            == RULE_OUTCOME_SATISFIED
        )
    unclassified_root = _html_facts(page_kind="other")
    unclassified_root_evaluation = _outcome(
        unclassified_root, "aeo.organization_identity"
    )
    assert unclassified_root_evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert unclassified_root_evaluation.expected_profile_membership is True
    assert unclassified_root_evaluation.score_roles == (SCORE_ROLE_AEO,)
    # Site scope follows root context, not page-kind confidence.
    non_root = _html_facts(page_kind="article")
    non_root["site"] = None
    assert (
        _outcome(non_root, "aeo.organization_identity").outcome
        == RULE_OUTCOME_NOT_APPLICABLE
    )


def test_soft_error_discriminates_http_200_error_content():
    healthy = _html_facts()
    healthy["delivery"]["status_code"] = 200
    assert _outcome(healthy, "technical.soft_error").outcome == RULE_OUTCOME_SATISFIED

    soft_error = _html_facts(title="Page not found")
    soft_error["delivery"]["status_code"] = 200
    evaluation = _outcome(soft_error, "technical.soft_error")
    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.evidence["matched_error_phrase"] == "page not found"


def test_soft_error_does_not_reclassify_real_error_responses():
    facts = _html_facts(title="404 Not Found")
    facts["delivery"]["status_code"] = 404
    evaluation = _outcome(facts, "technical.soft_error")
    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence["status_code"] == 404


def test_soft_error_ignores_error_phrases_in_body_copy():
    facts = _html_facts()
    facts["delivery"]["status_code"] = 200
    facts["body"]["text"] = "Learn what to do when a product page does not exist."

    evaluation = _outcome(facts, "technical.soft_error")

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence["matched_error_phrase"] == ""


def test_soft_error_reads_h1_text():
    facts = _html_facts()
    facts["delivery"]["status_code"] = 200
    facts["headings"]["h1_texts"] = ["Page not found"]

    evaluation = _outcome(facts, "technical.soft_error")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.evidence["matched_error_phrase"] == "page not found"


def test_soft_error_matches_error_phrase_within_title():
    facts = _html_facts(title="Error: Page not found | Acme")
    facts["delivery"]["status_code"] = 200

    evaluation = _outcome(facts, "technical.soft_error")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.evidence["matched_error_phrase"] == "page not found"


def test_soft_error_ignores_explanatory_editorial_title():
    facts = _html_facts(title="Why a page does not exist and what to do next")
    facts["delivery"]["status_code"] = 200

    evaluation = _outcome(facts, "technical.soft_error")

    assert evaluation.outcome == RULE_OUTCOME_SATISFIED
    assert evaluation.evidence["matched_error_phrase"] == ""


def test_trust_path_matches_terms_without_substring_false_positives():
    facts = _html_facts()
    facts["links"]["anchors"] = [
        {"url": "/aboutness", "anchor_text": "Read more", "is_internal": True}
    ]
    assert _outcome(facts, "aeo.trust_path_present").outcome == RULE_OUTCOME_MISSING

    facts["links"]["anchors"] = [
        {
            "url": "/legal/privacy-policy",
            "anchor_text": "Read more",
            "is_internal": True,
        }
    ]
    assert _outcome(facts, "aeo.trust_path_present").outcome == RULE_OUTCOME_SATISFIED


def test_entity_contact_path_ignores_unrelated_form_fields():
    facts = _html_facts(
        page_kind="about_contact",
        page_traits=["contact_intent"],
        contact_points=[],
        form_fields=["search", "newsletter"],
    )

    missing = _outcome(facts, "aeo.entity_value_proposition")
    contact_path = next(
        atom for atom in missing.evidence["atoms"] if atom["name"] == "contact_path"
    )
    assert contact_path["outcome"] == RULE_OUTCOME_MISSING

    facts["form_fields"] = ["Your email", "Message"]
    satisfied = _outcome(facts, "aeo.entity_value_proposition")
    contact_path = next(
        atom for atom in satisfied.evidence["atoms"] if atom["name"] == "contact_path"
    )
    assert contact_path["outcome"] == RULE_OUTCOME_SATISFIED


# --- v2 P2: extractability rules ---------------------------------------------


def _answer_page_facts(**overrides):
    """A page with independently observed FAQ/answer-task structure."""
    return _html_facts(page_kind="faq", page_traits=["has_faq"], **overrides)


def test_answer_first():
    assert (
        _outcome(_answer_page_facts(), "aeo.answer_first").outcome
        == RULE_OUTCOME_SATISFIED
    )
    short = _outcome(_answer_page_facts(direct_answer="Too short."), "aeo.answer_first")
    assert short.outcome == RULE_OUTCOME_MISSING
    assert short.evidence["answer_word_count"] == 2
    assert short.evidence["minimum_words"] == ANSWER_FIRST_MIN_WORDS
    # Exactly at the minimum passes.
    exactly = " ".join(f"w{i}" for i in range(ANSWER_FIRST_MIN_WORDS))
    assert (
        _outcome(_answer_page_facts(direct_answer=exactly), "aeo.answer_first").outcome
        == RULE_OUTCOME_SATISFIED
    )


def test_answer_first_does_not_apply_to_narrative_or_commercial_pages():
    """A style recommendation, not a defect, and not for every page.

    A service page has no obligation to open like a reference answer, a case
    study may deliberately open with context, and a narrative article is not
    worse for building to its point. Kept only where the reader arrived with a
    question -- and advisory even there.
    """
    for page_kind in ("article", "service", "comparison", "case_study_review"):
        ev = _outcome(
            _html_facts(page_kind=page_kind, direct_answer="Too short."),
            "aeo.answer_first",
        )
        assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE, page_kind
    rule = rule_for("aeo.answer_first")
    assert rule is not None
    assert rule.finding_class == FINDING_CLASS_ADVISORY


@pytest.mark.parametrize(
    ("rule_id", "finding_class"),
    [
        ("technical.single_h1", FINDING_CLASS_ADVISORY),
        ("technical.thin_content", FINDING_CLASS_ADVISORY),
        ("aeo.server_rendered_content", FINDING_CLASS_DIAGNOSTIC),
        ("aeo.content_date_present", FINDING_CLASS_ADVISORY),
        ("technical.ai_crawler_access", FINDING_CLASS_DIAGNOSTIC),
        ("aeo.answer_first", FINDING_CLASS_ADVISORY),
    ],
)
def test_pr1_proxy_rules_have_non_defect_ownership(
    rule_id: str, finding_class: str
) -> None:
    rule = rule_for(rule_id)
    assert rule is not None
    assert rule.finding_class == finding_class


def test_answer_first_missing_without_headings():
    facts = _answer_page_facts(
        headings={"h1_count": 0, "counts": {}, "h1_texts": [], "h2_texts": []}
    )
    ev = _outcome(facts, "aeo.answer_first")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["reason"] == "no_headings"


def _faq_facts(**overrides):
    """The healthy fixture as an FAQ with primary-content question headings."""
    values = {"question_heading_ratio": 1.0, **overrides}
    if "primary_heading_outline" not in values and "headings" not in values:
        question_ratio = float(values["question_heading_ratio"])
        subheadings = (
            ["What are Acme widgets?", "How do Acme widgets work?"]
            if question_ratio > QUESTION_HEADINGS_MIN_RATIO
            else ["Acme widget overview", "Using Acme widgets"]
        )
        values["primary_heading_outline"] = [
            {"level": 1, "text": "Acme Widget FAQ"},
            *({"level": 2, "text": text} for text in subheadings),
        ]
    return _html_facts(page_kind="faq", **values)


def test_question_headings():
    assert (
        _outcome(_faq_facts(), "aeo.question_headings").outcome
        == RULE_OUTCOME_SATISFIED
    )
    ev = _outcome(_faq_facts(question_heading_ratio=0.0), "aeo.question_headings")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["question_heading_ratio"] == 0.0
    assert ev.evidence["minimum_ratio"] == QUESTION_HEADINGS_MIN_RATIO


def test_question_headings_missing_without_subheadings():
    ev = _outcome(
        _faq_facts(
            question_heading_ratio=0.0,
            headings={
                "h1_count": 1,
                "counts": {"h1": 1},
                "h2_texts": [],
                "h3_texts": [],
            },
        ),
        "aeo.question_headings",
    )
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["reason"] == "no_subheadings"


def test_server_rendered_content():
    assert _outcome(_html_facts(), "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    # A JS shell: text-thin AND script-dominated -> fail.
    shell = _html_facts(
        body={"word_count": 5, "text": "tiny"}, inline_script_chars=500_000
    )
    ev = _outcome(shell, "aeo.server_rendered_content")
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["word_count"] == 5
    assert ev.evidence["inline_script_chars"] == 500_000
    # Text-thin but NOT script-dominated -> pass (not a JS-shell signature).
    thin_static = _html_facts(
        body={"word_count": 5, "text": "x" * 1000}, inline_script_chars=10
    )
    assert _outcome(thin_static, "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_SATISFIED
    )
    # At/above the minimum word count passes regardless of script volume.
    enough = _html_facts(
        body={"word_count": SERVER_RENDERED_MIN_WORDS, "text": "tiny"},
        inline_script_chars=500_000,
    )
    assert _outcome(enough, "aeo.server_rendered_content").outcome == (
        RULE_OUTCOME_SATISFIED
    )


def test_server_rendering_diagnostic_has_no_score_role() -> None:
    rule = rule_for("aeo.server_rendered_content")
    assert rule is not None

    evaluation = evaluate_rule(rule, _html_facts())

    assert rule.finding_class == FINDING_CLASS_DIAGNOSTIC
    assert rule.score_roles == ()
    assert evaluation.score_roles == ()


@pytest.mark.parametrize(
    "retired_id",
    [
        "aeo.outbound_citations",
        "aeo.author_present",
        "aeo.no_expand_gating",
    ],
)
def test_retired_semantic_proxy_ids_are_absent(retired_id: str) -> None:
    assert rule_for(retired_id) is None
    assert retired_id not in {rule.rule_id for rule in SITE_HEALTH_RULES}


# =========================================================================
# Page-type scoped applicability (multi-kind `page_kind:a|b|c` tokens)
# =========================================================================


def test_visible_attribution_does_not_apply_to_commercial_pages() -> None:
    for page_kind in ("product", "category", "pricing", "trust_policy", "homepage"):
        evaluation = _outcome(
            _html_facts(
                page_kind=page_kind,
                authorship={
                    "declared_author": "",
                    "declared_author_source": "",
                    "visible_byline": "",
                    "visible_date": "",
                    "visible_profile_url": "",
                },
            ),
            "aeo.visible_attribution",
        )
        assert evaluation.outcome == RULE_OUTCOME_NOT_APPLICABLE, page_kind


def test_visible_attribution_still_evaluates_on_articles() -> None:
    evaluation = _outcome(_attribution_facts(), "aeo.visible_attribution")

    assert evaluation.outcome == RULE_OUTCOME_MISSING
    assert evaluation.reason_code == "visible_attribution_absent"


def test_docs_freshness_depends_on_context_not_kind_or_date_presence() -> None:
    present_but_irrelevant = _outcome(
        _html_facts(
            page_kind="docs",
            dates={"published": "2026-01-15", "modified": ""},
            freshness_context={"required": False, "reasons": []},
        ),
        "aeo.content_date_present",
    )
    required_but_missing = _outcome(
        _html_facts(
            page_kind="docs",
            dates={"published": "", "modified": ""},
            freshness_context={
                "required": True,
                "reasons": ["version_specific_documentation"],
            },
        ),
        "aeo.content_date_present",
    )

    assert present_but_irrelevant.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert present_but_irrelevant.reason_code == "freshness_context_irrelevant"
    assert required_but_missing.outcome == RULE_OUTCOME_MISSING
    assert required_but_missing.reason_code == "freshness_signal_missing"


def test_question_headings_apply_to_faq_pages_only():
    # An FAQ whose sections are not questions is not really an FAQ, so the
    # finding survives there. A guide, a reference page or an essay carries no
    # such obligation and was being failed for prose style.
    facts = _html_facts(question_heading_ratio=0.0)
    assert (
        _outcome({**facts, "page_kind": "faq"}, "aeo.question_headings").outcome
        == RULE_OUTCOME_MISSING
    )
    for page_kind in ("guide", "docs", "article"):
        assert (
            _outcome({**facts, "page_kind": page_kind}, "aeo.question_headings").outcome
            == RULE_OUTCOME_NOT_APPLICABLE
        ), page_kind
    for page_kind in ("homepage", "product", "category"):
        assert (
            _outcome({**facts, "page_kind": page_kind}, "aeo.question_headings").outcome
            == RULE_OUTCOME_NOT_APPLICABLE
        )


def test_only_faq_kind_produces_determinate_answer_expectations():
    faq_kind = _html_facts(page_kind="faq", page_traits=[])
    embedded_faq = _html_facts(page_kind="article", page_traits=["has_faq"])
    for rule_id in ("aeo.answer_first", "aeo.question_headings"):
        assert _outcome(faq_kind, rule_id).outcome != RULE_OUTCOME_NOT_APPLICABLE
        assert _outcome(embedded_faq, rule_id).outcome == RULE_OUTCOME_NOT_APPLICABLE


def test_question_heading_ratio_requires_a_real_faq_pattern():
    sparse = _faq_facts(question_heading_ratio=QUESTION_HEADINGS_MIN_RATIO - 0.1)
    boundary = _faq_facts(question_heading_ratio=QUESTION_HEADINGS_MIN_RATIO)
    for facts in (sparse, boundary):
        assert _outcome(facts, "aeo.answer_first").outcome != (
            RULE_OUTCOME_NOT_APPLICABLE
        )
        assert _outcome(facts, "aeo.question_headings").outcome == RULE_OUTCOME_MISSING


def test_triggered_rule_requires_same_family_sibling_in_each_profile():
    def configured(rule_id: str, **overrides) -> SiteHealthRule:
        values = {
            "rule_id": rule_id,
            "rule_version": "1",
            "dimension": DIMENSION_AEO,
            "category": "test",
            "severity": "low",
            "weight": 0.0,
            "applicability_key": "always",
            "description": "test",
            "remediation": "test",
            "score_roles": (SCORE_ROLE_AEO,),
        }
        values.update(overrides)
        return SiteHealthRule(**values)

    sibling = configured("aeo.artifact_present")
    triggered = configured(
        "aeo.artifact_valid",
        kind_evidence=KIND_EVIDENCE_TRIGGERED,
        triggered_by=sibling.rule_id,
    )
    with pytest.raises(ValueError, match="share role and family"):
        validate_triggered_rule_links(
            (sibling, triggered),
            {sibling.rule_id: sibling, triggered.rule_id: triggered},
            {
                sibling.rule_id: "artifact-presence",
                triggered.rule_id: "artifact-quality",
            },
        )


def test_multi_kind_token_still_fails_closed_on_an_unclassified_page():
    # No page kind means we could not classify the page. We do not guess which
    # checklist it should answer for.
    facts = _attribution_facts()
    facts["page_kind"] = None
    assert (
        _outcome(facts, "aeo.visible_attribution").outcome
        == RULE_OUTCOME_NOT_APPLICABLE
    )


# --- classification confidence is metadata, never a scoring gate ------------


def _tiered(tier, **overrides):
    return _html_facts(
        page_kind="article",
        page_kind_evidence={"tier": tier, "confidence": "x"},
        authorship={
            "declared_author": "",
            "declared_author_source": "",
            "visible_byline": "",
            "visible_date": "",
            "visible_profile_url": "",
        },
        dates={"published": "", "modified": ""},
        **overrides,
    )


def test_kind_expectations_are_invariant_across_classifier_tiers():
    for tier in ("structural", "route", "semantic", ""):
        ev = _outcome(_tiered(tier), "aeo.visible_attribution")
        assert ev.outcome == RULE_OUTCOME_MISSING, tier
        assert ev.expected_profile_membership is True, tier


def test_advisories_are_offered_at_every_confidence_tier():
    # An opportunity costs nothing if the guess was wrong, and withholding a
    # suggestion helps no one. Only defects, which move the score, need
    # evidence the page owns.
    for tier in ("structural", "route", "semantic"):
        ev = _outcome(
            _tiered(tier, structured_data={"count": 0, "blocks": [], "types": []}),
            "aeo.structured_data_present",
        )
        assert ev.outcome == RULE_OUTCOME_MISSING, tier
        assert ev.finding_class == FINDING_CLASS_ADVISORY


def test_triggered_validation_runs_at_every_confidence_tier():
    """The trigger is the artifact, not the classification.

    A Product block that contradicts the visible page is a defect however the
    page was classified, so these rules are never gated. They self-resolve to
    not_applicable when the block is absent, which is what makes that safe.
    """
    contradicting = {
        "count": 1,
        "has_json_ld": True,
        "types": ["Article"],
        "blocks": [
            {
                "type": "Article",
                "syntax": "json-ld",
                "name": "A completely unrelated headline",
                "props_present": ["headline"],
            }
        ],
    }
    for tier in ("structural", "route", "semantic"):
        ev = _outcome(
            _tiered(tier, structured_data=contradicting),
            "aeo.schema_matches_content",
        )
        assert ev.outcome == RULE_OUTCOME_MISSING, tier


def test_missing_classifier_evidence_does_not_change_rule_applicability():
    facts = _attribution_facts()
    facts.pop("page_kind_evidence")
    assert _outcome(facts, "aeo.visible_attribution").outcome == RULE_OUTCOME_MISSING


def test_every_kind_scoped_rule_declares_its_evidence_class():
    # A new page-kind rule defaults to an expectation; triggered artifact
    # checks must opt in explicitly.
    for rule in SITE_HEALTH_RULES:
        assert rule.kind_evidence in KIND_EVIDENCE_CLASSES, rule.rule_id
