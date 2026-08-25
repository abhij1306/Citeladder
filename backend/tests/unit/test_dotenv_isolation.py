"""The suite must never read a developer's ``.env``.

This is the enforcement for the rule stated in ``tests/conftest.py`` and
``app/core/config/dotenv.py``. Without it the guard is a convention: someone
adds a sixth settings class with its own hard-coded ``env_file`` tuple, and a
real provider key silently loads into the next test run.

The failure being prevented is concrete. A developer ``.env`` sets
``DEFAULT_AGENT_API_KEY``; that makes ``default_agent_settings.configured``
true; the agent worker then builds a live gateway and posts evidence to a real
provider from a component test — a network call, a bill, and a
nondeterministic result, on a machine nobody was watching.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings

from app.core.config import (
    BASE_DIR,
    PROJECT_ROOT,
    Settings,
    encryption_key_configured,
    settings,
)
from app.core.config.abuse import AbuseSettings
from app.core.config.agent import DefaultAgentSettings, default_agent_settings
from app.core.config.billing_settings import BillingSettings
from app.core.config.dotenv import (
    DISABLE_DOTENV_VAR,
    dotenv_disabled,
    dotenv_sources,
)
from app.core.config.site_health_runtime import SiteHealthSettings

# Every ``BaseSettings`` subclass in the config package that declares an
# ``env_file``. A new one must be added here — and must route through
# ``dotenv_sources()`` — or the sweep below fails.
DOTENV_SETTINGS_CLASSES: tuple[type[BaseSettings], ...] = (
    Settings,
    AbuseSettings,
    DefaultAgentSettings,
    BillingSettings,
    SiteHealthSettings,
)


def test_the_guard_is_active_for_this_run() -> None:
    assert os.environ.get(DISABLE_DOTENV_VAR) == "1"
    assert dotenv_disabled() is True


def test_no_env_file_is_resolved_while_the_guard_is_active() -> None:
    # ``None`` is pydantic-settings' "read no file at all".
    assert dotenv_sources() is None


@pytest.mark.parametrize(
    "settings_class", DOTENV_SETTINGS_CLASSES, ids=lambda cls: cls.__name__
)
def test_no_settings_class_loads_a_dotenv_file(
    settings_class: type[BaseSettings],
) -> None:
    assert settings_class.model_config.get("env_file") is None


def test_every_config_module_routes_through_the_dotenv_owner() -> None:
    """No settings module may build its own ``.env`` path.

    A hard-coded tuple would bypass the opt-out entirely, which is exactly the
    state this repository was in before.
    """
    config_dir = Path(__file__).resolve().parents[2] / "app" / "core" / "config"
    offenders = [
        path.name
        for path in sorted(config_dir.glob("*.py"))
        if "env_file=" in path.read_text(encoding="utf-8")
        and "env_file=dotenv_sources()" not in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], (
        f"{offenders} declare env_file without app.core.config.dotenv."
        " Route it through dotenv_sources() so tests stay isolated."
    )


def test_the_suite_supplies_its_own_database_url() -> None:
    # Whatever the developer's `.env` says, the suite's URL is the one the
    # runner exported (or the documented default) — never a file read.
    assert settings.database_url == os.environ["DATABASE_URL"]


def test_crypto_secrets_are_the_declared_test_values() -> None:
    # Deterministic everywhere, and distinct from the shipped placeholders so
    # crypto-dependent paths actually run instead of failing closed.
    assert settings.encryption_key == os.environ["ENCRYPTION_KEY"]
    assert settings.jwt_secret_key == os.environ["JWT_SECRET_KEY"]
    assert encryption_key_configured(settings) is True


def test_no_model_provider_is_configured_during_tests() -> None:
    """The specific hazard: a live provider must be unreachable from a test.

    ``configured`` gates whether the agent worker builds a real gateway. If a
    developer key ever loads again, this is the test that says so.
    """
    assert default_agent_settings.configured is False
    assert default_agent_settings.resolved_api_key == ""


def test_a_developer_dotenv_is_not_being_read_even_when_present() -> None:
    """Skip when there is no `.env`; assert isolation when there is one."""
    candidates = [PROJECT_ROOT / ".env", BASE_DIR / ".env"]
    present = [path for path in candidates if path.exists()]
    if not present:
        pytest.skip("no .env in this checkout; the sweep above covers the rule")

    # The file exists and still contributed nothing: every settings class
    # resolved `env_file` to None.
    assert all(
        settings_class.model_config.get("env_file") is None
        for settings_class in DOTENV_SETTINGS_CLASSES
    )
