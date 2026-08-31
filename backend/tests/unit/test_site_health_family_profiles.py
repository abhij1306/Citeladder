"""Behavioral contracts for the single config-owned AEO family profile."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, fields, replace

import pytest

from app.core.config.site_health_measurement import (
    CAPABILITY_FAMILY_MANIFEST,
    CLASSIFIED_KIND_FAMILY_PROFILE,
    CapabilityFamily,
    CheckpointExpression,
    FamilyProfileRow,
    expected_checkpoints,
    expected_families,
    measurement_gap_reasons,
    profile_rows,
    relevant_dimensions,
    serialized_family_profile,
    validate_measurement_profile,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER, PAGE_KINDS
from app.core.config.site_health_traits import PAGE_TRAITS

_MEASURED = "measured"
_MEASUREMENT_GAP = "measurement_gap"
_NOT_APPLICABLE = "not_applicable"
_IMPLEMENTED_CHECKPOINT_IDS = frozenset(rule.rule_id for rule in SITE_HEALTH_RULES)
_RETIRED_CHECKPOINT_IDS = frozenset(
    {
        "aeo.author_present",
        "aeo.no_expand_gating",
        "aeo.outbound_citations",
    }
)

_EXPECTED_MANIFEST = (
    (
        "answer_content",
        "answerability",
        1.0,
        "page",
        (
            "aeo.editorial_lead_present",
            "aeo.answer_first",
            "aeo.entity_value_proposition",
            "aeo.product_answer_facts",
            "aeo.listing_answer_set",
        ),
    ),
    (
        "semantic_structure",
        "structure",
        1.0,
        "page",
        ("aeo.heading_hierarchy", "aeo.question_headings"),
    ),
    (
        "source_support",
        "evidence",
        0.5,
        "page",
        ("aeo.source_support_present",),
    ),
    (
        "commerce_facts",
        "evidence",
        0.5,
        "page",
        ("aeo.product_evidence_facts", "aeo.listing_item_facts"),
    ),
    (
        "structured_representation",
        "machine-readability",
        1.0,
        "page",
        (
            "aeo.schema_expected_for_type",
            "aeo.schema_required_valid",
            "aeo.schema_recommended_present",
            "aeo.schema_matches_content",
        ),
    ),
    (
        "visible_attribution",
        "authority",
        0.5,
        "page",
        ("aeo.visible_attribution", "aeo.product_brand_identity"),
    ),
    (
        "site_identity",
        "authority",
        0.5,
        "site",
        ("aeo.organization_identity", "aeo.trust_path_present"),
    ),
    (
        "currency",
        "freshness",
        1.0,
        "page",
        (
            "aeo.content_date_present",
            "aeo.offer_freshness_signal",
            "aeo.assortment_freshness_signal",
        ),
    ),
    (
        "indexability",
        "crawlability",
        1 / 3,
        "page",
        ("technical.indexable",),
    ),
    (
        "snippet_access",
        "crawlability",
        1 / 3,
        "page",
        ("search.snippet_access",),
    ),
    (
        "crawler_access",
        "crawlability",
        1 / 3,
        "site",
        ("search.crawler_access",),
    ),
)


def _manifest_signature(family: CapabilityFamily) -> tuple[object, ...]:
    return (
        family.family_id,
        family.dimension_id,
        family.budget,
        family.scope,
        family.checkpoint_ids,
    )


def _selected_rows(
    page_kind: str,
    page_traits: tuple[str, ...] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[FamilyProfileRow, ...]:
    return profile_rows(page_kind, page_traits=page_traits, context=context)


def _reason_values(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(reason) for reason in value.values()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return {str(reason) for reason in value}
    raise TypeError("measurement_gap_reasons must return an iterable or mapping")


def test_manifest_and_profile_serialize_canonically_from_the_public_artifact() -> None:
    expected = {
        "families": [
            asdict(family)
            for family in sorted(
                CAPABILITY_FAMILY_MANIFEST, key=lambda item: item.family_id
            )
        ],
        "profile": [
            asdict(row)
            for row in sorted(
                CLASSIFIED_KIND_FAMILY_PROFILE,
                key=lambda item: (
                    item.page_kind,
                    item.trait_condition,
                    item.family_id,
                ),
            )
        ],
    }
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"))

    assert serialized_family_profile() == canonical
    assert serialized_family_profile() == canonical
    assert (
        hashlib.sha256(canonical.encode()).hexdigest()
        == "8b35e75382270887332d912c5340107022790c5ba961f5f1167ef8eea33ef182"
    )


def test_fixed_family_manifest_is_exact_and_has_no_rule_count_aliases() -> None:
    actual = tuple(
        sorted(
            map(_manifest_signature, CAPABILITY_FAMILY_MANIFEST),
            key=lambda item: str(item[0]),
        )
    )
    expected = tuple(sorted(_EXPECTED_MANIFEST, key=lambda item: item[0]))
    assert actual == expected
    checkpoint_ids = tuple(
        checkpoint_id
        for family in CAPABILITY_FAMILY_MANIFEST
        for checkpoint_id in family.checkpoint_ids
    )
    assert len(checkpoint_ids) == len(set(checkpoint_ids))
    assert not (_RETIRED_CHECKPOINT_IDS & set(checkpoint_ids))
    assert "aeo.server_rendered_content" not in checkpoint_ids
    assert set(checkpoint_ids) <= _IMPLEMENTED_CHECKPOINT_IDS
    assert not (_RETIRED_CHECKPOINT_IDS & _IMPLEMENTED_CHECKPOINT_IDS)


def test_every_classified_kind_enumerates_every_family_at_base_condition() -> None:
    family_ids = {family.family_id for family in CAPABILITY_FAMILY_MANIFEST}
    classified_kinds = set(PAGE_KINDS) - {PAGE_KIND_OTHER}

    for page_kind in classified_kinds:
        rows = tuple(
            row
            for row in CLASSIFIED_KIND_FAMILY_PROFILE
            if row.page_kind == page_kind and row.trait_condition == "always"
        )
        assert len(rows) == len(family_ids), page_kind
        assert {row.family_id for row in rows} == family_ids, page_kind

    assert not any(
        row.page_kind == PAGE_KIND_OTHER for row in CLASSIFIED_KIND_FAMILY_PROFILE
    )
    assert _selected_rows(PAGE_KIND_OTHER) == ()


def test_profile_rows_have_one_accounted_status_and_honest_expressions() -> None:
    families = {family.family_id: family for family in CAPABILITY_FAMILY_MANIFEST}

    for row in CLASSIFIED_KIND_FAMILY_PROFILE:
        assert row.status in {_MEASURED, _MEASUREMENT_GAP, _NOT_APPLICABLE}
        assert row.family_id in families
        if row.status == _MEASURED:
            assert row.checkpoints, row
            assert not row.reason, row
            for expression in row.checkpoints:
                assert expression.checkpoint_id in _IMPLEMENTED_CHECKPOINT_IDS, row
                assert (
                    expression.checkpoint_id in families[row.family_id].checkpoint_ids
                )
                assert 0.0 < expression.internal_weight <= 1.0
        else:
            assert not row.checkpoints, row
            assert row.reason, row


def test_family_budgets_sum_to_one_per_dimension() -> None:
    dimensions = {family.dimension_id for family in CAPABILITY_FAMILY_MANIFEST}
    for dimension_id in dimensions:
        budget = math.fsum(
            family.budget
            for family in CAPABILITY_FAMILY_MANIFEST
            if family.dimension_id == dimension_id
        )
        assert budget == 1.0, dimension_id


def test_profile_derivations_use_rows_and_family_ownership_only() -> None:
    assert tuple(field.name for field in fields(FamilyProfileRow)) == (
        "page_kind",
        "trait_condition",
        "family_id",
        "status",
        "checkpoints",
        "reason",
    )
    assert tuple(field.name for field in fields(CapabilityFamily)) == (
        "family_id",
        "dimension_id",
        "budget",
        "scope",
        "checkpoint_ids",
    )
    assert tuple(field.name for field in fields(CheckpointExpression)) == (
        "checkpoint_id",
        "internal_weight",
    )
    families = {family.family_id: family for family in CAPABILITY_FAMILY_MANIFEST}
    contexts = (
        ((), None),
        ((), {"is_site_root": True}),
        ((), {"primary_schema_present": True}),
        ((), {"research_sensitive": True}),
        ((), {"freshness_sensitive": True}),
        *(((trait,), None) for trait in PAGE_TRAITS),
    )

    for page_kind in set(PAGE_KINDS) - {PAGE_KIND_OTHER}:
        for page_traits, context in contexts:
            rows = _selected_rows(page_kind, page_traits, context)
            assert len(rows) == len(families)
            assert {row.family_id for row in rows} == set(families)
            in_scope = {
                row.family_id
                for row in rows
                if families[row.family_id].scope == "page"
                or bool((context or {}).get("is_site_root"))
            }
            expected_family_ids = {
                row.family_id
                for row in rows
                if row.status in {_MEASURED, _MEASUREMENT_GAP}
                and row.family_id in in_scope
            }
            expected_checkpoint_ids = {
                expression.checkpoint_id
                for row in rows
                if row.status == _MEASURED and row.family_id in in_scope
                for expression in row.checkpoints
                if row.family_id != "structured_representation"
                or (
                    bool((context or {}).get("primary_schema_present"))
                    == (expression.checkpoint_id != "aeo.schema_expected_for_type")
                )
            }
            expected_dimension_ids = {
                families[family_id].dimension_id for family_id in expected_family_ids
            }
            expected_gap_reasons = {
                row.reason for row in rows if row.status == _MEASUREMENT_GAP
            }

            assert (
                set(
                    expected_checkpoints(
                        page_kind,
                        page_traits=page_traits,
                        crawl_context=context,
                    )
                )
                == expected_checkpoint_ids
            )
            assert (
                set(
                    expected_families(
                        page_kind,
                        page_traits=page_traits,
                        crawl_context=context,
                    )
                )
                == expected_family_ids
            )
            assert (
                set(
                    relevant_dimensions(
                        page_kind,
                        page_traits=page_traits,
                        crawl_context=context,
                    )
                )
                == expected_dimension_ids
            )
            assert (
                _reason_values(
                    measurement_gap_reasons(
                        page_kind,
                        page_traits=page_traits,
                        crawl_context=context,
                    )
                )
                == expected_gap_reasons
            )


def test_faq_structure_and_site_identity_internal_weights_are_exact() -> None:
    faq_structure = next(
        row for row in _selected_rows("faq") if row.family_id == "semantic_structure"
    )
    assert {
        expression.checkpoint_id: expression.internal_weight
        for expression in faq_structure.checkpoints
    } == {
        "aeo.heading_hierarchy": 0.5,
        "aeo.question_headings": 0.5,
    }

    site_identity_rows = tuple(
        row
        for row in CLASSIFIED_KIND_FAMILY_PROFILE
        if row.family_id == "site_identity" and row.status == _MEASURED
    )
    assert site_identity_rows
    for row in site_identity_rows:
        assert {
            expression.checkpoint_id: expression.internal_weight
            for expression in row.checkpoints
        } == {
            "aeo.organization_identity": 0.5,
            "aeo.trust_path_present": 0.5,
        }


def test_guarded_schema_expression_weights_are_exact() -> None:
    expected_weights = {
        "aeo.schema_expected_for_type": 1.0,
        "aeo.schema_required_valid": 0.5,
        "aeo.schema_recommended_present": 1 / 6,
        "aeo.schema_matches_content": 1 / 3,
    }
    measured_schema_rows = tuple(
        row
        for row in CLASSIFIED_KIND_FAMILY_PROFILE
        if row.family_id == "structured_representation" and row.status == _MEASURED
    )
    assert measured_schema_rows
    for row in measured_schema_rows:
        assert {
            expression.checkpoint_id: expression.internal_weight
            for expression in row.checkpoints
        } == expected_weights


def test_valid_profile_assembles_against_the_implemented_catalog() -> None:
    validate_measurement_profile(
        families=CAPABILITY_FAMILY_MANIFEST,
        rows=CLASSIFIED_KIND_FAMILY_PROFILE,
        implemented_checkpoint_ids=_IMPLEMENTED_CHECKPOINT_IDS,
    )


def _base_row() -> FamilyProfileRow:
    return next(
        row for row in CLASSIFIED_KIND_FAMILY_PROFILE if row.trait_condition == "always"
    )


def _gap_row() -> FamilyProfileRow:
    return next(
        row for row in CLASSIFIED_KIND_FAMILY_PROFILE if row.status == _MEASUREMENT_GAP
    )


def _na_row() -> FamilyProfileRow:
    return next(
        row for row in CLASSIFIED_KIND_FAMILY_PROFILE if row.status == _NOT_APPLICABLE
    )


def _measured_row() -> FamilyProfileRow:
    return next(
        row for row in CLASSIFIED_KIND_FAMILY_PROFILE if row.status == _MEASURED
    )


def _move_checkpoint_to_another_family(
    rows: tuple[FamilyProfileRow, ...],
) -> tuple[FamilyProfileRow, ...]:
    target = next(
        row
        for row in CLASSIFIED_KIND_FAMILY_PROFILE
        if row.status == _MEASURED and row.family_id != "semantic_structure"
    )
    return tuple(
        replace(
            row,
            checkpoints=(CheckpointExpression("aeo.heading_hierarchy", 1.0),),
        )
        if row is target
        else row
        for row in rows
    )


def _validate(
    rows: tuple[FamilyProfileRow, ...],
    families: tuple[CapabilityFamily, ...] = CAPABILITY_FAMILY_MANIFEST,
) -> None:
    validate_measurement_profile(
        families=families,
        rows=rows,
        implemented_checkpoint_ids=_IMPLEMENTED_CHECKPOINT_IDS,
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda rows: tuple(row for row in rows if row is not _base_row()),
        lambda rows: tuple(
            replace(row, status="unknown") if row is _base_row() else row
            for row in rows
        ),
        lambda rows: tuple(
            replace(row, reason="") if row is _gap_row() else row for row in rows
        ),
        lambda rows: tuple(
            replace(row, reason="primary_content_unavailable")
            if row is _na_row()
            else row
            for row in rows
        ),
        lambda rows: tuple(
            replace(
                row,
                checkpoints=(CheckpointExpression("aeo.unimplemented_proxy", 1.0),),
            )
            if row is _measured_row()
            else row
            for row in rows
        ),
        lambda rows: tuple(
            replace(row, checkpoints=()) if row is _measured_row() else row
            for row in rows
        ),
        _move_checkpoint_to_another_family,
    ),
    ids=(
        "omitted-base-family",
        "unsupported-status",
        "gap-without-reason",
        "na-with-uncertainty-reason",
        "unimplemented-checkpoint",
        "measured-without-checkpoint",
        "checkpoint-owned-by-another-family",
    ),
)
def test_invalid_profile_assembly_fails(
    mutate: Callable[[tuple[FamilyProfileRow, ...]], tuple[FamilyProfileRow, ...]],
) -> None:
    with pytest.raises(ValueError):
        _validate(mutate(CLASSIFIED_KIND_FAMILY_PROFILE))
