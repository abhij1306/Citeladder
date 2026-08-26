"""Reference-catalog evaluator for an exported Commerce catalog snapshot."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _workspace_file(raw: Path) -> Path:
    """Resolve a CLI input without allowing reads outside the working tree."""
    root = Path.cwd().resolve()
    resolved = raw.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evaluation input must be inside {root}") from exc
    if not resolved.is_file():
        raise ValueError(f"evaluation input is not a file: {resolved}")
    return resolved


def evaluate_catalog(
    exported: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    """Report false positives, false negatives, and canonical identity collisions."""
    observed = {
        str(row.get("canonical_url") or "")
        for row in exported.get("products", [])
        if isinstance(row, dict) and row.get("canonical_url")
    }
    expected = {
        str(row.get("canonical_url") or "")
        for row in reference.get("products", [])
        if isinstance(row, dict) and row.get("canonical_url")
    }
    identities = [
        str(row.get("canonical_url") or "")
        for row in exported.get("products", [])
        if isinstance(row, dict) and row.get("canonical_url")
    ]
    counts = Counter(identities)
    return {
        "expected_count": len(expected),
        "observed_count": len(observed),
        "false_positives": sorted(observed - expected),
        "false_negatives": sorted(expected - observed),
        "identity_collisions": sorted(
            url for url, count in counts.items() if count > 1
        ),
        "passed": observed == expected and all(count == 1 for count in counts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("exported", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    exported_path = _workspace_file(args.exported)
    reference_path = _workspace_file(args.reference)
    report = evaluate_catalog(
        json.loads(exported_path.read_text(encoding="utf-8")),
        json.loads(reference_path.read_text(encoding="utf-8")),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
