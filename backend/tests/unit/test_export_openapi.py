from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import export_openapi


def test_export_openapi_writes_the_versioned_api_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "nested" / "openapi.json"

    export_openapi(output)

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["info"]["title"] == "CiteLadder"
    assert "/health" in document["paths"]
    assert any(path.startswith("/api/v1/") for path in document["paths"])


def test_export_openapi_rejects_output_outside_the_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    try:
        export_openapi(tmp_path / "openapi.json")
    except ValueError as error:
        assert "must stay within" in str(error)
    else:
        raise AssertionError("export_openapi accepted an output outside the workspace")
