"""Unit tests for the pure topical-binding vocabulary builder + validator.

Covers the deterministic acceptance rule (shared non-stopword identity /
category token OR exact normalized phrase), Unicode/case/punctuation
normalization, the config-owned stopwords + minimum token length, the
competitor negative pin, and the empty-vocabulary fail-closed contract.
No database: the builder is exercised on plain strings and on ORM objects
built in memory.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.core.config.prompts import (
    BINDING_CODE_ACCEPTED,
    CODE_BINDING_VOCABULARY_EMPTY,
    CODE_PROMPT_OFF_TOPIC,
    TOPICAL_BINDING_MIN_TOKEN_CHARS,
    TOPICAL_BINDING_STOPWORDS,
)
from app.domain.prompts.topical_binding import (
    BindingResult,
    BindingVocabulary,
    _host_labels,
    _normalize_text,
    build_project_vocabulary,
    build_vocabulary,
    validate_prompt_binding,
)
from app.models.brand import Brand, BrandAlias, BrandProfile, Competitor, OwnedDomain
from app.models.product import Product
from app.models.project import Project
from app.models.prompt import Topic


def _vocabulary() -> BindingVocabulary:
    return build_vocabulary(
        names=["Acme Corp", "ACME Inc"],
        hosts=["acme.com"],
        texts=["Running Shoes", "Value-priced family footwear."],
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def test_normalize_text_folds_unicode_case_and_punctuation() -> None:
    assert _normalize_text("  Café  ACME-Corp!! ") == "cafe acme corp"
    assert _normalize_text("Söcks… &  SHOES?") == "socks shoes"
    assert _normalize_text("") == ""


def test_host_labels_strip_scheme_path_port_and_split_dots() -> None:
    assert _host_labels("https://Shop.Acme.com:8443/path") == ["shop", "acme", "com"]
    assert _host_labels("acme.com") == ["acme", "com"]


# ---------------------------------------------------------------------------
# Vocabulary build
# ---------------------------------------------------------------------------
def test_vocabulary_collects_identity_tokens_and_phrases() -> None:
    vocabulary = _vocabulary()
    assert "acme" in vocabulary.tokens
    assert "running" in vocabulary.tokens and "shoes" in vocabulary.tokens
    assert "footwear" in vocabulary.tokens
    # Multi-word identity strings become exact phrases.
    assert "acme corp" in vocabulary.phrases
    assert "running shoes" in vocabulary.phrases


def test_vocabulary_drops_stopwords_and_short_tokens() -> None:
    vocabulary = build_vocabulary(names=["The Acme Co"], hosts=["www.acme.com"])
    # "the"/"co"/"www"/"com" are stopwords; only the identity token survives.
    assert vocabulary.tokens == frozenset({"acme"})


def test_vocabulary_respects_config_owned_bounds() -> None:
    # The bounds live in config (invariant 1): the module owns none of them.
    assert TOPICAL_BINDING_MIN_TOKEN_CHARS >= 2
    assert "the" in TOPICAL_BINDING_STOPWORDS
    short = "x" * (TOPICAL_BINDING_MIN_TOKEN_CHARS - 1)
    vocabulary = build_vocabulary(names=[f"{short} acme"])
    assert short not in vocabulary.tokens
    assert "acme" in vocabulary.tokens


def test_build_project_vocabulary_uses_all_identity_sources() -> None:
    project = Project(name="P", brand_name="Acme Corp")
    brand = Brand(project_id=project.id, name="Acme Corp")
    brand.aliases.append(BrandAlias(brand_id=brand.id, alias="Acme"))
    brand.profile = BrandProfile(
        brand_id=brand.id,
        workspace_id=project.workspace_id or __import__("uuid").uuid4(),
        project_id=project.id,
        description="Family footwear retailer",
        positioning="Value-priced shoes",
        products_services=["running shoes", "insoles"],
        target_audience="Budget-conscious families",
    )
    project.brand = brand
    project.owned_domains.append(OwnedDomain(project_id=project.id, domain="acme.com"))
    project.topics.append(
        Topic(project_id=project.id, name="Sizing", description="Shoe fit help")
    )
    project.products.append(
        Product(
            project_id=project.id,
            sku="TRAIL-1",
            name="Trail Runner Pro",
            aliases=["TRP Shoe"],
            attributes={"category": "Hiking Footwear"},
        )
    )

    vocabulary = build_project_vocabulary(project)
    for expected in (
        "acme",
        "family",
        "footwear",
        "retailer",
        "running",
        "shoes",
        "insoles",
        "budget",
        "conscious",
        "families",
        "sizing",
        "shoe",
        "trail",
        "runner",
        "trp",
        "hiking",
    ):
        assert expected in vocabulary.tokens, expected
    assert "acme corp" in vocabulary.phrases
    assert "running shoes" in vocabulary.phrases
    assert "trail runner pro" in vocabulary.phrases


def test_business_context_flattens_one_string_list_level_only() -> None:
    project = Project(name="P", brand_name="Acme")
    brand = Brand(project_id=project.id, name="Acme")
    brand.profile = BrandProfile(
        brand_id=brand.id,
        workspace_id=project.workspace_id or __import__("uuid").uuid4(),
        project_id=project.id,
        business_context={
            "category": "workflow analytics",
            "category_aliases": [
                "process intelligence",
                ["journey analytics", {"ignored": "dictionary text"}],
                [["too deeply nested"]],
                42,
            ],
            "category_terms": {"ignored": "mapping text"},
        },
    )
    project.brand = brand

    vocabulary = build_project_vocabulary(project)

    assert {"workflow", "analytics", "process", "intelligence", "journey"} <= set(
        vocabulary.tokens
    )
    assert "ignored" not in vocabulary.tokens
    assert "dictionary" not in vocabulary.tokens
    assert "deeply" not in vocabulary.tokens


def test_build_project_vocabulary_excludes_competitors() -> None:
    project = Project(name="P", brand_name="Acme Corp")
    brand = Brand(project_id=project.id, name="Acme Corp")
    project.brand = brand
    project.competitors.append(
        Competitor(
            project_id=project.id,
            name="Globex",
            aliases=["Globex Co"],
            domains=["globex.com"],
        )
    )
    vocabulary = build_project_vocabulary(project)
    assert "globex" not in vocabulary.tokens
    assert all("globex" not in phrase for phrase in vocabulary.phrases)


def test_build_project_vocabulary_handles_missing_identity_rows() -> None:
    # No brand/profile/domains/topics at all -> empty vocabulary (fails closed).
    project = Project(name="P", brand_name="")
    assert build_project_vocabulary(project) == BindingVocabulary(
        tokens=frozenset(), phrases=frozenset()
    )
    # A brand row without profile/domains/topics still yields brand identity.
    project2 = Project(name="P", brand_name="Acme Corp")
    project2.brand = Brand(project_id=project2.id, name="Acme Corp")
    assert build_project_vocabulary(project2).tokens == frozenset({"acme"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validate_accepts_shared_identity_token() -> None:
    result = validate_prompt_binding("What are the best ACME shoes?", _vocabulary())
    assert result == BindingResult(
        accepted=True, code=BINDING_CODE_ACCEPTED, matched_token="acme"
    )


def test_validate_accepts_category_token_only() -> None:
    # No brand token at all: a category (products_services) token admits it.
    result = validate_prompt_binding("best running shoes in australia", _vocabulary())
    assert result.accepted is True
    assert result.code == BINDING_CODE_ACCEPTED
    assert result.matched_token in {"running", "shoes"}


def test_validate_accepts_exact_normalized_phrase() -> None:
    vocabulary = build_vocabulary(names=["7-11"])
    # "7"/"11" are below the minimum token length, so no token can match;
    # the exact normalized phrase is the only admission path.
    assert vocabulary.tokens == frozenset()
    assert vocabulary.phrases == frozenset({"7 11"})
    result = validate_prompt_binding("is 7 11 open late", vocabulary)
    assert result.accepted is True
    assert result.matched_token is None
    assert result.matched_phrase == "7 11"
    # A partial overlap with the phrase admits nothing.
    assert not validate_prompt_binding("is 7 open late", vocabulary).accepted


def test_validate_rejects_off_domain_text() -> None:
    result = validate_prompt_binding("best laptops for programming", _vocabulary())
    assert result == BindingResult(accepted=False, code=CODE_PROMPT_OFF_TOPIC)


def test_validate_rejects_stopword_only_overlap() -> None:
    vocabulary = build_vocabulary(names=["The Best Shoes Company"])
    assert "best" in TOPICAL_BINDING_STOPWORDS
    # "best"/"the" overlap is never enough on its own; "shoes" here matches
    # because it is a real identity token, so use text without it.
    result = validate_prompt_binding("what is the best option", vocabulary)
    assert result.accepted is False
    assert result.code == CODE_PROMPT_OFF_TOPIC


def test_validate_competitor_name_does_not_admit_off_domain_prompt() -> None:
    vocabulary = _vocabulary()  # built without any competitor rows
    result = validate_prompt_binding("is globex better than others", vocabulary)
    assert result.accepted is False
    assert result.code == CODE_PROMPT_OFF_TOPIC


def test_validate_empty_vocabulary_fails_closed() -> None:
    empty = BindingVocabulary(tokens=frozenset(), phrases=frozenset())
    result = validate_prompt_binding("anything at all", empty)
    assert result == BindingResult(accepted=False, code=CODE_BINDING_VOCABULARY_EMPTY)
    # Even on-domain-looking text cannot bind to an empty vocabulary.
    assert validate_prompt_binding("acme", empty).code == CODE_BINDING_VOCABULARY_EMPTY


def test_validate_is_unicode_case_punctuation_insensitive() -> None:
    assert validate_prompt_binding("  ÄCME!! running... shoes ", _vocabulary()).accepted
    assert validate_prompt_binding("cafe acmé corp", _vocabulary()).accepted


def test_binding_result_is_frozen() -> None:
    result = BindingResult(accepted=True, code=BINDING_CODE_ACCEPTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.accepted = False  # type: ignore[misc]
