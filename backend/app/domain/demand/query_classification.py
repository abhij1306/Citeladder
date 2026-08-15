"""Versioned deterministic branded-query classification and overrides."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.demand import (
    BRANDED_QUERY_CLASSES,
    BRANDED_QUERY_CLASSIFIER_VERSION,
)
from app.models.brand import Brand
from app.models.demand import BrandedQueryOverride
from app.models.project import Project

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True)
class QueryClassification:
    normalized_query: str
    classification: str
    matched_terms: tuple[str, ...]
    classifier_version: str = BRANDED_QUERY_CLASSIFIER_VERSION
    override_id: uuid.UUID | None = None


def normalize_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(_TOKEN_RE.findall(normalized))


def _domain_spellings(domains: list[str]) -> set[str]:
    spellings: set[str] = set()
    for value in domains:
        host = urlsplit(value if "://" in value else f"https://{value}").hostname or ""
        host = host.removeprefix("www.")
        label = host.split(".", 1)[0]
        normalized = normalize_query(label)
        if normalized:
            spellings.add(normalized)
            spellings.add(normalized.replace(" ", ""))
    return spellings


def classify_query(
    query: str,
    *,
    brand_name: str,
    aliases: list[str],
    owned_domains: list[str],
) -> QueryClassification:
    normalized = normalize_query(query)
    tokens = normalized.split()
    domain_terms = _domain_spellings(owned_domains)
    vocabulary = {
        term for value in [brand_name, *aliases] if (term := normalize_query(value))
    }
    vocabulary.update(domain_terms)
    matched = tuple(
        sorted(
            term
            for term in vocabulary
            if term in normalized and _contains_term(tokens, term.split())
        )
    )
    if not matched:
        return QueryClassification(normalized, "non_branded", ())

    canonical = normalize_query(brand_name)
    if len(canonical.split()) == 1 and canonical in matched:
        domain_supported = any(term in matched for term in domain_terms)
        if not domain_supported:
            return QueryClassification(normalized, "ambiguous", matched)
    return QueryClassification(normalized, "branded", matched)


def _contains_term(query_tokens: list[str], term_tokens: list[str]) -> bool:
    width = len(term_tokens)
    return any(
        query_tokens[index : index + width] == term_tokens
        for index in range(len(query_tokens) - width + 1)
    )


async def classify_project_query(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    query: str,
) -> QueryClassification | None:
    results = await classify_project_queries(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        queries=[query],
    )
    return results.get(normalize_query(query))


async def classify_project_queries(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    queries: list[str],
) -> dict[str, QueryClassification]:
    """Classify a bounded query set with one override read and one brand read."""
    normalized_queries = sorted({normalize_query(value) for value in queries if value})
    if not normalized_queries:
        return {}
    override_rows = list(
        (
            await session.scalars(
                select(BrandedQueryOverride)
                .where(BrandedQueryOverride.workspace_id == workspace_id)
                .where(BrandedQueryOverride.project_id == project_id)
                .where(BrandedQueryOverride.normalized_query.in_(normalized_queries))
                .distinct(BrandedQueryOverride.normalized_query)
                .order_by(
                    BrandedQueryOverride.normalized_query,
                    BrandedQueryOverride.ordinal.desc(),
                )
            )
        ).all()
    )
    overrides: dict[str, BrandedQueryOverride] = {}
    for row in override_rows:
        overrides.setdefault(row.normalized_query, row)
    project = await session.scalar(
        select(Project)
        .where(Project.workspace_id == workspace_id, Project.id == project_id)
        .options(
            selectinload(Project.brand).selectinload(Brand.aliases),
            selectinload(Project.owned_domains),
        )
    )
    if project is None:
        return {}
    brand_name = project.brand.name if project.brand is not None else project.brand_name
    aliases = (
        [item.alias for item in project.brand.aliases]
        if project.brand is not None
        else []
    )
    domains = [item.domain for item in project.owned_domains]
    results: dict[str, QueryClassification] = {}
    for normalized in normalized_queries:
        override = overrides.get(normalized)
        if override is not None:
            results[normalized] = QueryClassification(
                normalized,
                override.classification,
                (),
                override.classifier_version,
                override.id,
            )
        else:
            results[normalized] = classify_query(
                normalized,
                brand_name=brand_name,
                aliases=aliases,
                owned_domains=domains,
            )
    return results


async def append_override(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    query: str,
    classification: str,
) -> BrandedQueryOverride:
    if classification not in BRANDED_QUERY_CLASSES:
        raise ValueError("unknown branded query classification")
    normalized_query = normalize_query(query)
    if not normalized_query:
        raise ValueError("query must contain searchable characters")
    row = BrandedQueryOverride(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        normalized_query=normalized_query,
        classification=classification,
        classifier_version=BRANDED_QUERY_CLASSIFIER_VERSION,
    )
    session.add(row)
    await session.flush()
    return row
