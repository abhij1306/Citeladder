"""Unit tests for the unified API error envelope (WS-A A1).

Covers the canonical payload builder, ``ApiException`` (+ the coded legacy
dialect), the legacy ``HTTPException`` compatibility shim, the retryable
classification table, Pydantic validation sanitization (COM-5), and the two
global handlers (validation 422, unhandled 500) — all without a database.
"""

from __future__ import annotations

import json
import logging

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.config.errors import (
    CODE_HTTP_ERROR,
    CODE_INTERNAL_ERROR,
    CODE_METHOD_NOT_ALLOWED,
    CODE_NOT_FOUND,
    CODE_RATE_LIMITED,
    CODE_VALIDATION_ERROR,
    is_retryable_status,
)
from app.core.errors import (
    ApiException,
    api_exception_handler,
    error_envelope,
    http_exception_shim_handler,
    request_id_for,
    sanitize_validation_errors,
    unhandled_exception_handler,
    validation_error_summary,
)


def _request(correlation_id: str | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/probe",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    if correlation_id is not None:
        request.state.correlation_id = correlation_id
    return request


# =========================================================================
# error_envelope
# =========================================================================
def test_error_envelope_shape_and_detail_fallback() -> None:
    body = error_envelope(
        code="not_found", message="Project not found", request_id="abc", retryable=False
    )
    assert body["detail"] == "Project not found"
    assert body["error"] == {
        "code": "not_found",
        "message": "Project not found",
        "request_id": "abc",
        "retryable": False,
    }
    # details is omitted entirely when absent, present when given.
    assert "details" not in body["error"]
    with_details = error_envelope(
        code="x",
        message="m",
        request_id="",
        retryable=True,
        details={"limit": 10},
        detail={"code": "x", "message": "m", "limit": 10},
    )
    assert with_details["error"]["details"] == {"limit": 10}
    assert with_details["detail"] == {"code": "x", "message": "m", "limit": 10}


# =========================================================================
# ApiException
# =========================================================================
def test_api_exception_defaults_detail_to_message() -> None:
    exc = ApiException(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Product not found")
    assert exc.status_code == 404
    assert exc.detail == "Product not found"
    assert exc.code == CODE_NOT_FOUND
    assert exc.message == "Product not found"
    assert exc.details is None
    # It stays an HTTPException for legacy ``except HTTPException`` handling.
    assert isinstance(exc, HTTPException)


def test_api_exception_retryable_explicit_wins_over_status() -> None:
    assert (
        ApiException(500, CODE_INTERNAL_ERROR, "x").is_retryable() is True
    )  # 5xx classified retryable
    assert ApiException(422, CODE_VALIDATION_ERROR, "x").is_retryable() is False
    assert (
        ApiException(409, "conflict", "x", retryable=True).is_retryable() is True
    )  # explicit override


def test_api_exception_coded_preserves_legacy_dict_shape() -> None:
    exc = ApiException.coded(
        status.HTTP_409_CONFLICT,
        "stale_selection_version",
        "The monitored selection changed since it was loaded",
        details={"current_selection_version": 3},
    )
    # The legacy ``detail`` dict is byte-identical to the pre-envelope shape.
    assert exc.detail == {
        "code": "stale_selection_version",
        "message": "The monitored selection changed since it was loaded",
        "current_selection_version": 3,
    }
    assert exc.details == {"current_selection_version": 3}


async def test_api_exception_handler_renders_envelope() -> None:
    exc = ApiException.coded(
        status.HTTP_403_FORBIDDEN,
        "site_health_quota_exceeded",
        "quota exceeded",
        details={"limit": 50, "currently_used": 50},
    )
    response = await api_exception_handler(_request("req-1"), exc)
    assert response.status_code == 403
    expected = error_envelope(
        code="site_health_quota_exceeded",
        message="quota exceeded",
        request_id="req-1",
        retryable=False,
        details={"limit": 50, "currently_used": 50},
        detail={
            "code": "site_health_quota_exceeded",
            "message": "quota exceeded",
            "limit": 50,
            "currently_used": 50,
        },
    )
    assert json.loads(response.body) == expected


# =========================================================================
# Legacy HTTPException compatibility shim
# =========================================================================
async def test_shim_maps_string_detail_to_status_code() -> None:
    exc = HTTPException(status_code=404, detail="Workspace not found")
    response = await http_exception_shim_handler(_request("req-2"), exc)
    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["detail"] == "Workspace not found"
    assert body["error"]["code"] == CODE_NOT_FOUND
    assert body["error"]["message"] == "Workspace not found"
    assert body["error"]["request_id"] == "req-2"
    assert body["error"]["retryable"] is False
    assert "details" not in body["error"]


async def test_shim_classifies_retryable_statuses() -> None:
    exc = HTTPException(status_code=429, detail="slow down")
    body = json.loads((await http_exception_shim_handler(_request(), exc)).body)
    assert body["error"]["code"] == CODE_RATE_LIMITED
    assert body["error"]["retryable"] is True


async def test_shim_preserves_non_string_detail_payloads() -> None:
    for detail in ({"reason": "missing"}, ["first", "second"]):
        exc = HTTPException(status_code=422, detail=detail)
        body = json.loads((await http_exception_shim_handler(_request(), exc)).body)

        assert body["detail"] == detail
        assert body["error"]["message"] == "Unprocessable Entity"


async def test_shim_covers_the_frameworks_own_errors() -> None:
    """What still reaches the shim is Starlette's, not the application's.

    Every router raises an ``ApiException`` through ``core/http_errors.py``,
    so the coded-dialect parsing the shim used to carry (a ``{"code",
    "message", ...}`` detail split into code/message/details) is gone with the
    raises that produced it — ``ApiException.coded`` owns that shape now. The
    shim's remaining job is the framework's plain-string 404/405 and the
    detail-less error.
    """
    # Starlette's unknown-path 404 carries its own string detail.
    exc = HTTPException(status_code=405, detail="Method Not Allowed")
    body = json.loads((await http_exception_shim_handler(_request(), exc)).body)
    assert body["detail"] == "Method Not Allowed"
    assert body["error"]["code"] == CODE_METHOD_NOT_ALLOWED
    assert body["error"]["message"] == "Method Not Allowed"
    assert "details" not in body["error"]

    # No usable detail: the status phrase becomes both message and detail.
    exc_none = HTTPException(status_code=418)
    body_none = json.loads(
        (await http_exception_shim_handler(_request(), exc_none)).body
    )
    assert body_none["error"]["code"] == CODE_HTTP_ERROR  # 418 unmapped
    assert body_none["error"]["message"] == "I'm a Teapot"
    assert body_none["detail"] == "I'm a Teapot"
    assert "details" not in body_none["error"]


# =========================================================================
# Retryable classification (config-owned)
# =========================================================================
def test_is_retryable_status_table() -> None:
    assert is_retryable_status(408) is True
    assert is_retryable_status(429) is True
    for code in (500, 502, 503, 504, 599):
        assert is_retryable_status(code) is True
    for code in (400, 401, 403, 404, 409, 422):
        assert is_retryable_status(code) is False


# =========================================================================
# Validation sanitization (COM-5)
# =========================================================================
def test_sanitize_validation_errors_strips_internals() -> None:
    raw = [
        {
            "type": "missing",
            "loc": ("body", "products", 0, "sku"),
            "msg": "Field required",
            "input": {"name": "no sku here"},
            "url": "https://errors.pydantic.dev/2.11/v/missing",
        },
        {
            "type": "string_type",
            "loc": ("query", "limit"),
            "msg": "Input should be a valid string",
            "ctx": {"class": "str"},
            "input": 123,
        },
    ]
    sanitized = sanitize_validation_errors(raw)
    assert sanitized == [
        {
            "loc": ["products", "0", "sku"],
            "message": "Field required",
            "type": "missing",
        },
        {
            "loc": ["limit"],
            "message": "Input should be a valid string",
            "type": "string_type",
        },
    ]
    # No ctx / input / url keys survive anywhere.
    for entry in sanitized:
        assert set(entry) <= {"loc", "message", "type"}


def test_sanitize_validation_errors_tolerates_sparse_entries() -> None:
    assert sanitize_validation_errors([{}]) == [{"loc": [], "message": "Invalid value"}]


def test_validation_error_summary_first_error() -> None:
    errors = [
        {"loc": ["products", "0", "sku"], "message": "Field required"},
        {"loc": ["name"], "message": "Input should be a valid string"},
    ]
    assert validation_error_summary(errors) == "products.0.sku: Field required"
    assert validation_error_summary([{"loc": [], "message": "boom"}]) == "boom"
    assert validation_error_summary([]) == "Request validation failed"


# =========================================================================
# Global handlers
# =========================================================================
async def test_unhandled_exception_handler_hides_internals() -> None:
    # Capture with a handler attached DIRECTLY to the logger rather than
    # `caplog`. Any earlier test that calls `configure_logging()` installs
    # structlog with `cache_logger_on_first_use=True` and reconfigures the root
    # logger, after which caplog's root-level capture saw nothing here and this
    # test failed only in a full-suite run (never standalone). Binding to the
    # emitting logger is independent of root handlers and propagation.
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    err_logger = logging.getLogger("app.core.errors")
    handler = _Capture(level=logging.ERROR)
    err_logger.addHandler(handler)
    previous_level = err_logger.level
    err_logger.setLevel(logging.ERROR)
    try:
        # logger.exception reads sys.exc_info(), so invoke the handler from
        # inside a live except block (as Starlette does in production).
        try:
            raise RuntimeError("secret-internal-marker")
        except RuntimeError as exc:
            response = await unhandled_exception_handler(_request("req-500"), exc)
    finally:
        err_logger.removeHandler(handler)
        err_logger.setLevel(previous_level)

    logged = "\n".join(
        f"{record.getMessage()}\n{logging.Formatter().formatException(record.exc_info)}"
        if record.exc_info
        else record.getMessage()
        for record in records
    )
    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["error"]["code"] == CODE_INTERNAL_ERROR
    assert body["error"]["retryable"] is True
    assert body["error"]["request_id"] == "req-500"
    assert body["detail"] == body["error"]["message"]
    # No internals leak into the body...
    assert "secret-internal-marker" not in response.body.decode()
    assert "RuntimeError" not in response.body.decode()
    # ...and the request id is echoed on the response header for support.
    assert response.headers[settings.request_id_header] == "req-500"
    # The failure IS logged (with traceback) for operators.
    assert "unhandled_api_exception" in logged
    assert "secret-internal-marker" in logged
    # The client-visible request id is on the log record too: the correlation
    # contextvar may already be unwound here, so the handler must carry it
    # explicitly or the id handed to the user appears in no log line.
    assert records
    assert getattr(records[0], "request_id", None) == "req-500"


def test_request_id_for_prefers_request_state() -> None:
    assert request_id_for(_request("state-id")) == "state-id"
    # No state, no contextvar -> empty string (never raises).
    assert request_id_for(_request()) == ""
