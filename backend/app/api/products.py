# Products router: catalog CRUD, CSV import, and Commerce projections.
#
# Workspace-scoped through the parent project (invariant 5); the active
# workspace is resolved by ``require_active_workspace`` (flat surface —
# mirrors ``api/prompts.py``). The surface:
#   - GET/POST /projects/{project_id}/products
#   - GET/PATCH/DELETE /products/{product_id}
#   - POST /projects/{project_id}/products/import -> CSV/JSON bulk-create
#   - (Task 4) product visibility projections + CSV export
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.api.request_bodies import read_limited_body, read_limited_upload
from app.api.usage_limits import enforce_workspace_request
from app.core.config.abuse import abuse_settings
from app.core.config.errors import (
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    CODE_VALIDATION_ERROR,
)
from app.core.config.products import (
    PRODUCT_EVIDENCE_DEFAULT_LIMIT,
    PRODUCT_EVIDENCE_MAX_LIMIT,
)
from app.core.errors import (
    ApiException,
    sanitize_validation_errors,
    validation_error_summary,
)
from app.core.http_errors import raise_not_found
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.products.csv_import import ProductCsvError, parse_product_csv
from app.domain.products.schemas import (
    ProductAuditReferences,
    ProductEvidenceResponse,
    ProductImport,
    ProductImportResponse,
    ProductImportRowError,
    ProductInput,
    ProductResponse,
    ProductUpdate,
    ProductVisibilityResponse,
    ProductVisibilityTrendResponse,
    product_to_response,
)
from app.domain.products.service import (
    DuplicateProductError,
    ProductImportError,
    ProductNotFoundError,
    count_product_audit_references,
    create_product,
    delete_product,
    get_product,
    import_products,
    list_products,
    update_product,
)
from app.domain.products.visibility import (
    get_product_visibility,
    get_product_visibility_trend,
)
from app.domain.products.visibility_evidence import get_product_evidence
from app.domain.products.visibility_export import (
    load_product_visibility_export_bundle,
    product_visibility_csv,
)

router = APIRouter(tags=["products"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]

_RES_PROJECT = "Project"
_RES_PRODUCT = "Product"


def _not_found(detail: str) -> ApiException:
    return ApiException(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, detail)


def _conflict(detail: str) -> ApiException:
    return ApiException(status.HTTP_409_CONFLICT, CODE_CONFLICT, detail)


def _unprocessable(detail: str) -> ApiException:
    return ApiException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, CODE_VALIDATION_ERROR, detail
    )


# --------------------------------------------------------------------------
# Own catalog
# --------------------------------------------------------------------------
@router.get("/projects/{project_id}/products", response_model=list[ProductResponse])
async def list_products_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[ProductResponse]:
    try:
        products = await list_products(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    return [product_to_response(p) for p in products]


@router.post(
    "/projects/{project_id}/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_endpoint(
    project_id: uuid.UUID,
    payload: ProductInput,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ProductResponse:
    try:
        product = await create_product(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            payload=payload,
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    except DuplicateProductError as exc:
        raise _conflict(str(exc)) from exc
    return product_to_response(product)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product_endpoint(
    product_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ProductResponse:
    try:
        product = await get_product(
            session, workspace_id=ctx.workspace_id, product_id=product_id
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PRODUCT, cause=exc)
    return product_to_response(product)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product_endpoint(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ProductResponse:
    try:
        product = await update_product(
            session,
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            payload=payload,
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PRODUCT, cause=exc)
    except DuplicateProductError as exc:
        raise _conflict(str(exc)) from exc
    return product_to_response(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_endpoint(
    product_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> None:
    try:
        await delete_product(
            session, workspace_id=ctx.workspace_id, product_id=product_id
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PRODUCT, cause=exc)


@router.get(
    "/products/{product_id}/audit-references",
    response_model=ProductAuditReferences,
)
async def product_audit_references_endpoint(
    product_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ProductAuditReferences:
    """Read-only delete guard (D4): how many audit configurations froze this
    product. Deleting stays allowed — past runs keep their frozen copy."""
    try:
        count = await count_product_audit_references(
            session, workspace_id=ctx.workspace_id, product_id=product_id
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PRODUCT, cause=exc)
    return ProductAuditReferences(
        product_id=product_id, referenced=count > 0, audit_count=count
    )


# --------------------------------------------------------------------------
# CSV / JSON-rows bulk import (mirrors the prompts import flow)
# --------------------------------------------------------------------------
async def _resolve_import_rows(
    request: Request, file: UploadFile | None
) -> tuple[list[tuple[int, ProductInput]], list[ProductImportRowError]]:
    """Accept either a multipart CSV upload or a JSON body of parsed rows.

    Both converge to ``(numbered rows, row-level skip errors)`` for the
    service (D1): each row carries its 1-based source-row number so the
    import summary can name it. Malformed CSV (e.g. headerless) and
    schema-violating JSON are 422s, never 500s; CSV rows that fail field
    validation become row errors instead.
    """
    if file is not None:
        raw = _decode_csv(await read_limited_upload(file))
        parsed = parse_product_csv(raw)
        return parsed.rows, parsed.errors

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        # Malformed JSON / schema violations are client errors: surface them as
        # 422 like the CSV path, never as an unhandled 500.
        try:
            raw_body = await read_limited_body(request)
        except ValueError as exc:
            raise _unprocessable("Request body is not valid JSON") from exc
        try:
            products = ProductImport.model_validate_json(raw_body).products
        except ValidationError as exc:
            # COM-5: never serialize raw Pydantic text (the ``ProductImport``
            # model name, the errors.pydantic.dev URL, echoed input values)
            # into the response — sanitized field-level messages only.
            errors = sanitize_validation_errors(exc.errors())
            raise ApiException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_VALIDATION_ERROR,
                "Invalid product import payload: " + validation_error_summary(errors),
                details={"errors": errors},
            ) from exc
        return [(index + 1, row) for index, row in enumerate(products)], []

    # Raw CSV posted as text/csv (no multipart wrapper).
    csv_body = _decode_csv(await read_limited_body(request))
    parsed = parse_product_csv(csv_body)
    return parsed.rows, parsed.errors


def _decode_csv(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _unprocessable("CSV must be valid UTF-8") from exc


@router.post(
    "/projects/{project_id}/products/import",
    response_model=ProductImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_products_endpoint(
    project_id: uuid.UUID,
    request: Request,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    file: UploadFile | None = None,
) -> ProductImportResponse:
    """Bulk-import (D1): the refreshed catalog + a per-row outcome summary
    (created/skipped counts and the reason every skipped row was dropped)."""
    await enforce_workspace_request(
        session,
        workspace_id=ctx.workspace_id,
        operation="bulk_import",
        limit=abuse_settings.bulk_import_limit,
        window_seconds=abuse_settings.bulk_import_window_seconds,
    )
    try:
        rows, row_errors = await _resolve_import_rows(request, file)
    except ProductCsvError as exc:
        raise _unprocessable(str(exc)) from exc
    try:
        result = await import_products(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            rows=rows,
            row_errors=row_errors,
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    except ProductImportError as exc:
        raise _unprocessable(str(exc)) from exc
    return ProductImportResponse(
        items=[product_to_response(p) for p in result.catalog],
        summary=result.summary,
    )


# --------------------------------------------------------------------------
# Visibility projections (persisted rows only, invariant 7)
# --------------------------------------------------------------------------
@router.get(
    "/projects/{project_id}/products/visibility",
    response_model=ProductVisibilityResponse,
)
async def product_visibility_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
    engine: Annotated[str | None, Query()] = None,
) -> ProductVisibilityResponse:
    """Selected-audit product dashboard (defaults to the latest product audit)."""
    try:
        return await get_product_visibility(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
            engine=engine,
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Product visibility", cause=exc)
    except TrendQueryError as exc:
        raise _unprocessable(str(exc)) from exc


@router.get(
    "/projects/{project_id}/products/visibility/trends",
    response_model=ProductVisibilityTrendResponse,
)
async def product_visibility_trend_endpoint(
    project_id: uuid.UUID,
    product_id: Annotated[uuid.UUID, Query()],
    ctx: _WorkspaceDep,
    session: _SessionDep,
    engine: Annotated[str | None, Query()] = None,
) -> ProductVisibilityTrendResponse:
    """Three-point visibility history from persisted product snapshots."""
    try:
        return await get_product_visibility_trend(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            product_id=product_id,
            engine=engine,
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Product visibility", cause=exc)
    except TrendQueryError as exc:
        raise _unprocessable(str(exc)) from exc


@router.get(
    "/products/{product_id}/visibility/evidence",
    response_model=ProductEvidenceResponse,
)
async def product_evidence_endpoint(
    product_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
    engine: Annotated[str | None, Query()] = None,
    limit: Annotated[
        int, Query(ge=1, le=PRODUCT_EVIDENCE_MAX_LIMIT)
    ] = PRODUCT_EVIDENCE_DEFAULT_LIMIT,
) -> ProductEvidenceResponse:
    """Persisted mention evidence for one product (bounded, newest-first)."""
    try:
        return await get_product_evidence(
            session,
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            audit_id=audit_id,
            engine=engine,
            limit=limit,
        )
    except ProductNotFoundError as exc:
        raise_not_found(_RES_PRODUCT, cause=exc)
    except AnalysisNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    except TrendQueryError as exc:
        raise _unprocessable(str(exc)) from exc


@router.get("/projects/{project_id}/products/visibility/export.csv")
async def product_visibility_export_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    """Download the per-entry product visibility rows as CSV (persisted rows)."""
    try:
        audit, snapshots = await load_product_visibility_export_bundle(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Product visibility", cause=exc)
    except TrendQueryError as exc:
        raise _unprocessable(str(exc)) from exc
    body = product_visibility_csv(audit, snapshots)
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="product-visibility-{audit.id}.csv"'
            )
        },
    )
