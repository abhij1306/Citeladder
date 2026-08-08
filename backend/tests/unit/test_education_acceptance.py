"""Education v1 acceptance: the whole deterministic pipeline on one corpus.

Drives the SHIPPED path — parser, page-kind classifier, pack role classifier,
knowledge extractor, contradiction grouping, question coverage, journeys,
dimension scores — over a SYNTHETIC Education corpus, and asserts the S3
contract clause by clause.

The fixture is synthetic on purpose. Customer corpora are evaluation material
(`docs/evaluations/`) and never become shared pack fixtures: a customer's pages
are their data, and a test that encodes them turns one account's content into
part of the product.

Two properties make this an acceptance test rather than a smoke test:

1. The corpus publishes ZERO structured data. Every expectation below is
   therefore reachable from visible content alone — an extractor that only read
   JSON-LD would fail every one.
2. It renders a report, printed on the run, so the outcome is inspectable and
   diffable rather than reduced to a boolean.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis.site_health.intelligence import (
    CorpusSignals,
    KnowledgeIndex,
    is_extractable_predicate,
    resolve_journeys,
    resolve_question_coverage,
    score_dimensions,
)
from app.analysis.site_health.knowledge import (
    AssertionCandidate,
    compile_vocabulary,
    extract_page_knowledge,
    identity_key_for,
)
from app.analysis.site_health.page_kinds import classify as classify_page_kind
from app.analysis.site_health.parser import extract_page_facts
from app.core.config.industry_packs.catalog import load_pack
from app.core.config.industry_packs.reference import classify_page, compile_pack
from app.core.config.site_intelligence import (
    COVERAGE_ANSWERED_STRONG,
    COVERAGE_ANSWERED_WEAK,
    COVERAGE_MISSING,
    COVERAGE_STATES,
    COVERAGE_UNSUPPORTED,
    DIMENSION_IDS,
)
from app.domain.site_health.knowledge import conflict_policy_permits_multiple

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "core"
    / "config"
    / "industry_packs"
    / "fixtures"
    / "education"
)


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads((FIXTURES / "acceptance-corpus.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vocabulary():
    return compile_vocabulary(load_pack("education", "1.0.0"))


@pytest.fixture(scope="module")
def compiled():
    pack = load_pack("education", "1.0.0")
    return compile_pack(
        pack, manifest={"pack_id": "education", "pack_version": "1.0.0"}
    )


def _links_internally(facts: dict) -> bool:
    anchors = (facts.get("links") or {}).get("anchors") or ()
    return any(anchor.get("is_internal") for anchor in anchors)


def _analyzable(corpus: dict) -> list[dict]:
    return [p for p in corpus["pages"] if p.get("disposition", "analyze") == "analyze"]


@pytest.fixture(scope="module")
def analyzed(corpus, vocabulary, compiled) -> dict:
    """Run the whole deterministic pipeline over the fixture corpus once."""
    site_key = identity_key_for(corpus["registrable_domain"])
    entities: dict = {}
    assertions: list[AssertionCandidate] = []
    warnings: list[str] = []
    observed_roles: set[str] = set()
    roles_by_case: dict[str, str | None] = {}
    facts_by_case: dict[str, dict] = {}
    schema_pages = 0

    for page in corpus["pages"]:
        facts = extract_page_facts(
            page["html"].encode("utf-8"), final_url=page["url"], charset="utf-8"
        )
        facts_by_case[page["case"]] = facts
        if (facts.get("structured_data") or {}).get("blocks"):
            schema_pages += 1
        if page.get("disposition", "analyze") != "analyze":
            roles_by_case[page["case"]] = None
            continue
        kind = classify_page_kind(page["url"], facts)
        headings = facts.get("headings") or {}
        result = classify_page(
            compiled,
            {
                "url": page["url"],
                "title": facts.get("title") or None,
                "h1": (headings.get("h1_texts") or [None])[0],
                "headings": [
                    *(headings.get("h2_texts") or []),
                    *(headings.get("h3_texts") or []),
                ],
                "body": (facts.get("body") or {}).get("text") or None,
                "cta_text": facts.get("cta_text") or (),
                "form_fields": facts.get("form_fields") or (),
                "link_context": facts.get("link_context") or (),
                "schema_types": (facts.get("structured_data") or {}).get("types") or (),
                "page_kind": kind.page_kind,
                "corpus_disposition": "analyze",
            },
        )
        role = result.get("primary_role_id")
        roles_by_case[page["case"]] = role
        if role:
            observed_roles.add(str(role))

        knowledge = extract_page_knowledge(
            facts,
            vocabulary=vocabulary,
            industry_role_id=role,
            temporal_state=page["temporal_state"],
            site_identity_key=site_key,
            is_crawl_root=bool(page.get("is_root")),
            final_url=page["url"],
        )
        warnings.extend(knowledge.warnings)
        assertions.extend(knowledge.assertions)
        for candidate in knowledge.entities:
            entities.setdefault(candidate.ref, candidate)

    return {
        "entities": entities,
        "assertions": assertions,
        "warnings": warnings,
        "observed_roles": frozenset(observed_roles),
        "roles_by_case": roles_by_case,
        "facts_by_case": facts_by_case,
        "schema_pages": schema_pages,
        "documents": corpus["documents"],
    }


def _contradiction_count(analyzed: dict, vocabulary) -> tuple[int, frozenset[str]]:
    """Group contradictions with the PRODUCTION rule.

    Re-implementing the rule here would make this test agree with itself rather
    than with the shipped pipeline, which is the one thing an acceptance test
    must not do. ``conflict_policy_permits_multiple`` and the ``scope_complete``
    guard are imported from the domain module that finalization uses.
    """
    by_claim: dict[tuple, list[AssertionCandidate]] = {}
    for assertion in analyzed["assertions"]:
        by_claim.setdefault(
            (assertion.subject, assertion.predicate_id, assertion.scope_key), []
        ).append(assertion)

    disputes = 0
    disputed: set[str] = set()
    for (_subject, predicate_id, _scope), members in by_claim.items():
        spec = vocabulary.predicates.get(predicate_id)
        if spec is not None and conflict_policy_permits_multiple(
            spec.conflict_policy, spec.cardinality
        ):
            continue
        # Mirror production ``_group_contradictions``: unscoped members are
        # EXCLUDED from the comparison, not treated as disqualifying the whole
        # claim. Skipping the claim outright made this acceptance check accept a
        # dispute count the shipped grouper would never produce — two scoped
        # values still contradict each other with an unscoped third beside them.
        scoped = [member for member in members if member.scope_complete]
        if len({member.normalized_value for member in scoped}) < 2:
            continue
        disputes += 1
        disputed.add(predicate_id)
    return disputes, frozenset(disputed)


@pytest.fixture(scope="module")
def report(analyzed, vocabulary, corpus) -> dict:
    """Coverage, journeys, and dimensions over the analyzed corpus."""
    states: dict[str, set[str]] = {}
    for assertion in analyzed["assertions"]:
        states.setdefault(assertion.predicate_id, set()).add(assertion.temporal_state)

    disputes, disputed = _contradiction_count(analyzed, vocabulary)
    index = KnowledgeIndex(
        predicate_states={k: frozenset(v) for k, v in states.items()},
        disputed_predicates=disputed,
        entity_type_ids=frozenset(ref.entity_type_id for ref in analyzed["entities"]),
        entity_count=len(analyzed["entities"]),
        assertion_count=len(analyzed["assertions"]),
        contradiction_count=disputes,
    )

    # Signals derived FROM the corpus, so changing a fixture page changes the
    # inputs rather than leaving a stale literal behind.
    facts = analyzed["facts_by_case"]
    cases = [page["case"] for page in _analyzable(corpus)]
    analyzed_pages = len(cases)

    def counting(predicate) -> int:
        return sum(1 for case in cases if predicate(facts[case]))

    signals = CorpusSignals(
        analyzed_pages=analyzed_pages,
        indexable_pages=analyzed_pages,
        canonical_ok_pages=analyzed_pages,
        linked_pages=counting(_links_internally),
        declared_role_count=len(vocabulary.roles),
        role_page_counts=dict.fromkeys(analyzed["observed_roles"], 1),
        pages_with_usable_headings=counting(
            lambda f: int((f.get("headings") or {}).get("h1_count") or 0) == 1
        ),
        pages_with_question_headings=counting(
            lambda f: float(f.get("question_heading_ratio") or 0.0) > 0
        ),
        conversion_action_pages=counting(
            lambda f: bool(f.get("cta_text") or f.get("form_fields"))
        ),
    )
    coverage = resolve_question_coverage(
        vocabulary=vocabulary,
        knowledge=index,
        observed_role_ids=analyzed["observed_roles"],
        acquisition_failed=False,
    )
    journeys = resolve_journeys(
        vocabulary=vocabulary,
        observed_role_ids=analyzed["observed_roles"],
        coverage=coverage,
    )
    dimensions = score_dimensions(
        signals=signals,
        knowledge=index,
        coverage=coverage,
        journeys=journeys,
        vocabulary=vocabulary,
    )
    return {
        "coverage": coverage,
        "journeys": journeys,
        "dimensions": dimensions,
        "index": index,
        "signals": signals,
    }


# =========================================================================
# Premise
# =========================================================================
def test_the_fixture_publishes_no_structured_data(analyzed, corpus):
    """The premise every other assertion rests on.

    If the corpus ever grows structured data, the visible-content path stops
    being exercised and these results no longer prove what they claim.
    """
    assert analyzed["schema_pages"] == corpus["expected"]["structured_data_pages"] == 0


# =========================================================================
# Roles and corpus
# =========================================================================
def test_every_page_classifies_into_the_role_the_fixture_declares(analyzed, corpus):
    """The fixture is the authority; a drift in either direction fails here."""
    for page in corpus["pages"]:
        assert analyzed["roles_by_case"][page["case"]] == page["expected_role"], page[
            "case"
        ]


def test_the_admissions_funnel_is_identified(analyzed):
    assert "education.admissions_overview" in analyzed["observed_roles"]
    assert "education.fees" in analyzed["observed_roles"]


def test_utility_paths_are_confidently_excluded(analyzed):
    assert analyzed["roles_by_case"]["utility_excluded"] is None


def test_documents_are_inventoried_and_never_html_analyzed(analyzed):
    """Documents count toward the corpus without entering the HTML analyzer."""
    documents = analyzed["documents"]
    assert documents
    assert all(doc["item_kind"] == "document" for doc in documents)
    assert all(doc["disposition"] == "inventory_only" for doc in documents)
    assert not any(doc["url"] in analyzed["roles_by_case"] for doc in documents)


def test_an_unknown_document_date_stays_unknown(analyzed):
    archive = next(
        doc for doc in analyzed["documents"] if doc["case"] == "archive_document"
    )
    assert archive["temporal_state"] == "unknown"


# =========================================================================
# Knowledge
# =========================================================================
def test_the_organization_is_established_from_visible_content(analyzed, corpus):
    organization = next(
        candidate
        for ref, candidate in analyzed["entities"].items()
        if ref.entity_type_id == "education.organization"
    )
    assert organization.canonical_name == corpus["expected"]["organization_name"]


def test_one_inbox_yields_one_contact_point(analyzed, corpus):
    """A percent-escaped ``mailto:`` is the same address, not a second one."""
    contacts = [
        a for a in analyzed["assertions"] if a.predicate_id == "education.contact_point"
    ]
    assert len(contacts) == corpus["expected"]["organization_contact_points"]
    assert all("%" not in contact.normalized_value for contact in contacts)


def test_historical_evidence_is_preserved_without_becoming_current(analyzed, corpus):
    """Both figures survive with their own temporal state; neither is merged."""
    fees = [a for a in analyzed["assertions"] if a.value_type == "money"]
    observed = {(a.normalized_value, a.temporal_state) for a in fees}
    current, historical = corpus["expected"]["money_values"]

    assert (current, "current") in observed
    assert (historical, "historical") in observed
    assert (historical, "current") not in observed


def test_two_unscoped_fees_are_not_reported_as_a_contradiction(analyzed, report):
    """The judgement this fixture exists to pin down.

    The corpus states two different senior-school fees and never states which
    academic year, grade, or fee type either applies to. That is NOT proof of a
    conflict — they could be two different grades — so no contradiction is
    raised. What IS reported is that neither figure is scoped, which is the
    finding a reviewer can act on.

    A fabricated conflict is worse than a missed one: it would block publication
    of a fee that may be perfectly correct.
    """
    fees = [a for a in analyzed["assertions"] if a.value_type == "money"]

    assert len({a.normalized_value for a in fees}) == 2
    assert all(not a.scope_complete for a in fees)
    assert report["index"].contradiction_count == 0


def test_an_unscoped_fee_is_flagged_as_unscoped(analyzed, vocabulary):
    fee = next(a for a in analyzed["assertions"] if a.value_type == "money")
    required = vocabulary.predicates[fee.predicate_id].required_scope

    assert set(required) - set(fee.scope), "the fixture must leave scope unstated"
    assert fee.scope_complete is False


def test_no_fee_is_invented(analyzed, corpus):
    """The hard fabrication guard: nothing appears that the corpus lacks."""
    stated = set(corpus["expected"]["money_values"])
    for assertion in analyzed["assertions"]:
        if assertion.value_type != "money":
            continue
        assert assertion.currency, f"currency-less money: {assertion}"
        assert assertion.normalized_value in stated, f"invented fee: {assertion}"


def test_unstated_fee_scope_is_absent_not_defaulted(analyzed):
    fee = next(a for a in analyzed["assertions"] if a.value_type == "money")
    assert "academic_year" not in fee.scope
    assert "effective_period" not in fee.scope


# =========================================================================
# Coverage
# =========================================================================
def test_at_least_one_missing_and_one_weak_question_are_detected(report):
    counts = report["coverage"].counts
    weak = counts[COVERAGE_ANSWERED_WEAK] + counts[COVERAGE_UNSUPPORTED]

    assert counts[COVERAGE_MISSING] >= 1
    assert weak >= 1


def test_every_question_resolves_over_the_full_denominator(report, vocabulary):
    coverage = report["coverage"]
    assert len(coverage.questions) == len(vocabulary.questions)
    assert coverage.denominator == len(vocabulary.questions)
    assert all(question.state in COVERAGE_STATES for question in coverage.questions)
    assert all(question.reason for question in coverage.questions)


def test_no_question_is_answered_from_facts_this_analyzer_cannot_extract(
    report, vocabulary
):
    """A guard against the report flattering the site.

    A question whose required predicates are ALL outside this analyzer's
    deterministic set can never be answered — no path exists by which evidence
    for it could be produced. If one reads answered, the resolver has become
    generous with facts it never saw.
    """
    required_by_id = {
        spec.question_id: spec.required_predicate_ids for spec in vocabulary.questions
    }
    for question in report["coverage"].questions:
        required = required_by_id.get(question.question_id, ())
        if required and not any(
            is_extractable_predicate(predicate_id, vocabulary)
            for predicate_id in required
        ):
            assert question.state not in (
                COVERAGE_ANSWERED_STRONG,
                COVERAGE_ANSWERED_WEAK,
            ), question.question_id


def test_answered_questions_stay_a_minority_on_a_corpus_this_thin(report):
    counts = report["coverage"].counts
    answered = counts[COVERAGE_ANSWERED_STRONG] + counts[COVERAGE_ANSWERED_WEAK]
    assert answered < report["coverage"].denominator / 2


# =========================================================================
# Journeys and dimensions
# =========================================================================
def test_the_journey_reports_every_stage_with_unavailable_outcomes(report):
    journeys = report["journeys"]
    assert len(journeys) == 1
    stages = journeys[0].stages
    assert [stage.order for stage in stages] == sorted(stage.order for stage in stages)
    assert {state for stage in stages for state in stage.outcomes.values()} == {
        "unavailable"
    }


def test_the_convert_stage_shows_the_pages_it_has_and_the_ones_it_lacks(report):
    convert = next(
        stage
        for stage in report["journeys"][0].stages
        if stage.stage_id == "education.convert"
    )
    assert "education.admissions_overview" in convert.present_role_ids
    assert convert.missing_role_ids
    assert 0.0 < convert.role_coverage < 1.0


def test_the_composite_reports_over_all_six_dimensions_with_coverage(report):
    """The rule the whole scoring model exists to enforce."""
    dimensions = report["dimensions"]
    assert len(dimensions.dimensions) == len(DIMENSION_IDS)
    assert dimensions.composite_score == round(
        sum(d.score for d in dimensions.dimensions) / len(DIMENSION_IDS), 4
    )
    # A site with no structured data must NOT be flattered by its absence.
    machine = next(
        d for d in dimensions.dimensions if d.dimension_id == "machine_clarity"
    )
    assert machine.score == 0.0
    assert machine.coverage < 1.0


def test_the_report_renders_from_one_snapshot(report, analyzed, corpus, capsys):
    """Render the executive report so the run is inspectable, not a boolean."""
    lines = render_acceptance_report(corpus, analyzed, report)
    print("\n".join(lines))

    body = "\n".join(lines)
    for section in (
        "CORPUS",
        "KNOWLEDGE",
        "QUESTION COVERAGE",
        "ADMISSIONS JOURNEY",
        "DIMENSIONS",
        "LIMITATIONS",
    ):
        assert section in body


def render_acceptance_report(corpus: dict, analyzed: dict, report: dict) -> list[str]:
    """The executive report, rendered from one analyzed snapshot.

    Deliberately plain text and deterministic: it is an acceptance artifact and
    a reviewer must be able to diff two runs.
    """
    coverage = report["coverage"]
    dimensions = report["dimensions"]
    analyzable = _analyzable(corpus)
    unscoped = sum(1 for a in analyzed["assertions"] if not a.scope_complete)
    lines = [
        "",
        "=" * 72,
        f"SITE INTELLIGENCE ACCEPTANCE REPORT — {corpus['fixture_id']}",
        "=" * 72,
        "",
        "CORPUS",
        f"  discovered           {len(corpus['pages']) + len(corpus['documents'])}",
        f"  analyzed (html)      {len(analyzable)}",
        f"  inventory_only docs  {len(corpus['documents'])}",
        f"  excluded utility     {len(corpus['pages']) - len(analyzable)}",
        f"  pages with schema    {analyzed['schema_pages']}",
        "",
        "KNOWLEDGE",
        f"  entities             {len(analyzed['entities'])}",
        f"  assertions           {len(analyzed['assertions'])}",
        f"  contradictions       {report['index'].contradiction_count}",
        f"  unscoped claims      {unscoped}",
        f"  roles observed       {len(analyzed['observed_roles'])}",
        "",
        "QUESTION COVERAGE",
        f"  answered ratio       {coverage.answered_ratio}"
        f" over {coverage.denominator} required questions",
    ]
    lines += [
        f"    {state:24} {coverage.counts.get(state, 0)}" for state in COVERAGE_STATES
    ]
    lines.append("  answered:")
    lines += [
        f"    {question.state:16} {question.question_id:32} {question.reason}"
        for question in coverage.questions
        if question.state in (COVERAGE_ANSWERED_STRONG, COVERAGE_ANSWERED_WEAK)
    ]
    lines += ["", "ADMISSIONS JOURNEY"]
    lines += [
        f"  {stage.stage_id:28} pages {stage.role_coverage:<6}"
        f" answers {stage.question_coverage}"
        f" outcomes {sorted(set(stage.outcomes.values()))}"
        for stage in report["journeys"][0].stages
    ]
    lines += ["", "DIMENSIONS (full denominator, coverage beside)"]
    for dimension in dimensions.dimensions:
        unavailable = [c.label for c in dimension.components if c.score is None]
        lines.append(
            f"  {dimension.dimension_id:28} {dimension.score:<8}"
            f" coverage {dimension.coverage:<8}"
            + (f" unavailable: {', '.join(unavailable)}" if unavailable else "")
        )
    lines += [
        f"  {'COMPOSITE':28} {dimensions.composite_score}"
        f" coverage {dimensions.composite_coverage}",
        "",
        "LIMITATIONS",
        "  Document CONTENT is not extracted: documents are inventoried and",
        "  counted, and their claims are not admitted as facts.",
        "  Outcome measurement is unavailable until analytics events connect;",
        "  no stage outcome is reported as zero.",
        "  Predicates outside this analyzer's deterministic set resolve to",
        "  'unsupported' and are named as an analyzer gap, not a site gap.",
        "  Contradiction REVIEW is not implemented: disputes are detected and",
        "  grouped, and resolving one is still a later slice.",
        "=" * 72,
        "",
    ]
    return lines
