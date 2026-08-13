"""Shopify-specific OAuth validation and reconnect contracts."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.integrations import IntegrationOAuthState
from tests.component import test_integrations_oauth_api as oauth_tests

_oauth_credentials = oauth_tests._oauth_credentials
_fake_oauth = oauth_tests._fake_oauth


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "params"),
    [
        ("shopify", {}),
        ("shopify", {"shop": "shop.myshopify.com.evil.com"}),
        ("shopify", {"shop": "myshopify.com"}),
        ("shopify", {"shop": "a.b.myshopify.com"}),
        ("shopify", {"shop": "https://volt-city.myshopify.com.evil.com/admin"}),
        ("gsc", {"shop": "volt-city.myshopify.com"}),
    ],
)
async def test_oauth_start_rejects_invalid_shop_targets(
    client, db_session, _oauth_credentials, _fake_oauth, provider, params
) -> None:
    await oauth_tests._register(
        client, f"int-{provider}-shop-{len(params)}@example.com"
    )
    response = await client.get(
        f"{oauth_tests._BASE}/oauth/{provider}/start", params=params
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "oauth_shop_invalid"
    assert await db_session.scalar(select(func.count(IntegrationOAuthState.jti))) == 0


@pytest.mark.asyncio
async def test_shopify_callback_bad_hmac_rejected_before_any_exchange(
    client, db_session, _oauth_credentials, _fake_oauth
) -> None:
    await oauth_tests._register(client, "int-shopify-badhmac@example.com")
    state = oauth_tests._state_from_start(
        await oauth_tests._start(client, "shopify", params={"shop": oauth_tests._SHOP})
    )
    callback = await oauth_tests._shopify_callback(client, state, tamper="hmac")
    assert callback.headers["location"] == oauth_tests._landing(
        "error=oauth_state_invalid"
    )
    assert _fake_oauth.shopify_token_calls() == []
    assert await oauth_tests._grants(db_session) == []
    state_row = (await db_session.execute(select(IntegrationOAuthState))).scalar_one()
    assert state_row.consumed_at is None
    assert (await oauth_tests._shopify_callback(client, state)).headers[
        "location"
    ] == oauth_tests._landing("connected=shopify")


@pytest.mark.asyncio
async def test_shopify_callback_shop_mismatch_rejected(
    client, db_session, _oauth_credentials, _fake_oauth
) -> None:
    await oauth_tests._register(client, "int-shopify-mismatch@example.com")
    state = oauth_tests._state_from_start(
        await oauth_tests._start(client, "shopify", params={"shop": oauth_tests._SHOP})
    )
    callback = await oauth_tests._shopify_callback(
        client, state, shop="other-shop.myshopify.com"
    )
    assert callback.headers["location"] == oauth_tests._landing(
        "error=oauth_state_invalid"
    )
    assert _fake_oauth.shopify_token_calls() == []
    assert await oauth_tests._grants(db_session) == []
    assert await oauth_tests._connections(db_session) == []


@pytest.mark.asyncio
async def test_shopify_reconnect_repoints_single_connection(
    client, db_session, _oauth_credentials, _fake_oauth
) -> None:
    await oauth_tests._register(client, "int-shopify-reconnect@example.com")
    for _ in range(2):
        state = oauth_tests._state_from_start(
            await oauth_tests._start(
                client, "shopify", params={"shop": oauth_tests._SHOP}
            )
        )
        assert (
            "connected=shopify"
            in (await oauth_tests._shopify_callback(client, state)).headers["location"]
        )
    assert len(await oauth_tests._grants(db_session)) == 1
    (connection,) = await oauth_tests._connections(db_session)
    assert connection.account_ref == oauth_tests._SHOP
    assert len(_fake_oauth.shopify_token_calls()) == 2
