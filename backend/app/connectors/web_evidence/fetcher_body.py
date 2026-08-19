"""Bounded response-body decoding for the secure web fetcher.

This module owns content-type metadata and incremental wire/decoded byte
accounting.  Keeping it independent from transport orchestration makes the
security boundary easy to review: no response is buffered before both caps
have been enforced.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Iterable

import httpx

from app.connectors.web_evidence.contracts import FetchError, FetchResult
from app.core.config.site_health_acquisition import (
    BOT_BLOCK_BODY_MARKERS,
    BOT_BLOCK_MARKER_SCAN_BYTES,
    ERROR_MALFORMED_RESPONSE,
    ERROR_RESPONSE_TOO_LARGE,
)
from app.core.config.site_health_rules import PERSISTED_RESPONSE_HEADERS

_BOT_BLOCK_MARKER_BYTES: tuple[bytes, ...] = tuple(
    marker.encode("ascii") for marker in BOT_BLOCK_BODY_MARKERS
)


def is_bot_block_result(result: FetchResult) -> bool:
    """Config-owned bot-block signature on a fetch RESULT (spec §5.4).

    True when a distinctive challenge-platform marker appears within the first
    ``BOT_BLOCK_MARKER_SCAN_BYTES`` of the decoded body. This is a
    CLASSIFICATION, not a retry trigger: the worker turns it into
    ``ERROR_BOT_BLOCKED`` so the page presents as ``blocked``.

    Deliberately marker-only. A bare 401/403/503 is NOT enough: those statuses
    used to be a cheap trigger to RETRY with impersonation, and only a second
    blocked response promoted the outcome to ``bot_blocked``. With no retry
    there is no corroborating evidence, so a status-only rule would relabel
    every members-only 401 and every transient 503 as bot protection. The
    challenge markers stand on their own; the statuses keep their ordinary
    ``http_4xx``/``http_5xx`` classification.
    """
    if not _BOT_BLOCK_MARKER_BYTES:
        return False
    prefix = result.body[:BOT_BLOCK_MARKER_SCAN_BYTES].lower()
    if not any(marker in prefix for marker in _BOT_BLOCK_MARKER_BYTES):
        return False
    # Cloudflare can append its challenge bootstrap script to an otherwise
    # complete, indexable 200 response. Treating the marker alone as terminal
    # discarded real policy/content pages from Cube27. A genuine interstitial
    # does not contain a semantic article/main document with its own heading.
    meaningful_document = (
        200 <= result.status_code < 300
        and b"<h1" in prefix
        and (b"<main" in prefix or b"<article" in prefix)
    )
    return not meaningful_document


def redact_headers(headers: httpx.Headers | dict) -> dict[str, str]:
    """Keep only the config-allowlisted response headers (lowercased keys).

    Everything else (Set-Cookie, Authorization echoes, etc.) is dropped so no
    sensitive header is ever persisted or logged.
    """
    out: dict[str, str] = {}
    items: Iterable[tuple[str, str]] = (
        headers.items() if hasattr(headers, "items") else []
    )
    for key, value in items:
        lowered = str(key).lower()
        if lowered in PERSISTED_RESPONSE_HEADERS:
            out[lowered] = str(value)
    return out


def content_type(headers: httpx.Headers) -> str:
    return str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()


def content_type_gate_applies(status_code: int | None) -> bool:
    """Whether the content-type allowlist may reject this response.

    The allowlist exists to stop us downloading and parsing non-HTML CONTENT.
    An HTTP ERROR response is not content: its body is a diagnostic, and for a
    bot block it carries the very challenge markers we classify on. Rejecting
    one here hid the status behind ``unsupported_content_type`` — a 429 served
    as ``text/plain`` (the common WAF rate-limit shape) surfaced as a TERMINAL
    content-type failure instead of the retryable rate limit it is, and the
    whole crawl died on a transient block.

    So the gate applies to 2xx only — the responses whose body we actually
    keep as content. Error statuses are returned as results and classified
    from ``status_code`` by the caller; a 3xx body is discarded in favour of
    its ``Location``. The wire and decoded byte caps still bound the body on
    every path. An unknown status (``None``) keeps the gate ON — the
    conservative direction.
    """
    if status_code is None:
        return True
    return 200 <= status_code < 300


def charset(headers: httpx.Headers) -> str:
    """Return the lowercased ``charset`` parameter of Content-Type, if any.

    Preserved separately from ``content_type()`` (which intentionally strips
    parameters) so downstream HTML parsing can honor a non-UTF-8 charset
    instead of hard-coding UTF-8.
    """
    raw = str(headers.get("content-type", ""))
    for part in raw.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset":
            return value.strip().strip('"').strip("'").lower()
    return ""


class _DeflateDecoder:
    """``deflate`` decoder that tolerates the raw, headerless variant.

    ``Content-Encoding: deflate`` is specified as zlib-WRAPPED, but a good
    number of servers send bare DEFLATE with no zlib header. A default
    ``decompressobj()`` raises ``zlib.error`` on such a stream's first chunk,
    which the body reader turns into ``malformed_response`` — a healthy page
    lost to a server quirk rather than a real problem.

    So: try zlib-wrapped, and if the header is rejected before ANY output has
    been produced, retry the bytes seen so far raw (``-MAX_WBITS``) once and
    continue with that decompressor. Scoped to the header decision — once a
    format is settled, a mid-body ``zlib.error`` propagates and still fails the
    fetch, so genuinely corrupt bodies are not smuggled through.

    Exposes the ``decompress``/``flush``/``eof`` surface ``read_decoded_stream``
    uses, so the swap stays invisible to the truncation check (a stale
    reference to the discarded object would have reported every raw stream as
    truncated).
    """

    __slots__ = ("_obj", "_pending", "_settled")

    def __init__(self) -> None:
        self._obj = zlib.decompressobj()
        # Bytes fed so far, kept only until the format is settled so the raw
        # retry can replay them; dropped immediately after (never a full body).
        self._pending = b""
        self._settled = False

    def decompress(self, chunk: bytes) -> bytes:
        if self._settled:
            return self._obj.decompress(chunk)
        self._pending += chunk
        try:
            out = self._obj.decompress(chunk)
        except zlib.error:
            # zlib header rejected: replay everything as raw deflate.
            self._obj = zlib.decompressobj(-zlib.MAX_WBITS)
            out = self._obj.decompress(self._pending)
            self._settled = True
            self._pending = b""
            return out
        # A zlib header is 2 bytes, so that is when the verdict is final.
        if len(self._pending) >= 2:
            self._settled = True
            self._pending = b""
        return out

    def flush(self) -> bytes:
        return self._obj.flush()

    @property
    def eof(self) -> bool:
        return self._obj.eof


def incremental_decoder(content_encoding: str):
    """Return ``(decode_chunk, decompressor)`` for the wire encoding.

    ``decode_chunk`` is a ``callable(chunk)->bytes`` that feeds a chunk into the
    decompressor. ``decompressor`` is the underlying ``zlib`` object (``None``
    for identity/unknown encodings) so the caller can, after the stream ends,
    flush any buffered tail and inspect ``.eof`` — a gzip/deflate stream that
    was cut off mid-way never sets ``eof``, which is how a truncated response is
    detected (a truncated stream does not necessarily raise ``zlib.error``).

    Supports gzip and deflate (the encodings a compression bomb would use);
    ``identity``/unknown pass bytes through unchanged. brotli is not a
    dependency, so a ``br`` body is treated as opaque wire bytes (the wire cap
    still bounds it). ``deflate`` also accepts the raw headerless variant many
    servers send — see ``_DeflateDecoder``.
    """
    encoding = str(content_encoding or "").strip().lower()
    if encoding == "gzip":
        obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return (lambda chunk: obj.decompress(chunk)), obj
    if encoding == "deflate":
        decoder = _DeflateDecoder()
        return decoder.decompress, decoder
    return (lambda chunk: chunk), None


async def read_decoded_stream(
    response: httpx.Response,
    *,
    decode: Callable[[bytes], bytes],
    decompressor,
    max_wire: int,
    max_decoded: int,
) -> tuple[int, int, list[bytes]]:
    """Stream, decode, and cap a response before exposing its body."""
    wire_total = 0
    decoded_total = 0
    decoded_chunks: list[bytes] = []
    async for raw in response.aiter_raw():
        wire_total += len(raw)
        if wire_total > max_wire:
            raise FetchError(
                "response exceeded wire byte cap", error_code=ERROR_RESPONSE_TOO_LARGE
            )
        try:
            out = decode(raw)
        except zlib.error as exc:
            raise FetchError(
                "malformed compressed response body",
                error_code=ERROR_MALFORMED_RESPONSE,
            ) from exc
        if out:
            decoded_total += len(out)
            if decoded_total > max_decoded:
                raise FetchError(
                    "response exceeded decoded byte cap (compression bomb)",
                    error_code=ERROR_RESPONSE_TOO_LARGE,
                )
            decoded_chunks.append(out)
    if decompressor is None:
        return wire_total, decoded_total, decoded_chunks
    try:
        tail = decompressor.flush()
    except zlib.error as exc:
        raise FetchError(
            "malformed compressed response body", error_code=ERROR_MALFORMED_RESPONSE
        ) from exc
    if tail:
        decoded_total += len(tail)
        if decoded_total > max_decoded:
            raise FetchError(
                "response exceeded decoded byte cap (compression bomb)",
                error_code=ERROR_RESPONSE_TOO_LARGE,
            )
        decoded_chunks.append(tail)
    if not decompressor.eof:
        raise FetchError(
            "truncated compressed response body",
            error_code=ERROR_MALFORMED_RESPONSE,
            retryable=True,
        )
    return wire_total, decoded_total, decoded_chunks
