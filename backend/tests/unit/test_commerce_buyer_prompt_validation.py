"""The Commerce buyer-prompt style gate."""

from __future__ import annotations

from app.domain.commerce.buyer_prompt_validation import (
    admitted_buyer_prompts,
    buyer_prompt_error,
)
from app.domain.prompts.topical_binding import binding_tokens


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


class TestTopicality:
    """Register without topicality is the inverse of what the failure needed.

    Asked for buyer prompts for the "ACCESORIES" shelf of a linen-fashion
    label, the model returned "phone case with magsafe for iphone 15 pro" and
    four more like it. Every one is a flawless buyer prompt -- correct
    register, correct length, no survey framing, no repeated opening -- and
    every one passed, because nothing checked what the shop sells.
    """

    SHELF = frozenset(
        binding_tokens("linen midi dress denim jacket knit cardigan silk scarf")
    )

    def test_an_off_vertical_prompt_is_rejected(self) -> None:
        assert (
            buyer_prompt_error(
                "phone case with magsafe for iphone 15 pro",
                prior=[],
                vocabulary=self.SHELF,
            )
            == "off_topic"
        )
        assert (
            buyer_prompt_error(
                "cheap wireless earbuds under 30 that don't suck",
                prior=[],
                vocabulary=self.SHELF,
            )
            == "off_topic"
        )

    def test_a_prompt_about_the_shelf_is_admitted(self) -> None:
        assert (
            buyer_prompt_error(
                "linen midi dresses that do not wrinkle on a flight",
                prior=[],
                vocabulary=self.SHELF,
            )
            == ""
        )

    def test_an_unknown_shelf_disables_the_rule_rather_than_rejecting_all(
        self,
    ) -> None:
        # A target we know nothing about degrades to the previous behaviour;
        # generating nothing at all would be a worse failure than a loose one.
        assert (
            buyer_prompt_error(
                "phone case with magsafe for iphone 15 pro",
                prior=[],
                vocabulary=frozenset(),
            )
            == ""
        )

    def test_the_batch_helper_reports_the_reason(self) -> None:
        admitted, reasons = admitted_buyer_prompts(
            [
                "screen protector for samsung s24 ultra",
                "wide leg linen trousers for a summer wedding",
            ],
            vocabulary=self.SHELF,
        )
        assert admitted == ["wide leg linen trousers for a summer wedding"]
        assert reasons == ["off_topic"]


class TestPluralFolding:
    """Singular and plural of the same word must be the same token.

    The shelf vocabulary comes from product names and category terms, and the
    prompts come from a model that picks its own number. "accessories" folded
    to "accessorie" -- no sibilant before the "es", so the "-es" rule skipped
    it and the bare "-s" strip mangled it -- which never met "accessory". The
    one word the whole commerce failure was reported on.
    """

    def test_ies_plurals_meet_their_singular(self) -> None:
        for plural, singular in (
            ("accessories", "accessory"),
            ("categories", "category"),
            ("cookies", "cookie"),
        ):
            assert binding_tokens(plural) & binding_tokens(singular), (
                f"{plural} does not bind to {singular}"
            )

    def test_ie_singulars_are_not_split_off_by_the_ies_rule(self) -> None:
        # Folding "-ies" to "y" only works if "-ie" folds the same way;
        # otherwise "movies" and "movie" land on different tokens.
        assert binding_tokens("movies") & binding_tokens("movie")

    def test_existing_plural_rules_are_unchanged(self) -> None:
        for plural, singular in (
            ("dresses", "dress"),
            ("shoes", "shoe"),
            ("ties", "tie"),
        ):
            assert binding_tokens(plural) & binding_tokens(singular), (
                f"{plural} does not bind to {singular}"
            )
