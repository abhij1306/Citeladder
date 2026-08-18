# CSV parsing for prompt bulk-import.
#
# The import endpoint accepts either already-parsed JSON rows OR a raw CSV
# upload (the committed frontend contract posts a CSV ``File``; a future F7 may
# parse in the browser and post rows instead). This helper turns raw CSV text
# into ``PromptInput`` rows so both paths converge on the same create logic.
from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from app.core.config.http import (
    IMPORT_MAX_CELL_CHARS,
    IMPORT_MAX_COLUMNS,
    PROMPT_IMPORT_MAX_ROWS,
)
from app.domain.prompts.schemas import PromptInput

# Accepted header aliases -> canonical field. Case/space-insensitive.
_TEXT_KEYS = {"text", "prompt", "query", "question"}
_THEME_KEYS = {"theme", "topic", "category"}
_INTENT_KEYS = {"intent"}
_COHORT_KEYS = {"cohort"}
_ENABLED_KEYS = {"enabled", "is_enabled", "active"}

_TRUTHY = {"1", "true", "yes", "y", "t"}


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    token = value.strip().lower()
    if not token:
        return default
    return token in _TRUTHY


def _cohort(value: str | None) -> str:
    return "comparison" if (value or "").strip().lower() == "comparison" else "core"


def _read_prompt_rows(content: str) -> list[list[str]]:
    text = content.lstrip("\ufeff")
    if not text.strip():
        return []
    rows: list[list[str]] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) > IMPORT_MAX_COLUMNS:
            raise ValueError("Prompt CSV has too many columns")
        if any(len(cell) > IMPORT_MAX_CELL_CHARS for cell in row):
            raise ValueError("Prompt CSV cell is too long")
        if any(cell.strip() for cell in row):
            rows.append(row)
            if len(rows) > PROMPT_IMPORT_MAX_ROWS + 1:
                raise ValueError("Prompt CSV has too many rows")
    return rows


def _column_index(header: list[str], keys: Iterable[str]) -> int | None:
    accepted = set(keys)
    for index, name in enumerate(header):
        if name in accepted:
            return index
    return None


def _prompt_column_indices(header: list[str]) -> dict[str, int | None]:
    return {
        "text": _column_index(header, _TEXT_KEYS),
        "theme": _column_index(header, _THEME_KEYS),
        "intent": _column_index(header, _INTENT_KEYS),
        "cohort": _column_index(header, _COHORT_KEYS),
        "enabled": _column_index(header, _ENABLED_KEYS),
    }


def _prompt_cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    return row[index]


def _parse_prompt_row(
    row: list[str], columns: dict[str, int | None]
) -> PromptInput | None:
    raw_text = (_prompt_cell(row, columns["text"]) or "").strip()
    if not raw_text:
        return None
    return PromptInput(
        text=raw_text,
        theme=(_prompt_cell(row, columns["theme"]) or "").strip(),
        intent=(_prompt_cell(row, columns["intent"]) or "").strip(),
        cohort=_cohort(_prompt_cell(row, columns["cohort"])),
        enabled=_as_bool(_prompt_cell(row, columns["enabled"]), default=True),
    )


def parse_prompt_csv(content: str) -> list[PromptInput]:
    """Parse CSV text into ``PromptInput`` rows.

    Supports a header row (``text,theme,intent,cohort,enabled`` in any order,
    with common aliases) or a headerless single-column file of prompt texts.
    Empty rows are skipped; unknown intents are normalized to ``""`` downstream.
    """
    rows = _read_prompt_rows(content)
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    has_header = any(cell in _TEXT_KEYS for cell in header)
    data_row_count = len(rows) - (1 if has_header else 0)
    if data_row_count > PROMPT_IMPORT_MAX_ROWS:
        raise ValueError("Prompt CSV has too many rows")
    if not has_header:
        # Headerless: treat the first column of each row as the prompt text.
        return [
            PromptInput(text=row[0].strip()) for row in rows if row and row[0].strip()
        ]

    columns = _prompt_column_indices(header)
    prompts: list[PromptInput] = []
    for row in rows[1:]:
        prompt = _parse_prompt_row(row, columns)
        if prompt is not None:
            prompts.append(prompt)
    return prompts
