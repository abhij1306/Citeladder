# Serialization shim: catalog rows -> the plain product-scorer config dict.
#
# Mirrors ``domain/projects/shim.py project_scoring_identity``: the catalog is
# stored as normalized ``Product`` rows, but the
# deterministic product scorer consumes a plain dict via
# ``ProductScoringConfig.from_project``. The planner freezes this dict into
# every audit's ``configuration`` at creation (next to ``scoring_identity``)
# so re-scoring is deterministic — later catalog edits never alter an
# in-flight or completed audit (invariant 9).
#
# The dict shape:
#     {
#       "products": [
#           {"id", "sku", "name", "aliases", "variants", "price", "currency",
#            "url", "attributes"},
#           ...
#       ],
#     }
# Ids are strings; prices are floats (or None).
from __future__ import annotations

from typing import Any

from app.models.project import Project


def _price(value: Any) -> float | None:
    return float(value) if value is not None else None


def _project_variants(variants: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "name": str(variant.get("name") or ""),
            "sku": str(variant.get("sku") or ""),
            "price": _price(variant.get("price")),
        }
        for variant in (variants or [])
        if isinstance(variant, dict)
    ]


def _project_products(project: Project) -> list[dict[str, Any]]:
    return [
        {
            "id": str(product.id),
            "sku": product.sku or "",
            "name": product.name or "",
            "aliases": list(product.aliases or []),
            "variants": _project_variants(product.variants),
            "price": _price(product.price),
            "currency": product.currency or "",
            "url": product.url or "",
            "attributes": dict(product.attributes or {}),
        }
        for product in project.products
    ]


def project_product_identity(project: Project) -> dict[str, Any]:
    """Rebuild the plain catalog dict the product scorer expects from rows.

    Requires the project's ``products`` relationship to be loaded.
    """
    return {
        "products": _project_products(project),
    }
