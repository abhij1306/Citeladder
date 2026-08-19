# Unified API error envelope (plan WS-A A1).
#
# ONE canonical payload for every non-2xx API response:
#
#   {
#     "detail": <human string | legacy coded dict>,
#     "error": {
#       "code": <stable snake_case>,
#       "message": <human string>,
#       "request_id": <correlation id>,
#       "retryable": <bool>,
#       "details": <optional object>
#     }
#   }
#
# ``detail`` is retained verbatim (the same string or coded dict the endpoint
# has always returned) so existing clients/tests that read FastAPI's
# ``detail`` keep working during the transition; ``error`` is the additive
# canonical block. Migrated routers raise ``ApiException``; legacy raw
# ``HTTPException`` raises are normalized by the compatibility shim
# (``http_exception_shim_handler``) so migrated and unmigrated routers speak
# one contract while the sweep proceeds.
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.config.errors import (
    CODE_HTTP_ERROR,
    CODE_INTERNAL_ERROR,
    CODE_VALIDATION_ERROR,
    STATUS_DEFAULT_CODE,
    is_retryable_status,
)
from app.core.telemetry import get_correlation_id

logger = logging.getLogger("app.core.errors")

# First ``loc`` segments FastAPI prepends to validation-error locations. They
# are transport noise in a human-facing field path, so sanitized errors drop
# them ("body.products.0.sku" -> "products.0.sku").
_LOCATION_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})

_INTERNAL_ERROR_MESSAGE = "An unexpected error occurred"
_VALIDATION_ERROR_MESSAGE = "Request validation failed"
_INVALID_VALUE_MESSAGE = "Invalid value"

__all__ = [
    "ApiException",
    "api_exception_handler",
    "error_envelope",
    "http_exception_shim_handler",
    "request_id_for",
    "request_validation_error_handler",
    "sanitize_validation_errors",
    "unhandled_exception_handler",
    "validation_error_summary",
]


class ApiException(HTTPException):
    """An HTTP error carrying the canonical ``error`` block fields.

    Subclasses ``HTTPException`` so legacy ``except HTTPException`` handling
    and FastAPI's status/headers semantics keep working unchanged; the
    registered ``api_exception_handler`` renders the unified envelope.

    ``detail`` stays the legacy payload: the plain ``message`` string by
    default, or an explicit legacy shape via ``detail=`` /
    :meth:`coded` for the coded-error dialect (``{"code", "message", ...}``)
    the migrated routers already returned.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail if detail is not None else message,
            headers=headers,
        )
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details

    @classmethod
    def coded(
        cls,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> ApiException:
        """Coded-error dialect: ``detail`` keeps its exact legacy dict shape.

        The legacy dict is ``{"code", "message", **details}`` — byte-identical
        to what the coded selection/opportunity/crawl errors have always
        returned, while ``error.details`` carries the same extras in the
        canonical block.
        """
        legacy = {"code": code, "message": message, **(details or {})}
        return cls(
            status_code,
            code,
            message,
            retryable=retryable,
            details=details,
            detail=legacy,
        )

    def is_retryable(self) -> bool:
        """Explicit ``retryable`` wins; otherwise classify by status."""
        if self.retryable is not None:
            return self.retryable
        return is_retryable_status(self.status_code)


def request_id_for(request: Request) -> str:
    """The correlation id minted by the correlation middleware.

    Reads ``request.state`` first: the contextvar is already reset by the time
    the unhandled-exception path runs (the middleware unwound), while the
    request state survives.
    """
    state_id = getattr(request.state, "correlation_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    return get_correlation_id() or ""


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """Build the canonical payload; ``detail`` falls back to ``message``."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": retryable,
    }
    if details is not None:
        error["details"] = details
    return {"detail": detail if detail is not None else message, "error": error}


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _json_safe(value: Any) -> Any:
    """JSON-encodable projection of a raiser-supplied value, preserving None.

    ``ApiException.details``/``detail`` are arbitrary caller data and may hold
    values ``json.dumps`` cannot serialize (UUIDs, datetimes, Decimals, Enums,
    Pydantic models) — which would raise a 500 from inside the error handler
    itself. ``None`` passes through untouched so ``error_envelope``'s
    absent-details / detail-falls-back-to-message behavior is unchanged.
    """
    return None if value is None else jsonable_encoder(value)


def _legacy_detail_parts(
    exc: HTTPException,
) -> tuple[str | None, str | None, dict[str, Any] | None, Any]:
    detail: Any = exc.detail
    if isinstance(detail, str) and not detail:
        detail = None
    if isinstance(detail, dict):
        code, message = _legacy_code_message(detail)
        extras = _legacy_extras(detail)
        return code or None, message or None, extras or None, detail
    return None, detail if isinstance(detail, str) and detail else None, None, detail


def _legacy_code_message(detail: dict[str, Any]) -> tuple[str | None, str | None]:
    code = detail.get("code") if isinstance(detail.get("code"), str) else None
    message = detail.get("message") if isinstance(detail.get("message"), str) else None
    return code, message


def _legacy_extras(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in detail.items() if key not in ("code", "message")
    }


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    """Render an :class:`ApiException` as the unified envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=exc.code,
            message=exc.message,
            request_id=request_id_for(request),
            retryable=exc.is_retryable(),
            details=_json_safe(exc.details),
            detail=_json_safe(exc.detail),
        ),
        headers=exc.headers,
    )


def _parse_legacy_detail(
    exc: HTTPException,
) -> tuple[str | None, str, dict[str, Any] | None, str | dict[str, Any]]:
    """Split a legacy ``HTTPException.detail`` into envelope parts.

    Extracted from ``http_exception_shim_handler`` so the handler reads as
    "parse, then build the response": all the shape-sniffing a legacy detail
    needs (string / coded dict / absent) lives here, and the handler stays at
    one job. Returns ``(code, message, details, detail)`` where ``message`` is
    always resolved and ``detail`` is always JSON-safe.
    """
    code, message, details, detail = _legacy_detail_parts(exc)
    if message is None:
        message = _status_phrase(exc.status_code)
    if not isinstance(detail, (str, dict)):
        # A missing/non-text legacy detail (e.g. None) becomes the human
        # message so ``detail`` is always present and JSON-safe.
        detail = message
    return code, message, details, detail


async def http_exception_shim_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Compatibility shim: a legacy raw ``HTTPException`` -> the same envelope.

    A string detail maps to the status-derived default code. A coded dict
    detail (``{"code", "message", ...}``) keeps its code verbatim and lifts
    any extra keys into ``error.details``; the legacy detail itself (string or
    dict) is echoed in ``detail`` unchanged so existing readers keep working.
    Also covers Starlette's own routing errors (unknown path 404, 405).
    """
    code, message, details, detail = _parse_legacy_detail(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=code or STATUS_DEFAULT_CODE.get(exc.status_code, CODE_HTTP_ERROR),
            message=message,
            request_id=request_id_for(request),
            retryable=is_retryable_status(exc.status_code),
            details=details,
            detail=detail,
        ),
        headers=getattr(exc, "headers", None),
    )


def _error_loc_path(entry: Mapping[str, Any]) -> str:
    """Dotted field path from an error entry's ``loc`` (parts stringified).

    Sequence indices arrive as ints (``("variants", 0, "name")``), so joining
    without ``str()`` raises ``TypeError`` from inside an error path.
    """
    return ".".join(str(part) for part in entry.get("loc", ()))


def _error_message_text(entry: Mapping[str, Any]) -> str:
    """Human message from a SANITIZED entry (``message``) or a RAW Pydantic
    one (``msg``), falling back when neither is usable."""
    text = entry.get("message") or entry.get("msg")
    return str(text) if text else _INVALID_VALUE_MESSAGE


def sanitize_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map raw Pydantic error dicts to sanitized field-level entries (COM-5).

    Typed against the shapes the callers actually hold — Pydantic's
    ``list[ErrorDetails]`` (a TypedDict, so not a ``dict[str, Any]``) and
    FastAPI's ``Sequence[Any]`` — rather than forcing each call site to cast.
    Only ``.get()`` is used on each entry, so ``Mapping`` is the honest
    requirement.

    Strips everything that leaks internals — ``ctx`` (raw constraint values),
    ``input`` (echoed payloads, possibly secrets), and the
    ``errors.pydantic.dev`` URL — keeping the field location, Pydantic's human
    message, and the stable machine ``type``. The leading transport prefix
    (``body``/``query``/...) is dropped from the location.
    """
    sanitized: list[dict[str, Any]] = []
    for err in errors:
        loc = [str(part) for part in err.get("loc", ())]
        if loc and loc[0] in _LOCATION_PREFIXES:
            loc = loc[1:]
        entry: dict[str, Any] = {
            "loc": loc,
            "message": _error_message_text(err),
        }
        err_type = err.get("type")
        if isinstance(err_type, str) and err_type:
            entry["type"] = err_type
        sanitized.append(entry)
    return sanitized


def validation_error_summary(errors: Sequence[Mapping[str, Any]]) -> str:
    """One-line human summary (the first field error) for ``detail``/``message``.

    Reads tolerantly: the intended input is ``sanitize_validation_errors``
    output (``loc``/``message`` always present), but a raw Pydantic entry uses
    ``msg`` and may carry non-string ``loc`` parts, so both are accepted rather
    than raising ``KeyError``/``TypeError`` from inside an error path.
    """
    if not errors:
        return _VALIDATION_ERROR_MESSAGE
    first = errors[0]
    loc = _error_loc_path(first)
    message = _error_message_text(first)
    return f"{loc}: {message}" if loc else message


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Normalize request validation failures into the envelope (HTTP 422).

    Field-level errors land in ``error.details.errors`` sanitized — never the
    raw Pydantic serialization (model names, ``ctx`` internals, echoed input,
    ``errors.pydantic.dev`` URLs).
    """
    errors = sanitize_validation_errors(exc.errors())
    message = validation_error_summary(errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_envelope(
            code=CODE_VALIDATION_ERROR,
            message=message,
            request_id=request_id_for(request),
            retryable=False,
            details={"errors": errors},
            detail=message,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort 500: full detail to the log, nothing internal to the client.

    Logs the exception with the correlation id (the structlog pipeline
    enriches every record with it) and returns ``code: internal_error`` with
    no stack trace or internals in the body.
    """
    request_id = request_id_for(request)
    logger.exception(
        "unhandled_api_exception",
        # ``request_id`` is logged EXPLICITLY rather than left to the structlog
        # pipeline: that enrichment reads the correlation contextvar, which
        # ``request_id_for`` notes may already be unwound on this path. Without
        # it the id handed to the user could appear nowhere in the logs — the
        # one path where correlation matters most.
        extra={
            "method": request.method,
            "path": request.url.path,
            "request_id": request_id,
        },
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_envelope(
            code=CODE_INTERNAL_ERROR,
            message=_INTERNAL_ERROR_MESSAGE,
            request_id=request_id,
            retryable=is_retryable_status(status.HTTP_500_INTERNAL_SERVER_ERROR),
        ),
    )
    if request_id:
        # The correlation middleware already unwound on this path, so echo the
        # request-id header here for support correlation.
        response.headers[settings.request_id_header] = request_id
    return response
