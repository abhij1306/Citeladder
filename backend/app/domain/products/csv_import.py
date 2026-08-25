# CSV parsing for the product-catalog bulk-import.
#
# Mirrors ``domain/prompts/csv_import.py``: raw CSV text -> ``ProductInput``
# rows so the multipart-upload and JSON-rows import paths converge on the same
# create logic. DELIBERATE DEVIATION from prompts: headerless files are
# REJECTED — a product CSV without headers makes sku/name mapping ambiguous
# (``parse_prompt_csv`` accepts a headerless single column of texts).
from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from typing import NamedTuple

from pydantic import ValidationError

from app.core.config.http import IMPORT_MAX_CELL_CHARS, IMPORT_MAX_COLUMNS
from app.core.config.products import PRODUCT_IMPORT_MAX_ROWS
from app.core.errors import sanitize_validation_errors
from app.domain.products.schemas import (
    ProductImportRowError,
    ProductInput,
    ProductVariant,
)

# Accepted header aliases -> canonical field. Case/space/underscore-insensitive.
_SKU_KEYS = {"sku", "sku_id", "product_sku", "product_id"}
_NAME_KEYS = {"name", "product", "product_name", "product_title", "title"}
_PRICE_KEYS = {"price", "price_amount", "amount"}
_CURRENCY_KEYS = {"currency", "currency_code", "price_currency"}
_URL_KEYS = {"url", "link", "product_url", "owned_url"}
_ALIASES_KEYS = {"aliases", "alias"}
_VARIANT_KEYS = {"variant", "variants"}
# Extra columns folded into the ``attributes`` bag (completeness matrix keys).
_ATTRIBUTE_KEYS = {
    "brand": ("brand",),
    "category": ("category", "collection", "product_type"),
    "gtin": ("gtin", "barcode", "upc", "ean", "gtin13"),
    "mpn": ("mpn",),
    "availability": ("availability", "stock_status"),
    "condition": ("condition",),
    "description": ("description", "desc"),
    "variant_count": ("variant_count", "variants_count"),
}

_ALIAS_SEPARATORS = ("|", ";")


class ProductCsvError(ValueError):
    """Raised when a product CSV cannot be parsed into unambiguous rows."""


class ProductCsvParseResult(NamedTuple):
    """Numbered import rows plus the per-row skips (D1 import feedback).

    ``rows`` pairs each parsed row with its 1-based DATA-row number (the
    header is row 0, fully-blank rows are dropped before numbering) — the
    same numbering the browser preview shows. ``errors`` carries the rows
    that were skipped (empty sku, failing field validation) with reasons.
    """

    rows: list[tuple[int, ProductInput]]
    errors: list[ProductImportRowError]


def _split_list(value: str) -> list[str]:
    for separator in _ALIAS_SEPARATORS:
        if separator in value:
            return [part.strip() for part in value.split(separator) if part.strip()]
    return [value.strip()] if value.strip() else []


def _parse_price(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    # Tolerate currency symbols / thousand separators in the price column.
    text = text.replace(",", "")
    for symbol in ("US$", "AU$", "CA$", "A$", "C$", "$", "€", "£"):
        text = text.replace(symbol, "")
    text = text.strip()
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _row_validation_error(
    row_number: int, exc: ValidationError
) -> ProductImportRowError:
    """A failing ``ProductInput`` row -> a sanitized, skipped-row reason.

    Never a 500 (COM-5). Two shapes are guarded: an EMPTY sanitized list must
    not be indexed, and a ``loc`` carrying a sequence index (``variants``, 0)
    must be stringified before joining.
    """
    sanitized = sanitize_validation_errors(exc.errors())
    first = sanitized[0] if sanitized else {}
    return ProductImportRowError(
        row=row_number,
        field=".".join(str(part) for part in first.get("loc", ())),
        message=first.get("message") or "Invalid value",
    )


def _read_product_rows(content: str) -> list[list[str]]:
    text = content.lstrip("\ufeff")
    if not text.strip():
        return []
    rows: list[list[str]] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) > IMPORT_MAX_COLUMNS:
            raise ProductCsvError("Product CSV has too many columns")
        if any(len(cell) > IMPORT_MAX_CELL_CHARS for cell in row):
            raise ProductCsvError("Product CSV cell is too long")
        if any(cell.strip() for cell in row):
            rows.append(row)
            if len(rows) > PRODUCT_IMPORT_MAX_ROWS + 1:
                raise ProductCsvError("Product CSV has too many rows")
    return rows


def _column_index(header: list[str], keys: Iterable[str]) -> int | None:
    accepted = set(keys)
    for index, name in enumerate(header):
        if name in accepted:
            return index
    return None


def _product_column_indices(header: list[str]) -> dict[str, int | None]:
    columns = {
        "sku": _column_index(header, _SKU_KEYS),
        "name": _column_index(header, _NAME_KEYS),
        "price": _column_index(header, _PRICE_KEYS),
        "currency": _column_index(header, _CURRENCY_KEYS),
        "url": _column_index(header, _URL_KEYS),
        "aliases": _column_index(header, _ALIASES_KEYS),
        "variant": _column_index(header, _VARIANT_KEYS),
    }
    columns.update(
        {
            f"attribute:{key}": _column_index(header, aliases)
            for key, aliases in _ATTRIBUTE_KEYS.items()
        }
    )
    if columns["sku"] is None or columns["name"] is None:
        raise ProductCsvError(
            "Product CSV must include a header row with at least 'sku' and "
            "'name' columns"
        )
    return columns


def _product_cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _parse_product_row(
    row_number: int,
    row: list[str],
    columns: dict[str, int | None],
) -> tuple[ProductInput | None, ProductImportRowError | None]:
    sku = _product_cell(row, columns["sku"])
    if not sku:
        return None, ProductImportRowError(
            row=row_number,
            field="sku",
            message="Missing sku — the row was skipped (sku is the import identity)",
        )
    attributes = {
        key.removeprefix("attribute:"): _product_cell(row, index)
        for key, index in columns.items()
        if key.startswith("attribute:")
        and index is not None
        and _product_cell(row, index)
    }
    try:
        variant = _product_cell(row, columns["variant"])
        return ProductInput(
            sku=sku,
            name=_product_cell(row, columns["name"]) or sku,
            aliases=_split_list(_product_cell(row, columns["aliases"])),
            variants=[ProductVariant(name=variant)] if variant else [],
            price=_parse_price(_product_cell(row, columns["price"])),
            currency=_product_cell(row, columns["currency"]),
            url=_product_cell(row, columns["url"]),
            attributes=attributes,
        ), None
    except ValidationError as exc:
        return None, _row_validation_error(row_number, exc)


def parse_product_csv(content: str) -> ProductCsvParseResult:
    """Parse CSV text into numbered ``ProductInput`` rows + row-level skips.

    Requires a header row with at least ``name`` and ``sku`` (aliases
    accepted, any column order). BOM-stripped; fully-blank rows are skipped.
    Rows with an empty ``sku`` or that fail ``ProductInput`` validation are
    skipped WITH a reason (D1 — previously silent / an unhandled 500); a
    missing ``name`` falls back to the sku.
    """
    rows = _read_product_rows(content)
    if not rows:
        return ProductCsvParseResult(rows=[], errors=[])

    header = [cell.strip().lower().replace(" ", "_") for cell in rows[0]]
    columns = _product_column_indices(header)

    products: list[tuple[int, ProductInput]] = []
    errors: list[ProductImportRowError] = []
    for row_number, row in enumerate(rows[1:], start=1):
        product, error = _parse_product_row(row_number, row, columns)
        if product is not None:
            products.append((row_number, product))
        if error is not None:
            errors.append(error)
    return ProductCsvParseResult(rows=products, errors=errors)
