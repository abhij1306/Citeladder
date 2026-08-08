"""Benchmark the pure in-memory reference classifier on catalog fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from itertools import cycle, islice
from typing import Any

from .catalog import CATALOG_ROOT, load_pack, pack_manifest, registry
from .reference import classify_page, compile_pack


def _registered_version(pack_id: str) -> str:
    matches = [entry for entry in registry()["packs"] if entry["pack_id"] == pack_id]
    if len(matches) != 1:
        raise ValueError(f"unknown or multiply registered pack: {pack_id}")
    return str(matches[0]["version"])


def _fixture_facts(pack_id: str) -> tuple[dict[str, Any], ...]:
    path = CATALOG_ROOT / "fixtures" / pack_id / "role-classification.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    facts = tuple(case["facts"] for case in fixture["cases"])
    if not facts:
        raise ValueError(f"role fixture is empty for {pack_id}")
    return facts


def run_benchmark(
    pack_id: str,
    pages: int,
    *,
    warmup_pages: int = 500,
) -> dict[str, Any]:
    """Run a deterministic fixture-cycle benchmark and return measured metrics."""

    if pages <= 0:
        raise ValueError("pages must be greater than zero")
    if warmup_pages < 0:
        raise ValueError("warmup_pages must be zero or greater")

    version = _registered_version(pack_id)
    pack = load_pack(pack_id, version)
    compiled = compile_pack(
        pack,
        manifest=pack_manifest(pack_id, version),
    )
    facts = _fixture_facts(pack_id)

    for item in islice(cycle(facts), warmup_pages):
        classify_page(compiled, item)

    classified = 0
    abstained = 0
    conflicts = 0
    digest = hashlib.sha256()
    started = time.perf_counter_ns()
    for item in islice(cycle(facts), pages):
        result = classify_page(compiled, item)
        primary = result["primary_role_id"]
        reason = result["abstention_reason"]
        if primary is None:
            abstained += 1
        else:
            classified += 1
        conflicts += len(result["conflicts"])
        digest.update(str(primary or reason).encode("utf-8"))
        digest.update(b"\0")
    elapsed_ns = time.perf_counter_ns() - started

    elapsed_seconds = elapsed_ns / 1_000_000_000
    pages_per_second = pages / elapsed_seconds
    average_microseconds = elapsed_ns / pages / 1_000
    return {
        "benchmark_version": "industry-role-classifier-benchmark-1.0.0",
        "runtime_scope": (
            "pure in-memory reference classifier; catalog I/O and compilation "
            "excluded from timed loop"
        ),
        "pack_id": pack_id,
        "pack_version": version,
        "pack_content_hash": compiled.manifest["pack_content_hash"],
        "classifier_version": compiled.classifier_version,
        "pages": pages,
        "warmup_pages": warmup_pages,
        "fixture_case_count": len(facts),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "pages_per_second": round(pages_per_second, 2),
        "average_microseconds_per_page": round(average_microseconds, 3),
        "classified_pages": classified,
        "abstained_pages": abstained,
        "conflict_records": conflicts,
        "result_checksum": digest.hexdigest(),
    }


def _build_parser() -> argparse.ArgumentParser:
    pack_ids = tuple(str(entry["pack_id"]) for entry in registry()["packs"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, choices=pack_ids)
    parser.add_argument("--pages", type=int, default=10_000)
    parser.add_argument("--warmup-pages", type=int, default=500)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = run_benchmark(
            args.pack,
            args.pages,
            warmup_pages=args.warmup_pages,
        )
    except ValueError as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
