"""Site Health entitlement, inventory, page, issue, and export projections."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    CRAWL_STATUS_COMPLETED,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
)
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from tests.component.site_health_api_helpers import _register, _seed_scenario
from tests.component.site_health_helpers import seed_monitored_urls_allowance

pytestmark = pytest.mark.asyncio


async def test_entitlements_unresolved_seed_and_disclosure(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A workspace with no billing link resolves fail-closed: ``unresolved``,
    zero monitored limit, and no discovered-total disclosure."""
    await _register(client, "ent@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="ent@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.get("/api/v1/entitlements", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == str(scn.workspace_id)
    assert body["access_mode"] == "unresolved"
    assert body["resolver_status"] == "entitlement_unresolved"
    assert body["monitored_url_limit"] == 0
    # Unresolved entitlements never disclose the discovered total.
    assert body["count_disclosure"] is False
    assert body["contributing_grant_ids"] == []


async def test_entitlements_full_allowance_discloses(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A granted monitored-URL allowance projects the full mode: exact limit,
    disclosure on, and the contributing grant id surfaced."""

    await _register(client, "ent-full@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="ent-full@example.com")
        await seed_monitored_urls_allowance(
            session, workspace_id=scn.workspace_id, monitored_urls=50
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.get("/api/v1/entitlements", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == str(scn.workspace_id)
    assert body["access_mode"] == "full"
    assert body["resolver_status"] == "resolved"
    assert body["monitored_url_limit"] == 50
    assert body["count_disclosure"] is True
    assert len(body["contributing_grant_ids"]) == 1


async def test_crawl_summary_and_list(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "crawl@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="crawl@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    summary = await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=headers)
    assert summary.status_code == 200
    body = summary.json()
    assert body["id"] == str(scn.crawl_id)
    assert body["status"] == CRAWL_STATUS_COMPLETED
    assert body["analyzed_count"] == 2

    listing = await client.get(
        f"/api/v1/site-crawls?project_id={scn.project_id}", headers=headers
    )
    assert listing.status_code == 200
    assert any(row["id"] == str(scn.crawl_id) for row in listing.json()["items"])


async def test_inventory_monitored_filter(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "inv@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="inv@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    all_rows = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory", headers=headers
    )
    assert all_rows.status_code == 200
    assert len(all_rows.json()["items"]) == 3

    monitored = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory?monitored=true",
        headers=headers,
    )
    assert monitored.status_code == 200
    mitems = monitored.json()["items"]
    assert len(mitems) == 1
    assert mitems[0]["site_url_id"] == str(scn.monitored_url_id)
    assert mitems[0]["monitored"] is True


async def test_inventory_keyset_traversal_stable(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "keyset@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="keyset@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        path = f"/api/v1/site-crawls/{scn.crawl_id}/inventory?limit=1"
        if cursor:
            path += f"&cursor={cursor}"
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200
        page = resp.json()
        seen.extend(row["site_url_id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 3
    assert len(set(seen)) == 3  # no duplicates across pages


async def test_pages_and_issues_projection(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "pages@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="pages@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    pages = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages", headers=headers
    )
    assert pages.status_code == 200
    items = pages.json()["items"]
    # The pages view projects the whole project URL set (3), each row carrying
    # the strict `monitored` flag and a derived presentation status.
    assert len(items) == 3
    assert all("monitored" in row for row in items)
    monitored_flags = {row["site_url_id"]: row["monitored"] for row in items}
    assert monitored_flags[str(scn.monitored_url_id)] is True
    # The analyzed URLs surface a completed status.
    statuses = {row["site_url_id"]: row["analysis_status"] for row in items}
    assert statuses[str(scn.issue_url_id)] == PAGE_ANALYSIS_STATUS_COMPLETED

    # Filtering by a monitored toggle narrows the set.
    only_monitored = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages?monitored=true",
        headers=headers,
    )
    assert only_monitored.status_code == 200
    m_items = only_monitored.json()["items"]
    assert len(m_items) == 1
    assert m_items[0]["site_url_id"] == str(scn.monitored_url_id)

    # Grouped issues: one group, critical, canonical id resolved, affected=1.
    issues = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues", headers=headers
    )
    assert issues.status_code == 200
    ibody = issues.json()
    assert len(ibody["items"]) == 1
    group = ibody["items"][0]
    assert group["rule_id"] == "technical.title_present"
    assert group["title"] == "Missing page title"
    assert group["severity"] == "critical"
    assert group["affected_url_count"] == 1
    assert ibody["summary"]["issue_count"] == 1
    assert ibody["summary"]["affected_url_count"] == 1

    # Issue detail: canonical row, affected URLs, current label.
    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{scn.canonical_issue_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    dbody = detail.json()
    assert dbody["title"] == "Missing page title"
    assert dbody["affected_url_count"] == 1
    assert any(
        au["site_url_id"] == str(scn.issue_url_id) for au in dbody["affected_urls"]
    )


async def test_issue_catalog_separates_defect_and_advisory_quantities(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "finding-classes@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="finding-classes@example.com")
        issue = await session.scalar(
            select(SiteIssue).where(
                SiteIssue.crawl_id == scn.crawl_id,
                SiteIssue.rule_id == "technical.title_present",
            )
        )
        assert issue is not None
        issue.finding_class = "advisory"
        issue.description = "Advisory metadata"
        defect_analysis = await session.scalar(
            select(SitePageAnalysis).where(
                SitePageAnalysis.crawl_id == scn.crawl_id,
                SitePageAnalysis.site_url_id != issue.site_url_id,
            )
        )
        assert defect_analysis is not None
        defect_evaluation = SiteRuleEvaluation(
            workspace_id=scn.workspace_id,
            analysis_id=defect_analysis.id,
            source_artifact_id=defect_analysis.artifact_id,
            rule_id=issue.rule_id,
            dimension=issue.dimension,
            category=issue.category,
            severity="high",
            finding_class="defect",
            weight=1.0,
            outcome=RULE_OUTCOME_FAIL,
            evidence={"observed": "defect"},
            analyzer_version="v1",
            rule_version="v1",
        )
        session.add(defect_evaluation)
        await session.flush()
        session.add(
            SiteIssue(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                crawl_id=scn.crawl_id,
                site_url_id=defect_analysis.site_url_id,
                analysis_id=defect_analysis.id,
                evaluation_id=defect_evaluation.id,
                source_artifact_id=defect_analysis.artifact_id,
                rule_id=issue.rule_id,
                dimension=issue.dimension,
                category=issue.category,
                severity="high",
                finding_class="defect",
                evidence={"observed": "defect"},
                description="Defect metadata",
                remediation="Fix the defect.",
                analyzer_version="v1",
                rule_version="v1",
            )
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    defects = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues", headers=headers
    )
    assert defects.status_code == 200
    defect_body = defects.json()
    assert defect_body["items"][0]["description"] == "Defect metadata"
    assert defect_body["summary"] == {
        "issue_count": 1,
        "defect_issue_type_count": 1,
        "advisory_issue_type_count": 1,
        "occurrence_count": 1,
        "severity_counts": {
            "critical": 0,
            "high": 1,
            "medium": 0,
            "low": 0,
            "info": 0,
        },
        "dimension_counts": {"aeo": 0, "technical": 1},
        "affected_url_count": 1,
        "monitored_affected_url_count": 1,
    }

    advisories = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues?finding_class=advisory",
        headers=headers,
    )
    assert advisories.status_code == 200
    body = advisories.json()
    assert body["items"][0]["finding_class"] == "advisory"
    assert body["items"][0]["description"] == "Advisory metadata"
    assert body["items"][0]["id"] != defect_body["items"][0]["id"]
    assert body["summary"]["occurrence_count"] == 1
    assert body["summary"]["affected_url_count"] == 1
    assert body["summary"]["severity_counts"] == {
        "critical": 0,
        "high": 1,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{body['items'][0]['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["finding_class"] == "advisory"
    assert detail_body["description"] == "Advisory metadata"
    assert detail_body["affected_url_count"] == 1
    assert [row["site_url_id"] for row in detail_body["affected_urls"]] == [
        str(scn.issue_url_id)
    ]


async def test_page_type_projection_filters_and_exports(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """v2 P1: page rows/detail carry page_kind, the pages/inventory/issues
    lists filter by it, and all three export views gain the column."""
    await _register(client, "pagetype@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="pagetype@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # Page rows project the persisted page_kind (None for the unanalyzed URL).
    pages = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages", headers=headers
    )
    assert pages.status_code == 200
    types = {row["site_url_id"]: row["page_kind"] for row in pages.json()["items"]}
    assert types[str(scn.monitored_url_id)] == "article"
    assert types[str(scn.issue_url_id)] == "product"
    assert None in types.values()  # the third, unanalyzed URL

    # Pages page_kind filter: exact match; unknown values match nothing.
    filtered = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages?page_kind=article",
        headers=headers,
    )
    assert filtered.status_code == 200
    f_items = filtered.json()["items"]
    assert [row["site_url_id"] for row in f_items] == [str(scn.monitored_url_id)]
    unknown = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages?page_kind=not_a_type",
        headers=headers,
    )
    assert unknown.status_code == 200
    assert unknown.json()["items"] == []

    # Inventory rows carry page_kind and filter by it too.
    inventory = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory?page_kind=product",
        headers=headers,
    )
    assert inventory.status_code == 200
    i_items = inventory.json()["items"]
    assert [row["site_url_id"] for row in i_items] == [str(scn.issue_url_id)]
    assert i_items[0]["page_kind"] == "product"

    # Per-URL detail carries page_kind AND its persisted classifier evidence
    # (the "why this type?" disclosure payload); the lightweight list rows
    # above never project the evidence.
    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["page_kind"] == "product"
    detail_evidence = detail.json()["page_kind_evidence"]
    assert detail_evidence is not None
    assert detail_evidence["classifier_version"] == "sh-classifier-1"
    assert detail_evidence["classified_by"] == "path_pattern"
    assert detail_evidence["signals"][0]["page_kind"] == "product"
    assert "page_kind_evidence" not in pages.json()["items"][0]
    assert "page_kind_evidence" not in i_items[0]

    # Issues filter by the affected analysis's page_kind.
    product_issues = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues?page_kind=product",
        headers=headers,
    )
    assert product_issues.status_code == 200
    assert len(product_issues.json()["items"]) == 1
    assert product_issues.json()["summary"]["issue_count"] == 1
    article_issues = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues?page_kind=article",
        headers=headers,
    )
    assert article_issues.status_code == 200
    assert article_issues.json()["items"] == []
    assert article_issues.json()["summary"]["issue_count"] == 0

    # Issue detail: affected URLs carry their analysis's page_kind.
    issue_detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{scn.canonical_issue_id}",
        headers=headers,
    )
    assert issue_detail.status_code == 200
    affected = issue_detail.json()["affected_urls"]
    assert len(affected) == 1
    assert affected[0]["page_kind"] == "product"

    # All three export views carry the page_kind column.
    pages_csv = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=pages",
        headers=headers,
    )
    assert pages_csv.status_code == 200
    header = pages_csv.text.splitlines()[0].split(",")
    assert "page_kind" in header
    assert "article" in pages_csv.text
    assert "product" in pages_csv.text

    issues_csv = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=issues",
        headers=headers,
    )
    assert issues_csv.status_code == 200
    i_header = issues_csv.text.splitlines()[0].split(",")
    assert "page_kind" in i_header
    # The single issue group affected a product page.
    row = issues_csv.text.splitlines()[1].split(",")
    assert row[i_header.index("page_kind")] == "product"

    inventory_md = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.md?view=inventory",
        headers=headers,
    )
    assert inventory_md.status_code == 200
    assert "| page_kind |" in inventory_md.text


async def test_page_detail_and_history(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "detail@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="detail@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["facts"]["h1_count"] == 1
    assert body["facts"]["word_count"] == 400
    assert body["facts"]["internal_link_count"] == 1
    assert body["facts"]["external_link_count"] == 1
    assert body["delivery"]["field_cwv_available"] is False
    assert body["delivery"]["html_bytes"] == 2048
    # The failing rule surfaces as an issue row on the page detail.
    assert any(iss["rule_id"] == "technical.title_present" for iss in body["issues"])

    history = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}/issue-history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1

    grouped_history = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}/issue-history?view=grouped",
        headers=headers,
    )
    assert grouped_history.status_code == 200
    grouped_body = grouped_history.json()
    assert grouped_body["since_previous_crawl"]["has_previous_crawl"] is False
    assert grouped_body["items"][0]["occurrence_count"] == 1
    assert grouped_body["items"][0]["current_transition"] == "new"


async def test_exports_media_type_and_filename(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "export@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="export@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    csv_resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=issues",
        headers=headers,
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_resp.headers["content-disposition"]
    assert str(scn.crawl_id) in csv_resp.headers["content-disposition"]
    assert "technical.title_present" in csv_resp.text

    md_resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.md?view=pages",
        headers=headers,
    )
    assert md_resp.status_code == 200
    assert md_resp.headers["content-type"].startswith("text/markdown")
    assert md_resp.text.startswith("# ")


async def test_events_replay(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "events@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="events@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/events", headers=headers
    )
    assert resp.status_code == 200
    events = resp.json()
    # JSON replay returns a bare ordered list of redacted events.
    assert isinstance(events, list)
    assert any(e["event_type"] == "crawl.completed" for e in events)


async def test_second_workspace_isolation(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A user with two workspaces sees only the selected workspace's data.

    Reads, exports, and events for a crawl must 404 when the active
    workspace (X-Workspace-Id) is a different one the user also belongs to.
    """
    await _register(client, "multi@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="multi@example.com")
        # Second workspace the same user belongs to.
        user = await session.scalar(
            select(User).where(User.email == "multi@example.com")
        )
        assert user is not None
        other_ws = Workspace(name="Other WS")
        session.add(other_ws)
        await session.flush()
        session.add(
            WorkspaceMember(
                workspace_id=other_ws.id,
                user_id=user.id,
                role="owner",
            )
        )
        await session.commit()
        other_ws_id = other_ws.id

    other_headers = {"X-Workspace-Id": str(other_ws_id)}

    # Crawl summary, exports, and events are all scoped to the workspace.
    assert (
        await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=issues",
            headers=other_headers,
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/site-crawls/{scn.crawl_id}/events", headers=other_headers
        )
    ).status_code == 404

    # The correct workspace still resolves the crawl.
    ok_headers = {"X-Workspace-Id": str(scn.workspace_id)}
    assert (
        await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=ok_headers)
    ).status_code == 200
