#!/usr/bin/env python3
"""P2 e2e — Suite D: Starter mode — sitemap ingestion + crawl_finalize rules.

Precondition: the workspace entitlement has been set to ``starter`` via
scripts.set_site_health_entitlement (the wrapper shell does this).

Flow: crawl#1 = discovery only (sitemap ingestion admits the 10 sitemap URLs
incl. the link-less orphan page; no monitored set exists yet, so nothing is
analyzed). Select the 10 real pages as the monitored set. crawl#2 = analysis
of the monitored set + the finalize pass.

Expected: sitemap_orphan FAIL on the root (the orphan page is sitemap-listed
but never anchor-linked); broken_internal_link FAIL on the orphan page (it
links to a 404); broken_internal_link PASS on the 9 normal pages; sitemap
facts recorded in site_facts.

Run from backend/:  uv run python /tmp/sh-p2-e2e-starter.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/tmp")
from sh_p2_lib import (  # noqa: E402
    Api, FIXTURE_URL, check, create_crawl, create_project, list_all,
    register_or_login, summary, wait_crawl,
)

TUNNEL = FIXTURE_URL.rstrip("/")
ORPHAN_PATH = "/misc/orphan/"
MISSING_PATH = "/misc/definitely-missing/"
# The 10 real pages = 9 core fixture pages + the orphan. The missing page is
# deliberately NOT monitored (it would fail analysis and pollute counts).
CORE_PATHS = [
    "/", "/blog/post-1/", "/pricing/", "/docs/intro/", "/faq/",
    "/product/widget/", "/category/shoes/", "/about/", "/misc/plain/",
    ORPHAN_PATH,
]


def path_of(row: dict) -> str:
    path = row["normalized_url"].replace(TUNNEL, "") or "/"
    return path if path.startswith("/") else "/" + path


def main() -> int:
    api = Api()
    print("== auth + seed (entitlement must already be starter)")
    register_or_login(api)
    code, ent = api.get("/entitlements")
    check("entitlement is starter",
          code == 200 and ent.get("plan_key") == "starter",
          json.dumps(ent)[:250])
    project_id = create_project(api, "Fixture Co P2 Starter")
    print(f"  project {project_id}")

    print("== crawl#1 (discovery + sitemap ingestion, no analysis)")
    crawl1_id = create_crawl(api, project_id)
    print(f"  crawl#1 {crawl1_id}")
    crawl1 = wait_crawl(api, crawl1_id)
    # Discovery terminalizes partially_completed: the orphan page deliberately
    # links to /misc/definitely-missing/ (404), which is admitted and fails
    # its discover fetch (discovered>0 + failed>0 => partially_completed).
    check("crawl#1 partially_completed (deliberate 404 in link graph)",
          crawl1["status"] == "partially_completed",
          f"status={crawl1['status']}")
    check("crawl#1 failed_count == 1 (the 404 page)",
          crawl1["failed_count"] == 1, str(crawl1["failed_count"]))
    check("crawl#1 sample_mode false", crawl1["sample_mode"] is False)
    check("crawl#1 analyzed nothing (no monitored set yet)",
          crawl1["analyzed_count"] == 0, str(crawl1["analyzed_count"]))
    facts1 = crawl1.get("site_facts") or {}
    sm1 = facts1.get("sitemap") or {}
    check("crawl#1 sitemap fetched", sm1.get("fetched") is True,
          json.dumps(sm1)[:250])
    check("crawl#1 sitemap file recorded",
          any(f.endswith("/sitemap.xml") for f in (sm1.get("files") or [])),
          json.dumps(sm1)[:250])

    inventory = list_all(api, f"/site-crawls/{crawl1_id}/inventory")
    inv_paths = {path_of(row) for row in inventory}
    check("inventory has sitemap orphan page", ORPHAN_PATH in inv_paths,
          json.dumps(sorted(inv_paths)))
    src_by_path = {}
    for row in inventory:
        src = row.get("source")
        src_by_path.setdefault(path_of(row), set()).add(src)
    print(f"  inventory sources: { {p: sorted(s) for p, s in sorted(src_by_path.items())} }")

    print("== select monitored set (10 real pages)")
    code, mon = api.get(f"/projects/{project_id}/monitored-urls")
    assert code == 200, f"monitored-urls: {code} {mon}"
    version = mon["selection_version"]
    ids = [row["site_url_id"] for row in inventory
           if path_of(row) in CORE_PATHS]
    check("10 candidate ids resolved", len(ids) == 10,
          f"got {len(ids)}: {sorted(path_of(r) for r in inventory)}")
    code, put = api.put(f"/projects/{project_id}/monitored-urls", {
        "site_url_ids": ids,
        "expected_selection_version": version,
    })
    check("monitored set replaced", code == 200, f"code={code} {json.dumps(put)[:250]}")
    if code == 200:
        active = [u for u in put["monitored_urls"] if u["active"]]
        check("10 active monitored urls", len(active) == 10,
              f"got {len(active)}")

    print("== crawl#2 (analysis of monitored set + finalize pass)")
    crawl2_id = create_crawl(api, project_id)
    print(f"  crawl#2 {crawl2_id}")
    crawl2 = wait_crawl(api, crawl2_id)
    check("crawl#2 partially_completed (404 rediscovered)",
          crawl2["status"] == "partially_completed",
          f"status={crawl2['status']}")
    check("crawl#2 analyzed 10", crawl2["analyzed_count"] == 10,
          str(crawl2["analyzed_count"]))
    facts2 = crawl2.get("site_facts") or {}
    check("crawl#2 sitemap fetched",
          (facts2.get("sitemap") or {}).get("fetched") is True,
          json.dumps(facts2.get("sitemap"))[:250])
    stance2 = ((facts2.get("robots") or {}).get("ai_crawlers")) or {}
    check("crawl#2 GPTBot still blocked", stance2.get("GPTBot") == "block",
          json.dumps(stance2))

    pages = list_all(api, f"/site-crawls/{crawl2_id}/pages")
    by_path = {path_of(p): p for p in pages}

    print("== D1: sitemap_orphan on root")
    root = by_path.get("/")
    check("root analyzed", root is not None and root["analysis_status"] == "completed",
          json.dumps(root)[:200])
    if root:
        code, detail = api.get(f"/site-crawls/{crawl2_id}/pages/{root['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        so = evals.get("technical.sitemap_orphan")
        check("root sitemap_orphan FAIL", so is not None and so["outcome"] == "fail",
              json.dumps(so)[:250] if so else "missing")
        if so:
            ev = so["evidence"] or {}
            orphans = ev.get("orphan_urls") or []
            check("orphan_urls == [/misc/orphan/]",
                  len(orphans) == 1 and orphans[0].endswith(ORPHAN_PATH),
                  json.dumps(orphans))
            # sitemap-SOURCED URLs (source attribution: linked pages converge
            # to source=link; only sitemap-only URLs keep source=sitemap).
            check("sitemap_url_count == 1 (sitemap-sourced only)",
                  ev.get("sitemap_url_count") == 1,
                  str(ev.get("sitemap_url_count")))
            check("sitemap_orphan weight 0", so["weight"] == 0.0, str(so["weight"]))

    print("== D2: broken_internal_link per page")
    orphan = by_path.get(ORPHAN_PATH)
    check("orphan page analyzed", orphan is not None
          and orphan["analysis_status"] == "completed",
          json.dumps(orphan)[:200] if orphan else "absent")
    if orphan:
        code, detail = api.get(f"/site-crawls/{crawl2_id}/pages/{orphan['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        bil = evals.get("technical.broken_internal_link")
        check("orphan broken_internal_link FAIL",
              bil is not None and bil["outcome"] == "fail",
              json.dumps(bil)[:250] if bil else "missing")
        if bil:
            ev = bil["evidence"] or {}
            broken = ev.get("broken_urls") or []
            check("broken_urls contains /misc/definitely-missing/",
                  any(u.endswith(MISSING_PATH) for u in broken),
                  json.dumps(broken))
            check("orphan checked_count >= 2", (ev.get("checked_count") or 0) >= 2,
                  str(ev.get("checked_count")))
    for path in CORE_PATHS:
        if path == ORPHAN_PATH:
            continue
        page = by_path.get(path)
        if not page:
            check(f"{path} analyzed in crawl#2", False, "absent from pages")
            continue
        code, detail = api.get(f"/site-crawls/{crawl2_id}/pages/{page['site_url_id']}")
        evals = {ev["rule_id"]: ev for ev in detail["evaluations"]}
        bil = evals.get("technical.broken_internal_link")
        check(f"{path} broken_internal_link PASS",
              bil is not None and bil["outcome"] == "pass",
              json.dumps(bil)[:200] if bil else "missing")
        if path != "/":
            so = evals.get("technical.sitemap_orphan")
            check(f"{path} sitemap_orphan absent (root-anchored only)", so is None)

    print("== D3: finalize issues projected")
    code, issues_page = api.get(f"/site-crawls/{crawl2_id}/issues?limit=100")
    assert code == 200
    by_rule = {i["rule_id"]: i for i in issues_page["items"]}
    so_issue = by_rule.get("technical.sitemap_orphan")
    check("sitemap_orphan issue present (low)",
          so_issue is not None and so_issue["severity"] == "low",
          json.dumps(so_issue)[:200] if so_issue else "missing")
    bil_issue = by_rule.get("technical.broken_internal_link")
    check("broken_internal_link issue present (high)",
          bil_issue is not None and bil_issue["severity"] == "high",
          json.dumps(bil_issue)[:200] if bil_issue else "missing")
    if so_issue:
        check("sitemap_orphan issue label",
              so_issue["title"] == "Sitemap orphan URLs", so_issue["title"])
    if bil_issue:
        check("broken_internal_link issue label",
              bil_issue["title"] == "Broken internal links", bil_issue["title"])

    return summary("Suite D (Starter sitemap + finalize)")


if __name__ == "__main__":
    sys.exit(main())
