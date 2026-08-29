from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _reset_module() -> ModuleType:
    path = Path(__file__).parents[3] / "reset-db.py"
    spec = importlib.util.spec_from_file_location("citeladder_reset_db", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_reset_is_limited_to_loopback_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _reset_module()
    monkeypatch.setattr(module, "_configuration", lambda: {"APP_ENV": "development"})

    module.authorize_reset("postgresql+asyncpg://user:secret@127.0.0.1:5432/dev")
    with pytest.raises(RuntimeError, match=r"target host is 'shared\.example\.com'"):
        module.authorize_reset(
            "postgresql+asyncpg://user:secret@shared.example.com:5432/dev"
        )


def test_explicit_token_can_authorize_a_confirmed_remote_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _reset_module()
    monkeypatch.setattr(
        module,
        "_configuration",
        lambda: {
            "APP_ENV": "development",
            module.DESTRUCTIVE_RESET_VARIABLE: module.DESTRUCTIVE_RESET_TOKEN,
        },
    )

    module.authorize_reset(
        "postgresql+asyncpg://user:secret@shared.example.com:5432/disposable"
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///tmp/citeladder.db",
        "postgresql+asyncpg:///citeladder",
        "postgresql+asyncpg://user:secret@localhost:5432/postgres",
    ],
)
def test_connection_details_reject_unsupported_or_unsafe_targets(
    database_url: str,
) -> None:
    module = _reset_module()

    with pytest.raises(RuntimeError):
        module._connection_details(database_url)


def test_connection_details_redact_credentials() -> None:
    module = _reset_module()

    _admin, redacted, target = module._connection_details(
        "postgresql+asyncpg://user:secret@localhost:5432/citeladder"
    )

    assert target == "citeladder"
    assert "secret" not in redacted
    assert "user:***@localhost:5432/postgres" in redacted
