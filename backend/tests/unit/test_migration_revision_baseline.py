"""Static guards for CiteLadder's pre-launch, single-revision baseline."""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS_DIR = _BACKEND_ROOT.parent / "migrations" / "versions"
_BASELINE = _VERSIONS_DIR / "0001_initial.py"


def _created_tables(source: str) -> set[str]:
    tree = ast.parse(source)
    tables: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        tables.add(node.args[0].value)
    return tables


def test_0001_initial_is_the_only_migration_revision() -> None:
    revisions = sorted(_VERSIONS_DIR.glob("*.py"))

    assert revisions == [_BASELINE]
    source = _BASELINE.read_text(encoding="utf-8")
    assert 'revision = "0001_initial"' in source
    assert "down_revision = None" in source
    assert len(_created_tables(source)) == 110
    assert "industry_pack_id" not in source
    assert "from app.models" not in source


def test_baseline_contains_site_health_guidance_and_commerce_schema() -> None:
    source = _BASELINE.read_text(encoding="utf-8")
    tables = _created_tables(source)

    assert "opportunity_guidance" in tables
    assert (
        not {
            "commerce_discovery_runs",
            "commerce_discovery_tasks",
            "commerce_discovery_artifacts",
            "commerce_discovery_candidates",
            "commerce_candidate_reviews",
        }
        & tables
    )

    assert {
        "workspace_site_health_runtime",
        "site_health_profiles",
        "site_crawls",
        "site_crawl_phase_runs",
        "site_discovery_frontier",
        "site_urls",
        "site_url_observations",
        "monitored_site_urls",
        "site_crawl_tasks",
        "site_fetch_attempts",
        "site_fetch_artifacts",
        "site_page_analyses",
        "site_rule_evaluations",
        "site_issues",
        "site_health_snapshots",
        "site_page_link_metrics",
        "site_crawl_events",
    } <= tables

    for column in (
        "acquisition_transport",
        "acquisition_rung",
        "acquisition_trigger",
        "impersonation_profile",
        "acquisition_options",
        "acquisition_policy_version",
        "source_artifact_id",
    ):
        assert f'"{column}"' in source
