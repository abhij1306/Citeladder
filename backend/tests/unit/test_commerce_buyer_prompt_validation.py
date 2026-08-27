"""The Commerce buyer-prompt style gate."""

from __future__ import annotations

from app.domain.commerce.buyer_prompt_validation import (
    admitted_buyer_prompts,
    buyer_prompt_error,
)


class TestSurveyFraming:
    """The exact batch that shipped: five questions asked TO the shopper."""

    SHIPPED = [
        "What features do you prioritize when comparing different hygrometers "
        "for home use?",
        "How important is accuracy to you when selecting a hygrometer, and what "
        "range of humidity levels do you typically aim for?",
        "Do you prefer a hygrometer with a built-in display, or are you "
        "comfortable with a more minimalist design?",
        "What's your budget range for a hygrometer, and does it depend on "
        "additional features like connectivity or alerts?",
        "Have you encountered any common issues with hygrometers in the past, "
        "such as calibration problems or durability concerns?",
    ]

    def test_every_shipped_survey_question_is_rejected(self) -> None:
        admitted, reasons = admitted_buyer_prompts(self.SHIPPED)
        assert admitted == []
        assert set(reasons) == {"survey_framing"}

    def test_a_real_buyer_query_is_admitted(self) -> None:
        assert (
            buyer_prompt_error(
                "which hygrometer is most accurate for a humidor", prior=[]
            )
            == ""
        )
        assert (
            buyer_prompt_error(
                "best instant read thermometer for grilling under $50", prior=[]
            )
            == ""
        )


class TestBatchRules:
    def test_a_duplicate_is_rejected_regardless_of_spacing_or_case(self) -> None:
        prior = ["cheapest oven safe cookware set"]
        assert buyer_prompt_error("Cheapest  oven safe cookware set", prior=prior) == (
            "duplicate"
        )

    def test_a_third_row_sharing_an_opening_is_rejected(self) -> None:
        prior = [
            "best meat thermometer for smoking brisket",
            "best meat thermometer under 40 dollars",
        ]
        assert (
            buyer_prompt_error("best meat thermometer with a long probe", prior=prior)
            == "repeated_opening"
        )

    def test_length_bounds_reject_a_fragment_and_an_essay(self) -> None:
        assert buyer_prompt_error("thermometer", prior=[]) == "length"
        assert buyer_prompt_error(" ".join(["word"] * 40), prior=[]) == "length"

    def test_admitted_prompts_are_whitespace_normalized(self) -> None:
        admitted, reasons = admitted_buyer_prompts(
            ["  wireless   meat thermometer for iphone  "]
        )
        assert admitted == ["wireless meat thermometer for iphone"]
        assert reasons == []
