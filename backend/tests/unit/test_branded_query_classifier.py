from app.domain.demand.query_classification import classify_query, normalize_query


def test_multiword_brand_and_alias_match_on_token_boundaries() -> None:
    result = classify_query(
        "North Star pricing",
        brand_name="North Star Labs",
        aliases=["North Star"],
        owned_domains=["northstarlabs.com"],
    )
    assert result.classification == "branded"
    assert result.matched_terms == ("north star",)


def test_generic_single_token_brand_without_domain_support_is_ambiguous() -> None:
    result = classify_query(
        "cube pricing",
        brand_name="Cube",
        aliases=[],
        owned_domains=["cube27.com"],
    )
    assert result.classification == "ambiguous"


def test_owned_domain_spelling_supports_single_token_brand() -> None:
    result = classify_query(
        "citeladder pricing",
        brand_name="CiteLadder",
        aliases=[],
        owned_domains=["citeladder.com"],
    )
    assert result.classification == "branded"


def test_unmatched_query_is_non_branded_and_normalization_is_stable() -> None:
    result = classify_query(
        "  Best\u00a0running SHOES ",
        brand_name="CiteLadder",
        aliases=[],
        owned_domains=["citeladder.com"],
    )
    assert result.classification == "non_branded"
    assert normalize_query("  Best\u00a0running SHOES ") == "best running shoes"
