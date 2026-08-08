"""Acceptance tests for the canonical industry knowledge-pack catalog.

The suite is intentionally pure and offline. It exercises exact immutable
loading, deterministic resolution and classification, fixture replay, bounded
explainability, catalog validation, and the benchmark harness without wiring
the catalog into the shipped Site Health runtime.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.core.config.industry_packs import (
    CatalogError,
    classify_page,
    compile_pack,
    load_pack,
    load_resolved_pack,
    pack_manifest,
    registered_pack_refs,
    resolve_pack_id,
)
from app.core.config.industry_packs.benchmark import run_benchmark
from app.core.config.industry_packs.catalog import (
    CATALOG_ROOT,
    canonical_content_hash,
    registry,
)
from app.core.config.industry_packs.validate import validate_catalog

EXPECTED_PACK_IDS = {
    "automotive",
    "commerce",
    "education",
    "financial_services",
    "general_business",
    "healthcare",
    "hospitality",
    "local_services",
    "manufacturing",
    "media_publishing",
    "nonprofit",
    "professional_services",
    "real_estate",
    "recruiting_staffing",
    "restaurants",
    "saas",
}


def _fixture(pack_id: str) -> dict[str, Any]:
    path = CATALOG_ROOT / "fixtures" / pack_id / "role-classification.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _compiled(pack_id: str) -> Any:
    version = dict(registered_pack_refs())[pack_id]
    return compile_pack(
        load_pack(pack_id, version),
        manifest=pack_manifest(pack_id, version),
    )


def _case(pack_id: str, case_class: str) -> dict[str, Any]:
    matches = [
        case for case in _fixture(pack_id)["cases"] if case["case_class"] == case_class
    ]
    assert matches, f"no {case_class!r} fixture for {pack_id}"
    return matches[0]


def test_registry_contains_exact_required_pack_set_and_one_version_each() -> None:
    refs = registered_pack_refs()
    assert len(refs) == len(EXPECTED_PACK_IDS)
    assert {pack_id for pack_id, _version in refs} == EXPECTED_PACK_IDS
    assert len(dict(refs)) == len(refs)
    assert all(version == "1.0.0" for _pack_id, version in refs)


def test_exact_loader_verifies_registry_identity_hash_and_manifest() -> None:
    for entry in registry()["packs"]:
        pack_id = str(entry["pack_id"])
        version = str(entry["version"])
        pack = load_pack(pack_id, version)
        raw_path = CATALOG_ROOT / str(entry["file"])
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        assert pack["pack_id"] == pack_id
        assert pack["version"] == version
        assert canonical_content_hash(raw) == entry["content_hash"]
        assert pack_manifest(pack_id, version) == {
            "catalog_version": registry()["catalog_version"],
            "pack_id": pack_id,
            "pack_version": version,
            "pack_content_hash": entry["content_hash"],
            "classifier_version": pack["classification_policy"]["classifier_version"],
        }


def test_loaded_pack_is_recursively_immutable_and_process_cached() -> None:
    first = load_pack("education", "1.0.0")
    second = load_pack("education", "1.0.0")
    assert first is second
    assert isinstance(first, Mapping)
    assert isinstance(first["page_roles"], tuple)
    with pytest.raises(TypeError):
        first["label"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        first["classification_policy"]["minimum_score"] = 0  # type: ignore[index]


def test_exact_loader_fails_closed_for_unknown_id_or_version() -> None:
    with pytest.raises(CatalogError, match="unknown exact industry pack"):
        load_pack("unknown", "1.0.0")
    with pytest.raises(CatalogError, match="unknown exact industry pack"):
        load_pack("education", "9.9.9")


def test_resolver_handles_ids_aliases_and_taxonomy_without_guessing() -> None:
    assert resolve_pack_id("education") == "education"
    assert resolve_pack_id("school") == "education"
    assert resolve_pack_id("e-commerce") == "commerce"
    assert resolve_pack_id("new vehicles") == "automotive"
    assert resolve_pack_id("FINANCIAL SERVICES") == "financial_services"
    with pytest.raises(CatalogError, match="unknown industry identifier"):
        resolve_pack_id("definitely-not-a-real-industry")


def test_general_fallback_requires_explicit_opt_in() -> None:
    identifier = "definitely-not-a-real-industry"
    with pytest.raises(CatalogError):
        load_resolved_pack(identifier)
    fallback = load_resolved_pack(identifier, allow_general_fallback=True)
    assert fallback["pack_id"] == "general_business"


def test_every_role_fixture_replays_exactly_and_with_bounded_output() -> None:
    total_cases = 0
    for pack_id, version in registered_pack_refs():
        pack = load_pack(pack_id, version)
        compiled = compile_pack(
            pack,
            manifest=pack_manifest(pack_id, version),
        )
        fixture = _fixture(pack_id)
        assert fixture["pack_id"] == pack_id
        classes = {case["case_class"] for case in fixture["cases"]}
        assert {
            "positive",
            "negative",
            "unknown",
            "ambiguous",
            "schema_only",
            "historical",
            "conflicting",
        }.issubset(classes)
        for case in fixture["cases"]:
            total_cases += 1
            result = classify_page(compiled, case["facts"])
            if "expected_role_id" in case:
                assert result["primary_role_id"] == case["expected_role_id"], case[
                    "case_id"
                ]
            if "expected_abstention_reason" in case:
                assert (
                    result["abstention_reason"] == case["expected_abstention_reason"]
                ), case["case_id"]
            if case.get("expected_conflict_disclosure"):
                assert result["conflicts"], case["case_id"]
            if "expected_temporal_state" in case:
                assert result["temporal_state"] == case["expected_temporal_state"]
            assert len(result["evidence"]) <= compiled.maximum_evidence_records
            assert len(result["alternatives"]) <= compiled.maximum_alternatives
            assert len(result["conflicts"]) <= compiled.maximum_conflicts
            assert len(result["secondary_role_ids"]) <= (
                compiled.maximum_secondary_roles
            )
    assert total_cases >= 16 * 7


def test_classifier_is_deterministic_pure_and_manifest_stamped() -> None:
    compiled = _compiled("education")
    facts = copy.deepcopy(_case("education", "positive")["facts"])
    original = copy.deepcopy(facts)
    first = classify_page(compiled, facts)
    second = classify_page(compiled, facts)
    assert first == second
    assert facts == original
    assert first["manifest"] == dict(compiled.manifest)
    assert first["classifier_version"] == compiled.classifier_version


def test_classifier_abstains_for_invalid_schema_only_and_ineligible_inputs() -> None:
    compiled = _compiled("commerce")
    assert classify_page(compiled, {})["abstention_reason"] == "invalid_input"

    schema_only = _case("commerce", "schema_only")
    result = classify_page(compiled, schema_only["facts"])
    assert result["primary_role_id"] is None
    assert result["abstention_reason"] == "schema_only"

    positive = _case("commerce", "positive")
    result = classify_page(compiled, positive["facts"], pack_eligible=False)
    assert result["primary_role_id"] is None
    assert result["abstention_reason"] == "pack_not_eligible"


def test_classifier_respects_corpus_exclusion_and_discloses_conflicts() -> None:
    compiled = _compiled("education")
    facts = copy.deepcopy(_case("education", "positive")["facts"])
    facts["corpus_disposition"] = "exclude"
    excluded = classify_page(compiled, facts)
    assert excluded["primary_role_id"] is None
    assert excluded["abstention_reason"] == "not_applicable"

    conflict = _case("education", "conflicting")
    conflicted = classify_page(compiled, conflict["facts"])
    assert conflicted["conflicts"]
    assert all("type" in item and "role_id" in item for item in conflicted["conflicts"])


def test_catalog_validator_enforces_complete_canonical_repository_state() -> None:
    report = validate_catalog(check_hygiene=True)
    assert report.pack_count == 16
    assert report.validated_candidate_pack_count == 2
    assert report.foundation_pack_count == 14
    assert report.role_fixture_case_count >= 16 * 7
    assert report.faq_fixture_case_count >= 16 * 6
    assert report.counts["page_roles"] == 232
    assert report.counts["question_contracts"] == 347
    assert report.hygiene_checked is True


def test_small_benchmark_is_deterministic_in_scope_and_accounts_for_pages() -> None:
    first = run_benchmark("education", 64, warmup_pages=0)
    second = run_benchmark("education", 64, warmup_pages=0)
    assert first["pack_id"] == "education"
    assert first["pages"] == 64
    assert first["classified_pages"] + first["abstained_pages"] == 64
    assert first["result_checksum"] == second["result_checksum"]
    assert first["pages_per_second"] > 0
    assert "catalog I/O and compilation excluded" in first["runtime_scope"]


def test_canonical_data_has_no_customer_specific_shared_pack_facts() -> None:
    shared_paths: list[Path] = [
        CATALOG_ROOT / "core.json",
        CATALOG_ROOT / "registry.json",
        CATALOG_ROOT / "capabilities.json",
        CATALOG_ROOT / "taxonomy.json",
        CATALOG_ROOT / "schema-terms.json",
        *sorted((CATALOG_ROOT / "packs").glob("*.json")),
    ]
    shared_text = "\n".join(
        path.read_text(encoding="utf-8").casefold() for path in shared_paths
    )
    assert "the asian school" not in shared_text
    assert "theasianschool.net" not in shared_text

    project_fixture = CATALOG_ROOT / (
        "fixtures/education/asian-school-public-labels.json"
    )
    fixture_text = project_fixture.read_text(encoding="utf-8").casefold()
    assert "theasianschool.net" not in shared_text
    assert "the_asian_school" in fixture_text
