"""Industry-pack resolution, freeze, and role-classification wiring.

Covers the contract that makes a pack-governed result trustworthy: exactly one
pack is resolved and frozen per crawl, the frozen manifest is what a later read
renders, and the three role states (selected / executed abstention / never ran)
stay distinguishable.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.analysis.site_health.parser import extract_page_facts
from app.core.config.industry_packs.catalog import CatalogError, resolve_pack_id
from app.core.config.site_health import INDUSTRY_PACK_MANIFEST_KEY
from app.domain.site_health.industry_pack import (
    IndustryPackError,
    build_role_facts,
    classify_industry_role,
    compiled_pack_for_manifest,
    freeze_pack_manifest,
    frozen_manifest,
    resolve_project_pack_id,
)

_ADMISSIONS_HTML = b"""
<html><head><title>Admissions Procedure</title></head><body>
  <h1>Admissions</h1>
  <h2>How to apply</h2>
  <h2>Eligibility</h2>
  <a href="/apply" class="btn">Apply Now</a>
  <button>Enquire</button>
  <form>
    <label for="n">Student Name</label><input id="n" name="student_name">
    <input name="grade" placeholder="Grade applying for">
  </form>
  <p>Admission to grade 1 opens in January. Submit the registration form.</p>
</body></html>
"""


def _project(**kwargs):
    return SimpleNamespace(
        industry_pack_id=kwargs.get("industry_pack_id", ""),
        industry=kwargs.get("industry", ""),
        subindustry=kwargs.get("subindustry", ""),
    )


def _crawl(configuration):
    return SimpleNamespace(configuration=configuration)


def _facts(html: bytes = _ADMISSIONS_HTML, url: str = "https://s.test/admissions"):
    return extract_page_facts(html, final_url=url)


# --- resolution -----------------------------------------------------------


def test_explicit_canonical_pack_id_wins_over_labels():
    project = _project(industry_pack_id="commerce", industry="Education")
    assert resolve_project_pack_id(project) == "commerce"


def test_onboarding_label_resolves_at_write_time():
    assert resolve_project_pack_id(_project(industry="Education")) == "education"


def test_unknown_label_leaves_the_project_unpacked():
    """An unresolvable label must not silently become the general pack.

    Falling back would make every unmatched project claim pack-governed
    findings it was never calibrated for.
    """
    assert resolve_project_pack_id(_project(industry="Sasquatch Wrangling")) == ""
    assert freeze_pack_manifest("") is None


def test_freeze_returns_none_for_an_unregistered_pack_id():
    """A non-empty id the catalog does not know must not fake a manifest.

    Exercises the CatalogError recovery branch rather than the empty-id guard:
    the crawl runs generically instead of claiming a pack it never loaded.
    """
    assert freeze_pack_manifest("no_such_pack") is None


def test_general_fallback_is_never_implicit():
    with pytest.raises(CatalogError):
        resolve_pack_id("Sasquatch Wrangling")


# --- freeze ---------------------------------------------------------------


def test_freeze_records_the_exact_manifest():
    manifest = freeze_pack_manifest("education")
    assert manifest is not None
    assert manifest["pack_id"] == "education"
    assert manifest["pack_version"]
    assert len(manifest["pack_content_hash"]) == 64
    assert manifest["classifier_version"]
    assert manifest["catalog_version"]


def test_frozen_manifest_round_trips_through_configuration():
    manifest = freeze_pack_manifest("education")
    configuration = {INDUSTRY_PACK_MANIFEST_KEY: manifest}
    assert frozen_manifest(configuration) == manifest
    # A crawl with no pack, or a malformed entry, reads back as unpacked.
    assert frozen_manifest({}) is None
    assert frozen_manifest({INDUSTRY_PACK_MANIFEST_KEY: {"pack_id": ""}}) is None


def test_a_mismatched_frozen_hash_is_an_operational_failure():
    """A pack whose bytes changed must fail loudly, not classify anyway.

    Serving a re-released pack under an old crawl's manifest would silently
    change what that historical crawl means.
    """
    manifest = dict(freeze_pack_manifest("education") or {})
    manifest["pack_content_hash"] = "0" * 64
    with pytest.raises(IndustryPackError):
        compiled_pack_for_manifest(manifest)


def test_compiled_pack_is_cached_per_exact_version():
    manifest = freeze_pack_manifest("education")
    first = compiled_pack_for_manifest(manifest)
    second = compiled_pack_for_manifest(dict(manifest or {}))
    # Same object: the worker compiles once per process, never per page.
    assert first is second


# --- role facts -----------------------------------------------------------


def test_role_facts_never_invent_empty_strings_as_positive_facts():
    facts = extract_page_facts(
        b"<html><body></body></html>", final_url="https://s.test/x"
    )
    role_facts = build_role_facts(
        facts,
        page_kind="other",
        final_url="https://s.test/x",
        corpus_disposition="analyze",
    )
    # A missing title stays missing rather than becoming "", which would match
    # a signal looking for an empty value.
    assert role_facts["title"] is None
    assert role_facts["h1"] is None
    assert role_facts["body"] is None


def test_role_facts_carry_the_conversion_signals():
    role_facts = build_role_facts(
        _facts(),
        page_kind="other",
        final_url="https://s.test/admissions",
        corpus_disposition="analyze",
    )
    assert "Apply Now" in role_facts["cta_text"]
    assert "Student Name" in role_facts["form_fields"]


# --- classification wiring ------------------------------------------------


def test_education_admissions_page_selects_its_role():
    crawl = _crawl({INDUSTRY_PACK_MANIFEST_KEY: freeze_pack_manifest("education")})
    columns = classify_industry_role(
        crawl=crawl,
        facts=_facts(),
        page_kind="other",
        site_url=SimpleNamespace(corpus_disposition="analyze"),
    )
    assert columns["industry_role_id"] == "education.admissions_overview"
    assert columns["industry_role_confidence"] in {"high", "moderate"}
    # Committed to a role -> no abstention reason.
    assert columns["role_abstention_reason"] == ""
    assert columns["industry_pack_id"] == "education"
    assert columns["pack_content_hash"]


def test_an_unpacked_crawl_leaves_the_role_never_run():
    """No pack means no role columns — NOT an abstention.

    "We did not look" and "we looked and could not tell" are different facts,
    and only the second one is evidence about the page.
    """
    columns = classify_industry_role(
        crawl=_crawl({}),
        facts=_facts(),
        page_kind="other",
        site_url=SimpleNamespace(corpus_disposition="analyze"),
    )
    assert "industry_role_id" not in columns
    assert "role_abstention_reason" not in columns
    assert columns["corpus_disposition"] == "analyze"


def test_a_contentless_page_records_an_executed_abstention():
    crawl = _crawl({INDUSTRY_PACK_MANIFEST_KEY: freeze_pack_manifest("education")})
    columns = classify_industry_role(
        crawl=crawl,
        facts=extract_page_facts(
            b"<html><body><p>.</p></body></html>", final_url="https://s.test/zzz"
        ),
        page_kind="other",
        site_url=SimpleNamespace(corpus_disposition="analyze"),
    )
    # Ran, declined: NULL role WITH a reason, and the manifest still recorded.
    assert columns["industry_role_id"] is None
    assert columns["role_abstention_reason"]
    assert columns["industry_pack_id"] == "education"


def test_an_excluded_item_is_not_applicable_rather_than_guessed():
    crawl = _crawl({INDUSTRY_PACK_MANIFEST_KEY: freeze_pack_manifest("education")})
    columns = classify_industry_role(
        crawl=crawl,
        facts=_facts(),
        page_kind="other",
        site_url=SimpleNamespace(corpus_disposition="exclude"),
    )
    assert columns["industry_role_id"] is None
    assert columns["role_abstention_reason"] == "not_applicable"


def test_classification_is_deterministic():
    """Identical artifacts must reproduce identical knowledge (S2 gate)."""
    crawl = _crawl({INDUSTRY_PACK_MANIFEST_KEY: freeze_pack_manifest("education")})
    site_url = SimpleNamespace(corpus_disposition="analyze")
    first = classify_industry_role(
        crawl=crawl, facts=_facts(), page_kind="other", site_url=site_url
    )
    second = classify_industry_role(
        crawl=crawl, facts=_facts(), page_kind="other", site_url=site_url
    )
    assert first == second
