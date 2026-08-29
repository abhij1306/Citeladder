"""Export the FastAPI OpenAPI document for cross-stack contract validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.main import app


def export_openapi(output: Path) -> None:
    """Write a deterministic JSON representation of the shipped API contract."""
    workspace = Path.cwd().resolve()
    resolved_output = output.resolve()
    if not resolved_output.is_relative_to(workspace):
        msg = f"OpenAPI output must stay within {workspace}"
        raise ValueError(msg)

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    export_openapi(arguments.output)


if __name__ == "__main__":
    main()
