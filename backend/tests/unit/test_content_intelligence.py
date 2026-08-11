"""Pure gates for deterministic Content Intelligence policy."""

from __future__ import annotations

import uuid

import pytest

from app.core.config.content_intelligence import CONTENT_SKILL_CATALOG
from app.domain.content.intelligence import (
    ContentValidationBlockedError,
    _validate_visible_schema_parity,
    validate_output,
)
from app.domain.content.service import _skill_definition
from app.models.content import ContentBrief, TaskContextPackage


def _brief(*, question: str = "What are the admission requirements?") -> ContentBrief:
    return ContentBrief(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        version=1,
        identity_hash="a" * 64,
        kind="faq",
        title="Admissions FAQ",
        target={"url": "https://school.example/admissions"},
        requirements={
            "questions": [
                {"question_id": "admissions.requirements", "question": question}
            ]
        },
        allowed_facts=[],
        prohibited_claims=[],
        source_refs=[],
        verification_criteria=[],
        brief_builder_version="content-brief-v1",
        evidence_hash="b" * 64,
    )


def _context(brief: ContentBrief) -> TaskContextPackage:
    return TaskContextPackage(
        id=uuid.uuid4(),
        workspace_id=brief.workspace_id,
        project_id=brief.project_id,
        brief_id=brief.id,
        task_type="content:faq",
        manifest={},
        rendered_context={
            "allowed_facts": [
                {
                    "assertion_id": "fact-1",
                    "predicate_id": "admissions.minimum_age",
                    "value": "Applicants must be 16 years old.",
                }
            ],
            "sources": [{"url": "https://school.example/admissions"}],
        },
        omissions=[],
        selection_policy_version="content-context-v1",
        manifest_hash="c" * 64,
        char_count=100,
    )


def test_validator_blocks_invented_sensitive_claims_and_unselected_links() -> None:
    brief = _brief()
    context = _context(brief)

    status, checks = validate_output(
        output_text=(
            "What are the admission requirements? Applicants must be 17 years old. "
            "See https://unrelated.example/fees."
        ),
        brief=brief,
        context=context,
    )

    assert status == "blocked"
    failed = {item["check_id"] for item in checks if not item["passed"]}
    assert failed == {"unsupported_sensitive_claims", "internal_links"}


def test_validator_does_not_treat_fact_metadata_as_an_allowed_claim() -> None:
    brief = _brief()
    context = _context(brief)
    context.rendered_context["allowed_facts"][0]["assertion_id"] = "assertion-2027"

    status, checks = validate_output(
        output_text="What are the admission requirements? Applications open in 2027.",
        brief=brief,
        context=context,
    )

    assert status == "blocked"
    claim_check = next(
        item for item in checks if item["check_id"] == "unsupported_sensitive_claims"
    )
    assert claim_check["evidence"] == ["2027"]


def test_validator_accepts_context_bound_education_answer() -> None:
    brief = _brief()
    context = _context(brief)

    status, checks = validate_output(
        output_text=(
            "What are the admission requirements? Applicants must be 16 years old. "
            "See https://school.example/admissions."
        ),
        brief=brief,
        context=context,
    )

    assert status == "passed"
    assert all(item["passed"] for item in checks)


def test_faq_schema_requires_exact_visible_question_and_answer_parity() -> None:
    schema = {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "name": "What is the returns window?",
                "acceptedAnswer": {"text": "Returns are accepted within 30 days."},
            }
        ],
    }
    visible = "## What is the returns window?\n\nReturns are accepted within 30 days."
    _validate_visible_schema_parity(visible, schema)

    with pytest.raises(
        ContentValidationBlockedError, match="faq_visible_schema_mismatch"
    ):
        _validate_visible_schema_parity(
            "## What is the returns window?\n\nContact support for details.", schema
        )

    with pytest.raises(ContentValidationBlockedError, match="faq_schema_invalid"):
        _validate_visible_schema_parity(
            visible, {"@type": "FAQPage", "mainEntity": [None]}
        )


def test_versioned_catalog_covers_education_and_commerce_reuse() -> None:
    expected = {
        "faq_visible",
        "faq_jsonld",
        "answer_first",
        "page_refresh",
        "comparison",
        "guide",
        "education_admissions",
        "education_program",
        "commerce_category",
        "commerce_pdp",
        "commerce_policy",
        "internal_links",
    }
    assert expected <= CONTENT_SKILL_CATALOG.keys()
    assert all(item["version"] for item in CONTENT_SKILL_CATALOG.values())


def test_generation_rejects_skill_formats_the_worker_cannot_render() -> None:
    brief = _brief()
    brief.kind = "faq_schema"

    with pytest.raises(ValueError, match="content_skill_output_unsupported"):
        _skill_definition(brief, "faq_jsonld")
