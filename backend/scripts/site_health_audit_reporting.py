"""Write the bounded committed outputs for the Site Health HTTP audit."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

COMPANIES = ("goodee", "lootcrate", "potgang", "united by blue")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_csv_artifacts(
    prefix: Path,
    manifest: list[dict[str, Any]],
    reported: list[dict[str, Any]],
    missed: list[dict[str, Any]],
) -> None:
    manifest_fields = [
        "company",
        "url",
        "page_kind",
        "web_score",
        "aeo_score",
        "selection_reason",
        "crawl_id",
        "analysis_id",
        "artifact_id",
        "status_code",
        "final_url",
        "content_type",
        "body_sha256",
        "body_file",
        "headers_file",
        "crawl_completed_at",
        "audit_fetched_at",
        "error",
    ]
    report_fields = list(reported[0]) if reported else ["company", "url", "verdict"]
    missed_fields = list(missed[0]) if missed else ["company", "url", "rule_id"]
    _write_csv(
        prefix.with_name(prefix.name + "-fixture-manifest.csv"),
        manifest_fields,
        manifest,
    )
    _write_csv(
        prefix.with_name(prefix.name + "-reported-occurrences.csv"),
        report_fields,
        reported,
    )
    _write_csv(
        prefix.with_name(prefix.name + "-missed-findings.csv"),
        missed_fields,
        missed,
    )


def _per_rule_counts(
    reported: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    per_rule: dict[str, dict[str, int]] = defaultdict(lambda: Counter())
    for row in reported:
        per_rule[row["rule_id"]][row["verdict"]] += 1
    return per_rule


def _rule_table_lines(
    per_rule: dict[str, dict[str, int]], missed: list[dict[str, Any]]
) -> list[str]:
    missed_by_rule = Counter(row["rule_id"] for row in missed)
    lines: list[str] = []
    for rule in sorted(set(per_rule) | set(missed_by_rule)):
        counts = per_rule.get(rule, {})
        verified = counts.get("verified", 0)
        wrong = counts.get("wrong", 0)
        total = verified + wrong
        precision = verified / total if total else 0
        lines.append(
            f"| `{rule}` | {verified} | {wrong} | "
            f"0 | {missed_by_rule[rule]} | {precision:.1%} | n/a |"
        )
    return lines


def _report_lines(
    root: Path,
    run_id: str,
    stamp: str,
    artifact_dir: Path,
    selected_count: int,
    reported: list[dict[str, Any]],
    missed: list[dict[str, Any]],
) -> list[str]:
    summary = Counter(row["verdict"] for row in reported)
    replay_summary = Counter(row["corrected_replay_result"] for row in reported)
    lines = [
        f"# Site Health 50-URL HTTP Audit ({stamp})",
        "",
        f"Run: `{run_id}`",
        "",
        "## Contract",
        "",
        "Frozen responses were acquired once via `SecureFetcher` with no "
        "JavaScript. `verified` means the reported defect is observable in the "
        "bounded HTTP response; `wrong` means it is not observable. Cocofloss "
        "was excluded.",
        "",
        "## Selection",
        "",
        f"Exactly **{selected_count}** URLs: a 12-URL base from each of "
        f"{', '.join(COMPANIES)}, plus two global lowest-score URLs. Raw bodies "
        "and redacted headers are gitignored under "
        f"`{artifact_dir.relative_to(root).as_posix()}`.",
        "",
        "## Results",
        "",
        f"Reported occurrences: {len(reported)}; verified: "
        f"{summary['verified']}; wrong: {summary['wrong']}; frozen-fact "
        f"replay-only candidates classified `not_comparable`: {len(missed)}.",
        "",
        "## Corrected frozen-corpus replay",
        "",
        "The audit-demonstrated corrected rules were re-run over the same frozen "
        "responses, including corrected page classification and applicability. "
        "Against their independently reviewed occurrences, "
        f"it retained {replay_summary['retained_verified']} verified findings, "
        f"lost {replay_summary['lost_verified']} verified findings, removed "
        f"{replay_summary['removed_wrong']} wrong findings, and retained "
        f"{replay_summary['remaining_wrong']} wrong findings.",
        "",
        "The two baseline-wrong crawl-graph broken-link aggregates are not "
        "raw-page replayable. Their corrected persistence owner now creates "
        "source-page occurrences with bounded target URL and HTTP status "
        "evidence; verification requires a future explicitly authorized crawl.",
        "",
        "| Rule | Verified (TP) | Wrong (FP) | Comparable FN | "
        "Replay-only candidates | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_rule_table_lines(_per_rule_counts(reported), missed))
    lines.extend(
        [
            "",
            "No comparable false negatives were established. The replay-only "
            "candidates are retained as a bounded triage appendix, but "
            "classification or applicability drift means they cannot truthfully "
            "enter recall.",
            "",
            "## Reproduction",
            "",
            "The committed CSVs contain bounded observations and SHA-256 hashes. "
            "Raw response fixtures are local-only and can be replayed by the "
            "audit helper before and after detector changes; no replacement "
            "product crawl was persisted.",
            "",
        ]
    )
    return lines


def _write_manifest(
    root: Path,
    prefix: Path,
    run_id: str,
    run_time: datetime,
    artifact_dir: Path,
    selected_count: int,
    latest: dict[str, dict[str, Any]],
    fetch_manifest: list[dict[str, Any]],
) -> None:
    manifest = {
        "run_id": run_id,
        "created_at": run_time.isoformat(),
        "selected_url_count": selected_count,
        "raw_artifacts": artifact_dir.relative_to(root).as_posix(),
        "raw_artifacts_gitignored": True,
        "companies": list(COMPANIES),
        "crawls": {key: str(value["crawl_id"]) for key, value in latest.items()},
        "body_hashes": {row["url"]: row["body_sha256"] for row in fetch_manifest},
    }
    prefix.with_name(prefix.name + "-fixture-manifest.json").write_text(
        _json(manifest), encoding="utf-8"
    )


def _print_summary(
    root: Path,
    run_id: str,
    prefix: Path,
    selected_count: int,
    reported: list[dict[str, Any]],
    missed: list[dict[str, Any]],
) -> None:
    summary = Counter(row["verdict"] for row in reported)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "selected": selected_count,
                "reported": len(reported),
                "verified": summary["verified"],
                "wrong": summary["wrong"],
                "missed": len(missed),
                "prefix": str(prefix.relative_to(root)),
            },
            indent=2,
        )
    )


def write_audit_outputs(
    *,
    root: Path,
    output_dir: Path,
    run_id: str,
    run_time: datetime,
    artifact_dir: Path,
    selected_count: int,
    latest: dict[str, dict[str, Any]],
    fetch_manifest: list[dict[str, Any]],
    reported: list[dict[str, Any]],
    missed: list[dict[str, Any]],
) -> None:
    stamp = run_time.strftime("%Y-%m-%d")
    prefix = output_dir / f"{stamp}-site-health-50-url-audit"
    _write_csv_artifacts(prefix, fetch_manifest, reported, missed)
    _write_manifest(
        root,
        prefix,
        run_id,
        run_time,
        artifact_dir,
        selected_count,
        latest,
        fetch_manifest,
    )
    lines = _report_lines(
        root, run_id, stamp, artifact_dir, selected_count, reported, missed
    )
    prefix.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    _print_summary(root, run_id, prefix, selected_count, reported, missed)
