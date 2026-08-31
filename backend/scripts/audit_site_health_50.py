"""Freeze and audit the 50-URL Site Health HTTP corpus.

This is a non-product evaluation helper. It reads the latest completed crawl
for the four requested projects, fetches the selected URLs once through the
normal SSRF-safe acquisition boundary, and writes redacted bounded artifacts.
Raw response bodies are written only below the gitignored artifacts directory.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.analysis.site_health.page_analysis import analyze_page
from app.analysis.site_health.parser import extract_page_facts
from app.connectors.web_evidence.contracts import FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.core.config.site_health_acquisition import FETCH_PURPOSE_ANALYZE
from app.core.database import engine
from app.domain.site_health.service.issues import issue_group_id

_reporting = importlib.import_module(
    "scripts.site_health_audit_reporting"
    if __package__
    else "site_health_audit_reporting"
)

ROOT = Path(__file__).resolve().parents[2]
COMPANIES = ("goodee", "lootcrate", "potgang", "united by blue")
MAX_TEXT = 400
SCHEMA_KEYS = ("schema", "structured_data", "structuredData")
REDACTED_EVIDENCE_KEYS = frozenset(
    {"body", "class", "classes", "html", "raw_html", "selector", "value"}
)
CORRECTED_REPLAY_RULE_IDS = frozenset(
    {
        "aeo.answer_first",
        "aeo.editorial_lead_present",
        "aeo.entity_value_proposition",
        "aeo.heading_hierarchy",
        "aeo.listing_answer_set",
        "aeo.listing_item_facts",
        "aeo.product_answer_facts",
        "aeo.product_brand_identity",
        "aeo.question_headings",
        "aeo.visible_attribution",
        "web.accessibility_form_names",
    }
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _redact_evidence(value: Any) -> Any:
    """Bound stored evidence for committed CSV/Markdown artifacts."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            if str(key).lower() in REDACTED_EVIDENCE_KEYS:
                continue
            out[str(key)[:80]] = _redact_evidence(item)
        return out
    if isinstance(value, list):
        return [_redact_evidence(item) for item in value[:30]]
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_TEXT]


def _score(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None else 101.0


def _unselected_by_score(
    rows: list[dict[str, Any]], seen: set[str], score_key: str
) -> list[dict[str, Any]]:
    return sorted(
        (row for row in rows if row["url"] not in seen),
        key=lambda row: (_score(row, score_key), row["page_kind"], row["url"]),
    )


def _prefer_novel_kind(
    candidates: list[dict[str, Any]], chosen: list[dict[str, Any]]
) -> dict[str, Any]:
    chosen_kinds = {row["page_kind"] for row in chosen}
    for candidate in candidates:
        if candidate["page_kind"] not in chosen_kinds:
            return candidate
    return candidates[0]


def _select_company_rows(
    rows: list[dict[str, Any]], company: str
) -> list[dict[str, Any]]:
    pool = [row for row in rows if row["company"] == company]
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    score_streams = ("web_score", "aeo_score")
    stream_index = 0
    while len(chosen) < min(12, len(pool)) and stream_index < len(pool) * 4:
        score_key = score_streams[stream_index % len(score_streams)]
        candidates = _unselected_by_score(pool, seen, score_key)
        if not candidates:
            break
        candidate = (
            _prefer_novel_kind(candidates, chosen) if len(chosen) < 8 else candidates[0]
        )
        selected = dict(candidate)
        selected["selection_reason"] = f"{company}: alternating {score_key} rank"
        chosen.append(selected)
        seen.add(candidate["url"])
        stream_index += 1
    return chosen


def _select_global_rows(
    rows: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen_urls = {row["url"] for row in selected}
    seen_kinds = {row["page_kind"] for row in selected}
    remaining = [row for row in rows if row["url"] not in seen_urls]
    additions: list[dict[str, Any]] = []
    for score_key in ("web_score", "aeo_score"):
        candidates = _unselected_by_score(remaining, set(), score_key)
        if not candidates:
            continue
        candidate = next(
            (row for row in candidates if row["page_kind"] not in seen_kinds),
            candidates[0],
        )
        selected_row = dict(candidate)
        selected_row["selection_reason"] = f"global lowest remaining {score_key}"
        additions.append(selected_row)
        remaining = [row for row in remaining if row["url"] != candidate["url"]]
        seen_kinds.add(candidate["page_kind"])
    return additions


def select_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select 12/company, alternating score streams, then 2 global URLs.

    Distinct page kinds are favored before score tie-breaking. Selection is
    deterministic on score, kind, normalized URL, and UUID.
    """
    selected = [
        row for company in COMPANIES for row in _select_company_rows(rows, company)
    ]
    selected.extend(_select_global_rows(rows, selected))
    if len(selected) != 50:
        raise RuntimeError(f"expected exactly 50 selected URLs, got {len(selected)}")
    return selected


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_TEXT]


def _review_payload_rows(payload: Any, path: Path) -> list[Any]:
    if isinstance(payload, dict):
        rows = payload.get(
            "reviews", payload.get("rows", payload.get("occurrences", []))
        )
    else:
        rows = payload
    if not isinstance(rows, list):
        raise RuntimeError(f"review payload must be a list: {path}")
    return rows


def _parse_review_row(row: Any, path: Path) -> tuple[str, dict[str, str]] | None:
    if not isinstance(row, dict):
        return None
    occurrence_id = str(row.get("occurrence_id") or "")
    verdict = str(row.get("verdict") or "")
    if not occurrence_id or verdict not in {"verified", "wrong"}:
        raise RuntimeError(f"invalid independent review row in {path}")
    review = {
        "verdict": verdict,
        "observation": _plain(row.get("observation") or row.get("exact_observation")),
        "confidence": str(row.get("confidence") or "medium"),
    }
    return occurrence_id, review


def _load_independent_reviews(review_dir: Path) -> dict[str, dict[str, str]]:
    """Load human/agent verdicts kept beside the gitignored frozen corpus."""
    reviews: dict[str, dict[str, str]] = {}
    for path in sorted(review_dir.glob("review-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in _review_payload_rows(payload, path):
            parsed = _parse_review_row(row, path)
            if parsed is None:
                continue
            occurrence_id, review = parsed
            if occurrence_id in reviews:
                raise RuntimeError(f"duplicate review for occurrence {occurrence_id}")
            reviews[occurrence_id] = review
    return reviews


def _corrected_replay_result(verdict: str, outcome: str) -> str:
    if not outcome:
        return "not_replayed"
    claims_issue = outcome in {"missing", "partial"}
    if verdict == "verified":
        return "retained_verified" if claims_issue else "lost_verified"
    return "remaining_wrong" if claims_issue else "removed_wrong"


async def _latest_crawls(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    result = await conn.execute(
        text("""
        SELECT p.id project_id, p.name company, p.website_url, c.id crawl_id,
               c.completed_at crawl_completed_at
        FROM projects p JOIN site_crawls c ON c.project_id = p.id
        WHERE lower(p.name) = ANY(:companies)
          AND c.status IN ('completed', 'partially_completed')
        ORDER BY lower(p.name), c.completed_at DESC
        """),
        {"companies": list(COMPANIES)},
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in result.mappings().all():
        latest.setdefault(str(row["company"]).lower(), dict(row))
    missing = set(COMPANIES) - set(latest)
    if missing:
        raise RuntimeError(f"missing latest completed crawl for {missing}")
    return latest


async def _candidate_rows(
    conn: AsyncConnection, crawl_ids: list[Any]
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text("""
        SELECT lower(p.name) company, c.id crawl_id, u.id site_url_id,
               u.normalized_url url, a.id analysis_id, a.artifact_id,
               a.page_kind, a.page_traits, a.web_fundamentals_score web_score,
               a.aeo_readiness_score aeo_score, a.created_at analysis_created_at,
               fa.fetched_at crawl_fetch_time, c.completed_at crawl_completed_at
        FROM site_crawls c JOIN projects p ON p.id=c.project_id
        JOIN site_page_analyses a ON a.crawl_id=c.id AND a.is_current
        JOIN site_urls u ON u.id=a.site_url_id
        JOIN site_fetch_artifacts fa ON fa.id=a.artifact_id
        WHERE c.id = ANY(:crawl_ids)
        ORDER BY lower(p.name), a.web_fundamentals_score NULLS FIRST,
                 a.aeo_readiness_score NULLS FIRST, u.normalized_url
        """),
        {"crawl_ids": crawl_ids},
    )
    return [dict(row) for row in result.mappings().all()]


async def _occurrences_by_url(
    conn: AsyncConnection, crawl_ids: list[Any]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result = await conn.execute(
        text("""
        SELECT i.id occurrence_id, i.evaluation_id, i.analysis_id, i.site_url_id,
               i.crawl_id, lower(p.name) company, u.normalized_url url,
               a.page_kind, i.rule_id, i.dimension, i.category, i.severity,
               i.finding_class, i.evidence issue_evidence, i.description,
               i.remediation, e.reason_code, e.outcome,
               e.evidence evaluation_evidence, i.analyzer_version, i.rule_version
        FROM site_issues i JOIN projects p ON p.id=i.project_id
        JOIN site_urls u ON u.id=i.site_url_id
        JOIN site_page_analyses a ON a.id=i.analysis_id
        JOIN site_rule_evaluations e ON e.id=i.evaluation_id
        WHERE i.crawl_id = ANY(:crawl_ids)
          AND lower(p.name) = ANY(:companies)
        ORDER BY lower(p.name), u.normalized_url, i.rule_id, i.id
        """),
        {"crawl_ids": crawl_ids, "companies": list(COMPANIES)},
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in result.mappings().all():
        grouped[(str(row["crawl_id"]), str(row["url"]))].append(dict(row))
    return grouped


async def _load_snapshot() -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    async with engine.connect() as conn:
        latest = await _latest_crawls(conn)
        crawl_ids = [row["crawl_id"] for row in latest.values()]
        candidates = await _candidate_rows(conn, crawl_ids)
        issues_by_url = await _occurrences_by_url(conn, crawl_ids)
    return latest, select_rows(candidates), issues_by_url


def _fixture_paths(
    fixture_dir: Path | None, body_name: str, headers_name: str
) -> tuple[Path | None, Path | None, Path | None]:
    if fixture_dir is None:
        return None, None, None
    body_path = fixture_dir / body_name
    return body_path, fixture_dir / headers_name, body_path.with_suffix(".meta.json")


def _read_existing_fixture(
    body_path: Path | None,
    headers_path: Path | None,
    metadata_path: Path | None,
) -> dict[str, Any] | None:
    if body_path is None or headers_path is None or metadata_path is None:
        return None
    if (
        not body_path.exists()
        or not headers_path.exists()
        or not metadata_path.exists()
    ):
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "body": body_path.read_bytes(),
        "headers": json.loads(headers_path.read_text(encoding="utf-8")),
        "final_url": metadata["final_url"],
        "status_code": metadata["status_code"],
        "content_type": metadata["content_type"],
        "charset": metadata["charset"],
        "audit_time": datetime.fromtimestamp(body_path.stat().st_mtime, UTC),
    }


async def _load_response(
    fetcher: SecureFetcher,
    url: str,
    body_path: Path | None,
    headers_path: Path | None,
    metadata_path: Path | None,
    run_time: datetime,
) -> dict[str, Any]:
    existing = _read_existing_fixture(body_path, headers_path, metadata_path)
    if existing is not None:
        return existing
    result = await fetcher.fetch(
        FetchRequest(url=url, purpose=FETCH_PURPOSE_ANALYZE, method="GET"),
        root_registrable_domain=None,
        enforce_scope=False,
    )
    return {
        "body": result.body,
        "headers": result.redacted_headers,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "charset": result.charset,
        "audit_time": run_time,
    }


def _freeze_response(
    artifact_dir: Path,
    body_name: str,
    headers_name: str,
    response: dict[str, Any],
) -> None:
    (artifact_dir / body_name).write_bytes(response["body"])
    (artifact_dir / headers_name).write_text(
        _json(response["headers"]), encoding="utf-8"
    )
    (artifact_dir / body_name).with_suffix(".meta.json").write_text(
        _json(
            {
                "final_url": response["final_url"],
                "status_code": response["status_code"],
                "content_type": response["content_type"],
                "charset": response["charset"],
            }
        ),
        encoding="utf-8",
    )


def _analyze_response(response: dict[str, Any]) -> dict[str, Any]:
    facts = extract_page_facts(
        response["body"],
        final_url=response["final_url"],
        content_type=response["content_type"],
        charset=response["charset"],
        status_code=response["status_code"],
        redacted_headers=response["headers"],
    )
    parsed = analyze_page(facts).evaluations
    corrected = tuple(
        evaluation
        for evaluation in parsed
        if evaluation.rule_id in CORRECTED_REPLAY_RULE_IDS
    )
    return {"parsed": parsed, "corrected": corrected}


async def _audit_selected_row(
    fetcher: SecureFetcher,
    selected_row: dict[str, Any],
    index: int,
    artifact_dir: Path,
    reuse_raw_dir: Path | None,
    run_time: datetime,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    url = str(selected_row["url"])
    item = dict(selected_row)
    digest_prefix = hashlib.sha256(url.encode()).hexdigest()[:16]
    body_name = f"{index:03d}-{digest_prefix}.html"
    headers_name = body_name.replace(".html", ".headers.json")
    body_path, headers_path, metadata_path = _fixture_paths(
        reuse_raw_dir, body_name, headers_name
    )
    try:
        response = await _load_response(
            fetcher, url, body_path, headers_path, metadata_path, run_time
        )
        if reuse_raw_dir is None:
            _freeze_response(artifact_dir, body_name, headers_name, response)
        item.update(
            {
                "status_code": response["status_code"],
                "final_url": response["final_url"],
                "content_type": response["content_type"],
                "body_sha256": hashlib.sha256(response["body"]).hexdigest(),
                "body_file": body_name,
                "headers_file": headers_name,
                "audit_fetched_at": response["audit_time"].isoformat(),
                "error": "",
            }
        )
        return item, _analyze_response(response)
    except Exception as exc:  # noqa: BLE001 - record each URL failure
        item.update(
            {
                "status_code": getattr(exc, "status_code", None),
                "final_url": "",
                "content_type": "",
                "body_sha256": "",
                "body_file": "",
                "headers_file": "",
                "audit_fetched_at": run_time.isoformat(),
                "error": type(exc).__name__,
            }
        )
        return item, None


async def _fetch_corpus(
    selected: list[dict[str, Any]],
    artifact_dir: Path,
    reuse_raw_dir: Path | None,
    run_time: datetime,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any] | None]]:
    manifest: list[dict[str, Any]] = []
    observations: dict[str, dict[str, Any] | None] = {}
    async with SecureFetcher(resolver=SystemDnsResolver()) as fetcher:
        for index, selected_row in enumerate(selected, start=1):
            item, analysis = await _audit_selected_row(
                fetcher,
                selected_row,
                index,
                artifact_dir,
                reuse_raw_dir,
                run_time,
            )
            manifest.append(item)
            observations[str(item["url"])] = analysis
    return manifest, observations


def _validate_review_coverage(
    reviews: dict[str, dict[str, str]],
    manifest: list[dict[str, Any]],
    issues_by_url: dict[tuple[str, str], list[dict[str, Any]]],
) -> None:
    expected_ids = {
        str(issue["occurrence_id"])
        for row in manifest
        for issue in issues_by_url.get((str(row["crawl_id"]), str(row["url"])), ())
    }
    review_ids = set(reviews)
    missing = expected_ids - review_ids
    unexpected = review_ids - expected_ids
    if missing or unexpected:
        raise RuntimeError(
            "independent review coverage mismatch: "
            f"missing {sorted(missing)}, unexpected {sorted(unexpected)}"
        )


def _replayed_outcomes(
    observations: dict[str, dict[str, Any] | None],
) -> dict[tuple[str, str], str]:
    return {
        (url, str(evaluation.rule_id)): str(evaluation.outcome)
        for url, analysis in observations.items()
        for evaluation in ((analysis or {}).get("corrected") or ())
    }


def _reported_row(
    manifest_row: dict[str, Any],
    issue: dict[str, Any],
    review: dict[str, str],
    replayed_outcome: str,
) -> dict[str, Any]:
    observation = review["observation"]
    return {
        "company": manifest_row["company"],
        "url": manifest_row["url"],
        "page_kind": manifest_row["page_kind"],
        "web_score": manifest_row["web_score"],
        "aeo_score": manifest_row["aeo_score"],
        "selection_reason": manifest_row["selection_reason"],
        "crawl_id": manifest_row["crawl_id"],
        "group_id": str(
            issue_group_id(issue["crawl_id"], issue["rule_id"], issue["finding_class"])
        ),
        "occurrence_id": issue["occurrence_id"],
        "evaluation_id": issue["evaluation_id"],
        "rule_id": issue["rule_id"],
        "dimension": issue["dimension"],
        "category": issue["category"],
        "severity": issue["severity"],
        "finding_class": issue["finding_class"],
        "description": issue["description"],
        "remediation": issue["remediation"],
        "reason_code": issue["reason_code"],
        "analyzer_version": issue["analyzer_version"],
        "rule_version": issue["rule_version"],
        "stored_evidence": _json(
            _redact_evidence(issue["issue_evidence"] or issue["evaluation_evidence"])
        ),
        "independent_observation": observation,
        "exact_offending_element_schema_heading": observation,
        "verdict": review["verdict"],
        "confidence": review["confidence"],
        "corrected_replay_outcome": replayed_outcome,
        "corrected_replay_result": _corrected_replay_result(
            review["verdict"], replayed_outcome
        ),
        "content_sha256": manifest_row["body_sha256"],
        "crawl_fetch_time": manifest_row["crawl_fetch_time"],
        "audit_fetch_time": manifest_row["audit_fetched_at"],
    }


def _build_reported(
    manifest: list[dict[str, Any]],
    issues_by_url: dict[tuple[str, str], list[dict[str, Any]]],
    reviews: dict[str, dict[str, str]],
    replayed: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    reported: list[dict[str, Any]] = []
    for manifest_row in manifest:
        url = str(manifest_row["url"])
        occurrence_key = (str(manifest_row["crawl_id"]), url)
        for issue in issues_by_url.get(occurrence_key, []):
            review = reviews[str(issue["occurrence_id"])]
            replayed_outcome = replayed.get((url, issue["rule_id"]), "")
            reported.append(
                _reported_row(manifest_row, issue, review, replayed_outcome)
            )
    return reported


def _missed_row(manifest_row: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return {
        "company": manifest_row["company"],
        "url": manifest_row["url"],
        "page_kind": manifest_row["page_kind"],
        "rule_id": rule_id,
        "independent_observation": (
            "deterministic frozen-fact evaluation missing from persisted occurrence"
        ),
        "comparison_status": "not_comparable",
        "comparison_reason": (
            "replay-only candidate; classification and applicability were not "
            "independently established on the stored contract"
        ),
        "content_sha256": manifest_row["body_sha256"],
        "audit_fetch_time": manifest_row["audit_fetched_at"],
    }


def _build_missed(
    manifest: list[dict[str, Any]],
    observations: dict[str, dict[str, Any] | None],
    reported: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reported_keys = {
        (row["url"], row["rule_id"]) for row in reported if row["verdict"] == "verified"
    }
    missed: list[dict[str, Any]] = []
    for manifest_row in manifest:
        analysis = observations.get(str(manifest_row["url"])) or {}
        for evaluation in analysis.get("parsed", ()):
            if getattr(evaluation, "outcome", "") not in {"missing", "partial"}:
                continue
            rule_id = str(getattr(evaluation, "rule_id", ""))
            if (manifest_row["url"], rule_id) not in reported_keys:
                missed.append(_missed_row(manifest_row, rule_id))
    return missed


async def _run(run_id: str, reuse_raw_dir: Path | None = None) -> None:
    run_time = datetime.now(UTC)
    artifact_dir = ROOT / "artifacts" / "site-health-audit" / run_id
    output_dir = ROOT / "docs" / "evaluations"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest, selected, issues_by_url = await _load_snapshot()
    fetch_manifest, observations = await _fetch_corpus(
        selected, artifact_dir, reuse_raw_dir, run_time
    )
    review_dir = reuse_raw_dir if reuse_raw_dir is not None else artifact_dir
    reviews = _load_independent_reviews(review_dir)
    _validate_review_coverage(reviews, fetch_manifest, issues_by_url)
    reported = _build_reported(
        fetch_manifest, issues_by_url, reviews, _replayed_outcomes(observations)
    )
    missed = _build_missed(fetch_manifest, observations, reported)
    _reporting.write_audit_outputs(
        root=ROOT,
        output_dir=output_dir,
        run_id=run_id,
        run_time=run_time,
        artifact_dir=artifact_dir,
        selected_count=len(selected),
        latest=latest,
        fetch_manifest=fetch_manifest,
        reported=reported,
        missed=missed,
    )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    parser.add_argument("--reuse-raw-dir", type=Path)
    args = parser.parse_args()
    asyncio.run(_run(args.run_id, args.reuse_raw_dir))


if __name__ == "__main__":
    main()
