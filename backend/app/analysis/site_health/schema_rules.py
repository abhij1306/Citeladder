"""Page-kind schema expectation and visible-content checks."""

from __future__ import annotations

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_page_profiles import PRODUCT_SCHEMA_EXPECTATION
from app.core.config.site_health_rules import SCHEMA_CONTENT_MATCH_MAX_CANDIDATES
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_OTHER,
    PageKindSchemaExpectation,
)


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_PASS if condition else RULE_OUTCOME_FAIL


def _expectation_for(facts: dict) -> PageKindSchemaExpectation:
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    if page_kind == PRODUCT_SCHEMA_EXPECTATION.page_kind:
        return PRODUCT_SCHEMA_EXPECTATION
    return PAGE_KIND_EXPECTED_SCHEMA.get(
        page_kind, PAGE_KIND_EXPECTED_SCHEMA[PAGE_KIND_OTHER]
    )


def _expected_blocks(facts: dict, expectation: PageKindSchemaExpectation) -> list[dict]:
    structured = facts.get("structured_data") or {}
    expected = set(expectation.expected_types)
    return [
        block
        for block in (structured.get("blocks") or [])
        if str(block.get("type") or "") in expected
    ]


def check_schema_expected_for_type(facts: dict) -> tuple[str, dict]:
    expectation = _expectation_for(facts)
    structured = facts.get("structured_data") or {}
    found_types = sorted(str(value) for value in (structured.get("types") or []))
    return _pass_fail(bool(_expected_blocks(facts, expectation))), {
        "page_kind": expectation.page_kind,
        "expected_types": list(expectation.expected_types),
        "found_types": found_types[:20],
    }


def _missing_paths(block: dict, paths: tuple[str, ...]) -> list[str]:
    present = set(block.get("props_present") or [])
    return [path for path in paths if path not in present]


def _schema_property_candidates(
    blocks: list[dict], expectation: PageKindSchemaExpectation, *, recommended: bool
) -> list[tuple[dict, tuple[str, ...], list[str]]]:
    candidates = []
    for block in blocks:
        paths = expectation.properties_for(
            str(block.get("type") or ""), recommended=recommended
        )
        if paths:
            candidates.append((block, paths, _missing_paths(block, paths)))
    return candidates


def _has_shallow_microdata(
    candidates: list[tuple[dict, tuple[str, ...], list[str]]],
) -> bool:
    return any(
        str(block.get("syntax") or "") == "microdata"
        and not (block.get("props_present") or [])
        for block, _paths, _missing in candidates
    )


def _schema_property_check(facts: dict, *, recommended: bool) -> tuple[str, dict]:
    label = "recommended" if recommended else "required"
    expectation = _expectation_for(facts)
    blocks = _expected_blocks(facts, expectation)
    if not blocks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_expected_type_block"}
    candidates = _schema_property_candidates(
        blocks, expectation, recommended=recommended
    )
    if not candidates:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": f"no_{label}_properties"}
    block, paths, missing = min(candidates, key=lambda candidate: len(candidate[2]))
    evidence = {
        "page_kind": expectation.page_kind,
        "schema_type": str(block.get("type") or ""),
        "expected_types": list(expectation.expected_types),
        label: list(paths),
        "missing": missing,
        "checked_blocks": len(candidates),
    }
    if missing and _has_shallow_microdata(candidates):
        evidence["extraction"] = "microdata_shallow"
    return _pass_fail(not missing), evidence


def check_schema_required_valid(facts: dict) -> tuple[str, dict]:
    return _schema_property_check(facts, recommended=False)


def check_schema_recommended_present(facts: dict) -> tuple[str, dict]:
    return _schema_property_check(facts, recommended=True)


def check_schema_matches_content(facts: dict) -> tuple[str, dict]:
    expectation = _expectation_for(facts)
    blocks = _expected_blocks(facts, expectation)
    if not blocks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_expected_type_block"}
    candidates = _schema_names(blocks)
    if not candidates:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_schema_names"}
    lowered = _visible_names(facts)
    matched = any(
        candidate.lower() in hay for candidate in candidates for hay in lowered
    )
    return _pass_fail(matched), {
        "page_kind": expectation.page_kind,
        "candidates": [candidate[:256] for candidate in candidates],
        "matched_visible_content": matched,
    }


def _schema_names(blocks: list[dict]) -> list[str]:
    return [
        str(block.get("name") or "").strip()
        for block in blocks
        if str(block.get("name") or "").strip()
    ][:SCHEMA_CONTENT_MATCH_MAX_CANDIDATES]


def _visible_names(facts: dict) -> list[str]:
    headings = facts.get("headings") or {}
    values = [str(facts.get("title") or "")]
    values.extend(str(text) for text in (headings.get("h1_texts") or []))
    return [value.lower() for value in values if value]
