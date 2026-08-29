"""The two seams the development seeder monkeypatches or implements.

Both were broken and silently so. ``seed_dev_data`` patched
``app.workers.audit_worker.build_adapter``, an attribute that stopped existing
when the execution path moved to ``app.workers.audit.execution``; the
assignment created a new attribute nobody read, so seeded audits ran against
real providers with fake dev keys. Separately it handed ``SiteHealthWorker`` a
raw ``httpx.MockTransport`` where an ``AcquisitionTransport`` is required, so
every seeded crawl fetch would have raised ``AttributeError`` on the missing
``fetch``.

Nothing failed loudly in either case, because ``scripts/`` was outside the type
gate. It is inside it now, and these tests exercise both seams end to end: the
adapter one by driving the real ``_build_adapter_or_fail`` and checking WHICH
factory it reached, the transport one by calling ``fetch`` and checking what
comes back.
"""

from __future__ import annotations

import types

import pytest

from app.connectors.web_evidence.contracts import (
    AcquisitionTransport,
    FetchRequest,
    ResolvedTarget,
)
from app.core.config.site_health_acquisition import FETCH_PURPOSE_ANALYZE
from app.core.security import encrypt_secret
from app.workers.audit import execution as audit_execution
from scripts.seed_dev_runs import seeded_adapter
from scripts.seed_dev_support import (
    _build_seed_adapter,
    _SeedAcquisitionTransport,
    _SeedStubAdapter,
    _site_transport,
)


class _Executor(audit_execution.AuditExecutionMixin):
    """The mixin alone; only the happy path of the adapter build is driven."""


def _context() -> types.SimpleNamespace:
    """The fields ``_build_adapter_or_fail`` actually reads.

    Deliberately not the real ``ExecutionContext`` dataclass: this test is
    about which factory the method resolves, and a dozen unrelated required
    fields would make it fail for reasons that have nothing to do with that.
    """
    return types.SimpleNamespace(
        logical_engine="chatgpt",
        transport_provider="openai",
        api_key_encrypted=encrypt_secret("dev-fake-key-for-chatgpt"),
        configuration={"country_code": "US"},
        base_url="",
    )


class TestAdapterFactorySeam:
    async def test_the_real_execution_path_reaches_the_seeded_factory(self) -> None:
        """Drive ``_build_adapter_or_fail`` itself, inside ``seeded_adapter``.

        This is the assertion the original bug would have failed: patching a
        module that no longer holds the name leaves the production factory in
        place, and the adapter that comes back is a real provider client.
        """
        with seeded_adapter():
            adapter = await _Executor()._build_adapter_or_fail(_context(), {})

        assert isinstance(adapter, _SeedStubAdapter)
        assert adapter.logical_engine == "chatgpt"
        assert adapter.transport_provider == "openai"

    async def test_outside_the_context_the_production_factory_is_used(self) -> None:
        """The stub must not leak past the ``with`` block."""
        adapter = await _Executor()._build_adapter_or_fail(_context(), {})

        assert not isinstance(adapter, _SeedStubAdapter)

    def test_seeded_adapter_installs_the_stub_and_restores_the_original(self) -> None:
        original = audit_execution.build_adapter

        with seeded_adapter():
            assert audit_execution.build_adapter is _build_seed_adapter

        assert audit_execution.build_adapter is original

    def test_seeded_adapter_restores_the_original_after_a_failure(self) -> None:
        original = audit_execution.build_adapter

        with pytest.raises(RuntimeError):
            with seeded_adapter():
                raise RuntimeError("seed stage blew up")

        assert audit_execution.build_adapter is original


def _target(path: str) -> ResolvedTarget:
    return ResolvedTarget(
        url=f"https://wanderlustgear.com{path}",
        scheme="https",
        host="wanderlustgear.com",
        port=443,
        connect_ip="93.184.216.34",
    )


def _request(path: str) -> FetchRequest:
    return FetchRequest(
        url=f"https://wanderlustgear.com{path}", purpose=FETCH_PURPOSE_ANALYZE
    )


class TestAcquisitionTransportSeam:
    def test_the_seed_transport_satisfies_the_acquisition_contract(self) -> None:
        """``SecureFetcher`` calls ``transport.fetch(request, target, ...)``.

        An ``httpx.MockTransport`` has ``handle_async_request``, not ``fetch``,
        so passing one straight through fails at the first crawl fetch.
        """
        transport = _site_transport()

        assert isinstance(transport, AcquisitionTransport)
        assert hasattr(transport, "fetch")

    async def test_fetch_returns_the_underlying_response_unchanged(self) -> None:
        result = await _site_transport().fetch(
            _request("/backpacks"),
            _target("/backpacks"),
            max_wire_bytes=1_000_000,
            max_decoded_bytes=1_000_000,
            timeout_seconds=5.0,
        )

        assert result.status_code == 200
        assert result.content_type == "text/html"
        assert b"Backpacks Catalog" in result.body
        assert result.requested_url == "https://wanderlustgear.com/backpacks"
        assert result.final_url == "https://wanderlustgear.com/backpacks"
        assert result.wire_bytes == len(result.body)

    async def test_fetch_preserves_the_headers_the_seeded_page_declares(self) -> None:
        """The home page ships gzipped with an HSTS header, on purpose.

        Those headers are what the crawl's delivery-signal rules read, so the
        adapter must pass them through rather than normalizing them away. The
        BODY, though, arrives already decoded: ``httpx`` transparently inflates
        a ``content-encoding: gzip`` response on ``aread()``, so callers see
        markup while the header still advertises the encoding.
        """
        result = await _site_transport().fetch(
            _request("/"),
            _target("/"),
            max_wire_bytes=1_000_000,
            max_decoded_bytes=1_000_000,
            timeout_seconds=5.0,
        )

        assert result.redacted_headers["content-encoding"] == "gzip"
        assert "strict-transport-security" in result.redacted_headers
        assert b"Wanderlust Gear Co. - Home" in result.body

    async def test_an_unseeded_path_comes_back_as_a_404(self) -> None:
        result = await _site_transport().fetch(
            _request("/nope"),
            _target("/nope"),
            max_wire_bytes=1_000_000,
            max_decoded_bytes=1_000_000,
            timeout_seconds=5.0,
        )

        assert result.status_code == 404

    async def test_a_response_over_the_configured_bounds_raises(self) -> None:
        """The bound is a fixture guarantee, not a soft limit.

        A seeded page that outgrows the crawl's byte ceiling must fail the seed
        run loudly rather than being silently truncated into a thin page the
        rules then score as a content gap.
        """
        with pytest.raises(AssertionError, match="exceeded configured crawl bounds"):
            await _site_transport().fetch(
                _request("/backpacks"),
                _target("/backpacks"),
                max_wire_bytes=10,
                max_decoded_bytes=10,
                timeout_seconds=5.0,
            )

    async def test_an_error_from_the_underlying_handler_propagates(self) -> None:
        """A handler fault is a broken fixture; it must not become a 4xx."""

        def _boom(_request: object) -> None:
            raise RuntimeError("offline page handler failed")

        with pytest.raises(RuntimeError, match="offline page handler failed"):
            await _SeedAcquisitionTransport(_boom).fetch(
                _request("/"),
                _target("/"),
                max_wire_bytes=1_000_000,
                max_decoded_bytes=1_000_000,
                timeout_seconds=5.0,
            )
