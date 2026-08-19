"""ASGI request-size boundary tests."""

from __future__ import annotations

import pytest

from app.core.http_security import RequestBodyLimitMiddleware


@pytest.mark.parametrize(
    "declared",
    [b"+1", b" 1", b"1 ", b"1.0", b"\xb2", b""],
)
def test_declared_content_length_requires_ascii_decimal_digits(declared: bytes) -> None:
    assert (
        RequestBodyLimitMiddleware._declared_too_large(
            {b"content-length": declared}, max_bytes=100
        )
        is True
    )


def test_declared_content_length_preserves_missing_and_valid_semantics() -> None:
    assert RequestBodyLimitMiddleware._declared_too_large({}, max_bytes=100) is False
    assert (
        RequestBodyLimitMiddleware._declared_too_large(
            {b"content-length": b"100"}, max_bytes=100
        )
        is False
    )
