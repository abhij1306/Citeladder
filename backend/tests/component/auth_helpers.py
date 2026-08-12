"""Shared HTTP authentication setup for component tests."""

from __future__ import annotations

import httpx


async def register_and_login(
    client: httpx.AsyncClient, email: str, password: str = "password123"
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert registration.status_code == 202
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
