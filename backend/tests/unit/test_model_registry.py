"""Pure guards for ORM model registration used by Alembic metadata."""

from __future__ import annotations

from sqlalchemy.orm import configure_mappers

import app.models as models


def test_models_are_exported_and_registered_once() -> None:
    expected = {
        "OpportunityGuidance": "opportunity_guidance",
        "CommerceProduct": "commerce_products",
        "CommerceProductObservation": "commerce_product_observations",
        "CommerceShelfSnapshot": "commerce_shelf_snapshots",
        "WorkspaceSiteHealthRuntime": "workspace_site_health_runtime",
        "SiteHealthProfile": "site_health_profiles",
        "SiteCrawl": "site_crawls",
        "SiteCrawlPhaseRun": "site_crawl_phase_runs",
        "SiteDiscoveryFrontier": "site_discovery_frontier",
        "SiteUrl": "site_urls",
        "SiteUrlObservation": "site_url_observations",
        "MonitoredSiteUrl": "monitored_site_urls",
        "SiteCrawlTask": "site_crawl_tasks",
        "SiteFetchAttempt": "site_fetch_attempts",
        "SiteFetchArtifact": "site_fetch_artifacts",
        "SitePageAnalysis": "site_page_analyses",
        "SiteRuleEvaluation": "site_rule_evaluations",
        "SiteIssue": "site_issues",
        "SiteHealthSnapshot": "site_health_snapshots",
        "SiteCrawlEvent": "site_crawl_events",
    }

    retired_models = {
        "SiteLinkReference",
        "SiteLinkGraphSnapshot",
        "SiteLinkGraphNode",
        "SiteLinkGraphEdge",
    }
    retired_tables = {
        "site_link_references",
        "site_link_graph_snapshots",
        "site_link_graph_nodes",
        "site_link_graph_edges",
    }
    assert retired_models.isdisjoint(models.__all__)
    assert retired_tables.isdisjoint(models.Base.metadata.tables)

    assert len(models.__all__) == len(set(models.__all__))
    for model_name, table_name in expected.items():
        assert model_name in models.__all__
        assert getattr(models, model_name).__table__.name == table_name
        assert table_name in models.Base.metadata.tables

    configure_mappers()


def test_site_health_critical_metadata_contracts() -> None:
    task = models.SiteCrawlTask.__table__
    assert "uq_site_crawl_task_slot" in {
        constraint.name for constraint in task.constraints
    }
    assert "uq_site_crawl_task_idempotency_key" in {
        constraint.name for constraint in task.constraints
    }
    assert "ix_site_crawl_tasks_claim" in {index.name for index in task.indexes}

    observation = models.SiteUrlObservation.__table__
    assert {
        "fk_site_url_observation_crawl_scoped",
        "fk_site_url_observation_site_url_scoped",
        "uq_site_url_observation",
    } <= {constraint.name for constraint in observation.constraints}

    analysis = models.SitePageAnalysis.__table__
    assert "uq_site_page_analysis_version" not in {
        constraint.name for constraint in analysis.constraints
    }
    assert "uq_site_page_analysis_current" in {index.name for index in analysis.indexes}
