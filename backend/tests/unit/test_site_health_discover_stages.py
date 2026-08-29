"""Defensive sitemap admission tests."""

from __future__ import annotations

import inspect

from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.workers.site_health.phases import discover_stages


class _Collector:
    urls = ("https://example.com/unsafe", "https://example.com/accepted")


def test_sitemap_admission_skips_one_url_when_identity_policy_rejects(
    monkeypatch,
) -> None:
    original = discover_stages.canonical_identity

    def reject_one(url: str):
        if url.endswith("/unsafe"):
            raise UrlPolicyError("unsafe sitemap URL")
        return original(url)

    monkeypatch.setattr(discover_stages, "canonical_identity", reject_one)

    assert discover_stages._admitted_sitemap_urls(
        _Collector(),
        root_registrable_domain="example.com",
        include_globs=None,
        exclude_globs=None,
    ) == ("https://example.com/accepted",)


def test_discover_persistence_uses_the_explicit_context_seam() -> None:
    assert not hasattr(discover_stages, "DiscoverPersistenceMixin")
    site_setup_parameters = inspect.signature(
        discover_stages.collect_site_setup
    ).parameters
    assert next(iter(site_setup_parameters)) == "ctx"
    assert (
        next(iter(inspect.signature(discover_stages._persist_discover).parameters))
        == "ctx"
    )
