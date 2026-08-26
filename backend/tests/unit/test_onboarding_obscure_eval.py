"""Integrity checks for the frozen obscure-brand onboarding corpus."""

from evaluations.onboarding_identity_competitor_cases import OBSCURE_BRAND_CASES


def test_obscure_corpus_has_ten_distinct_evidence_grounded_cases() -> None:
    assert len(OBSCURE_BRAND_CASES) == 10
    assert len({case.brand_name.casefold() for case in OBSCURE_BRAND_CASES}) == 10
    assert all(
        case.owned_domain and case.frozen_evidence for case in OBSCURE_BRAND_CASES
    )
    assert all(case.expected_category_terms for case in OBSCURE_BRAND_CASES)


def test_lanhtropy_frozen_evidence_guards_the_linen_regression() -> None:
    case = next(case for case in OBSCURE_BRAND_CASES if case.brand_name == "Lanhtropy")
    evidence = " ".join(case.frozen_evidence).casefold()

    assert "linen" in evidence
    assert "women" in evidence
    assert case.forbidden_category_terms == ("leather goods",)
