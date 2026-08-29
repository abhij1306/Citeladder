"""Non-blocking reference diagnostics for an exported Commerce catalog."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
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


def _rows(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _reference_rows(reference: dict[str, Any]) -> list[dict[str, Any]]:
    categories = _rows(reference.get("categories"), label="reference.categories")
    rows: list[dict[str, Any]] = []
    for category in categories:
        products = _rows(
            category.get("products"),
            label=f"reference category {category.get('name', '')}.products",
        )
        for product in products:
            rows.append(
                {
                    **product,
                    "category_name": product.get("category_name")
                    or category.get("name"),
                    "category_url": product.get("category_url") or category.get("url"),
                }
            )
    return rows


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _comparison(
    references: list[dict[str, Any]],
    observed_by_url: dict[str, dict[str, Any]],
    *,
    observed_field: str,
    reference_field: str,
    normalize: Callable[[Any], Any],
) -> dict[str, Any]:
    matched: list[str] = []
    changed: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for reference in references:
        url = str(reference.get("product_url") or "")
        observed = observed_by_url.get(url)
        value = observed.get(observed_field) if observed else None
        if value in (None, ""):
            unavailable.append(url)
        elif normalize(value) == normalize(reference.get(reference_field)):
            matched.append(url)
        else:
            changed.append(
                {
                    "canonical_url": url,
                    "reference": reference.get(reference_field),
                    "observed": value,
                    "classification": "unresolved",
                }
            )
    return {
        "matched_count": len(matched),
        "changed_count": len(changed),
        "unavailable_count": len(unavailable),
        "matched": matched,
        "changed": changed,
        "unavailable": unavailable,
    }


def _membership_bucket(
    reference: dict[str, Any],
    observed_by_url: dict[str, dict[str, Any]],
    by_url: dict[str, dict[str, Any]],
    by_name: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Classify one reference row as observed / changed / missing / unavailable."""
    product_url = str(reference.get("product_url") or "")
    category_url = str(reference.get("category_url") or "")
    category_name = str(reference.get("category_name") or "")
    expected = {"product_url": product_url, "category_url": category_url}
    product = observed_by_url.get(product_url)
    category = by_url.get(category_url) or by_name.get(_normalized_text(category_name))
    if product is None or category is None:
        return "unavailable", expected
    category_ids = [str(value) for value in product.get("category_ids") or []]
    if str(category.get("id") or "") in category_ids:
        return "observed", expected
    if category_ids:
        return "changed", {**expected, "observed_category_ids": category_ids}
    return "missing", expected


def _membership_report(
    references: list[dict[str, Any]],
    observed_by_url: dict[str, dict[str, Any]],
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    by_url = {str(row.get("canonical_url") or ""): row for row in categories}
    by_name = {_normalized_text(row.get("name")): row for row in categories}
    buckets: dict[str, list[dict[str, Any]]] = {
        "observed": [],
        "missing": [],
        "changed": [],
        "unavailable": [],
    }
    for reference in references:
        bucket, payload = _membership_bucket(
            reference, observed_by_url, by_url, by_name
        )
        buckets[bucket].append(payload)
    return {
        "reference_count": len(references),
        **{f"{name}_count": len(rows) for name, rows in buckets.items()},
        **buckets,
    }


def _row_identifier_violations(
    reference: dict[str, Any], observed: dict[str, Any]
) -> list[dict[str, str]]:
    """Identifier fields on one product whose value was derived, not sourced."""
    url = str(reference.get("product_url") or "")
    derived = {
        str(reference.get("product_identifier") or ""),
        str(reference.get("style_code") or ""),
        str(reference.get("catalog_numeric_id") or ""),
    } - {""}
    sources = observed.get("field_sources")
    sources = sources if isinstance(sources, dict) else {}
    violations: list[dict[str, str]] = []
    for field in ("sku", "gtin", "mpn"):
        value = str(observed.get(field) or "")
        source = sources.get(field)
        source_kind = source.get("kind") if isinstance(source, dict) else ""
        if value in derived and source_kind not in {"site_health", "csv", "edit"}:
            violations.append({"canonical_url": url, "field": field, "value": value})
    return violations


def _identifier_violations(
    references: list[dict[str, Any]], observed_by_url: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for reference in references:
        observed = observed_by_url.get(str(reference.get("product_url") or ""))
        if observed is not None:
            violations.extend(_row_identifier_violations(reference, observed))
    return violations


def _index_products(
    products: list[dict[str, Any]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return the exported canonical URLs and the first row for each of them."""
    observed_urls: list[str] = []
    observed_by_url: dict[str, dict[str, Any]] = {}
    for row in products:
        url = str(row.get("canonical_url") or "")
        if url:
            observed_urls.append(url)
            observed_by_url.setdefault(url, row)
    return observed_urls, observed_by_url


def _acquisition_report(unavailable: Any) -> dict[str, Any]:
    """An export that omits the list is distinct from one reporting none."""
    if isinstance(unavailable, list):
        return {"state": "reported", "items": unavailable}
    return {"state": "unavailable_in_export", "items": []}


def evaluate_catalog(
    exported: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    """Compare a dated reference without turning drift into a release gate."""
    if not isinstance(exported, dict) or not isinstance(reference, dict):
        raise ValueError("exported catalog and reference must be objects")
    products = _rows(exported.get("products"), label="exported.products")
    categories = _rows(exported.get("categories"), label="exported.categories")
    references = _reference_rows(reference)
    expected_urls = {str(row.get("product_url") or "") for row in references} - {""}
    observed_urls, observed_by_url = _index_products(products)
    counts = Counter(observed_urls)
    title_report = _comparison(
        references,
        observed_by_url,
        observed_field="name",
        reference_field="product_title",
        normalize=_normalized_text,
    )
    price_report = _comparison(
        references,
        observed_by_url,
        observed_field="price",
        reference_field="current_price_aud",
        normalize=lambda value: round(float(value), 2),
    )
    memberships = _membership_report(references, observed_by_url, categories)
    drift = [
        *title_report["changed"],
        *price_report["changed"],
        *memberships["changed"],
    ]
    acquisition_report = _acquisition_report(exported.get("acquisition_unavailable"))
    observed_url_set = set(observed_urls)
    return {
        "reference_dataset_id": reference.get("dataset_id"),
        "reference_crawl_date": reference.get("crawl_date"),
        "reference_urls": {
            "reference_count": len(expected_urls),
            "observed_count": len(expected_urls & observed_url_set),
            "missing": sorted(expected_urls - observed_url_set),
            "non_reference_products": sorted(observed_url_set - expected_urls),
        },
        "category_memberships": memberships,
        "category_urls_emitted_as_products": sorted(
            {
                str(row.get("category_url") or "")
                for row in references
                if row.get("category_url") in observed_url_set
            }
        ),
        "duplicate_canonical_products": sorted(
            url for url, count in counts.items() if count > 1
        ),
        "titles": title_report,
        "prices": price_report,
        "identifier_provenance_violations": _identifier_violations(
            references, observed_by_url
        ),
        "acquisition_unavailable": acquisition_report,
        "reference_drift": {
            "classification": "unresolved",
            "count": len(drift),
            "items": drift,
        },
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


if __name__ == "__main__":
    main()
