"""Shared test fixtures for the CiteLadder backend.

Uses an async Postgres database with a fresh, isolated schema per test (no
SQLite: the models use Postgres UUID columns). A throwaway
``citeladder_tests_<runid>`` database is created for the session and dropped on
teardown — nothing persists between runs and the dev database is never touched.

**The suite never reads ``.env``.** A developer ``.env`` carries real provider
keys, OAuth client secrets, and the Fernet encryption key; loading them turns
"is this provider configured?" branches ON inside tests, which is how a
component test once posted evidence to a live provider endpoint. So this module
sets ``CITELADDER_DISABLE_DOTENV`` and its own deterministic values in the
process environment BEFORE anything from ``app`` is imported (see
``app/core/config/dotenv.py``). Test configuration is declared here, in the
repository — identical on a laptop, in CI, and in review.

The one thing the suite cannot invent is a Postgres server. Export
``TEST_DATABASE_URL`` (preferred) or ``DATABASE_URL`` to point at one; without
either, the localhost default is tried and a clear error names both variables.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# --- Test configuration, before the first `app` import ---------------------
# Order matters: pydantic-settings reads env_file and environment at class
# definition time, so every one of these has to be set before `app.core.config`
# is imported below.

# The server the suite may create its throwaway database on. `.env` is NOT a
# source: the runner supplies this explicitly, or accepts the local default.
_DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/citeladder"
)
_RESOLVED_DATABASE_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or _DEFAULT_TEST_DATABASE_URL
)

# Deterministic, non-secret stand-ins. These are published test values, not
# credentials: they exist so crypto-dependent code paths (Fernet encryption,
# JWT signing, referral hashing) run identically everywhere. They must not be
# any of the shipped placeholders, which `encryption_key_configured` treats as
# MISSING so a real deployment fails closed.
_TEST_ENVIRONMENT = {
    "CITELADDER_DISABLE_DOTENV": "1",
    "DATABASE_URL": _RESOLVED_DATABASE_URL,
    "APP_ENV": "development",
    "JWT_SECRET_KEY": "citeladder-test-jwt-secret-key-not-a-real-secret",
    "ENCRYPTION_KEY": "citeladder-test-encryption-key-not-a-real-secret",
    "REFERRAL_HASH_SALT": "citeladder-test-referral-salt-not-a-real-secret",
}
for _name, _value in _TEST_ENVIRONMENT.items():
    os.environ[_name] = _value

# Any provider credential inherited from the shell would defeat the point, so
# they are cleared too: `.env` is disabled, but an exported key is not.
_PROVIDER_CREDENTIAL_SUFFIXES = ("_API_KEY", "_CLIENT_SECRET", "_CLIENT_ID")
for _name in [
    name
    for name in os.environ
    if name.isupper() and name.endswith(_PROVIDER_CREDENTIAL_SUFFIXES)
]:
    del os.environ[_name]

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.main import app  # noqa: E402

_TEST_RUN_ID = uuid.uuid4().hex[:12]
_TEST_SCHEMA = f"test_{re.sub(r'[^a-zA-Z0-9_]', '_', _TEST_RUN_ID)}"

# Between-test cleanup, as one round trip. Raw SQL bypasses the engine's
# ``schema_translate_map`` (which only rewrites SQLAlchemy constructs), so the
# schema is spelled out here.
#
# This deliberately uses DELETE rather than TRUNCATE. TRUNCATE is the faster
# choice for large tables, but it takes an ACCESS EXCLUSIVE lock and rewrites
# (and fsyncs) each table's storage even when the table is already empty —
# across 67 mostly-empty test tables that measured ~1280ms per test, i.e. the
# dominant cost of the whole suite. DELETE on an empty table is a no-op seq
# scan; the same cleanup measured ~8ms, a ~167x improvement.
#
# The statements are wrapped in a DO block because asyncpg sends statements as
# prepared statements and refuses multiple commands in one — the DO block is a
# single command, so all 67 deletes still cost one round trip.
#
# Order matters for DELETE (unlike TRUNCATE ... CASCADE): a parent row cannot go
# while a child still references it. ``sorted_tables`` is dependency order
# (parents first), so it is reversed here to delete children first.
# ``SET CONSTRAINTS ALL DEFERRED`` covers the FK cycles between the audit-task /
# artifact tables that make a total order impossible; it is a no-op for
# non-deferrable constraints rather than an error.
#
# NOTE: do NOT try to narrow this to "only non-empty tables" using
# ``pg_class.reltuples`` / ``relpages`` / ``pg_stat_all_tables.n_live_tup``.
# Those counters are estimates: ``reltuples`` is ``-1`` on a never-analyzed
# table (so it matches every freshly created table, narrowing nothing), while
# ``relpages`` and ``n_live_tup`` still read 0 immediately after an insert, so
# genuinely written tables get skipped and their rows leak into the next test.
with warnings.catch_warnings():
    # Emits a cycle warning for the audit-task / artifact tables; the deferred
    # constraints above are what actually makes those safe to delete.
    warnings.simplefilter("ignore")
    _DELETE_ORDER = list(reversed(Base.metadata.sorted_tables))

# ``consumable_ledger`` RESTRICT-references ``audit_tasks`` / ``audits``, and
# the audit snapshot/audit tables CASCADE into ``audit_tasks`` (the task row
# sits late in the order, entangled in the artifact cycle). Deleting a
# snapshot/audit row therefore cascades into tasks while ledger history still
# exists and trips the RESTRICT guard — so immutable ledger history must be
# emptied BEFORE any table whose delete can cascade into the task cycle.
# Stable sort: only the named tables move, everything else keeps its order.
_DELETE_ORDER.sort(key=lambda table: table.name != "consumable_ledger")

_CLEANUP_SQL = "DO $$ BEGIN SET CONSTRAINTS ALL DEFERRED; {deletes} END $$;".format(
    deletes="".join(
        f'DELETE FROM "{_TEST_SCHEMA}"."{table.name}";' for table in _DELETE_ORDER
    )
)


@pytest.fixture(autouse=True)
async def _reset_pooled_answer_engine_clients():
    """Give every test a clean answer-engine connection pool.

    Adapters reuse a pooled ``httpx.AsyncClient`` per event loop so a run's
    provider calls share keep-alive connections instead of handshaking 30 times.
    That cache would otherwise outlive a test: whichever test happened to make
    the first provider call would fix the client every later test reuses,
    silently defeating per-test transport stubs and leaking sockets across the
    loops pytest-asyncio hands out.
    """
    from app.connectors.answer_engines.http_client import aclose_shared_clients

    await aclose_shared_clients()
    yield
    await aclose_shared_clients()


@pytest.fixture(autouse=True)
def _pin_site_health_sample_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the suite from dev ``.env`` sample-policy overrides.

    The neutral Site Health sample policy is settings-driven (the dev ``.env``
    ships a raised ``SITE_HEALTH_SAMPLE_URL_LIMIT`` for full-feature testing).
    Tests assert the SHIPPED defaults, so pin both the analysis budget and the
    decoupled inventory cap back to their constants for every test regardless
    of the developer's local env.
    """
    from app.core.config.site_health_crawl_policy import (
        SAMPLE_DISCOVERY_URL_CAP,
        SAMPLE_URL_LIMIT,
    )
    from app.core.config.site_health_runtime import (
        site_health_settings,
    )

    monkeypatch.setattr(site_health_settings, "sample_url_limit", SAMPLE_URL_LIMIT)
    monkeypatch.setattr(
        site_health_settings, "sample_discovery_url_cap", SAMPLE_DISCOVERY_URL_CAP
    )


@pytest.fixture(autouse=True)
def _pin_audit_prompt_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the suite a configured funded/trial prompt-count policy.

    The shipped default is UNSET (``audit_prompt_count is None``), under
    which funded and trial audit creation fails closed with
    ``prompt_count_policy_unconfigured``. Tests written against the
    funded/trial paths exercise budget/credit/rate mechanics, not the
    count policy, so the suite runs with a generous configured count; the
    unset/configured enforcement itself is pinned explicitly by the
    topical-binding tests (which monkeypatch this knob back to None or to a
    small limit).
    """
    from app.core.config.audits import audit_settings

    monkeypatch.setattr(audit_settings, "audit_prompt_count", 500)


@pytest.fixture(autouse=True)
def _seed_test_funded_cost_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep funded mechanics testable without enabling them in production.

    Production intentionally ships no current-route execution observation and
    therefore fails funded admission closed. Component tests that exercise
    reservations, settlement, and concurrency need one explicit test-only audit
    observation; every other route remains unresolved.
    """
    from app.core.config.costs import (
        _EXPECTED_COST_CATALOG,
        ROUTE_CLAUDE,
        _ExpectedCostEstimate,
    )

    monkeypatch.setitem(
        _EXPECTED_COST_CATALOG,
        ROUTE_CLAUDE,
        _ExpectedCostEstimate(
            token_cost_microusd=2_890,
            search_fee_microusd=10_000,
            expected_searches=3,
        ),
    )


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create a throwaway session database on the configured Postgres server.

    Reuses the server (host/port/credentials) resolved at import time from
    ``TEST_DATABASE_URL`` / ``DATABASE_URL`` — never from ``.env`` — but never
    touches that server's own database: a dedicated
    ``citeladder_tests_<runid>`` database is created up front and force-dropped
    on teardown, so test state can never persist between runs.
    """
    base = make_url(settings.database_url)
    db_name = f"citeladder_tests_{_TEST_RUN_ID}"
    admin_dsn = base.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )

    async def _admin_execute(statement: str) -> None:
        conn = await asyncpg.connect(dsn=admin_dsn)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    try:
        asyncio.run(_admin_execute(f'CREATE DATABASE "{db_name}"'))
    except (OSError, asyncpg.PostgresError) as exc:
        # The suite deliberately does not read `.env`, so a developer whose
        # Postgres is not on the default host/port has to say where it is. Say
        # exactly that, rather than surfacing a bare connection refusal.
        raise pytest.UsageError(
            f"Cannot reach Postgres at {base.host}:{base.port} as "
            f"{base.username!r} ({type(exc).__name__}: {exc}).\n"
            "The test suite never reads .env. Export TEST_DATABASE_URL (or "
            "DATABASE_URL) with the server it should create its throwaway "
            "test database on, for example:\n"
            "  $env:TEST_DATABASE_URL = "
            "'postgresql+asyncpg://postgres:<password>@127.0.0.1:5432/citeladder'"
        ) from exc
    try:
        yield base.set(database=db_name).render_as_string(hide_password=False)
    finally:
        # FORCE (PG13+) disconnects any lingering sessions before the drop.
        asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


@pytest_asyncio.fixture(scope="session")
async def _schema_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Build the test schema ONCE per session and yield a scoped engine.

    Creating ``Base.metadata`` per test is prohibitively slow: the models carry
    67 tables and 184 indexes, so a per-test ``create_all`` costs ~250 DDL
    round-trips *per test* (~1s of setup each, minutes of CI wall-clock across
    the suite). The schema is immutable during a run, so it is built once and
    every test reuses it; isolation comes from truncating rows between tests
    (see ``session_factory``), which is orders of magnitude cheaper than DDL.

    The engine — and therefore its connection pool — is session-scoped for the
    same reason: a per-test engine reconnects to Postgres on every test.
    """
    quoted = f'"{_TEST_SCHEMA}"'
    engine = create_async_engine(test_database_url, future=True, echo=False)
    scoped_engine = engine.execution_options(schema_translate_map={None: _TEST_SCHEMA})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted}"))
    async with scoped_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield scoped_engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    _schema_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory bound to the shared per-session test schema.

    Every table is emptied on teardown so tests never leak state into each
    other — the same isolation the old per-test schema gave, without paying to
    rebuild the schema each time. See ``_CLEANUP_SQL`` for why that is a batched
    DELETE rather than a TRUNCATE.

    The factory stays bound to the shared engine (rather than to a single
    connection inside an outer transaction that gets rolled back) because the
    queue tests exercise ``SELECT ... FOR UPDATE SKIP LOCKED`` from concurrent
    sessions: they need genuinely separate connections, which a rollback-based
    fixture could not give them.

    The keyword arguments MUST mirror ``app.core.database.SessionLocal``.
    ``autoflush`` was the one that did not: production disables it, the fixture
    inherited SQLAlchemy's ``True``, and so every component test ran with
    different write-visibility semantics than the code it was testing. Under
    that gap a ``session.add`` followed by a SELECT read back the pending row
    in tests and silently did not in production — which let the crawl-finalize
    issues ship missing from every snapshot rollup while the test asserting
    ``snapshot.issue_count == len(issues)`` passed.
    """
    factory = async_sessionmaker(
        _schema_engine,
        expire_on_commit=False,
        class_=AsyncSession,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        async with _schema_engine.begin() as conn:
            await conn.execute(text(_CLEANUP_SQL))


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client whose DB dependency is bound to the per-test schema.

    Overrides ``get_session`` so every request opens a fresh session against
    the isolated schema, mirroring production request scoping.
    """
    from app.core.database import get_session

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_session, None)
