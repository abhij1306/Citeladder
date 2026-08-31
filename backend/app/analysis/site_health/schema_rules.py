"""Page-kind schema expectation and visible-content checks."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_page_profiles import (
    PRODUCT_SCHEMA_EXPECTATION,
    SCHEMA_CONTENT_MATCH_MAX_CANDIDATES,
    SCHEMA_CONTENT_MATCH_MIN_TOKEN_OVERLAP,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_OTHER,
    PageKindSchemaExpectation,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalized_tokens(value: str) -> set[str]:
    """Lowercase alphanumeric word tokens of ``value``."""
    return set(_TOKEN_RE.findall(str(value or "").lower()))


def matches_by_tokens(claim: str, visible: str) -> bool:
    """Whether a schema claim and visible text describe the same thing.

    Compared by shared word tokens rather than substring containment: a
    storefront writes "Dillen Letter Carrier" in its H1 and
    "Dillen Letter Carrier, Caramel" in its markup, and calling that a
    contradiction produced a HIGH-severity finding on essentially every
    correctly marked-up product page.
    """
    claim_sequence = _TOKEN_RE.findall(str(claim or "").lower())
    if not claim_sequence:
        return False
    visible_sequence = _TOKEN_RE.findall(str(visible or "").lower())
    if not visible_sequence:
        return False
    if any(
        visible_sequence[start : start + len(claim_sequence)] == claim_sequence
        for start in range(len(visible_sequence) - len(claim_sequence) + 1)
    ):
        return True
    claim_tokens = set(claim_sequence)
    visible_tokens = set(visible_sequence)
    shared = len(claim_tokens & visible_tokens)
    # A schema name is often the longer string ("Gretta Satchel, Brown Tmoro"
    # for a heading of "Gretta Satchel"). Require meaningful coverage in both
    # directions when the full claim is not a visible token-boundary phrase.
    ratio = min(shared / len(claim_tokens), shared / len(visible_tokens))
    return ratio >= SCHEMA_CONTENT_MATCH_MIN_TOKEN_OVERLAP


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_SATISFIED if condition else RULE_OUTCOME_MISSING


def schema_expectation_for(facts: dict) -> PageKindSchemaExpectation:
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    if page_kind == PRODUCT_SCHEMA_EXPECTATION.page_kind:
        return PRODUCT_SCHEMA_EXPECTATION
    return PAGE_KIND_EXPECTED_SCHEMA.get(
        page_kind, PAGE_KIND_EXPECTED_SCHEMA[PAGE_KIND_OTHER]
    )


def _normalized_document_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = parsed.hostname.lower()
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _document_urls(facts: dict) -> set[str]:
    delivery = facts.get("delivery") or {}
    return {
        normalized
        for value in (delivery.get("final_url"), facts.get("canonical_url"))
        if (normalized := _normalized_document_url(value))
    }


def _expected_blocks(
    blocks: list[dict], expectation: PageKindSchemaExpectation
) -> list[dict]:
    expected = set(expectation.expected_types)
    return [block for block in blocks if str(block.get("type") or "") in expected]


def _document_entity_references(
    blocks: list[dict], document_urls: set[str]
) -> tuple[set[str], set[str]]:
    """Return page IDs and declared primary IDs attached to this document."""
    page_ids: set[str] = set()
    declared_primary_ids: set[str] = set()
    for block in blocks:
        if _normalized_document_url(block.get("url")) not in document_urls:
            continue
        if page_id := str(block.get("schema_id") or ""):
            page_ids.add(page_id)
        if primary_id := str(block.get("main_entity_id") or ""):
            declared_primary_ids.add(primary_id)
    return page_ids, declared_primary_ids


def _primary_schema_bindings(
    blocks: list[dict],
    candidates: list[dict],
    document_urls: set[str],
) -> tuple[set[int], set[int]]:
    """Identify candidates selected by declarations and by document URL."""
    page_ids, declared_primary_ids = _document_entity_references(blocks, document_urls)
    declared_candidates: set[int] = set()
    url_candidates: set[int] = set()
    for index, block in enumerate(candidates):
        schema_id = str(block.get("schema_id") or "")
        page_reference = str(block.get("main_entity_of_page_id") or "")
        if (
            schema_id in declared_primary_ids
            or page_reference in page_ids
            or _normalized_document_url(page_reference) in document_urls
        ):
            declared_candidates.add(index)
        if _normalized_document_url(block.get("url")) in document_urls:
            url_candidates.add(index)
    return declared_candidates, url_candidates


def _resolve_primary_schema_selection(
    candidates: list[dict],
    evidence: dict,
    declared_candidates: set[int],
    url_candidates: set[int],
) -> tuple[str, list[dict], dict]:
    """Resolve primary-entity bindings without conflating their evidence."""
    if declared_candidates and url_candidates:
        corroborated = declared_candidates & url_candidates
        if len(corroborated) == 1:
            index = next(iter(corroborated))
            return RULE_OUTCOME_SATISFIED, [candidates[index]], evidence
        if not corroborated:
            return (
                RULE_OUTCOME_UNKNOWN,
                [],
                {
                    **evidence,
                    "reason": "conflicting_schema_entities",
                    "declared_candidate_indexes": sorted(declared_candidates),
                    "url_candidate_indexes": sorted(url_candidates),
                },
            )
        selected = corroborated
    else:
        selected = declared_candidates or url_candidates
    if len(selected) == 1:
        index = next(iter(selected))
        return RULE_OUTCOME_SATISFIED, [candidates[index]], evidence
    if len(selected) > 1 or len(candidates) > 1:
        return (
            RULE_OUTCOME_UNKNOWN,
            [],
            {
                **evidence,
                "reason": "ambiguous_primary_schema_entity",
            },
        )

    only = candidates[0]
    if _normalized_document_url(only.get("url")):
        return (
            RULE_OUTCOME_MISSING,
            [],
            {
                **evidence,
                "reason": "expected_schema_absent",
            },
        )
    return RULE_OUTCOME_SATISFIED, candidates, evidence


def _primary_schema_selection(
    facts: dict, expectation: PageKindSchemaExpectation
) -> tuple[str, list[dict], dict]:
    structured = facts.get("structured_data") or {}
    all_blocks = list(structured.get("blocks") or ())
    candidates = _expected_blocks(all_blocks, expectation)
    evidence = {
        "page_kind": expectation.page_kind,
        "expected_types": list(expectation.expected_types),
        "candidate_count": len(candidates),
    }
    if not candidates:
        return (
            RULE_OUTCOME_MISSING,
            [],
            {
                **evidence,
                "reason": "expected_schema_absent",
            },
        )

    declared_candidates, url_candidates = _primary_schema_bindings(
        all_blocks, candidates, _document_urls(facts)
    )
    return _resolve_primary_schema_selection(
        candidates,
        evidence,
        declared_candidates,
        url_candidates,
    )


def primary_schema_present(facts: dict) -> bool:
    expectation = schema_expectation_for(facts)
    outcome, blocks, _evidence = _primary_schema_selection(facts, expectation)
    return outcome == RULE_OUTCOME_SATISFIED and bool(blocks)


def check_schema_expected_for_type(facts: dict) -> tuple[str, dict]:
    expectation = schema_expectation_for(facts)
    outcome, blocks, evidence = _primary_schema_selection(facts, expectation)
    structured = facts.get("structured_data") or {}
    evidence["found_types"] = sorted(
        str(value) for value in (structured.get("types") or [])
    )[:20]
    evidence["primary_schema_type"] = str(blocks[0].get("type") or "") if blocks else ""
    return outcome, evidence


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
    expectation = schema_expectation_for(facts)
    selection_outcome, blocks, selection_evidence = _primary_schema_selection(
        facts, expectation
    )
    if selection_outcome == RULE_OUTCOME_UNKNOWN:
        return selection_outcome, selection_evidence
    if selection_outcome != RULE_OUTCOME_SATISFIED:
        return RULE_OUTCOME_NOT_APPLICABLE, {
            **selection_evidence,
            "reason": "no_expected_type_block",
        }
    candidates = _schema_property_candidates(
        blocks, expectation, recommended=recommended
    )
    if not candidates:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": f"no_{label}_properties"}
    block, paths, missing = candidates[0]
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
    expectation = schema_expectation_for(facts)
    selection_outcome, blocks, selection_evidence = _primary_schema_selection(
        facts, expectation
    )
    if selection_outcome == RULE_OUTCOME_UNKNOWN:
        return selection_outcome, selection_evidence
    if selection_outcome != RULE_OUTCOME_SATISFIED:
        return RULE_OUTCOME_NOT_APPLICABLE, {
            **selection_evidence,
            "reason": "no_expected_type_block",
        }
    candidates = _schema_names(blocks)
    if not candidates:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_schema_names"}
    lowered = _visible_names(facts)
    matched = any(
        matches_by_tokens(candidate, hay) for candidate in candidates for hay in lowered
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
