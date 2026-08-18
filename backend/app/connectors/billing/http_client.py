"""Application-lifespan pooled HTTP clients for billing providers."""

from __future__ import annotations

import asyncio
import weakref

import httpx

from app.core.config.billing_settings import (
    billing_settings,
)

_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    weakref.WeakKeyDictionary()
)


def shared_billing_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=billing_settings.request_timeout_seconds,
            limits=httpx.Limits(
                max_connections=billing_settings.http_max_connections,
                max_keepalive_connections=billing_settings.http_max_keepalive_connections,
                keepalive_expiry=billing_settings.http_keepalive_expiry_seconds,
            ),
        )
        _clients[loop] = client
    return client


async def aclose_shared_billing_clients() -> None:
    for loop, client in list(_clients.items()):
        if _clients.pop(loop, None) is None:
            continue
        await client.aclose()
