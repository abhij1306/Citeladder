"""Page traits: what else is on a page, independent of what it is for.

``page_kind`` answers "what is this page for" and is exclusive -- exactly one
kind wins, and everything the losing signals knew is discarded. That single
answer was being asked to carry two jobs.

A product page with an FAQ block had to become either a product or an FAQ, and
the losing signal was discarded. Growing the taxonomy to
``product_with_faq``, ``service_with_local``, or ``guide_with_faq`` would
multiply kinds without covering every combination. Traits are additive: that
page stays a ``product`` and separately gains ``has_faq``.

Traits are also how two conflated kinds are separated without splitting them.
``about_contact`` bundles pages with genuinely different success criteria --
demanding contact details of ``/about/our-story`` invents a fault, while not
checking them on ``/contact-us`` misses an obvious improvement. Likewise
``case_study_review`` bundles "problem, intervention, result" with "item,
evaluator, verdict".

A trait is an observation, never an inference about purpose. Each is read from
evidence the page actually carries.

Pure, deterministic, bounded, versioned. No I/O, no ORM, no model call.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.core.config import site_health_taxonomy as _taxonomy
from app.core.config import site_health_traits as _config


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _count(value: Any) -> int:
    """A persisted count as an int, or 0 when the value is not one.

    Facts are replayed from JSONB written by an older extractor, so every
    reader in this module is defensive -- except the three that reached for
    ``int()`` directly. A count that came back as a string or a dict raised,
    and unlike a rule check (whose exception ``evaluate_rule`` converts into a
    distinct ERROR outcome) ``derive_traits`` is called straight from the
    worker with no guard, so one malformed field failed the whole page
    analysis. The module docstring promised this never happens.
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _path_segments(final_url: str) -> set[str]:
    """Lowercased exact path segments, so ``/aboutery`` is not ``/about``."""
    try:
        path = (urlsplit(str(final_url or "")).path or "").lower()
    except ValueError:
        return set()
    return {segment for segment in path.split("/") if segment}


def _haystack(facts: dict[str, Any]) -> str:
    """Title plus first H1, whitespace-bounded for phrase matching."""
    headings = _mapping(facts.get("headings"))
    h1_texts = [str(text) for text in _sequence(headings.get("h1_texts"))]
    parts = [str(facts.get("title") or ""), *h1_texts[:1]]
    return f" {' '.join(parts).lower()} "


def _schema_types(facts: dict[str, Any]) -> set[str]:
    structured = _mapping(facts.get("structured_data"))
    return {str(value) for value in _sequence(structured.get("types"))}


def _intent(trait: str, final_url: str, facts: dict[str, Any]) -> bool:
    """Route segment, else a bounded title/H1 phrase."""
    segments = _config.PAGE_TRAIT_ROUTE_SEGMENTS.get(trait, ())
    if _path_segments(final_url) & set(segments):
        return True
    haystack = _haystack(facts)
    return any(
        f" {phrase} " in haystack
        for phrase in _config.PAGE_TRAIT_TITLE_PHRASES.get(trait, ())
    )


def _has_faq(facts: dict[str, Any]) -> bool:
    """FAQPage markup, or subheadings that are literally questions.

    Deliberately STRICTER than the classifier's FAQ content signal, which
    counts any heading opening with what/why/how/where as a question. That is
    right for the classifier, where the signal competes with others and is
    resolved by tier precedence -- but an ordinary article with the headings
    "What drying removes", "Why it matters indoors" would carry has_faq on the
    same test, and a trait stands alone: whatever keys on it fires with no
    second opinion.

    A question mark is the unambiguous evidence, so that is what is required.
    """
    if set(_config.PAGE_TRAIT_SCHEMA_TYPES[_config.PAGE_TRAIT_HAS_FAQ]) & _schema_types(
        facts
    ):
        return True
    headings = _mapping(facts.get("headings"))
    texts = [
        str(text)
        for key in ("h2_texts", "h3_texts")
        for text in _sequence(headings.get(key))
    ]
    if len(texts) < _taxonomy.PAGE_KIND_FAQ_MIN_HEADINGS:
        return False
    questions = sum(1 for text in texts if text.strip().endswith("?"))
    return questions / len(texts) >= _taxonomy.PAGE_KIND_FAQ_QUESTION_RATIO


def _has_reviews(facts: dict[str, Any]) -> bool:
    if set(
        _config.PAGE_TRAIT_SCHEMA_TYPES[_config.PAGE_TRAIT_HAS_REVIEWS]
    ) & _schema_types(facts):
        return True
    product = _mapping(_mapping(facts.get("structured_data")).get("product"))
    return bool(_sequence(product.get("ratings")))


def _has_variants(facts: dict[str, Any]) -> bool:
    """Identify a variant-selection context without reading variant evidence.

    The product-answer atom validates a real selector or Product variant
    declaration. Its applicability instead comes from the visible choice a
    reader is offered, persisted independently in ``form_fields``.
    """
    field_tokens = {
        token
        for field in _sequence(facts.get("form_fields"))
        for token in re.findall(r"[a-z0-9]+", str(field).casefold())
    }
    return bool(field_tokens & _config.PAGE_TRAIT_VARIANT_FORM_FIELDS)


def _listing(facts: dict[str, Any]) -> bool:
    listing = _mapping(_mapping(facts.get("entity")).get("listing"))
    size = _count(listing.get("largest_card_list_size"))
    return size >= _taxonomy.LISTING_MIN_CARD_ITEMS


def _local_intent(facts: dict[str, Any]) -> bool:
    location = _mapping(_mapping(facts.get("entity")).get("location"))
    if _count(location.get("address_entity_count")) < 1:
        return False
    return bool(location.get("has_phone") or location.get("has_hours"))


def has_contact_form_fields(facts: dict[str, Any]) -> bool:
    raw_fields = _sequence(facts.get("form_fields"))
    fields = {str(field).strip().lower() for field in raw_fields}
    tokens = {token for field in fields for token in field.split()}
    return bool(tokens & _config.PAGE_TRAIT_CONTACT_FORM_FIELDS)


def _contact_intent(final_url: str, facts: dict[str, Any]) -> bool:
    # An authored mailto:/tel: is proof on its own -- the page hands the
    # reader a way to make contact, whatever it calls itself.
    if _sequence(facts.get("contact_points")):
        return True
    if has_contact_form_fields(facts):
        return True
    return _intent(_config.PAGE_TRAIT_CONTACT_INTENT, final_url, facts)


def _procedural(facts: dict[str, Any]) -> bool:
    if set(
        _config.PAGE_TRAIT_SCHEMA_TYPES[_config.PAGE_TRAIT_PROCEDURAL]
    ) & _schema_types(facts):
        return True
    steps = _count(facts.get("ordered_list_steps"))
    return steps >= _config.PAGE_TRAIT_PROCEDURAL_MIN_STEPS


def derive_traits(final_url: str, facts: dict[str, Any]) -> tuple[str, ...]:
    """Observed traits for one page, in stable config order.

    Never raises and never guesses: a trait is present only when the page
    carries evidence for it. Returns a tuple so the result is hashable and
    ordering is deterministic across runs (invariant 9).
    """
    observed = {
        _config.PAGE_TRAIT_HAS_FAQ: _has_faq(facts),
        _config.PAGE_TRAIT_HAS_REVIEWS: _has_reviews(facts),
        _config.PAGE_TRAIT_HAS_VARIANTS: _has_variants(facts),
        _config.PAGE_TRAIT_LISTING: _listing(facts),
        _config.PAGE_TRAIT_LOCAL_INTENT: _local_intent(facts),
        _config.PAGE_TRAIT_CONTACT_INTENT: _contact_intent(final_url, facts),
        _config.PAGE_TRAIT_ABOUT_INTENT: _intent(
            _config.PAGE_TRAIT_ABOUT_INTENT, final_url, facts
        ),
        _config.PAGE_TRAIT_CASE_STUDY_INTENT: _intent(
            _config.PAGE_TRAIT_CASE_STUDY_INTENT, final_url, facts
        ),
        _config.PAGE_TRAIT_COMPARISON_CONTENT: _intent(
            _config.PAGE_TRAIT_COMPARISON_CONTENT, final_url, facts
        ),
        _config.PAGE_TRAIT_PROCEDURAL: _procedural(facts),
    }
    return tuple(trait for trait in _config.PAGE_TRAITS if observed[trait])
