"""Pinned curl-cffi acquisition transport for Site Health.

The transport performs exactly one network request. Redirect orchestration and
URL admission remain owned by ``SecureFetcher`` so every hop is resolved and
validated before curl receives it.
"""

from __future__ import annotations

import time

from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException, Timeout

from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
    ResolvedTarget,
)
from app.connectors.web_evidence.targets import (
    validate_resolved_target as _validate_resolved_target,
)
from app.core.config.site_health_acquisition import (
    ERROR_ACQUISITION_UNAVAILABLE,
    ERROR_CONNECTION_FAILED,
    ERROR_MALFORMED_RESPONSE,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_CONTENT_TYPE,
    SITE_HEALTH_USER_AGENT,
)
from app.core.config.site_health_rules import (
    PERSISTED_RESPONSE_HEADERS,
)


def _header_values(headers: object, name: str) -> list[str]:
    """Read a header case-insensitively without losing repeated values."""

    get_list = getattr(headers, "get_list", None)
    if callable(get_list):
        return [str(value) for value in get_list(name) if value is not None]

    items = getattr(headers, "multi_items", None)
    if not callable(items):
        items = getattr(headers, "items", None)
    if not callable(items):
        return []
    wanted = name.casefold()
    return [
        str(value)
        for key, value in items()
        if str(key).casefold() == wanted and value is not None
    ]


def _header_value(headers: object, name: str) -> str:
    return ", ".join(_header_values(headers, name))


def _singleton_header_value(headers: object, name: str) -> str:
    values = _header_values(headers, name)
    if len(values) > 1:
        raise FetchError(
            f"curl response contained repeated {name.lower()} headers",
            error_code=ERROR_MALFORMED_RESPONSE,
        )
    return values[0] if values else ""


def _redacted_headers(headers: object) -> dict[str, str]:
    return {
        key: value
        for key in sorted(PERSISTED_RESPONSE_HEADERS)
        if (value := _header_value(headers, key))
    }


def _content_type(headers: object) -> str:
    return (
        _singleton_header_value(headers, "content-type")
        .split(";", 1)[0]
        .strip()
        .lower()
    )


def _charset(headers: object) -> str:
    content_type = _singleton_header_value(headers, "content-type")
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset":
            return value.strip().strip('"').strip("'").lower()
    return ""


def _curl_resolve_entry(target: ResolvedTarget) -> str:
    address = (
        f"[{target.connect_ip}]" if ":" in target.connect_ip else target.connect_ip
    )
    return f"{target.host}:{target.port}:{address}"


def _request_headers(request: FetchRequest, default_user_agent: str) -> dict[str, str]:
    headers = {name.lower(): value for name, value in request.headers.items()}
    headers.setdefault("user-agent", default_user_agent)
    return headers


def _transport_error_code(exc: RequestException) -> int | None:
    try:
        return int(exc.code)
    except (AttributeError, TypeError, ValueError):
        return None


class CurlCffiTransport:
    """One-hop curl request pinned to a previously validated address."""

    def __init__(
        self,
        *,
        impersonation_profile: str,
        user_agent: str = SITE_HEALTH_USER_AGENT,
    ) -> None:
        self._impersonation_profile = impersonation_profile
        self._user_agent = user_agent

    async def aclose(self) -> None:
        """No-op: this rung holds only per-request state.

        Required by ``AcquisitionTransport`` because a rung that DOES own
        long-lived resources (the browser rung owns OS processes) must be
        closable through the same interface.
        """

    async def fetch(
        self,
        request: FetchRequest,
        target: ResolvedTarget,
        *,
        max_wire_bytes: int,
        max_decoded_bytes: int,
        timeout_seconds: float,
    ) -> FetchResult:
        """Fetch one admitted target with DNS pinning and bounded streaming."""

        _validate_resolved_target(target)
        started = time.monotonic()
        headers = _request_headers(request, self._user_agent)
        options = {
            CurlOpt.RESOLVE: [_curl_resolve_entry(target)],
            CurlOpt.MAXFILESIZE_LARGE: max_wire_bytes,
        }
        try:
            async with AsyncSession(
                trust_env=False,
                verify=True,
                allow_redirects=False,
                timeout=timeout_seconds,
                impersonate=self._impersonation_profile,
                headers=headers,
                curl_options=options,
            ) as session:
                response = await session.request(
                    request.method,
                    target.url,
                    stream=True,
                    allow_redirects=False,
                    timeout=timeout_seconds,
                )
                ttfb_ms = int((time.monotonic() - started) * 1000)
                body = await self._bounded_body(response, max_decoded_bytes)
        except Timeout as exc:
            raise FetchError(
                "curl acquisition timed out",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except RequestException as exc:
            raise FetchError(
                "curl acquisition connection failed",
                error_code=ERROR_CONNECTION_FAILED,
                retryable=True,
                transport_error_code=_transport_error_code(exc),
            ) from exc

        if response.primary_ip != target.connect_ip:
            raise FetchError(
                "curl acquisition did not use the validated address",
                error_code=ERROR_ACQUISITION_UNAVAILABLE,
                retryable=False,
            )
        wire_bytes = int(response.download_size or len(body))
        if wire_bytes > max_wire_bytes:
            raise FetchError(
                "curl response exceeded wire byte cap",
                error_code=ERROR_RESPONSE_TOO_LARGE,
            )
        content_type = _content_type(response.headers)
        if (
            request.allowed_content_types
            and content_type
            and content_type not in request.allowed_content_types
            and 200 <= response.status_code < 300
        ):
            raise FetchError(
                f"unsupported content type: {content_type}",
                error_code=ERROR_UNSUPPORTED_CONTENT_TYPE,
                status_code=response.status_code,
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            status_code=response.status_code,
            redacted_headers=_redacted_headers(response.headers),
            content_type=content_type,
            http_version=str(response.http_version or ""),
            body=body,
            wire_bytes=wire_bytes,
            decoded_bytes=len(body),
            ttfb_ms=ttfb_ms,
            latency_ms=latency_ms,
            charset=_charset(response.headers),
            redirect_location=_singleton_header_value(response.headers, "location"),
        )

    @staticmethod
    async def _bounded_body(response, max_decoded_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_content():
                total += len(chunk)
                if total > max_decoded_bytes:
                    if response.quit_now is not None:
                        response.quit_now.set()
                    raise FetchError(
                        "curl response exceeded decoded byte cap",
                        error_code=ERROR_RESPONSE_TOO_LARGE,
                    )
                chunks.append(chunk)
        finally:
            await response.aclose()
        return b"".join(chunks)
