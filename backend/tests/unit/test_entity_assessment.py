from app.analysis.entity_assessment import assess_entities
from app.analysis.scoring import CompetitorConfig, ScoringConfig


def _config() -> ScoringConfig:
    return ScoringConfig(
        brand_name="Acme",
        brand_aliases=("Acme",),
        owned_domains=("acme.test",),
        unintended_domains=(),
        competitors=(
            CompetitorConfig("Rival", ("Rival",), ("rival.test",)),
            CompetitorConfig("Other", ("Other",), ("other.test",)),
        ),
    )


def test_entity_assessment_keeps_recommendation_mention_and_absence_distinct() -> None:
    rows = assess_entities("We recommend Rival. Acme is also mentioned.", _config())
    states = {row["entity_name"]: row["state"] for row in rows}
    assert states == {"Acme": "mentioned", "Rival": "recommended", "Other": "absent"}
    rival = next(row for row in rows if row["entity_name"] == "Rival")
    assert rival["evidence_spans"]


def test_empty_answer_is_unavailable_not_absent() -> None:
    assert {row["state"] for row in assess_entities("", _config())} == {"unavailable"}


def test_trailing_recommendation_language_classifies_the_entity() -> None:
    rows = assess_entities("Rival is recommended for teams like yours.", _config())
    states = {row["entity_name"]: row["state"] for row in rows}
    assert states["Rival"] == "recommended"


def test_trailing_negation_classifies_recommended_against() -> None:
    rows = assess_entities("Rival is not recommended for teams like yours.", _config())
    states = {row["entity_name"]: row["state"] for row in rows}
    assert states["Rival"] == "recommended_against"


def test_determiner_between_recommendation_and_alias_still_recommends() -> None:
    rows = assess_entities("We recommend the Rival for this.", _config())
    states = {row["entity_name"]: row["state"] for row in rows}
    assert states["Rival"] == "recommended"


def test_alias_matching_honours_ampersand_and_punctuation_equivalence() -> None:
    config = ScoringConfig(
        brand_name="Best & Less",
        brand_aliases=("Best & Less",),
        owned_domains=(),
        unintended_domains=(),
        competitors=(),
    )
    for answer in ("Best&Less is recommended.", "Best and Less is recommended."):
        rows = assess_entities(answer, config)
        assert [row["state"] for row in rows] == ["recommended"], answer
