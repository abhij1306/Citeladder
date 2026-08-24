# Product-catalog service (workspace-scoped through the project, invariant 5).
#
# A product belongs to a project, which is workspace-scoped, so every query
# joins through ``Project`` and filters by ``workspace_id`` — mirroring
# ``domain/prompts/service.py``. Owns manual CRUD and insert-only CSV import
# for the uploaded product catalog.
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.products import (
    PRODUCT_IMPORT_MAX_ROWS,
    PRODUCT_ORIGIN_IMPORTED,
    PRODUCT_ORIGIN_MANUAL,
)
from app.domain.products.schemas import (
    ProductImportRowError,
    ProductImportSummary,
    ProductInput,
)
from app.models.audit import Audit
from app.models.product import Product
from app.models.project import Project


class ProductNotFoundError(LookupError):
    """Raised when a product (or its parent project) is missing or not in the
    caller's workspace."""


class DuplicateProductError(ValueError):
    """Raised when ``(project_id, sku)`` collides."""


class ProductImportError(ValueError):
    """Raised when an import payload violates the config caps."""


async def _project_in_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    result = await session.execute(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ProductNotFoundError("Project not found")
    return project


# --------------------------------------------------------------------------
# Own catalog (Product)
# --------------------------------------------------------------------------
async def list_products(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[Product]:
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )
    result = await session.execute(
        select(Product)
        .where(Product.project_id == project_id)
        .order_by(Product.created_at.asc())
    )
    return list(result.scalars().all())


async def get_product(
    session: AsyncSession, *, workspace_id: uuid.UUID, product_id: uuid.UUID
) -> Product:
    result = await session.execute(
        select(Product)
        .join(Project, Project.id == Product.project_id)
        .where(
            Product.id == product_id,
            Project.workspace_id == workspace_id,
        )
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise ProductNotFoundError("Product not found")
    return product


def _apply_product_fields(product: Product, data: dict[str, Any]) -> None:
    for field in ("sku", "name", "url", "currency"):
        # Non-nullable columns: apply only when a value is actually provided.
        if data.get(field) is not None:
            setattr(product, field, str(data[field]).strip())
    for field in ("aliases", "variants", "attributes"):
        if data.get(field) is not None:
            setattr(product, field, data[field])
    # ``price`` is the one nullable field: an explicit JSON null clears it.
    if "price" in data:
        product.price = data["price"]


async def create_product(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: Any,
) -> Product:
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )
    product = Product(project_id=project_id, origin=PRODUCT_ORIGIN_MANUAL)
    _apply_product_fields(product, payload.model_dump(exclude_unset=True))
    session.add(product)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateProductError(
            "A product with this SKU already exists in this project"
        ) from exc
    await session.refresh(product)
    return product


async def update_product(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: Any,
) -> Product:
    product = await get_product(
        session, workspace_id=workspace_id, product_id=product_id
    )
    _apply_product_fields(product, payload.model_dump(exclude_unset=True))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateProductError(
            "A product with this SKU already exists in this project"
        ) from exc
    await session.refresh(product)
    return product


async def delete_product(
    session: AsyncSession, *, workspace_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    product = await get_product(
        session, workspace_id=workspace_id, product_id=product_id
    )
    await session.delete(product)
    await session.commit()


@dataclass(frozen=True)
class ProductImportResult:
    """The import outcome (D1): the refreshed catalog + the per-row summary."""

    catalog: list[Product]
    summary: ProductImportSummary


def _prepare_import_rows(
    *,
    project_id: uuid.UUID,
    rows: list[tuple[int, ProductInput]],
    errors: list[ProductImportRowError],
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    values: list[dict[str, Any]] = []
    candidates: list[tuple[int, str]] = []
    seen_skus: set[str] = set()
    for row_number, row in rows:
        value, candidate, error = _prepare_import_row(
            project_id=project_id,
            row_number=row_number,
            row=row,
            seen_skus=seen_skus,
        )
        if error is not None:
            errors.append(error)
            continue
        assert value is not None and candidate is not None
        candidates.append(candidate)
        values.append(value)
    return values, candidates


def _prepare_import_row(
    *,
    project_id: uuid.UUID,
    row_number: int,
    row: ProductInput,
    seen_skus: set[str],
) -> tuple[
    dict[str, Any] | None,
    tuple[int, str] | None,
    ProductImportRowError | None,
]:
    sku = str(row.sku or "").strip()
    if not sku:
        return (
            None,
            None,
            ProductImportRowError(
                row=row_number,
                field="sku",
                message="Missing sku — the row was skipped "
                "(sku is the import identity)",
            ),
        )
    if sku in seen_skus:
        return (
            None,
            None,
            ProductImportRowError(
                row=row_number,
                field="sku",
                message=f"Duplicate sku '{sku}' in this import — "
                "the first occurrence was kept",
            ),
        )
    seen_skus.add(sku)
    return (
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "sku": sku,
            "name": str(row.name or "").strip() or sku,
            "aliases": list(row.aliases or []),
            "variants": [v.model_dump() for v in (row.variants or [])],
            "price": row.price,
            "currency": str(row.currency or "").strip().upper(),
            "url": str(row.url or "").strip(),
            "attributes": dict(row.attributes or {}),
            "origin": PRODUCT_ORIGIN_IMPORTED,
        },
        (row_number, sku),
        None,
    )


def _record_import_conflicts(
    *,
    candidates: list[tuple[int, str]],
    inserted_skus: set[str],
    errors: list[ProductImportRowError],
) -> int:
    created = 0
    for row_number, sku in candidates:
        if sku in inserted_skus:
            created += 1
            continue
        errors.append(
            ProductImportRowError(
                row=row_number,
                field="sku",
                message=f"A product with sku '{sku}' already exists — "
                "it was left unchanged",
            )
        )
    return created


async def import_products(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    rows: list[tuple[int, ProductInput]],
    row_errors: Iterable[ProductImportRowError] = (),
) -> ProductImportResult:
    """CSV bulk-create: persist already-parsed product rows as ``imported``.

    ``rows`` pairs each parsed row with its 1-based source-row number so the
    summary can name it; ``row_errors`` carries the parse-stage skips (empty
    sku / field validation) to fold into the same summary. Rows are NEVER a
    request failure: an empty sku is skipped, a repeat within the upload is
    dropped keeping the FIRST occurrence (``ON CONFLICT DO NOTHING`` cannot
    resolve two conflicting rows in the SAME statement), and a clash with an
    existing product is skipped — ``RETURNING`` reports exactly which skus
    were inserted, so ``created`` is exact even under a concurrent import.
    Returns the full refreshed catalog plus the summary (D1).
    """
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if len(rows) > PRODUCT_IMPORT_MAX_ROWS:
        raise ProductImportError(
            f"Import accepts at most {PRODUCT_IMPORT_MAX_ROWS} rows"
        )
    errors = list(row_errors)
    # One multi-VALUES INSERT rather than a statement per row: the cap is 500
    # rows, so a per-row execute costs up to 500 round-trips per import.
    values, candidates = _prepare_import_rows(
        project_id=project_id, rows=rows, errors=errors
    )
    inserted_skus: set[str] = set()
    if values:
        result = await session.execute(
            pg_insert(Product)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_product_project_sku")
            .returning(Product.sku)
        )
        inserted_skus = set(result.scalars().all())
    created = _record_import_conflicts(
        candidates=candidates, inserted_skus=inserted_skus, errors=errors
    )
    await session.commit()
    catalog = await list_products(
        session, workspace_id=workspace_id, project_id=project_id
    )
    errors.sort(key=lambda error: error.row)
    return ProductImportResult(
        catalog=catalog,
        summary=ProductImportSummary(
            created=created,
            updated=0,  # v1 imports are insert-only (reserved, see schema).
            skipped=len(errors),
            errors=errors,
        ),
    )


async def count_product_audit_references(
    session: AsyncSession, *, workspace_id: uuid.UUID, product_id: uuid.UUID
) -> int:
    """Count the project's audits whose FROZEN configuration references this
    product (D4 delete guard — read-only; the freeze itself already
    guarantees audit integrity, invariant 9)."""
    product = await get_product(
        session, workspace_id=workspace_id, product_id=product_id
    )
    count = await session.scalar(
        select(func.count(Audit.id)).where(
            Audit.project_id == product.project_id,
            Audit.workspace_id == workspace_id,
            # JSONB containment: any frozen ``products`` element carrying this
            # id (extra element keys are ignored by ``@>``).
            Audit.configuration.contains({"products": [{"id": str(product.id)}]}),
        )
    )
    return int(count or 0)
