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
        "SiteDiscoveryFrontier": "site_discovery_frontier",
        "SiteUrl": "site_urls",
        "SiteUrlObservation": "site_url_observations",
        "MonitoredSiteUrl": "monitored_site_urls",
        "SiteCrawlTask": "site_crawl_tasks",
        "SiteFetchAttempt": "site_fetch_attempts",
        "SiteFetchArtifact": "site_fetch_artifacts",
        "SitePageAnalysis": "site_page_analyses",
        "SitePageLinkMetric": "site_page_link_metrics",
        "SiteObservedArchitecture": "site_observed_architectures",
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

    link_metric = models.SitePageLinkMetric.__table__
    assert {
        "fk_site_page_link_metric_crawl_scoped",
        "fk_site_page_link_metric_site_url_scoped",
        "uq_site_page_link_metric",
    } <= {constraint.name for constraint in link_metric.constraints}

    architecture = models.SiteObservedArchitecture.__table__
    assert {
        "fk_site_observed_architecture_crawl_scoped",
        "uq_site_observed_architecture",
    } <= {constraint.name for constraint in architecture.constraints}

    evaluation = models.SiteRuleEvaluation.__table__
    assert "source_architecture_id" in evaluation.c
    assert "scope" in evaluation.c
    assert "ck_site_rule_evaluations_scope" in {
        constraint.name for constraint in evaluation.constraints
    }
    evaluation_unique = next(
        constraint
        for constraint in evaluation.constraints
        if constraint.name == "uq_site_rule_evaluation"
    )
    assert {column.name for column in evaluation_unique.columns} == {
        "analysis_id",
        "rule_id",
        "source_architecture_id",
    }
    assert evaluation_unique.dialect_options["postgresql"]["nulls_not_distinct"]
