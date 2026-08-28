"""Commerce catalog commands and side-effect-free persisted reads."""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import (
    COMMERCE_CATEGORY_EDIT_VERSION,
    COMMERCE_EDIT_VERSION,
    COMMERCE_IMPORT_ERROR_LIMIT,
    COMMERCE_IMPORT_MAX_BYTES,
    COMMERCE_IMPORT_MAX_ROWS,
    COMMERCE_IMPORTER_VERSION,
    COMMERCE_PROJECTOR_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.commerce.eligibility import project_sells_catalog
from app.domain.commerce.schemas import (
    CatalogEditRequest,
    CatalogImportRequest,
    CatalogImportResponse,
    CatalogResponse,
    CatalogRowOutcome,
    CategoryEditRequest,
    CategoryResponse,
    ProductResponse,
)
from app.domain.integrations.sync import integrity_constraint_name
from app.domain.site_health.normalization import canonical_identity
from app.models.analytics import AnalyticsTask
from app.models.commerce import (
    CommerceCategory,
    CommerceCategoryObservation,
    CommerceCsvImport,
    CommerceProduct,
    CommerceProductCategory,
    CommerceProductObservation,
)
from app.models.project import Project


class CommerceNotFoundError(LookupError):
    pass


class CommerceConflictError(ValueError):
    pass


_CATEGORY_NAME_UNIQUE_CONSTRAINT = "uq_commerce_category_name"


class CommerceImportError(ValueError):
    pass


_FIELDS = (
    "canonical_url",
    "name",
    "description",
    "brand",
    "price",
    "currency",
    "sku",
    "gtin",
    "mpn",
    "variants",
    "attributes",
)


async def require_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if project is None:
        raise CommerceNotFoundError("Project not found")
    return project


async def _memberships(
    session: AsyncSession, *, project_id: uuid.UUID
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], dict[uuid.UUID, int]]:
    rows = (
        await session.execute(
            select(
                CommerceProductCategory.product_id,
                CommerceProductCategory.category_id,
            ).where(CommerceProductCategory.project_id == project_id)
        )
    ).all()
    by_product: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    by_category: dict[uuid.UUID, int] = defaultdict(int)
    for product_id, category_id in rows:
        by_product[product_id].append(category_id)
        by_category[category_id] += 1
    return by_product, by_category


def _product_response(
    product: CommerceProduct, category_ids: list[uuid.UUID]
) -> ProductResponse:
    return ProductResponse.model_validate(product).model_copy(
        update={"category_ids": category_ids}
    )


async def get_catalog(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CatalogResponse:
    """Read current persisted projections; never starts projection work."""
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    products = list(
        (
            await session.scalars(
                select(CommerceProduct)
                .where(
                    CommerceProduct.workspace_id == workspace_id,
                    CommerceProduct.project_id == project_id,
                )
                .order_by(CommerceProduct.name, CommerceProduct.canonical_url)
            )
        ).all()
    )
    categories = list(
        (
            await session.scalars(
                select(CommerceCategory)
                .where(
                    CommerceCategory.workspace_id == workspace_id,
                    CommerceCategory.project_id == project_id,
                )
                .order_by(CommerceCategory.name)
            )
        ).all()
    )
    by_product, by_category = await _memberships(session, project_id=project_id)
    categories.sort(
        key=lambda row: (
            -by_category[row.id],
            row.name.casefold(),
            str(row.id),
        )
    )
    queue_rows = (
        await session.execute(
            select(AnalyticsTask.status, func.count())
            .where(
                AnalyticsTask.workspace_id == workspace_id,
                AnalyticsTask.project_id == project_id,
                AnalyticsTask.task_kind == "commerce_catalog_projection",
            )
            .group_by(AnalyticsTask.status)
        )
    ).all()
    return CatalogResponse(
        products=[_product_response(row, by_product[row.id]) for row in products],
        categories=[
            CategoryResponse.model_validate(row).model_copy(
                update={"product_count": by_category[row.id]}
            )
            for row in categories
        ],
        projection_tasks={status: count for status, count in queue_rows},
    )


async def edit_category(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CategoryEditRequest,
) -> CategoryResponse:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    category = await session.scalar(
        select(CommerceCategory).where(
            CommerceCategory.id == category_id,
            CommerceCategory.project_id == project_id,
            CommerceCategory.workspace_id == workspace_id,
        )
    )
    if category is None:
        raise CommerceNotFoundError("Category not found")
    observed: dict[str, Any] = {}
    if "name" in payload.model_fields_set:
        name = str(payload.name or "").strip()
        if not name:
            raise CommerceConflictError("category name cannot be empty")
        normalized = " ".join(name.casefold().split())
        duplicate = await session.scalar(
            select(CommerceCategory.id).where(
                CommerceCategory.project_id == project_id,
                CommerceCategory.normalized_name == normalized,
                CommerceCategory.id != category.id,
            )
        )
        if duplicate is not None:
            raise CommerceConflictError("category name already exists")
        category.name = name
        category.normalized_name = normalized
        observed["name"] = name
    if "role" in payload.model_fields_set and payload.role is not None:
        category.role = payload.role
        observed["role"] = payload.role
    if not observed:
        raise CommerceConflictError("category edit must supply a name or role")
    observation = CommerceCategoryObservation(
        workspace_id=workspace_id,
        project_id=project_id,
        category_id=category.id,
        observed_fields=observed,
        edit_version=COMMERCE_CATEGORY_EDIT_VERSION,
    )
    session.add(observation)
    await session.flush()
    sources = dict(category.field_sources or {})
    for field in observed:
        sources[field] = {
            "kind": "edit",
            "source_id": str(observation.id),
            "version": COMMERCE_CATEGORY_EDIT_VERSION,
        }
    category.field_sources = sources
    await _commit_category_edit(session)
    product_count = await session.scalar(
        select(func.count()).where(CommerceProductCategory.category_id == category.id)
    )
    return CategoryResponse.model_validate(category).model_copy(
        update={"product_count": product_count or 0}
    )


async def _commit_category_edit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if integrity_constraint_name(exc) != _CATEGORY_NAME_UNIQUE_CONSTRAINT:
            raise
        raise CommerceConflictError("category name already exists") from exc


def _csv_reader(content: str) -> csv.DictReader:
    if not content.strip():
        raise CommerceImportError("CSV is empty")
    sample = content[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error as exc:
        raise CommerceImportError("CSV delimiter could not be determined") from exc
    if dialect.delimiter != ",":
        raise CommerceImportError("Only comma-delimited CSV is supported")
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        raise CommerceImportError("CSV header is missing")
    normalized = [str(value or "").strip().casefold() for value in reader.fieldnames]
    if len(normalized) != len(set(normalized)):
        raise CommerceImportError("CSV header contains duplicate columns")
    supported = set(_FIELDS) | {"category", "categories"}
    if not set(normalized) & supported:
        raise CommerceImportError("CSV has no supported catalog columns")
    reader.fieldnames = normalized
    return reader


def _clean_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key or "").strip().casefold(): str(value or "").strip()
        for key, value in raw.items()
    }


def _price(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        price = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("price must be a number") from exc
    if price < 0:
        raise ValueError("price cannot be negative")
    return price


async def _identity_matches(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    canonical_url: str,
    gtin: str,
    sku: str,
) -> CommerceProduct | None:
    conditions = []
    if canonical_url:
        conditions.append(CommerceProduct.canonical_url == canonical_url)
    if gtin:
        conditions.append(CommerceProduct.gtin == gtin)
    if sku:
        conditions.append(CommerceProduct.sku == sku)
    if not conditions:
        return None
    matches = list(
        (
            await session.scalars(
                select(CommerceProduct).where(
                    CommerceProduct.project_id == project_id, or_(*conditions)
                )
            )
        ).all()
    )
    unique = {row.id: row for row in matches}
    if len(unique) > 1:
        raise CommerceConflictError("identifiers resolve to different products")
    return next(iter(unique.values()), None)


def _csv_values(row: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in _FIELDS:
        if field not in row or not row[field]:
            continue
        if field == "price":
            values[field] = _price(row[field])
        elif field == "canonical_url":
            values[field] = canonical_identity(row[field])[0]
        elif field in {"variants", "attributes"}:
            raise ValueError(f"{field} must be managed through the Catalog editor")
        else:
            values[field] = row[field]
    return values


async def _category(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    name: str,
) -> CommerceCategory:
    normalized = " ".join(name.casefold().split()) or "uncategorized"
    existing = await session.scalar(
        select(CommerceCategory).where(
            CommerceCategory.project_id == project_id,
            CommerceCategory.normalized_name == normalized,
        )
    )
    if existing is not None:
        return existing
    value = "Uncategorized" if normalized == "uncategorized" else name.strip()
    category = CommerceCategory(
        workspace_id=workspace_id,
        project_id=project_id,
        name=value,
        normalized_name=normalized,
        role="unknown",
    )
    session.add(category)
    await session.flush()
    return category


async def _merge_categories(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product_id: uuid.UUID,
    names: list[str],
    source_observation_id: uuid.UUID,
) -> None:
    for name in names:
        category = await _category(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
        )
        exists = await session.scalar(
            select(CommerceProductCategory.id).where(
                CommerceProductCategory.product_id == product_id,
                CommerceProductCategory.category_id == category.id,
            )
        )
        if exists is None:
            session.add(
                CommerceProductCategory(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    product_id=product_id,
                    category_id=category.id,
                    source_observation_id=source_observation_id,
                )
            )


async def import_catalog(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CatalogImportRequest,
) -> CatalogImportResponse:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    if len(payload.content.encode("utf-8")) > COMMERCE_IMPORT_MAX_BYTES:
        raise CommerceImportError(
            f"CSV exceeds the {COMMERCE_IMPORT_MAX_BYTES} byte limit"
        )
    reader = _csv_reader(payload.content)
    rows = list(reader)
    if len(rows) > COMMERCE_IMPORT_MAX_ROWS:
        raise CommerceImportError(
            f"CSV exceeds the {COMMERCE_IMPORT_MAX_ROWS} row limit"
        )
    content_hash = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    prior = await session.scalar(
        select(CommerceCsvImport).where(
            CommerceCsvImport.project_id == project_id,
            CommerceCsvImport.content_hash == content_hash,
        )
    )
    if prior is not None:
        return _import_response(prior)
    artifact = CommerceCsvImport(
        workspace_id=workspace_id,
        project_id=project_id,
        content_hash=content_hash,
        filename=payload.filename,
        content_type=payload.content_type,
        raw_payload=payload.content,
    )
    session.add(artifact)
    await session.flush()
    outcomes: list[CatalogRowOutcome] = []
    for row_number, raw in enumerate(rows, start=2):
        try:
            async with session.begin_nested():
                outcome = await _import_row(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    import_id=artifact.id,
                    row_number=row_number,
                    row=_clean_row(raw),
                )
        except (ValueError, CommerceConflictError) as exc:
            outcome = CatalogRowOutcome(
                row_number=row_number,
                status="rejected",
                error_code="identity_conflict"
                if isinstance(exc, CommerceConflictError)
                else "invalid_row",
                detail=str(exc)[:500],
            )
        outcomes.append(outcome)
    counts = {key: 0 for key in ("created", "updated", "unchanged", "rejected")}
    for outcome in outcomes:
        counts[outcome.status] += 1
    artifact.row_outcomes = [row.model_dump(mode="json") for row in outcomes]
    artifact.created_count = counts["created"]
    artifact.updated_count = counts["updated"]
    artifact.unchanged_count = counts["unchanged"]
    artifact.rejected_count = counts["rejected"]
    await session.commit()
    return CatalogImportResponse(
        import_id=artifact.id,
        **counts,
        row_outcomes=outcomes[:COMMERCE_IMPORT_ERROR_LIMIT],
    )


async def _import_row(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    import_id: uuid.UUID,
    row_number: int,
    row: dict[str, str],
) -> CatalogRowOutcome:
    values = _csv_values(row)
    product, created = await _resolve_import_product(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        values=values,
    )
    changed = _apply_import_values(
        product, values=values, import_id=import_id, row_number=row_number
    )
    observation = _csv_observation(
        workspace_id=workspace_id,
        project_id=project_id,
        product=product,
        import_id=import_id,
        row_number=row_number,
        values=values,
    )
    session.add(observation)
    await session.flush()
    names = _category_names(row)
    if names:
        await _merge_categories(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            product_id=product.id,
            names=names,
            source_observation_id=observation.id,
        )
    status = "created" if created else "updated" if changed else "unchanged"
    return CatalogRowOutcome(
        row_number=row_number, status=status, product_id=product.id
    )


async def _resolve_import_product(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    values: dict[str, Any],
) -> tuple[CommerceProduct, bool]:
    canonical_url = str(values.get("canonical_url") or "")
    product = await _identity_matches(
        session,
        project_id=project_id,
        canonical_url=canonical_url,
        gtin=str(values.get("gtin") or ""),
        sku=str(values.get("sku") or ""),
    )
    if product is not None:
        return product, False
    if not canonical_url:
        raise ValueError("canonical_url is required for a new product")
    product = CommerceProduct(
        workspace_id=workspace_id,
        project_id=project_id,
        canonical_url=canonical_url,
    )
    session.add(product)
    await session.flush()
    return product, True


def _apply_import_values(
    product: CommerceProduct,
    *,
    values: dict[str, Any],
    import_id: uuid.UUID,
    row_number: int,
) -> bool:
    changed = False
    sources = dict(product.field_sources or {})
    for field, value in values.items():
        if getattr(product, field) != value:
            setattr(product, field, value)
            changed = True
        sources[field] = {
            "kind": "csv",
            "source_id": str(import_id),
            "row_number": row_number,
            "version": COMMERCE_IMPORTER_VERSION,
        }
    product.field_sources = sources
    return changed


def _csv_observation(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product: CommerceProduct,
    import_id: uuid.UUID,
    row_number: int,
    values: dict[str, Any],
) -> CommerceProductObservation:
    observed = dict(values)
    if isinstance(observed.get("price"), Decimal):
        observed["price"] = float(observed["price"])
    return CommerceProductObservation(
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product.id,
        source_kind="csv",
        csv_import_id=import_id,
        csv_row_number=row_number,
        observed_fields=observed,
        importer_version=COMMERCE_IMPORTER_VERSION,
    )


def _category_names(row: dict[str, str]) -> list[str]:
    raw = row.get("categories") or row.get("category") or ""
    return [name.strip() for name in raw.replace("|", ";").split(";") if name.strip()]


def _import_response(row: CommerceCsvImport) -> CatalogImportResponse:
    return CatalogImportResponse(
        import_id=row.id,
        created=row.created_count,
        updated=row.updated_count,
        unchanged=row.unchanged_count,
        rejected=row.rejected_count,
        row_outcomes=[
            CatalogRowOutcome.model_validate(item) for item in (row.row_outcomes or [])
        ][:COMMERCE_IMPORT_ERROR_LIMIT],
    )


async def edit_product(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: CatalogEditRequest,
) -> ProductResponse:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    product = await session.scalar(
        select(CommerceProduct).where(
            CommerceProduct.id == product_id,
            CommerceProduct.project_id == project_id,
            CommerceProduct.workspace_id == workspace_id,
        )
    )
    if product is None:
        raise CommerceNotFoundError("Product not found")
    supplied = payload.model_fields_set
    if "canonical_url" in supplied and payload.canonical_url:
        normalized_url = canonical_identity(payload.canonical_url)[0]
        duplicate = await session.scalar(
            select(CommerceProduct.id).where(
                CommerceProduct.project_id == project_id,
                CommerceProduct.canonical_url == normalized_url,
                CommerceProduct.id != product.id,
            )
        )
        if duplicate is not None:
            raise CommerceConflictError("canonical_url belongs to another product")
    observed = _apply_edit_values(product, payload=payload, supplied=supplied)
    observation = CommerceProductObservation(
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product.id,
        source_kind="edit",
        observed_fields=observed,
        edit_version=COMMERCE_EDIT_VERSION,
    )
    session.add(observation)
    await session.flush()
    sources = dict(product.field_sources or {})
    for field in observed:
        sources[field] = {
            "kind": "edit",
            "source_id": str(observation.id),
            "version": COMMERCE_EDIT_VERSION,
        }
    product.field_sources = sources
    if "category_ids" in supplied:
        await _replace_product_categories(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            product=product,
            category_ids=payload.category_ids or [],
            observation_id=observation.id,
        )
    await session.commit()
    category_ids = list(
        await session.scalars(
            select(CommerceProductCategory.category_id).where(
                CommerceProductCategory.product_id == product.id
            )
        )
    )
    return _product_response(product, category_ids)


def _apply_edit_values(
    product: CommerceProduct,
    *,
    payload: CatalogEditRequest,
    supplied: set[str],
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    cleared_values: dict[str, Any] = {
        "price": None,
        "sku": None,
        "gtin": None,
        "mpn": None,
        "variants": [],
        "attributes": {},
    }
    for field in supplied & (set(_FIELDS) | {"lifecycle_state"}):
        value = getattr(payload, field)
        if field == "canonical_url":
            if not value:
                raise CommerceConflictError("canonical_url cannot be cleared")
            value = canonical_identity(value)[0]
        if field == "lifecycle_state" and value is None:
            raise CommerceConflictError("lifecycle_state cannot be cleared")
        applied = value if value is not None else cleared_values.get(field, "")
        setattr(product, field, applied)
        observed[field] = applied
    return observed


async def _replace_product_categories(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product: CommerceProduct,
    category_ids: list[uuid.UUID],
    observation_id: uuid.UUID,
) -> None:
    await session.execute(
        delete(CommerceProductCategory).where(
            CommerceProductCategory.product_id == product.id
        )
    )
    for category_id in category_ids:
        valid = await session.scalar(
            select(CommerceCategory.id).where(
                CommerceCategory.id == category_id,
                CommerceCategory.project_id == project_id,
                CommerceCategory.workspace_id == workspace_id,
            )
        )
        if valid is None:
            raise CommerceNotFoundError("Category not found")
        session.add(
            CommerceProductCategory(
                workspace_id=workspace_id,
                project_id=project_id,
                product_id=product.id,
                category_id=category_id,
                source_observation_id=observation_id,
            )
        )


async def enqueue_catalog_projection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source_analysis_id: uuid.UUID,
) -> None:
    if not await project_sells_catalog(
        session, workspace_id=workspace_id, project_id=project_id
    ):
        return
    key = f"commerce:project:{source_analysis_id}:{COMMERCE_PROJECTOR_VERSION}"
    await session.execute(
        insert(AnalyticsTask)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            task_kind="commerce_catalog_projection",
            payload={"source_analysis_id": str(source_analysis_id)},
            idempotency_key=key,
            status=TASK_STATUS_QUEUED,
        )
        .on_conflict_do_nothing(index_elements=[AnalyticsTask.idempotency_key])
    )
