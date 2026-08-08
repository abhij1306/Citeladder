"""Pure request-control tests for value-aware Site Health crawl planning."""

from __future__ import annotations

import ast
import inspect
import uuid

import pytest
from pydantic import ValidationError

from app.core.config.site_health import site_health_settings
from app.core.config.site_health_page_profiles import PAGE_PROFILE_RULE_VERSION
from app.domain.site_health import discovery
from app.domain.site_health.api_schemas import (
    StartAnalysisRequest,
    StartDiscoveryRequest,
)
from app.domain.site_health.planner import (
    CrawlPlanError,
    _controls_for_request,
    _frozen_configuration,
    _preview_input_rows,
    create_crawl,
    create_page_rerun_crawl,
)
from app.domain.site_health.schemas import FrontierCandidate


def test_production_controls_keep_the_automatic_page_limit(monkeypatch):
    monkeypatch.setattr(
        "app.domain.site_health.planner.site_health_settings.advanced_controls_enabled",
        False,
    )
    mode, limit, seeds, page_kinds = _controls_for_request(
        input_mode=None,
        requested_page_limit=None,
        seed_urls=None,
        page_kinds=None,
    )
    assert mode == "auto"
    assert limit == 10
    assert seeds == []
    assert page_kinds == []


def test_phase_request_counts_must_be_positive_and_bounded():
    with pytest.raises(ValidationError):
        StartDiscoveryRequest(additional_url_count=0)
    with pytest.raises(ValidationError):
        StartAnalysisRequest(
            requested_url_count=0,
            expected_selection_version=0,
        )
    with pytest.raises(ValidationError):
        StartAnalysisRequest(
            requested_url_count=1,
            site_url_ids=[uuid.uuid4()] * (site_health_settings.max_analysis_urls + 1),
            expected_selection_version=0,
        )


def test_production_rejects_development_only_exact_mode(monkeypatch):
    monkeypatch.setattr(
        "app.domain.site_health.planner.site_health_settings.advanced_controls_enabled",
        False,
    )
    with pytest.raises(CrawlPlanError, match="advanced crawl controls"):
        _controls_for_request(
            input_mode="exact_urls",
            requested_page_limit=None,
            seed_urls=["https://example.com/products/widget"],
            page_kinds=None,
        )


def test_development_allows_exact_mode_with_frozen_requested_limit(monkeypatch):
    monkeypatch.setattr(
        "app.domain.site_health.planner.site_health_settings.advanced_controls_enabled",
        True,
    )
    mode, limit, seeds, page_kinds = _controls_for_request(
        input_mode="exact_urls",
        requested_page_limit=3,
        seed_urls=["https://example.com/products/widget"],
        page_kinds=["product"],
    )
    assert (mode, limit, seeds, page_kinds) == (
        "exact_urls",
        3,
        ["https://example.com/products/widget"],
        ["product"],
    )


def test_preview_parses_csv_text_and_json_without_creating_a_crawl():
    raw = "https://example.com/a\nhttps://example.com/b"
    assert _preview_input_rows(raw, "text") == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert _preview_input_rows(raw, "csv") == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert _preview_input_rows('{"urls":["https://example.com/a"]}', "json") == [
        "https://example.com/a"
    ]


def test_frozen_configuration_stamps_supplemental_page_profile_rule_version():
    class Runtime:
        discovery_mode = "sample"
        count_disclosure = False
        sample_url_limit = 10
        monitored_url_limit = 0
        discovery_url_cap = 10
        resolved_registry_revision = "registry-v1"
        resolved_entitlement_lifecycle_version = 1

    configuration = _frozen_configuration(
        root_registrable_domain="example.com",
        include_globs=[],
        exclude_globs=[],
        runtime=Runtime(),
    )

    assert configuration["page_profile_rule_version"] == PAGE_PROFILE_RULE_VERSION
    assert "advanced_controls_enabled" not in configuration


def test_frozen_configuration_only_enables_phase_lifecycle_when_requested():
    class Runtime:
        discovery_mode = "sample"
        count_disclosure = False
        sample_url_limit = 10
        monitored_url_limit = 0
        discovery_url_cap = 10
        resolved_registry_revision = "registry-v1"
        resolved_entitlement_lifecycle_version = 1

    configuration = _frozen_configuration(
        root_registrable_domain="example.com",
        include_globs=[],
        exclude_globs=[],
        runtime=Runtime(),
        advanced_controls_enabled=True,
    )

    assert configuration["advanced_controls_enabled"] is True


def test_normal_and_page_rerun_creation_share_the_frozen_configuration() -> None:
    for creation_path in (create_crawl, create_page_rerun_crawl):
        tree = ast.parse(inspect.getsource(creation_path))
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_frozen_configuration"
            for node in ast.walk(tree)
        )


async def test_hard_excluded_candidate_never_reaches_enqueue_or_fetch(monkeypatch):
    class Crawl:
        configuration = {
            "root_registrable_domain": "example.com",
            "include_globs": [],
            "exclude_globs": [],
            "requested_page_limit": 10,
        }
        sample_mode = False
        admitted_url_count = 0

    async def fail_if_admitted(*_args, **_kwargs):
        raise AssertionError("hard-excluded URL reached admission/enqueue")

    pending_frontier_checked = False

    async def no_automatic_selection(*_args, **_kwargs):
        return None

    async def empty_pending_frontier(*_args, **_kwargs):
        nonlocal pending_frontier_checked
        pending_frontier_checked = True
        return []

    monkeypatch.setattr(discovery, "_upsert_site_url", fail_if_admitted)
    monkeypatch.setattr(discovery, "_automatic_remaining", no_automatic_selection)
    monkeypatch.setattr(discovery, "_pending_frontier", empty_pending_frontier)
    result = await discovery.admit_candidates(
        None,
        crawl=Crawl(),
        candidates=[
            FrontierCandidate(
                url="https://example.com/checkout",
                url_hash="blocked",
                depth=1,
                source_kind="link",
            )
        ],
    )
    assert result.admitted == 0
    assert pending_frontier_checked is True
