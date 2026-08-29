"""False-positive avoidance as a CI contract.

Every fixture below except one is a page a competent site owner built
correctly. The contract each carries is not "these findings appeared" but
"these findings must NEVER appear", so a rule that starts accusing a valid page
fails this suite instead of reaching a customer's crawl.

The contract is stated in DEFECT terms. An advisory failure is a free
suggestion that does not touch the score, so it is deliberately not constrained
here; only ``finding_class == defect`` failures are asserted, because those are
the ones that lower a health score and feed Opportunities.

``KNOWN_FALSE_POSITIVES`` is the ratchet. It lists, per fixture, the defects a
valid page produces TODAY that it should not produce. Every entry is a bug with
a fix already planned; landing that fix deletes the entry. The suite asserts
the list is exact in both directions, so it cannot quietly grow to cover new
breakage and cannot keep a stale entry after a fix lands.

Pure and offline: fixtures are parsed from disk, nothing touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.rules import evaluate_all
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
)
from app.core.config.site_health_rules import FINDING_CLASS_DEFECT

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site_health"

# A healthy delivery for every fixture: HTTPS, HSTS, compressed, fast, 200.
# Delivery-level rules are not what this suite is about, so they are held
# constant and passing rather than left to vary per fixture.
_HEADERS = {
    "content-encoding": "gzip",
    "strict-transport-security": "max-age=63072000",
    "cache-control": "public, max-age=300",
}


@dataclass(frozen=True)
class FixtureContract:
    """One page and the findings it must and must never produce."""

    fixture: str
    url: str
    page_kind: str
    confidence: str
    #: Defects this page genuinely deserves. Empty for a well-built page.
    must_fail: frozenset[str] = frozenset()
    #: Defects this page must never produce. The false-positive guard.
    must_never_fail: frozenset[str] = frozenset()
    #: True when the page is deliberately broken (documents intent only).
    is_counter_example: bool = False
    #: Why this fixture exists, in one line.
    why: str = ""
    sitemap_member: bool = True


# Findings no correctly-built page of any kind should ever produce. Listed once
# and folded into every valid fixture's ``must_never_fail`` below.
_NEVER_ON_A_VALID_PAGE = frozenset(
    {
        "aeo.structured_data_present",
        "aeo.open_graph_present",
        "technical.thin_content",
        "technical.canonical_present",
        "technical.meta_description_present",
        "technical.canonical_conflict",
    }
)

_CONTRACTS: tuple[FixtureContract, ...] = (
    FixtureContract(
        fixture="flat_category_listing.html",
        url="https://northgate.example/womens-dresses",
        page_kind="category",
        confidence="high",
        why="38 words of prose over a real 8-item grid: length is not the verdict",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {"aeo.answer_first", "aeo.question_headings", "aeo.schema_required_valid"},
    ),
    FixtureContract(
        fixture="contact_page.html",
        url="https://northgate.example/contact-us",
        page_kind="about_contact",
        confidence="medium",
        why="27 words, but address, phone, email, hours and a form: complete",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {"aeo.answer_first", "aeo.question_headings", "aeo.author_present"},
    ),
    FixtureContract(
        fixture="faq_accordion.html",
        url="https://northgate.example/faq",
        page_kind="faq",
        confidence="medium",
        why="answers server-rendered inside closed details: present, not hidden",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {
            "aeo.no_expand_gating",
            "aeo.question_headings",
            "aeo.schema_required_valid",
        },
    ),
    FixtureContract(
        fixture="category_faceted_canonical.html",
        url="https://northgate.example/oak-dining-tables?sort=price-asc",
        page_kind="category",
        confidence="high",
        why="a sorted view canonicalised onto its parent: the point of canonical",
        must_never_fail=_NEVER_ON_A_VALID_PAGE | {"aeo.answer_first"},
    ),
    FixtureContract(
        fixture="tracked_url_canonical.html",
        url=(
            "https://northgate.example/blog/oiled-or-lacquered-oak"
            "?utm_source=newsletter"
        ),
        page_kind="article",
        confidence="medium",
        why="from a newsletter, so a tracking parameter must not read as a conflict",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {"aeo.answer_first", "aeo.author_present", "aeo.date_present"},
    ),
    FixtureContract(
        fixture="article_no_schema.html",
        url="https://northgate.example/blog/kiln-dried-oak",
        page_kind="article",
        confidence="medium",
        why="visible byline, visible date, real citations, zero JSON-LD",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {
            "aeo.answer_first",
            "aeo.author_present",
            "aeo.date_present",
            "aeo.outbound_citations",
            "aeo.schema_required_valid",
        },
    ),
    FixtureContract(
        fixture="docs_reference.html",
        url="https://northgate.example/docs/api/orders",
        page_kind="docs",
        confidence="medium",
        why="reference documentation has no subheadings and no question headings",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {"aeo.answer_first", "aeo.question_headings", "aeo.date_present"},
    ),
    FixtureContract(
        fixture="support_index.html",
        url="https://northgate.example/support/getting-started",
        page_kind="faq",
        confidence="medium",
        why="a /support/ route guess must not admit the whole FAQ checklist",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {
            "aeo.answer_first",
            "aeo.question_headings",
            "aeo.schema_required_valid",
            "aeo.schema_matches_content",
        },
    ),
    FixtureContract(
        fixture="guide_no_howto.html",
        url="https://northgate.example/guides/re-oiling-an-oak-table",
        page_kind="guide",
        confidence="medium",
        why="a real how-to with steps and an outcome, and no HowTo markup",
        must_never_fail=_NEVER_ON_A_VALID_PAGE
        | {
            "aeo.answer_first",
            "aeo.author_present",
            "aeo.date_present",
            "aeo.question_headings",
            "aeo.schema_required_valid",
        },
    ),
    FixtureContract(
        fixture="broken_pdp_schema_mismatch.html",
        url="https://northgate.example/oak-dining-tables/ilkley",
        page_kind="product",
        confidence="high",
        is_counter_example=True,
        why="the counter-example: schema and noindex both contradict the page",
        must_fail=frozenset(
            {
                "aeo.product_visible_schema_parity",
                "aeo.schema_matches_content",
                "aeo.product_offer_details",
                "technical.indexable",
            }
        ),
        must_never_fail=frozenset(
            {
                "aeo.structured_data_present",
                "aeo.open_graph_present",
                "technical.thin_content",
            }
        ),
    ),
)

_CONTRACTS_BY_FIXTURE = {contract.fixture: contract for contract in _CONTRACTS}

# --- the ratchet -------------------------------------------------------------
#
# Defects a VALID page produces today that it must not produce. Each entry names
# the phase that removes it. Deleting entries is the point; adding one requires
# explaining why a new false positive is acceptable, which it is not.
KNOWN_FALSE_POSITIVES: dict[str, frozenset[str]] = {
    "flat_category_listing.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2 - absent optional markup
            "aeo.open_graph_present",  # phase 2 - absent optional markup
            "technical.canonical_present",  # phase 2 - recommended, not mandatory
            "technical.meta_description_present",  # phase 2 - snippets are generated
            "technical.thin_content",  # phase 5 - 38 words over a real grid
        }
    ),
    "contact_page.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "technical.thin_content",  # phase 5 - complete in 27 words
        }
    ),
    "faq_accordion.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "aeo.no_expand_gating",  # phase 2 - the text IS in the DOM
        }
    ),
    "category_faceted_canonical.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "technical.canonical_conflict",  # phase 2 - a legitimate cross-canonical
            "technical.thin_content",  # phase 5
        }
    ),
    "tracked_url_canonical.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "aeo.answer_first",  # phase 2 - the byline is read as the answer
            "aeo.author_present",  # phase 2 - visible byline never read
            "aeo.date_present",  # phase 2 - visible date never read
            "technical.canonical_conflict",  # phase 2 - a tracking parameter
            "technical.thin_content",  # phase 5 - 225 words against a 300 floor
        }
    ),
    "article_no_schema.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.answer_first",  # phase 2
            "aeo.author_present",  # phase 2
            "aeo.date_present",  # phase 2
            "technical.thin_content",  # phase 5
        }
    ),
    "docs_reference.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "aeo.question_headings",  # phase 2 - the page has no subheadings at all
            "aeo.date_present",  # phase 2 - "Last updated 11 March 2026" is visible
            "technical.thin_content",  # phase 5
        }
    ),
    "support_index.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "aeo.question_headings",  # phase 3 - a route-tier FAQ guess
            "technical.thin_content",  # phase 5 - 118 words against a 120 floor
        }
    ),
    "guide_no_howto.html": frozenset(
        {
            "aeo.structured_data_present",  # phase 2
            "aeo.open_graph_present",  # phase 2
            "aeo.answer_first",  # phase 2
            "aeo.author_present",  # phase 2
            "aeo.date_present",  # phase 2
            "aeo.question_headings",  # phase 2 - a guide is not an FAQ
        }
    ),
    "broken_pdp_schema_mismatch.html": frozenset(
        {
            "aeo.open_graph_present",  # phase 2
            "technical.thin_content",  # phase 5 - a PDP with a visible price
        }
    ),
}


def _defect_failures(contract: FixtureContract) -> tuple[set[str], set[str]]:
    """``(defect failures, errors)`` for one fixture, end to end."""
    body = (_FIXTURES / contract.fixture).read_bytes()
    facts = extract_page_facts(
        body,
        final_url=contract.url,
        content_type="text/html",
        status_code=200,
        redacted_headers=_HEADERS,
        http_version="2",
        ttfb_ms=120,
        latency_ms=240,
        wire_bytes=len(body) // 3,
        decoded_bytes=len(body),
    )
    assessment = classify(contract.url, facts)
    # Mirrors the worker's evaluation-copy enrichment exactly
    # (``analyze_rows._classify_and_score``).
    facts["page_kind"] = assessment.page_kind
    facts["page_kind_evidence"] = assessment.to_evidence()
    facts["sitemap_member"] = contract.sitemap_member
    evaluations = evaluate_all(facts)
    defects = {
        ev.rule_id
        for ev in evaluations
        if ev.outcome == RULE_OUTCOME_FAIL and ev.finding_class == FINDING_CLASS_DEFECT
    }
    errors = {ev.rule_id for ev in evaluations if ev.outcome == RULE_OUTCOME_ERROR}
    return defects, errors


_IDS = [contract.fixture for contract in _CONTRACTS]


@pytest.mark.parametrize("contract", _CONTRACTS, ids=_IDS)
def test_fixture_classifies_as_the_contract_states(contract: FixtureContract) -> None:
    """A contract is only meaningful if the page reached the kind it names."""
    body = (_FIXTURES / contract.fixture).read_bytes()
    facts = extract_page_facts(body, final_url=contract.url, content_type="text/html")
    assessment = classify(contract.url, facts)
    assert assessment.page_kind == contract.page_kind, contract.why
    assert assessment.confidence == contract.confidence, contract.why


@pytest.mark.parametrize("contract", _CONTRACTS, ids=_IDS)
def test_fixture_produces_exactly_its_contracted_defects(
    contract: FixtureContract,
) -> None:
    """The ratchet: every defect is either deserved or a listed known bug.

    Equality in both directions. A NEW false positive fails here because it is
    in neither set, and a fixed one fails here until its
    ``KNOWN_FALSE_POSITIVES`` entry is deleted -- so the list can only shrink.
    """
    defects, _errors = _defect_failures(contract)
    allowed = contract.must_fail | KNOWN_FALSE_POSITIVES.get(
        contract.fixture, frozenset()
    )
    assert defects == allowed, (
        f"{contract.fixture}: {contract.why}\n"
        f"  unexpected new defects: {sorted(defects - allowed)}\n"
        f"  contracted but absent:  {sorted(allowed - defects)}"
    )


@pytest.mark.parametrize("contract", _CONTRACTS, ids=_IDS)
def test_forbidden_findings_are_only_ever_known_bugs(
    contract: FixtureContract,
) -> None:
    """No ``must_never_fail`` finding may appear except as a listed known bug."""
    defects, _errors = _defect_failures(contract)
    forbidden = (contract.must_never_fail & defects) - KNOWN_FALSE_POSITIVES.get(
        contract.fixture, frozenset()
    )
    assert not forbidden, (
        f"{contract.fixture} must never produce {sorted(forbidden)}: {contract.why}"
    )


@pytest.mark.parametrize("contract", _CONTRACTS, ids=_IDS)
def test_deserved_findings_survive(contract: FixtureContract) -> None:
    """A rule must not be 'fixed' by weakening it into silence."""
    defects, _errors = _defect_failures(contract)
    assert contract.must_fail <= defects, (
        f"{contract.fixture} stopped reporting {sorted(contract.must_fail - defects)}"
    )


@pytest.mark.parametrize("contract", _CONTRACTS, ids=_IDS)
def test_no_rule_errors_on_any_fixture(contract: FixtureContract) -> None:
    """An ERROR outcome is a wiring bug, never a finding about the page."""
    _defects, errors = _defect_failures(contract)
    assert not errors, f"{contract.fixture} raised in {sorted(errors)}"


def test_counter_example_exists() -> None:
    """Without a broken page the suite could pass by silencing everything."""
    counter = [contract for contract in _CONTRACTS if contract.is_counter_example]
    assert counter, "the suite needs at least one deliberately broken fixture"
    assert all(contract.must_fail for contract in counter)


def test_known_false_positives_only_cover_documented_targets() -> None:
    """Every allowlist entry must be a finding some contract forbids.

    Stops the ratchet being used to wave through a defect nobody decided was
    wrong -- an entry here has to correspond to a stated ``must_never_fail``.
    """
    for fixture, rule_ids in KNOWN_FALSE_POSITIVES.items():
        contract = _CONTRACTS_BY_FIXTURE.get(fixture)
        assert contract is not None, f"{fixture} has no contract"
        undocumented = rule_ids - contract.must_never_fail
        assert not undocumented, (
            f"{fixture}: {sorted(undocumented)} is allowlisted but not forbidden"
        )


def test_every_fixture_has_a_contract() -> None:
    """A fixture nobody asserts against is a fixture that guards nothing."""
    on_disk = {path.name for path in _FIXTURES.glob("*.html")}
    # The region/entity fixtures are exercised by test_site_health_fact_regions.
    region_suite_only = {
        "hydrated_collection_shell.html",
        "pdp_with_recommendations.html",
        "policy_with_recommendations.html",
        "single_store_page.html",
        "store_locator_index.html",
    }
    assert on_disk - region_suite_only == set(_CONTRACTS_BY_FIXTURE)
