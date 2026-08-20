"""Bounded request-body readers shared by bulk-import endpoints."""

from __future__ import annotations

from fastapi import Request, UploadFile, status

from app.core.config.http import IMPORT_BODY_MAX_BYTES, IMPORT_READ_CHUNK_BYTES
from app.core.http_errors import raise_api_error


def _check_declared_length(request: Request, limit: int) -> None:
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        declared = int(raw)
    except ValueError as exc:
        raise_api_error(
            status.HTTP_400_BAD_REQUEST,
            "Invalid Content-Length header",
            cause=exc,
        )
    if declared > limit:
        raise_api_error(status.HTTP_413_CONTENT_TOO_LARGE, "Import body too large")


async def read_limited_upload(
    upload: UploadFile, *, limit: int = IMPORT_BODY_MAX_BYTES
) -> bytes:
    """Read an upload in chunks and stop at ``limit + 1`` bytes."""
    # Multipart framing makes Content-Length larger than the file, so the
    # declaration is enforced by the global ASGI ceiling. The file itself is
    # bounded here independently.
    body = bytearray()
    while True:
        chunk = await upload.read(min(IMPORT_READ_CHUNK_BYTES, limit + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > limit:
            raise_api_error(status.HTTP_413_CONTENT_TOO_LARGE, "Import file too large")


async def read_limited_body(
    request: Request, *, limit: int = IMPORT_BODY_MAX_BYTES
) -> bytes:
    """Stream a raw/JSON body with declared and observed byte ceilings."""
    _check_declared_length(request, limit)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise_api_error(status.HTTP_413_CONTENT_TOO_LARGE, "Import body too large")
    return bytes(body)
