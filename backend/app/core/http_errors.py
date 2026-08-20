# Shared HTTP error helpers for the API layer.
#
# One place to raise the API's errors so the detail strings, the status ->
# code mapping, and the unified envelope stay consistent across 17 routers.
# Everything here raises an ``ApiException`` (an ``HTTPException`` subclass),
# so the response carries the canonical ``error`` block (WS-A A1) while any
# ``except HTTPException`` handling keeps working unchanged.
#
# Routers do NOT raise raw ``HTTPException``. The registered shim still exists
# for Starlette's own routing errors (unknown path 404, method 405), which the
# application never raises itself.
from __future__ import annotations

from typing import Any, NoReturn

from fastapi import status

from app.core.config.errors import (
    CODE_HTTP_ERROR,
    CODE_NOT_FOUND,
    STATUS_DEFAULT_CODE,
)
from app.core.errors import ApiException


def raise_not_found(resource: str, *, cause: BaseException | None = None) -> NoReturn:
    """Raise a 404 ``ApiException`` whose detail is ``"{resource} not found"``.

    ``cause`` preserves explicit exception chaining (``raise ... from exc``) for
    the handlers that translate a domain "not found" into the HTTP response.
    """
    exc = ApiException(
        status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, f"{resource} not found"
    )
    if cause is not None:
        raise exc from cause
    raise exc


def api_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: dict[str, Any] | None = None,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> ApiException:
    """Build an ``ApiException`` for a plain (uncoded) API failure.

    ``code`` defaults to the status's canonical code (``STATUS_DEFAULT_CODE``,
    invariant 1) — the same code the legacy shim derived — so a router that
    has no domain-specific code does not have to invent one. ``detail``
    overrides the legacy ``detail`` payload for the handful of endpoints whose
    clients read a dict body that is not the ``{"code", "message"}`` dialect.

    Returned rather than raised for the router-local ``_not_found(exc)`` /
    ``_unprocessable(exc)`` factories that are used as ``raise f(exc) from exc``.
    """
    return ApiException(
        status_code,
        code or STATUS_DEFAULT_CODE.get(status_code, CODE_HTTP_ERROR),
        message,
        details=details,
        detail=detail,
        headers=headers,
    )


def raise_api_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: dict[str, Any] | None = None,
    detail: Any = None,
    headers: dict[str, str] | None = None,
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise :func:`api_error`, chaining ``cause`` when one is supplied."""
    exc = api_error(
        status_code,
        message,
        code=code,
        details=details,
        detail=detail,
        headers=headers,
    )
    if cause is not None:
        raise exc from cause
    raise exc


def coded_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> ApiException:
    """Build a domain-coded ``ApiException`` (``detail`` keeps its dict shape).

    For the endpoints whose contract is the coded dialect
    (``{"code", "message", **details}``) rather than a human string.
    """
    return ApiException.coded(
        status_code, code, message, details=details, headers=headers
    )


def raise_coded_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise :func:`coded_error`, chaining ``cause`` when one is supplied."""
    exc = coded_error(status_code, code, message, details=details, headers=headers)
    if cause is not None:
        raise exc from cause
    raise exc
