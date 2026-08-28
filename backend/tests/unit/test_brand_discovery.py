"""Focused unit contracts for two-pass visibility onboarding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.connectors.web_evidence.brand_evidence import (
    BrandEvidenceLink,
    BrandEvidencePage,
)
from app.core.config.brand_discovery import _discovery_research_system_prompt
from app.core.config.visibility_prompts import (
    CONFIRMED_OFFERING_SOURCE_REF,
    MODEL_PRIOR_SOURCE_REF,
    TEMPLATE_LEAD_INS,
    TOPIC_SELECTION_SYSTEM_PROMPT,
    VISIBILITY_PROMPT_MAX_WORDS,
    prompt_system_prompt,
)
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryCreate,
    CompetitorQualification,
    ConfirmedDiscoveryProfile,
    DiscoveryCompetitorSuggestion,
)
from app.domain.projects.offering_harvest import harvest_offerings
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_primary_market,
    normalize_website_url,
)
from app.domain.projects.onboarding.research import (
    _customer_warnings,
    _is_peer_company,
)
from app.domain.projects.onboarding.service import discovery_catalog
from app.domain.projects.onboarding.site_resolution import resolve_site
from app.domain.projects.onboarding.topic_admission import (
    admit_topics,
    confirmed_offering_topics,
)
from app.domain.prompts.portfolio_validation import (
    PortfolioValidator,
    brand_terms,
    market_terms,
    ordered_portfolio,
    positioning_shingles,
)
from app.domain.prompts.style import words as _words


def _profile() -> dict:
    return {
        "description": "Acme sells family footwear.",
        "positioning": "Affordable shoes.",
        "products_services": ["Footwear"],
        "target_audience": "Families",
    }


def test_normalizes_url_and_market() -> None:
    url, domain = normalize_website_url("HTTPS://WWW.Example.COM:443/shop#offers")
    assert url == "https://www.example.com/shop"
    assert domain == "example.com"
    assert normalize_primary_market("in") == "IN"


@pytest.mark.parametrize("value", ["javascript:alert(1)", "file:///tmp/x", "localhost"])
def test_rejects_invalid_public_urls(value: str) -> None:
    with pytest.raises(InvalidWebsiteUrl):
        normalize_website_url(value)


def test_create_contract_requires_market() -> None:
    with pytest.raises(ValidationError):
        BrandDiscoveryCreate(brand_name="Acme", website_url="https://acme.example")


@pytest.mark.parametrize(
    "payload",
    [
        {**_profile(), "positioning": " "},
        {**_profile(), "target_audience": " "},
        {**_profile(), "products_services": [" "]},
    ],
)
def test_confirmed_profile_rejects_blank_required_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ConfirmedDiscoveryProfile(**payload)


def _competitor(model: str | None) -> DiscoveryCompetitorSuggestion:
    return DiscoveryCompetitorSuggestion(
        name="Peer",
        domains=["peer.example"],
        business_model=model,
        qualification=CompetitorQualification(
            product_substitutability=1,
            customer_use_case_overlap=1,
            geographic_relevance=1,
            question_visibility=1,
        ),
    )


def test_services_firm_does_not_accept_product_vendor_as_peer() -> None:
    assert not _is_peer_company(
        _competitor("b2b_saas"), brand_model="professional_service"
    )
    assert _is_peer_company(
        _competitor("professional_service"), brand_model="professional_service"
    )
    assert _is_peer_company(_competitor(None), brand_model="professional_service")


def test_research_prompt_no_longer_owns_topics() -> None:
    """Topic selection is its own pass; the research prompt must not compete."""
    prompt = _discovery_research_system_prompt()
    assert "TOPICS." not in prompt
    assert "COMPETITORS must be substitutable" in prompt


def test_topic_prompt_asks_for_selection_not_invention() -> None:
    prompt = TOPIC_SELECTION_SYSTEM_PROMPT
    assert "SELECT, MERGE, and NAME - do not invent" in prompt
    assert "offering_candidates" in prompt
    # The exact failure the old contract shipped is named as a non-example.
    assert "Ecommerce Marketplace" in prompt
    assert "insufficient_evidence" in prompt


def test_prompt_instruction_shows_register_for_the_business_kind() -> None:
    """A law firm's prompts must not be taught with shopping examples."""
    legal = prompt_system_prompt("professional_service")
    retail = prompt_system_prompt("retail")
    assert "redundancy dispute" in legal
    assert "cheap baby clothes in bulk" not in legal
    assert "cheap baby clothes in bulk" in retail
    assert f"{VISIBILITY_PROMPT_MAX_WORDS} words" in retail
    # An unknown facet still gets a concrete register rather than nothing.
    assert "GOOD" in prompt_system_prompt("")


def _candidate(name: str, refs: list[str] | None = None) -> dict:
    return {"name": name, "description": "", "source_refs": refs or ["nav-1"]}


def _admit(names: list[str], **kwargs) -> list[str]:
    topics = admit_topics(
        [_candidate(name) for name in names],
        known_refs=kwargs.get("known_refs", {"nav-1"}),
        forbidden_terms=kwargs.get("forbidden_terms", ["Acme"]),
        business_terms=kwargs.get("business_terms", []),
    )
    return [topic.name for topic in topics]


def test_forbidden_terms_match_complete_tokens_and_phrases() -> None:
    assert _admit(
        ["Hair Care", "Air Purifiers", "Nail Care", "AI", "Enterprise AI Tools"],
        forbidden_terms=["AI"],
    ) == ["Hair Care", "Air Purifiers", "Nail Care"]


def test_admission_rejects_the_topics_that_shipped_to_a_real_customer() -> None:
    """The exact five-row output that made this contract necessary."""
    assert (
        _admit(
            [
                "Online Retail",
                "Ecommerce Marketplace",
                "Online General Merchandise",
                "Online Department Store",
                "Consumer Goods Online Store",
            ]
        )
        == []
    )


def test_provider_rule_only_rejects_names_that_are_wholly_provider_words() -> None:
    """Substring containment rejected real departments on real retailers."""
    assert _admit(["School Uniforms", "Bank Holidays", "Online Payments"]) == [
        "School Uniforms",
        "Bank Holidays",
        "Online Payments",
    ]


def test_admission_keeps_what_customers_actually_shop_for() -> None:
    assert _admit(
        ["Kids Clothing", "Air Conditioners", "Knee Replacement", "Payment Links"]
    ) == ["Kids Clothing", "Air Conditioners", "Knee Replacement", "Payment Links"]


def test_admission_allows_buyer_qualifiers_the_old_contract_banned() -> None:
    """Cheap, affordable and price bounds are how demand is really expressed."""
    names = _admit(
        ["Mobile Phones Under 25000", "Affordable Winter Jackets", "Emergency Plumbing"]
    )
    assert len(names) == 3


def test_admission_collapses_restatements_of_one_topic() -> None:
    names = _admit(["Air Conditioners", "Air Conditioner", "Footwear", "Homewares"])
    assert names == ["Air Conditioners", "Footwear", "Homewares"]


def test_recognised_brand_keeps_topics_with_no_resolvable_evidence() -> None:
    """adidas: the site 403s, but the model knows the brand.

    Refusing here contradicted the same run's profile pass, which named the
    category and five competitors from that identical prior knowledge.
    """
    topics = admit_topics(
        [
            _candidate("Running Shoes", ["missing"]),
            _candidate("Football Boots", []),
            _candidate("Training Apparel", ["missing"]),
        ],
        known_refs=set(),
        forbidden_terms=["Adidas"],
        business_terms=[],
        allow_model_prior=True,
    )
    assert [topic.name for topic in topics] == [
        "Running Shoes",
        "Football Boots",
        "Training Apparel",
    ]
    # Provenance stays legible: none of these came from a page we fetched.
    assert {ref for topic in topics for ref in topic.source_refs} == {
        MODEL_PRIOR_SOURCE_REF
    }


def test_unrecognised_brand_still_requires_real_evidence() -> None:
    """The permission is narrow: without recognition nothing changes."""
    assert (
        admit_topics(
            [
                _candidate("Running Shoes", ["missing"]),
                _candidate("Football Boots", []),
                _candidate("Training Apparel", ["missing"]),
            ],
            known_refs=set(),
            forbidden_terms=[],
            business_terms=[],
            allow_model_prior=False,
        )
        == []
    )


def test_recognised_brand_still_prefers_real_refs_when_they_resolve() -> None:
    """A page-backed topic keeps its page ref rather than being stamped."""
    topics = admit_topics(
        [_candidate("Running Shoes"), _candidate("Bags"), _candidate("Hats")],
        known_refs={"nav-1"},
        forbidden_terms=[],
        business_terms=[],
        allow_model_prior=True,
    )
    assert {ref for topic in topics for ref in topic.source_refs} == {"nav-1"}


def test_admission_keeps_departments_that_merely_look_alike() -> None:
    """Character similarity would merge these; token identity must not."""
    names = _admit(["Women's Footwear", "Men's Footwear", "Kids' Footwear"])
    assert len(names) == 3


def test_admission_drops_brand_and_unbound_evidence_without_padding() -> None:
    assert _admit(["Acme Footwear", "Footwear", "Bags"]) == ["Footwear", "Bags"]
    topics = admit_topics(
        [
            _candidate("Footwear", ["missing"]),
            _candidate("Bags"),
            _candidate("Hats"),
        ],
        known_refs={"nav-1"},
        forbidden_terms=[],
        business_terms=[],
    )
    assert [topic.name for topic in topics] == ["Bags", "Hats"]


def test_category_restatement_rule_yields_to_a_single_offering_business() -> None:
    """A mattress brand whose category IS mattresses must keep the topic."""
    assert _admit(["Mattresses"], business_terms=["mattresses"]) == ["Mattresses"]
    # When a specific topic survives, the provider-category restatement drops.
    names = _admit(
        ["Mattresses", "Pillows", "Bed Frames"],
        business_terms=["mattresses"],
    )
    assert "Mattresses" not in names


def test_confirmed_offerings_are_a_simple_provenanced_recovery_path() -> None:
    topics = confirmed_offering_topics(
        [" Analytics Software ", "analytics software", "Process Mining"]
    )
    assert [topic.name for topic in topics] == ["Analytics Software", "Process Mining"]
    assert {ref for topic in topics for ref in topic.source_refs} == {
        CONFIRMED_OFFERING_SOURCE_REF
    }


def _validator(**kwargs) -> PortfolioValidator:
    return PortfolioValidator(
        topic_ids=kwargs.get("topic_ids", frozenset({"t1", "t2"})),
        brand_terms=kwargs.get("brand_terms", ["Acme"]),
        competitor_terms=kwargs.get("competitor_terms", ["Rival"]),
        positioning=kwargs.get("positioning", frozenset()),
        market_words=kwargs.get("market_words", ("India", "Indian")),
    )


def _offer(validator: PortfolioValidator, text: str, **kwargs) -> str:
    return validator.offer(
        {
            "topic_id": kwargs.get("topic_id", "t1"),
            "text": text,
            "intent": kwargs.get("intent", "discovery"),
        },
        cohort=kwargs.get("cohort", "core"),
    )


@pytest.mark.parametrize("lead_in", TEMPLATE_LEAD_INS)
def test_every_shipped_template_frame_is_rejected(lead_in: str) -> None:
    """The old prompt asked for these to be avoided; the model used them."""
    assert _offer(_validator(), f"{lead_in} kids clothing today") == "template_lead_in"


def test_pasted_positioning_is_rejected() -> None:
    validator = _validator(
        positioning=positioning_shingles(
            [
                "Indian consumers seeking a wide range of products with "
                "competitive pricing, convenience, and fast delivery"
            ]
        )
    )
    assert (
        _offer(
            validator,
            "Shoes for Indian consumers seeking a wide range of products "
            "with competitive pricing",
        )
        == "positioning_paste_in"
    )


def test_buyer_language_is_accepted() -> None:
    validator = _validator()
    assert _offer(validator, "I want to buy cheap baby clothes in bulk") == ""
    assert (
        _offer(
            validator,
            "Looking for kids school shoes before term starts",
            topic_id="t2",
        )
        == ""
    )
    assert len(validator.accepted) == 2


def test_repeated_openings_are_capped_across_the_portfolio() -> None:
    validator = _validator()
    assert _offer(validator, "best running shoes for flat feet") == ""
    assert (
        _offer(validator, "best running shoes under 5000 rupees", topic_id="t2") == ""
    )
    assert _offer(validator, "best running shoes for wide toes") == "repeated_opening"


def test_ordinary_words_containing_a_country_code_are_not_market_mentions() -> None:
    """A bare "IN" matched inside "running", capping nearly every prompt."""
    assert "IN" not in market_terms("IN", [])
    validator = _validator(market_words=market_terms("IN", []))
    assert not validator._names_market("best running shoes for finding flat feet")
    assert validator._names_market("cheap school shoes in India")


def test_words_tokenize_every_script_not_just_ascii() -> None:
    assert _words("सस्ते बच्चों के कपड़े") == ["सस्ते", "बच्चों", "के", "कपड़े"]
    assert _words("Men's Shoes under 5000!") == ["men", "s", "shoes", "under", "5000"]


def test_named_brand_rows_reject_an_unknown_topic_id() -> None:
    """An invented id is a rejection, not a silently detached prompt."""
    validator = _validator()
    assert (
        _offer(
            validator,
            "is Acme any good for school shoes",
            topic_id="not-a-real-topic",
            cohort="brand_diagnostic",
        )
        == "topic_id"
    )
    # A canonical id is kept, so the row stays bound to the topic it names.
    assert (
        _offer(
            validator,
            "is Acme any good for school shoes",
            topic_id="t1",
            cohort="brand_diagnostic",
        )
        == ""
    )
    assert validator.accepted[0]["topic_id"] == "t1"
    # Naming no topic at all remains valid for this cohort.
    assert (
        _offer(
            validator,
            "does Acme sell wide fit kids trainers",
            topic_id="",
            cohort="brand_diagnostic",
        )
        == ""
    )
    assert validator.accepted[1]["topic_id"] == ""


def test_market_is_named_at_most_once_per_topic() -> None:
    validator = _validator()
    assert _offer(validator, "where to buy school shoes in India cheaply") == ""
    assert (
        _offer(validator, "which Indian store sells kids winter jackets")
        == "market_mention_cap"
    )
    # A different topic gets its own allowance.
    assert _offer(validator, "best Indian sites for baby clothes", topic_id="t2") == ""


def test_unbound_brand_diagnostics_do_not_share_a_topic_market_cap() -> None:
    validator = _validator()
    assert (
        _offer(
            validator,
            "is Acme reliable for buyers in India",
            topic_id="",
            cohort="brand_diagnostic",
        )
        == ""
    )
    assert (
        _offer(
            validator,
            "does Acme support customers across India",
            topic_id="",
            cohort="brand_diagnostic",
        )
        == ""
    )


def test_short_form_of_a_multi_word_brand_is_still_the_brand() -> None:
    """ "Best Apollo hospital for..." shipped as an ORGANIC prompt."""
    terms = brand_terms("Apollo Hospitals", [])
    assert "Apollo Hospitals" in terms
    assert "apollo" in terms
    # The provider word is not the brand and must stay usable by everyone.
    assert "hospitals" not in terms
    validator = _validator(brand_terms=terms)
    assert (
        _offer(validator, "Best Apollo hospital for kidney stone treatment")
        == "tracked_name"
    )


def test_identity_rules_per_cohort() -> None:
    assert _offer(_validator(), "is Acme good for kids shoes") == "tracked_name"
    assert (
        _offer(_validator(), "best shop for kids shoes", cohort="brand_diagnostic")
        == "missing_brand_name"
    )
    assert (
        _offer(
            _validator(),
            "how does Acme compare for kids shoes",
            cohort="comparison",
            intent="comparison",
        )
        == "missing_competitor_name"
    )
    assert (
        _offer(
            _validator(),
            "Acme or Rival for kids school shoes",
            cohort="comparison",
            intent="comparison",
        )
        == ""
    )


def test_length_bounds_reject_prose_and_fragments() -> None:
    long_text = " ".join(["shoes"] * (VISIBILITY_PROMPT_MAX_WORDS + 1))
    assert _offer(_validator(), long_text) == "length"
    assert _offer(_validator(), "cheap shoes") == "length"


def test_portfolio_is_ordered_round_robin_so_activation_covers_every_topic() -> None:
    prompts = [
        {"topic_id": "t1", "text": "a", "intent": "discovery", "cohort": "core"},
        {"topic_id": "t1", "text": "b", "intent": "discovery", "cohort": "core"},
        {"topic_id": "t2", "text": "c", "intent": "discovery", "cohort": "core"},
        {
            "topic_id": "x",
            "text": "d",
            "intent": "discovery",
            "cohort": "brand_diagnostic",
        },
    ]
    ordered = ordered_portfolio(prompts, topic_ids=["t1", "t2"])
    assert [item["text"] for item in ordered] == ["a", "c", "b", "d"]


def _page(links: list[tuple[str, str]]) -> BrandEvidencePage:
    return BrandEvidencePage(
        url="https://acme.com/",
        title="",
        meta_description="",
        text="text",
        navigation_links=tuple(
            BrandEvidenceLink(url=f"https://acme.com{path}", label=label)
            for label, path in links
        ),
    )


def _harvest(
    links: list[tuple[str, str]], *, brand_terms: list[str] | None = None
) -> list[str]:
    harvest = harvest_offerings((_page(links),), brand_terms=brand_terms or ["Acme"])
    return [node.label for node in harvest.nodes]


def test_harvest_keeps_offerings_and_drops_chrome() -> None:
    assert _harvest(
        [
            ("Login", "/account/login"),
            ("Cart", "/viewcart"),
            ("Investor Relations", "/investors"),
            ("Dr. Jane Roe", "/team/jane-roe"),
            ("Kids Clothing", "/kids-clothing"),
            ("Air Conditioners", "/air-conditioners"),
            ("Shop now", "/new-arrivals"),
            ("Deutsch", "/de"),
            ("Acme Originals", "/originals"),
        ]
    ) == ["Kids Clothing", "Air Conditioners"]


def test_harvest_caps_a_city_index_so_it_cannot_flood_the_budget() -> None:
    labels = _harvest(
        [("Plumbing", "/plumbing"), ("Carpentry", "/carpentry")]
        + [(f"Plumber in City{index}", f"/city{index}") for index in range(30)]
    )
    assert labels[:2] == ["Plumbing", "Carpentry"]
    assert sum(1 for label in labels if label.startswith("Plumber in")) <= 3


def test_harvest_keeps_possessive_departments_apart() -> None:
    """ "Men's Shoes" and "Women's Shoes" both carry a bare "s" token."""
    labels = _harvest(
        [
            ("Men's Shoes", "/mens-shoes"),
            ("Women's Shoes", "/womens-shoes"),
            ("Kids' Shoes", "/kids-shoes"),
            ("Men's Shirts", "/mens-shirts"),
        ]
    )
    assert len(labels) == 4


def test_harvest_reports_empty_when_no_readable_list_is_published() -> None:
    page = _page([("Login", "/account/login")])
    assert not harvest_offerings((page,), brand_terms=["Acme"]).is_ready


def test_harvest_rejects_query_identified_detail_pages() -> None:
    assert _harvest(
        [
            ("Kids Clothing", "/kids-clothing"),
            ("Air Conditioners", "/air-conditioners"),
            ("Mobile Phones", "/mobile-phones"),
            ("One Phone", "/product?pid=123"),
        ]
    ) == ["Kids Clothing", "Air Conditioners", "Mobile Phones"]


def test_harvest_matches_brand_names_as_complete_phrases() -> None:
    assert _harvest(
        [
            ("Party Supplies", "/party-supplies"),
            ("Art Originals", "/art-originals"),
            ("Home Decor", "/home-decor"),
            ("Gifts", "/gifts"),
        ],
        brand_terms=["Art"],
    ) == ["Party Supplies", "Home Decor", "Gifts"]


def test_catalog_exposes_only_stored_visibility_cohorts() -> None:
    assert discovery_catalog()["prompt_cohorts"] == [
        "core",
        "brand_diagnostic",
        "comparison",
    ]


def test_customer_warnings_only_report_material_gaps() -> None:
    assert _customer_warnings(model_available=True, competitors_found=True) == []
    assert _customer_warnings(model_available=False, competitors_found=False) == [
        "research_degraded",
        "competitors_not_found",
    ]


@pytest.mark.asyncio
async def test_https_to_http_redirect_is_not_used_as_research(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=200,
        final_url="http://acme.com/",
        body=b"<html><body>Brand text</body></html>",
        charset="utf-8",
    )

    class Fetcher:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def fetch(self, _request):
            return response

    monkeypatch.setattr(
        "app.domain.projects.onboarding.site_resolution.SecureFetcher",
        lambda **_kwargs: Fetcher(),
    )
    site = await resolve_site("acme.com", "https://acme.com/")
    assert site.page is None
    assert site.warning == "research_degraded"


def test_brand_named_after_its_category_keeps_the_category_word_usable() -> None:
    """Red Dress banned "dress" and shipped a portfolio of two branded prompts.

    Every organic dress query was rejected as `tracked_name`, the core cohort
    emptied, and the only survivors were the two mandatory brand-diagnostic
    prompts -- which are required to name the brand.
    """
    terms = brand_terms("Red Dress", [], ["Dresses", "Women's clothing"])
    assert "Red Dress" in terms
    assert "dress" not in terms
    validator = _validator(brand_terms=terms)
    assert _offer(validator, "best summer dresses for a beach wedding") == ""
    # The full name is still the brand and still cannot appear organically.
    assert _offer(validator, "is Red Dress good for petite sizing") == "tracked_name"


def test_brand_named_with_ordinary_english_keeps_that_word_usable() -> None:
    """ "I Love Dooney" banned "love" and left a portfolio of brand prompts.

    The same collapse as the Red Dress case, from the other side: "love" is
    not category language, so no confirmed category could ever unban it, yet
    it appears in a large share of ordinary apparel queries. Every one of them
    was rejected as `tracked_name`, the core cohort emptied, and the fixed
    brand-diagnostic and comparison prompts became the whole portfolio. It
    looked brand-specific because it depended on the brand's own name.
    """
    terms = brand_terms("I Love Dooney", ["ilovedooney"], ["Handbags", "Purses"])
    assert "I Love Dooney" in terms
    assert "love" not in terms
    # The distinctive token is still the brand and is still banned.
    assert "dooney" in terms
    validator = _validator(brand_terms=terms)
    assert _offer(validator, "leather handbags i would love for everyday work") == ""
    assert _offer(validator, "are Dooney bags worth the price") == "tracked_name"
    # The site's own spelling is one word and is never a token of the name, so
    # it has to be banned as an alias.
    assert _offer(validator, "is ilovedooney a legit place to buy bags") == (
        "tracked_name"
    )


def test_category_vocabulary_never_unbans_a_real_brand_token() -> None:
    terms = brand_terms("Apollo Hospitals", [], ["Cardiac care", "Hospitals"])
    assert "apollo" in terms
    validator = _validator(brand_terms=terms)
    assert (
        _offer(validator, "Best Apollo hospital for kidney stone treatment")
        == "tracked_name"
    )


def test_one_unreadable_row_no_longer_voids_its_whole_batch() -> None:
    """An unknown slot is dropped without discarding a valid planned row."""
    import json

    from app.domain.prompts.generation_contract import parse_planned_output
    from app.domain.prompts.query_patterns import build_prompt_slots

    slots = build_prompt_slots(
        topics=[{"id": "t1", "name": "Linen Dresses", "description": ""}],
        count=2,
        cohort="core",
    )

    raw = json.dumps(
        {
            "prompts": [
                {
                    "slot_id": "q1",
                    "text": "Best linen dresses for a summer wedding",
                },
                {"slot_id": "unknown", "text": "Linen dresses under 200 online"},
            ]
        }
    )
    rows, dropped = parse_planned_output(raw, slots=slots)

    assert [row.text for row in rows] == ["Best linen dresses for a summer wedding"]
    assert dropped == 1


def test_onboarding_uses_the_shared_constrained_buyer_query_plan() -> None:
    import uuid

    from app.domain.projects.discovery_schemas import DiscoveryTopic
    from app.domain.projects.onboarding.portfolio_generation import (
        _brand_request,
        _topic_request,
        onboarding_brand_context,
    )
    from tests.fixtures.archetype_text import slots_from_user_message

    topic = DiscoveryTopic(
        topic_id=uuid.uuid4(),
        name="Product Feed Management",
        description="Retail catalog distribution and diagnostics",
        source_refs=["confirmed-profile"],
    )
    brand_context = onboarding_brand_context(
        brand_name="Feedonomics",
        primary_market="US",
        profile={
            "business_model": "b2b_saas",
            "buyer_register": "technical_buyer",
            "description": "Feedonomics manages retail product feeds.",
        },
        competitors=["Productsup"],
    )
    user, slots = _topic_request(
        brand_context=brand_context, topics=[topic], rejected=()
    )

    # Weighted toward the archetypes an assistant answers by naming a business,
    # and still reaching every stage.
    assert [slot.archetype for slot in slots] == [
        "consideration_recommend",
        "decision_buy",
        "consideration_recommend",
        "consideration_compare",
        "decision_validate",
        "awareness_solve",
        "awareness_learn",
    ]
    # Every planned slot names a job and a surface form, and never a sentence
    # frame the model would have to copy.
    planned = slots_from_user_message(user)
    assert len(planned) == 7
    assert {slot["form"] for slot in planned} == {
        "question",
        "first_person",
        "search_phrase",
    }
    assert all(slot["job"] and "exact form" not in slot["job"] for slot in planned)

    _, brand_slots = _brand_request(
        brand_context=brand_context,
        competitors=["Productsup"],
        topics=[topic],
        count=2,
        cohort="brand_diagnostic",
    )
    assert [slot.archetype for slot in brand_slots] == [
        "brand_awareness_learn",
        "brand_decision_validate",
    ]
    assert all(slot.topic_id is None for slot in brand_slots)


def test_admission_rejects_an_unsplit_bundle_but_keeps_real_departments() -> None:
    """ "Womenswear including plus size" is two departments wearing one name.

    It reached a customer's portfolio and became "What is womenswear including
    plus size?" -- a question nobody types. A bare "and" stays legal, because
    "Footwear and Accessories" is a department people really do shop.
    """
    assert _admit(["Womenswear including plus size"]) == []
    assert _admit(["Beauty, Toys and More"]) == []
    assert _admit(["Beauty, Toys &amp; More"]) == []
    assert _admit(["Footwear and Accessories"]) == ["Footwear and Accessories"]
    assert _admit(["School Uniforms"]) == ["School Uniforms"]
