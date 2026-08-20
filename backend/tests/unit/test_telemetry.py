"""Structured logging and explicitly gated Logfire instrumentation."""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from app.core import telemetry
from app.core.config import Settings, settings
from app.core.telemetry import instrument_fastapi, instrument_worker


def test_logfire_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOGFIRE_ENABLED", "LOGFIRE_TOKEN", "LOGFIRE_ENABLED_IN_TESTS"):
        monkeypatch.delenv(name, raising=False)
    fresh = Settings(_env_file=None)

    assert fresh.logfire_enabled is False
    assert fresh.logfire_token == ""
    assert fresh.logfire_enabled_in_tests is False


def test_logfire_defaults_target_the_us_region_and_base_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("LOGFIRE_BASE_URL", "LOGFIRE_SERVICE_NAME"):
        monkeypatch.delenv(name, raising=False)
    fresh = Settings(_env_file=None)

    assert fresh.logfire_base_url == "https://logfire-us.pydantic.dev"
    assert fresh.logfire_service_name == "citeladder"


@pytest.mark.parametrize(
    "module",
    [
        "opentelemetry.instrumentation.fastapi",
        "opentelemetry.instrumentation.httpx",
        "opentelemetry.instrumentation.sqlalchemy",
        "opentelemetry.instrumentation.system_metrics",
    ],
)
def test_logfire_instrumentation_dependencies_are_installed(module: str) -> None:
    assert importlib.import_module(module)


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


class _SpyLoggingHandler(logging.Handler):
    """Real handler subclass: the bridge attaches this to the ROOT logger."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - inert
        return


class _LogfireSpy:
    """Stands in for the logfire module inside ``sys.modules``."""

    LogfireLoggingHandler = _SpyLoggingHandler

    def __init__(self) -> None:
        self.configure_calls: list[dict[str, Any]] = []
        self.instrumented_apps: list[object] = []
        self.instrumented: list[str] = []

    def AdvancedOptions(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        return kwargs

    def configure(self, **kwargs: Any) -> None:
        self.configure_calls.append(kwargs)

    def instrument_fastapi(self, app: object) -> None:
        self.instrumented_apps.append(app)

    def instrument_system_metrics(self) -> None:
        self.instrumented.append("system-metrics")

    def instrument_httpx(self) -> None:
        self.instrumented.append("httpx")

    def instrument_sqlalchemy(self, engine: object) -> None:
        del engine
        self.instrumented.append("sqlalchemy")


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[_LogfireSpy]:
    """Install the spy and undo the process-wide state configuration leaves."""
    instance = _LogfireSpy()
    monkeypatch.setitem(sys.modules, "logfire", instance)
    # Configuration is once-per-process by design, so every test needs a
    # process that has not been configured yet.
    monkeypatch.setattr(telemetry, "_logfire_configured", False)
    root_logger = logging.getLogger()
    existing = list(root_logger.handlers)
    try:
        yield instance
    finally:
        for handler in list(root_logger.handlers):
            if handler not in existing:
                root_logger.removeHandler(handler)


def test_logfire_instrumentation_is_disabled_by_default(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = object()
    monkeypatch.setattr(settings, "logfire_enabled", False)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(app)

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def test_logfire_instrumentation_requires_a_token(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_fastapi(object())

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def test_logfire_instrumentation_stays_disabled_during_tests_by_default(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", False)

    instrument_fastapi(object())

    assert spy.configure_calls == []
    assert spy.instrumented_apps == []


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_service_name", "test-service")
    monkeypatch.setattr(settings, "logfire_environment", "test-environment")
    monkeypatch.setattr(settings, "logfire_base_url", "https://logfire-us.example")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)


def test_logfire_instrumentation_configures_explicitly_enabled_tests(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = object()
    _enable(monkeypatch)

    instrument_fastapi(app)

    assert spy.configure_calls == [
        {
            "token": "test-token",
            # The API process reports under its own role suffix.
            "service_name": "test-service-api",
            "environment": "test-environment",
            "send_to_logfire": "if-token-present",
            # structlog owns stdout; Logfire's console exporter would both
            # duplicate it and crash on a cp1252 Windows console.
            "console": False,
            "advanced": {"base_url": "https://logfire-us.example"},
        }
    ]
    assert spy.instrumented_apps == [app]


def test_logfire_configuration_attaches_the_shared_instrumentation(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)

    instrument_fastapi(object())

    assert spy.instrumented == ["system-metrics", "httpx", "sqlalchemy"]
    assert any(
        isinstance(handler, _SpyLoggingHandler)
        for handler in logging.getLogger().handlers
    )


def test_logfire_configuration_survives_an_unavailable_instrumentor(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken optional instrumentor must never take the process down."""
    _enable(monkeypatch)

    def _boom() -> None:
        raise RuntimeError("instrumentor unavailable")

    monkeypatch.setattr(spy, "instrument_httpx", _boom)

    instrument_fastapi(object())

    assert spy.instrumented == ["system-metrics", "sqlalchemy"]


def test_logfire_configuration_survives_a_missing_instrumentor_attribute(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    monkeypatch.delattr(_LogfireSpy, "instrument_httpx")

    instrument_fastapi(object())

    assert spy.instrumented == ["system-metrics", "sqlalchemy"]


def test_logfire_worker_instrumentation_uses_its_own_service_name(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)

    instrument_worker("audit-worker")

    assert spy.configure_calls[0]["service_name"] == "test-service-audit-worker"
    assert spy.instrumented_apps == []


def test_logfire_worker_instrumentation_respects_the_disabled_gate(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "logfire_enabled", False)
    monkeypatch.setattr(settings, "logfire_token", "test-token")
    monkeypatch.setattr(settings, "logfire_enabled_in_tests", True)

    instrument_worker("audit-worker")

    assert spy.configure_calls == []


def test_logfire_configures_only_once_per_process(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)

    instrument_worker("audit-worker")
    instrument_worker("audit-worker")

    assert len(spy.configure_calls) == 1
    assert spy.instrumented == ["system-metrics", "httpx", "sqlalchemy"]


def test_logfire_uses_app_environment_when_not_configured(
    spy: _LogfireSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "logfire_environment", "")
    monkeypatch.setattr(settings, "app_env", "staging")

    instrument_fastapi(object())

    assert spy.configure_calls[0]["environment"] == "staging"
