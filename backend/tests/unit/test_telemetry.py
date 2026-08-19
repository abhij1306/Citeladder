"""Structured logging and explicitly gated Logfire instrumentation."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest

from app.core.config import Settings, settings
from app.core.telemetry import instrument_fastapi


def test_logfire_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOGFIRE_ENABLED", "LOGFIRE_TOKEN", "LOGFIRE_ENABLED_IN_TESTS"):
        monkeypatch.delenv(name, raising=False)
    fresh = Settings(_env_file=None)

    assert fresh.logfire_enabled is False
    assert fresh.logfire_token == ""
    assert fresh.logfire_enabled_in_tests is False


def test_logfire_fastapi_instrumentation_dependency_is_installed() -> None:
    assert importlib.import_module("opentelemetry.instrumentation.fastapi")


def test_logfire_settings_accept_explicit_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFIRE_ENABLED", "true")
    monkeypatch.setenv("LOGFIRE_TOKEN", "test-token")
    monkeypatch.setenv("LOGFIRE_SERVICE_NAME", "test-service")
    monkeypatch.setenv("LOGFIRE_ENVIRONMENT", "staging")
    monkeypatch.setenv("LOGFIRE_ENABLED_IN_TESTS", "true")

    configured = Settings(_env_file=None)

    assert configured.logfire_enabled is True
    assert configured.logfire_token == "test-token"
    assert configured.logfire_service_name == "test-service"
    assert configured.logfire_environment == "staging"
    assert configured.logfire_enabled_in_tests is True


class _LogfireSpy:
    def __init__(self) -> None:
        self.configure_calls: list[dict[str, Any]] = []
        self.instrumented_apps: list[object] = []

    def configure(self, **kwargs: Any) -> None:
        self.configure_calls.append(kwargs)

    def instrument_fastapi(self, app: object) -> None:
        self.instrumented_apps.append(app)


def test_logfire_instrumentation_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _LogfireSpy()
    app = object()
    monkeypatch.setitem(sys.modules, "logfire", spy)
    monkeypatch.setattr(settings, "logfire_enabled", False)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(app)

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def test_logfire_instrumentation_requires_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _LogfireSpy()
    monkeypatch.setitem(sys.modules, "logfire", spy)
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(object())

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def test_logfire_instrumentation_stays_disabled_during_tests_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _LogfireSpy()
    monkeypatch.setitem(sys.modules, "logfire", spy)
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", False)

    instrument_fastapi(object())

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def test_logfire_instrumentation_configures_explicitly_enabled_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _LogfireSpy()
    app = object()
    monkeypatch.setitem(sys.modules, "logfire", spy)
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_service_name", "test-service")
    monkeypatch.setattr(settings, "logfire_environment", "test-environment")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(app)

    assert spy.configure_calls == [
        {
            "token": "test-token",
            "service_name": "test-service",
            "environment": "test-environment",
            "send_to_logfire": "if-token-present",
        }
    ]
    assert spy.instrumented_apps == [app]


def test_logfire_uses_app_environment_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _LogfireSpy()
    monkeypatch.setitem(sys.modules, "logfire", spy)
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_environment", "")
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(object())

    assert spy.configure_calls[0]["environment"] == "staging"
