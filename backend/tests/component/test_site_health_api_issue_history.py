"""Site Health crawl scoping, issue history, pagination, and rerun scenarios."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    INVENTORY_SOURCE_CRAWL_IDS_KEY,
)
from app.models.site_health.analysis import SiteIssue
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl, SiteUrlObservation
from tests.component.site_health_api_helpers import (
    _add_second_crawl,
    _hash,
    _register,
    _seed_issue_for_url,
    _seed_scenario,
)
from tests.component.site_health_helpers import seed_monitored_urls_allowance

pytestmark = pytest.mark.asyncio


async def test_selected_crawl_scoping_no_downgrade_leakage(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 1: a later crawl only surfaces the URLs IT admitted.

    The first crawl admits all 3 URLs (a/b/c). A later "downgraded" crawl of the
    same project admits only the root (a). Inventory / pages / page-detail /
    exports for the later crawl must never leak b/c from the project's fuller
    historical catalog.
    """
    await _register(client, "scope@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="scope@example.com")
        second = await _add_second_crawl(session, scn, admit_slugs=("a",))
        second_id = second.id
        # Resolve b's site_url_id (admitted to the first crawl, not the second).
        url_b = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == scn.project_id,
                SiteUrl.normalized_url == "https://acme.test/b",
            )
        )
        assert url_b is not None
        url_b_id = url_b.id
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # First crawl still admits all three.
    first_inv = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory", headers=headers
    )
    assert len(first_inv.json()["items"]) == 3

    # Second crawl admitted only the root: inventory + pages scope to it.
    inv = await client.get(
        f"/api/v1/site-crawls/{second_id}/inventory", headers=headers
    )
    assert inv.status_code == 200
    inv_urls = {row["normalized_url"] for row in inv.json()["items"]}
    assert inv_urls == {"https://acme.test/a"}

    pages = await client.get(f"/api/v1/site-crawls/{second_id}/pages", headers=headers)
    assert {row["normalized_url"] for row in pages.json()["items"]} == {
        "https://acme.test/a"
    }

    # A URL the first crawl admitted but the second did not is a 404 on the
    # second crawl's page-detail (no cross-crawl catalog leak).
    leaked = await client.get(
        f"/api/v1/site-crawls/{second_id}/pages/{url_b_id}", headers=headers
    )
    assert leaked.status_code == 404

    # Exports over the later crawl carry only its admitted URL.
    csv_resp = await client.get(
        f"/api/v1/site-crawls/{second_id}/export.csv?view=inventory",
        headers=headers,
    )
    assert csv_resp.status_code == 200
    assert "https://acme.test/a" in csv_resp.text
    assert "https://acme.test/b" not in csv_resp.text
    assert "https://acme.test/c" not in csv_resp.text


async def test_starter_recrawl_keeps_prior_discovered_inventory_visible(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A fresh analysis crawl must not collapse All Discovered to its subset."""
    await _register(client, "inventory-continuity@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="inventory-continuity@example.com")
        second = await _add_second_crawl(session, scn, admit_slugs=("a",))
        second.configuration = {INVENTORY_SOURCE_CRAWL_IDS_KEY: [str(scn.crawl_id)]}
        await session.commit()
        second_id = second.id
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    inventory = await client.get(
        f"/api/v1/site-crawls/{second_id}/inventory", headers=headers
    )
    assert inventory.status_code == 200
    assert {row["normalized_url"] for row in inventory.json()["items"]} == {
        "https://acme.test/a",
        "https://acme.test/b",
        "https://acme.test/c",
    }

    pages = await client.get(f"/api/v1/site-crawls/{second_id}/pages", headers=headers)
    assert pages.status_code == 200
    by_url = {row["normalized_url"]: row for row in pages.json()["items"]}
    assert set(by_url) == {
        "https://acme.test/a",
        "https://acme.test/b",
        "https://acme.test/c",
    }
    # Current observations stay on the current detail route. Inherited-only
    # rows link to the immutable source crawl where their detail exists.
    assert by_url["https://acme.test/a"]["crawl_id"] == str(second_id)
    assert by_url["https://acme.test/b"]["crawl_id"] == str(scn.crawl_id)


async def test_issue_history_bounded_to_crawl_chronology(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 5: an earlier crawl's URL history never shows a later crawl's issues.

    The seeded (earlier) crawl records an issue on url_b. A later crawl records
    a second issue on the same URL. Requesting the URL's issue-history under the
    EARLIER crawl must return only the earlier issue (chronology bound).
    """
    await _register(client, "history@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="history@example.com")
        # Later crawl admitting url_b, with a NEW issue on url_b.
        second = await _add_second_crawl(session, scn, admit_slugs=("a", "b"))
        await _seed_issue_for_url(
            session,
            scn,
            crawl_id=second.id,
            site_url_id=scn.issue_url_id,
            rule_id="aeo.answerable_question",
            dimension="aeo",
            category="content",
            severity="high",
        )
        await session.commit()
        second_id = second.id
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # Earlier crawl: only the earlier issue is in history.
    earlier = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}/issue-history",
        headers=headers,
    )
    assert earlier.status_code == 200
    earlier_rules = {i["rule_id"] for i in earlier.json()["items"]}
    assert earlier_rules == {"technical.title_present"}

    # Later crawl: history spans that crawl and prior ones (both issues).
    later = await client.get(
        f"/api/v1/site-crawls/{second_id}/pages/{scn.issue_url_id}/issue-history",
        headers=headers,
    )
    assert later.status_code == 200
    later_rules = {i["rule_id"] for i in later.json()["items"]}
    assert later_rules == {
        "technical.title_present",
        "aeo.answerable_question",
    }


async def test_issue_detail_requires_group_id_and_exposes_member_occurrences(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Occurrence identity is never accepted as ambiguous group identity."""
    await _register(client, "canon@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="canon@example.com")
        original_issue_id = await session.scalar(
            select(SiteIssue.id).where(
                SiteIssue.crawl_id == scn.crawl_id,
                SiteIssue.site_url_id == scn.issue_url_id,
                SiteIssue.rule_id == "technical.title_present",
            )
        )
        assert original_issue_id is not None
        # Add a second issue for the SAME rule on url_c (a later member).
        url_c = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == scn.project_id,
                SiteUrl.normalized_url == "https://acme.test/c",
            )
        )
        assert url_c is not None
        member_id = await _seed_issue_for_url(
            session,
            scn,
            crawl_id=scn.crawl_id,
            site_url_id=url_c.id,
            rule_id="technical.title_present",
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    occurrence_request = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{member_id}",
        headers=headers,
    )
    assert occurrence_request.status_code == 404

    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{scn.canonical_issue_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["group_id"] == str(scn.canonical_issue_id)
    assert body["affected_url_count"] == 2
    assert {row["occurrence_id"] for row in body["occurrences"]} == {
        str(original_issue_id),
        str(member_id),
    }


async def test_grouped_issues_canonical_id_stable_under_filters(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 4: the grouped-issue canonical id does not move when filters apply.

    Adding a same-rule issue on url_c must not change the deterministic group
    id, whether unfiltered or filtered to a single affected URL.
    """
    await _register(client, "stable@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="stable@example.com")
        url_c = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == scn.project_id,
                SiteUrl.normalized_url == "https://acme.test/c",
            )
        )
        assert url_c is not None
        url_c_id = url_c.id
        await _seed_issue_for_url(
            session,
            scn,
            crawl_id=scn.crawl_id,
            site_url_id=url_c_id,
            rule_id="technical.title_present",
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    unfiltered = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues", headers=headers
    )
    groups = unfiltered.json()["items"]
    assert len(groups) == 1
    assert groups[0]["group_id"] == str(scn.canonical_issue_id)
    assert groups[0]["affected_url_count"] == 2

    # Filter to only url_c: the group id is unchanged, only the affected count
    # narrows.
    filtered = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues?site_url_id={url_c_id}",
        headers=headers,
    )
    fgroups = filtered.json()["items"]
    assert len(fgroups) == 1
    assert fgroups[0]["group_id"] == str(scn.canonical_issue_id)
    assert fgroups[0]["affected_url_count"] == 1


async def test_tampered_cursor_returns_typed_400(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 6: a malformed/tampered cursor is a 400, never a 500."""
    await _register(client, "cursor@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="cursor@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # Garbage cursor on inventory (url keyset).
    inv = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory?cursor=not-a-cursor",
        headers=headers,
    )
    assert inv.status_code == 400

    # Garbage cursor on crawl list (created_at keyset) is also a typed 400.
    crawls = await client.get(
        f"/api/v1/site-crawls?project_id={scn.project_id}&cursor=%%%bad",
        headers=headers,
    )
    assert crawls.status_code == 400

    # A cursor valid for one filter set, replayed against a different filter, is
    # rejected as a scope mismatch (400), not silently accepted.
    first = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory?limit=1", headers=headers
    )
    valid_cursor = first.json()["next_cursor"]
    assert valid_cursor
    replayed = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/inventory"
        f"?limit=1&monitored=true&cursor={valid_cursor}",
        headers=headers,
    )
    assert replayed.status_code == 400


async def test_export_csv_neutralizes_formula_in_url(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 6: an admitted URL beginning with a formula trigger is neutralized.

    A URL that begins with ``@``/``=``/``+``/``-`` must be prefixed with ``'``
    in the exported CSV so a spreadsheet renders it as text.
    """
    await _register(client, "formula@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="formula@example.com")
        # A pathological URL that begins with a formula trigger, admitted to
        # the crawl so it appears in the inventory export.
        danger = "@evil.example/=cmd"
        su = SiteUrl(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            normalized_url=danger,
            url_hash=_hash(danger),
            display_url=danger,
            host="evil.example",
            latest_title="danger",
            latest_content_type="text/html",
            last_seen_crawl_id=scn.crawl_id,
        )
        session.add(su)
        await session.flush()
        session.add(
            SiteUrlObservation(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                crawl_id=scn.crawl_id,
                site_url_id=su.id,
                source_kind="link",
                depth=1,
                observed_url=danger,
                final_url=danger,
                status_code=200,
                content_type="text/html",
                title="danger",
            )
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    csv_resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=inventory",
        headers=headers,
    )
    assert csv_resp.status_code == 200
    # The neutralizing single-quote precedes the formula trigger in the cell.
    assert "'@evil.example/=cmd" in csv_resp.text


async def test_non_default_workspace_reads_and_exports_succeed(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Item 7: a selected NON-default workspace resolves reads + exports (200).

    The isolation test proves a foreign workspace 404s. This proves the flip
    side: when the seeded workspace is NOT the user's default, passing its
    X-Workspace-Id header still resolves every read + export (the header is
    honored, not just the default workspace).
    """
    await _register(client, "nondefault@example.com")
    async with session_factory() as session:
        # A first (default-candidate) workspace with no site-health data, plus
        # the seeded workspace. Registration created the user's own default;
        # the seeded Acme workspace is a second, non-default one.
        scn = await _seed_scenario(session, email="nondefault@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # Reads resolve in the non-default workspace.
    assert (
        await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=headers)
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
        )
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/site-crawls/{scn.crawl_id}/issues", headers=headers)
    ).status_code == 200

    # Exports resolve in the non-default workspace (X-Workspace-Id honored).
    csv_resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=pages",
        headers=headers,
    )
    assert csv_resp.status_code == 200
    assert "attachment" in csv_resp.headers["content-disposition"]

    # Events (SSE backing store) resolve in the non-default workspace.
    events = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/events", headers=headers
    )
    assert events.status_code == 200


async def test_rerun_page_from_completed_crawl_mints_new_crawl(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Handoff finding 1: 'Re-audit this page' must work from a COMPLETED crawl.

    The source crawl is terminal, so enqueuing an analyze task into it would be
    cooperatively cancelled by the worker and never run. The endpoint must mint
    a FRESH single-page rerun crawl and return its identity so the client polls
    the new run rather than the terminal source crawl.
    """
    from app.core.config.site_health_contracts import (
        CRAWL_ACTIVE_STATUSES,
    )
    from tests.component.site_health_helpers import seed_monitored_urls_allowance

    await _register(client, "rerun@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="rerun@example.com")
        # The monitored URL is user-source, so a positive allowance is
        # required to rerun it.
        await seed_monitored_urls_allowance(
            session, workspace_id=scn.workspace_id, monitored_urls=50
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.post(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.monitored_url_id}/rerun",
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    # Response shape: identity to poll the fresh rerun.
    assert set(body) == {
        "crawl_id",
        "site_url_id",
        "task_id",
        "created_new_crawl",
        "analysis_status",
    }
    assert body["created_new_crawl"] is True
    assert body["site_url_id"] == str(scn.monitored_url_id)
    # A brand-new crawl id, distinct from the terminal source crawl.
    new_crawl_id = uuid.UUID(body["crawl_id"])
    assert new_crawl_id != scn.crawl_id
    assert body["analysis_status"] == "pending"

    async with session_factory() as session:
        new_crawl = await session.get(SiteCrawl, new_crawl_id)
        assert new_crawl is not None
        # The new crawl is active (runnable), not terminal.
        assert new_crawl.status in CRAWL_ACTIVE_STATUSES
        # Exactly one analyze task was seeded for the reran URL — and no
        # discover root task (so the worker never re-crawls the whole site).
        seeded = (
            (
                await session.execute(
                    select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == new_crawl_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(seeded) == 1
        assert seeded[0].task_kind == TASK_KIND_ANALYZE
        assert seeded[0].site_url_id == scn.monitored_url_id
        assert str(seeded[0].id) == body["task_id"]
        # The returned URL is resolvable on the NEW crawl (an observation row
        # exists) so page-detail polling of the new crawl works.
        obs = await session.scalar(
            select(SiteUrlObservation.id).where(
                SiteUrlObservation.crawl_id == new_crawl_id,
                SiteUrlObservation.site_url_id == scn.monitored_url_id,
            )
        )
        assert obs is not None


async def test_rerun_page_unmonitored_url_is_conflict(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A URL that is not in the active monitored selection cannot be rerun."""

    await _register(client, "rerun-conflict@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="rerun-conflict@example.com")
        await seed_monitored_urls_allowance(
            session, workspace_id=scn.workspace_id, monitored_urls=50
        )
        await session.commit()
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    # ``issue_url_id`` (url_b) is analyzed/admitted but NOT monitored.
    resp = await client.post(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{scn.issue_url_id}/rerun",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "rerun_not_allowed"
