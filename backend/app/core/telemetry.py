# Structured logging, correlation ids, and optional Logfire instrumentation.
from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from functools import lru_cache
from typing import Any
from uuid import uuid4

structlog: Any | None = None
try:
    import structlog as _structlog

    structlog = _structlog
except ImportError:  # pragma: no cover - optional dependency fallback
    pass

__all__ = [
    "configure_logging",
    "generate_correlation_id",
    "get_correlation_id",
    "instrument_fastapi",
    "instrument_worker",
    "reset_correlation_id",
    "set_correlation_id",
]

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _add_correlation_id(
    logger: object,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    del logger, method_name
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


@lru_cache(maxsize=1)
def configure_logging() -> None:
    """Configure JSON structured logging with correlation-id enrichment."""
    if structlog is None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            stream=sys.stdout,
        )
        return

    shared_processors: list[Any] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _add_correlation_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    if not any(
        isinstance(existing, logging.StreamHandler)
        and getattr(existing, "stream", None) is sys.stdout
        and isinstance(
            getattr(existing, "formatter", None),
            structlog.stdlib.ProcessorFormatter,
        )
        for existing in root_logger.handlers
    ):
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


# One Logfire service name per runnable process. The compose stack hands every
# service the SAME environment block, so a per-role suffix has to come from the
# code that starts the process — otherwise all ten processes report as one
# service and their traces are impossible to tell apart in Logfire.
_logfire_configured = False


def _service_name(role: str) -> str:
    from app.core.config import settings

    return f"{settings.logfire_service_name}-{role}"


def _configure_logfire(role: str) -> Any | None:
    """Configure the Logfire SDK once for this process; return it, or ``None``.

    Logfire is optional: absent token, disabled flag, disabled test gate, or an
    uninstalled SDK all degrade to a no-op so local development, imports, and
    tests keep working with the JSON-log fallback alone.
    """
    global _logfire_configured
    from app.core.config import settings

    if (
        not settings.logfire_enabled
        or not settings.logfire_token
        or ("pytest" in sys.modules and not settings.logfire_enabled_in_tests)
    ):
        return None
    try:
        import logfire
    except ImportError:  # pragma: no cover - optional dependency fallback
        logging.getLogger("app.core.telemetry").debug(
            "logfire not installed; skipping instrumentation"
        )
        return None
    if _logfire_configured:
        return logfire
    logfire.configure(
        token=settings.logfire_token,
        service_name=_service_name(role),
        environment=settings.logfire_environment or settings.app_env,
        send_to_logfire="if-token-present",
        # This process already owns its stdout format: structlog renders one
        # JSON object per record (``configure_logging``). Logfire's pretty
        # console exporter would interleave a second, differently shaped
        # rendering of the same spans into that stream -- and on a Windows
        # cp1252 console its box-drawing characters raise UnicodeEncodeError
        # inside the exporter, turning every span carrying a traceback into an
        # "Exception while exporting Span" error. Spans still go to Logfire.
        console=False,
        advanced=logfire.AdvancedOptions(base_url=settings.logfire_base_url),
    )
    _logfire_configured = True
    _instrument_process(logfire)
    return logfire


def _instrument_process(logfire: Any) -> None:
    """Attach the instrumentation every CiteLadder process shares.

    Each integration ships in its own optional OpenTelemetry package, so a
    partial install must degrade instead of taking the process down at startup
    (invariant: telemetry never breaks the app). Database spans come from the
    SQLAlchemy layer only — adding the asyncpg instrumentor on top of it emits
    a second span for the same query.
    """
    log = logging.getLogger("app.core.telemetry")

    def _try(label: str, instrument_name: str) -> None:
        try:
            instrument = getattr(logfire, instrument_name)
            instrument()
        except Exception:  # pragma: no cover - optional instrumentation
            log.warning("logfire %s instrumentation unavailable", label, exc_info=True)

    _try("system-metrics", "instrument_system_metrics")
    # Captures method, URL, status, and timing only. Request and response
    # bodies stay out of telemetry, so answer-engine prompts and completions
    # are never shipped to Logfire (see connectors/agent/client.py).
    _try("httpx", "instrument_httpx")

    def _sqlalchemy() -> None:
        from app.core.database import engine

        logfire.instrument_sqlalchemy(engine=engine.sync_engine)

    try:
        _sqlalchemy()
    except Exception:  # pragma: no cover - optional instrumentation
        log.warning("logfire sqlalchemy instrumentation unavailable", exc_info=True)

    def _logging_bridge() -> None:
        handler = logfire.LogfireLoggingHandler()
        root_logger = logging.getLogger()
        # Added ALONGSIDE the structlog JSON handler, never in place of it:
        # stdout logs remain the source of truth for anyone reading container
        # output, and Logfire is a second consumer of the same records.
        if not any(
            isinstance(existing, logfire.LogfireLoggingHandler)
            for existing in root_logger.handlers
        ):
            root_logger.addHandler(handler)

    try:
        _logging_bridge()
    except Exception:  # pragma: no cover - optional instrumentation
        log.warning("logfire logging instrumentation unavailable", exc_info=True)


def instrument_fastapi(app: Any) -> None:
    """Configure Logfire for the API process and instrument its routes."""
    logfire = _configure_logfire("api")
    if logfire is None:
        return
    logfire.instrument_fastapi(app)


def instrument_worker(role: str) -> None:
    """Configure Logfire for a worker process under its own service name.

    ``role`` is the short, stable service suffix (``audit-worker``), so each
    background process is separable from the API and from its siblings in the
    Logfire service list.
    """
    _configure_logfire(role)


def generate_correlation_id() -> str:
    return uuid4().hex[:16]


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    return _correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id_ctx.reset(token)
