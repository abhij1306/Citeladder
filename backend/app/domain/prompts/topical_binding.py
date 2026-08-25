# Topical binding: deterministic project-identity admission for prompt text.
#
# Topic + BrandProfile + brand aliases + owned domains are the binding
# authoritative category identity (no project-category column). This module
# builds a NORMALIZED positive vocabulary from that identity and validates
# that a prompt shares at least one non-stopword identity/category token or
# an exact normalized phrase with it. Two hard rules:
#
#   - Competitor rows are NEVER part of the positive vocabulary: naming a
#     competitor alone can never admit an off-domain prompt.
#   - The vocabulary NEVER leaves the backend: it is not sent to any
#     answer-engine provider (invariant 6) and not returned by any API — the
#     typed ``BindingResult`` carries only safe matched-token/phrase metadata.
#
# Stopwords and the minimum token length are config-owned
# (``config/prompts.py``, invariant 1). Empty vocabulary fails CLOSED and
# directs the caller to complete the project identity or use generation.
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.prompts import (
    BINDING_CODE_ACCEPTED,
    CODE_BINDING_VOCABULARY_EMPTY,
    CODE_PROMPT_OFF_TOPIC,
    PROMPT_GROUNDING_BUSINESS_CONTEXT_FIELDS,
    TOPICAL_BINDING_MIN_TOKEN_CHARS,
    TOPICAL_BINDING_STOPWORDS,
)
from app.models.brand import Brand
from app.models.project import Project

if TYPE_CHECKING:
    from collections.abc import Iterable


class TopicalBindingError(ValueError):
    """Prompt text failed project topical binding (coded, API-mapped).

    Follows the FundedAdmissionError pattern: a config-owned ``code``
    (``prompt_off_topic`` | ``binding_vocabulary_empty``) plus optional
    structured ``details`` (e.g. per-row import failures). Raised BEFORE any
    persistence, so a rejection never writes a row.
    """

    def __init__(
        self, message: str, *, code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class BindingVocabulary:
    """The normalized positive identity/category vocabulary of a project.

    ``tokens`` are single non-stopword tokens (brand/alias words, owned-domain
    host labels, topic/profile words); ``phrases`` are normalized multi-word
    identity strings matched exactly against the normalized prompt.
    """

    tokens: frozenset[str]
    phrases: frozenset[str]


@dataclass(frozen=True, slots=True)
class BindingResult:
    """The outcome of binding one prompt text to a project's vocabulary.

    Frozen + typed; ``code`` is one of the config-owned binding codes and the
    matched token/phrase metadata is safe to surface (it is the caller's own
    project identity, never provider data).
    """

    accepted: bool
    code: str
    matched_token: str | None = None
    matched_phrase: str | None = None


# Human-facing guidance per failure code (the stable contract is the code).
BINDING_FAILURE_MESSAGES: dict[str, str] = {
    CODE_PROMPT_OFF_TOPIC: (
        "Prompt text does not share any brand, owned-domain, or category term "
        "with this project's identity (brand name/aliases, owned domains, "
        "topics, or brand profile)."
    ),
    CODE_BINDING_VOCABULARY_EMPTY: (
        "This project has no brand identity to bind prompts against yet. "
        "Complete the project identity (brand name/aliases, owned domains, "
        "topics, or brand profile) or use prompt generation first."
    ),
}

# Anything that is not an ASCII letter/digit collapses to a single space.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_text(text: str) -> str:
    """NFKD ascii-fold + casefold + punctuation collapse to single spaces."""
    folded = (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    return _NON_ALNUM.sub(" ", folded).strip()


def _binding_tokens(text: str) -> list[str]:
    """Normalized non-stopword tokens of ``text`` eligible for binding."""
    return [
        token
        for token in _normalize_text(text).split()
        if len(token) >= TOPICAL_BINDING_MIN_TOKEN_CHARS
        and token not in TOPICAL_BINDING_STOPWORDS
    ]


def _phrase_of(text: str) -> str:
    """The normalized exact phrase for a multi-word identity string (or "").

    Any value with at least two normalized parts contributes a phrase — even
    one whose parts are all stopwords/below the token floor (e.g. the brand
    "7-11" -> "7 11"): the exact phrase is then the ONLY way such an
    identity can admit a prompt.
    """
    normalized = _normalize_text(text)
    if len(normalized.split()) < 2:
        return ""
    return normalized


def _host_labels(host: str) -> list[str]:
    """Dot-separated labels of an owned-domain host (scheme/path stripped)."""
    bare = (host or "").strip().casefold()
    bare = bare.split("://")[-1].split("/")[0].split(":")[0]
    return [label for label in bare.split(".") if label]


def build_vocabulary(
    *,
    names: Iterable[str] = (),
    hosts: Iterable[str] = (),
    texts: Iterable[str] = (),
) -> BindingVocabulary:
    """Assemble the positive vocabulary from raw identity strings.

    ``names``: canonical brand name + aliases (identity phrases + tokens).
    ``hosts``: owned-domain hosts (each host label contributes tokens).
    ``texts``: category text (topic names/descriptions, brand-profile
    description/positioning/target audience, products/services entries).
    Competitor data must NEVER be passed in (negative vocabulary pin).
    """
    tokens: set[str] = set()
    phrases: set[str] = set()
    for name in names:
        tokens.update(_binding_tokens(name))
        phrase = _phrase_of(name)
        if phrase:
            phrases.add(phrase)
    for host in hosts:
        for label in _host_labels(host):
            tokens.update(_binding_tokens(label))
    for text in texts:
        tokens.update(_binding_tokens(text))
        phrase = _phrase_of(text)
        if phrase:
            phrases.add(phrase)
    return BindingVocabulary(tokens=frozenset(tokens), phrases=frozenset(phrases))


def _clean(value: str | None) -> str:
    """Coerce a nullable identity column to a plain string."""
    return value or ""


def _business_context_values(context: dict[str, object]) -> list[str]:
    values: list[str] = []
    for field in PROMPT_GROUNDING_BUSINESS_CONTEXT_FIELDS:
        raw = context.get(field)
        candidates = raw if isinstance(raw, list) else [raw]
        for candidate in candidates:
            if isinstance(candidate, str):
                values.append(candidate)
            elif isinstance(candidate, list):
                values.extend(item for item in candidate if isinstance(item, str))
    return values


def _catalog_vocabulary(project: Project) -> tuple[list[str], list[str]]:
    names: list[str] = []
    categories: list[str] = []
    for product in project.products:
        names.append(_clean(product.name))
        names.extend(
            _clean(alias) for alias in (product.aliases or []) if isinstance(alias, str)
        )
        categories.append(_clean((product.attributes or {}).get("category")))
    return names, categories


def build_project_vocabulary(project: Project) -> BindingVocabulary:
    """Build the binding vocabulary from a project's persisted identity rows.

    Sources: canonical brand name + ``BrandAlias`` rows, ``OwnedDomain`` host
    labels, ``Topic`` name + description, catalog product names/aliases/category,
    and ``BrandProfile`` products/services + description + positioning + target
    audience.
    ``Competitor`` rows are deliberately never read.
    """
    names: list[str] = []
    hosts: list[str] = []
    texts: list[str] = []
    brand = project.brand
    if brand is not None:
        names.append(_clean(brand.name))
        names.extend(_clean(alias.alias) for alias in brand.aliases)
        profile = brand.profile
        if profile is not None:
            texts.extend(profile.products_services or [])
            texts.extend(_business_context_values(dict(profile.business_context or {})))
            texts.append(_clean(profile.description))
            texts.append(_clean(profile.positioning))
            texts.append(_clean(profile.target_audience))
    hosts.extend(_clean(domain.domain) for domain in project.owned_domains)
    for topic in project.topics:
        texts.append(_clean(topic.name))
        texts.append(_clean(topic.description))
    catalog_names, catalog_categories = _catalog_vocabulary(project)
    names.extend(catalog_names)
    texts.extend(catalog_categories)
    return build_vocabulary(names=names, hosts=hosts, texts=texts)


def has_project_binding_context(project: Project) -> bool:
    """Whether the project has category context suitable for topical gating.

    Brand names, aliases, and domains identify the measured entity but do not
    describe its market. A curated profile or topic does, so only those rows
    activate the lexical audit gate.
    """
    brand = project.brand
    profile = brand.profile if brand is not None else None
    if profile is not None and any(
        (
            _clean(profile.description).strip(),
            _clean(profile.positioning).strip(),
            _clean(profile.target_audience).strip(),
            any(_clean(item).strip() for item in profile.products_services or []),
        )
    ):
        return True
    return any(
        _clean(topic.name).strip() or _clean(topic.description).strip()
        for topic in project.topics
    )


def validate_prompt_binding(
    text: str, vocabulary: BindingVocabulary, *, topic_text: str = ""
) -> BindingResult:
    """Bind one prompt text to the project vocabulary (pure, deterministic).

    Accepts when the prompt shares at least one normalized non-stopword
    identity/category token with the vocabulary OR contains an exact
    normalized vocabulary phrase. Empty vocabulary fails CLOSED with
    ``binding_vocabulary_empty`` so the caller completes the project identity
    or uses generation instead of admitting unbound text.

    ``topic_text`` is the name/description of the topic this prompt is being
    filed under. A prompt is admitted when it binds to ITS OWN topic even if
    it shares no token with the wider project vocabulary.

    Why: a measurement prompt must be brand-NEUTRAL — the same text is run for
    the brand and its competitors to see who gets mentioned, so a prompt
    naming the brand measures nothing. Correct prompts therefore share only
    CATEGORY wording, and category wording legitimately varies from the
    project's stored terms ("BI dashboards" under a
    "business_intelligence_and_analytics" topic shares no literal token: "bi"
    is below the token floor). Binding a prompt to the topic a human is
    deliberately filing it under keeps the off-domain check meaningful without
    rejecting correct, on-topic prompts.
    """
    if not vocabulary.tokens and not vocabulary.phrases:
        return BindingResult(accepted=False, code=CODE_BINDING_VOCABULARY_EMPTY)
    # The prompt's own topic is category identity for THIS prompt, so it
    # widens the vocabulary for this check only (never mutates the project's).
    effective = vocabulary
    if topic_text.strip():
        topic_vocabulary = build_vocabulary(texts=[topic_text])
        effective = BindingVocabulary(
            tokens=vocabulary.tokens | topic_vocabulary.tokens,
            phrases=vocabulary.phrases | topic_vocabulary.phrases,
        )
    normalized = _normalize_text(text)
    for token in normalized.split():
        if (
            len(token) >= TOPICAL_BINDING_MIN_TOKEN_CHARS
            and token not in TOPICAL_BINDING_STOPWORDS
            and token in effective.tokens
        ):
            return BindingResult(
                accepted=True, code=BINDING_CODE_ACCEPTED, matched_token=token
            )
    padded = f" {normalized} "
    for phrase in sorted(effective.phrases):
        if f" {phrase} " in padded:
            return BindingResult(
                accepted=True, code=BINDING_CODE_ACCEPTED, matched_phrase=phrase
            )
    return BindingResult(accepted=False, code=CODE_PROMPT_OFF_TOPIC)


async def load_project_vocabulary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> BindingVocabulary:
    """Load the project's binding identity (workspace-scoped) + build the vocabulary.

    One query with the five identity relationships eager-loaded; callers
    already authorized the project through their own scoped lookup, and the
    workspace filter here keeps this loader safe to call standalone
    (invariant 5).
    """
    result = await session.execute(
        select(Project)
        .options(
            selectinload(Project.brand).selectinload(Brand.aliases),
            selectinload(Project.brand).selectinload(Brand.profile),
            selectinload(Project.owned_domains),
            selectinload(Project.topics),
            selectinload(Project.products),
        )
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    return build_project_vocabulary(result.scalars().unique().one())


async def enforce_prompt_binding(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    text: str,
    topic_text: str = "",
) -> BindingResult:
    """Require ``text`` to bind to the project's vocabulary (raises coded).

    The shared enforcement for the single-text mutation paths (manual create,
    text update, activation transition). A rejection raises
    ``TopicalBindingError`` BEFORE any write. ``topic_text`` is the topic the
    prompt is being filed under; see ``validate_prompt_binding``.
    """
    vocabulary = await load_project_vocabulary(
        session, workspace_id=workspace_id, project_id=project_id
    )
    result = validate_prompt_binding(text, vocabulary, topic_text=topic_text)
    if not result.accepted:
        raise TopicalBindingError(
            BINDING_FAILURE_MESSAGES[result.code], code=result.code
        )
    return result
