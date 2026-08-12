from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import provision_dev_login


class _SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


def _arrange_existing_login(monkeypatch: pytest.MonkeyPatch):
    user = SimpleNamespace(id="user-id", email="dev@example.com", role="admin")
    workspace = SimpleNamespace(id="workspace-id")
    account = SimpleNamespace(id="account-id")
    session = AsyncMock()

    monkeypatch.setattr(
        provision_dev_login, "_require_local_development_target", lambda: None
    )
    monkeypatch.setattr(
        provision_dev_login, "SessionLocal", lambda: _SessionContext(session)
    )
    monkeypatch.setattr(
        provision_dev_login, "get_user_by_email", AsyncMock(return_value=user)
    )
    monkeypatch.setattr(
        provision_dev_login,
        "ensure_personal_workspace",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(
        provision_dev_login, "ensure_user_billing", AsyncMock(return_value=account)
    )
    monkeypatch.setattr(provision_dev_login, "issue_override_bundle", AsyncMock())
    dispose_engine = AsyncMock()
    monkeypatch.setattr(provision_dev_login, "dispose_engine", dispose_engine)
    return user, session, dispose_engine


def test_run_verifies_credentials_in_the_provisioning_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, dispose_engine = _arrange_existing_login(monkeypatch)
    authenticate_user = AsyncMock(return_value=("token", user))
    monkeypatch.setattr(provision_dev_login, "authenticate_user", authenticate_user)

    asyncio.run(provision_dev_login._run(user.email, "password123", 100))

    session.commit.assert_awaited_once()
    authenticate_user.assert_awaited_once_with(session, user.email, "password123")
    dispose_engine.assert_awaited_once()


def test_run_fails_when_written_credentials_do_not_authenticate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _session, dispose_engine = _arrange_existing_login(monkeypatch)
    monkeypatch.setattr(
        provision_dev_login, "authenticate_user", AsyncMock(return_value=None)
    )

    with pytest.raises(RuntimeError, match="credentials did not authenticate"):
        asyncio.run(provision_dev_login._run(user.email, "wrong-password", 100))

    dispose_engine.assert_awaited_once()


def test_run_rejects_non_admin_returned_by_registration_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _session, dispose_engine = _arrange_existing_login(monkeypatch)
    user.role = "user"
    get_user = AsyncMock(side_effect=[None, user])
    monkeypatch.setattr(provision_dev_login, "get_user_by_email", get_user)
    monkeypatch.setattr(
        provision_dev_login, "register_user", AsyncMock(return_value=None)
    )

    with pytest.raises(RuntimeError, match="not an admin account"):
        asyncio.run(provision_dev_login._run(user.email, "password123", 100))

    dispose_engine.assert_awaited_once()


def test_run_preserves_missing_user_failure_after_registration_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _session, dispose_engine = _arrange_existing_login(monkeypatch)
    monkeypatch.setattr(
        provision_dev_login,
        "get_user_by_email",
        AsyncMock(side_effect=[None, None]),
    )
    monkeypatch.setattr(
        provision_dev_login, "register_user", AsyncMock(return_value=None)
    )

    with pytest.raises(RuntimeError, match="registration did not persist"):
        asyncio.run(provision_dev_login._run(user.email, "password123", 100))

    dispose_engine.assert_awaited_once()
