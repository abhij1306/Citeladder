"""Operator CLI: propose/verify the v8 commercial catalog's provider price refs.

The catalog is CONFIG-OWNED (invariant 1): every plan/add-on/top-up price and
its PRIVATE provider reference live in ``app/core/config/billing_catalog.py`` and reach
this script only through ``commercial_catalog()``. The script therefore never
invents a key, an amount, or a reference — it reports what the current settings
resolve to so an operator can see exactly which items are unavailable because a
private ref is absent.

Operations:

- ``propose`` prints the catalog items that still need a provider price ref,
  with the exact ``"{catalog_key}:{region}:{purpose}"`` settings key to fill;
- ``verify`` exits nonzero when any purchasable item is missing its ref.

``create`` is deliberately NOT implemented: creating a live provider plan is a
money-moving side effect that belongs to a reviewed operator runbook, not to a
script that could be run by accident. It exits nonzero with a safe message.

No secret is ever accepted on argv or printed: the script reads normal settings
and prints only safe catalog identity (keys, regions, purposes, amounts).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from app.core.config.billing_catalog import (
    PRICE_PURPOSE_BASE,
    PRICE_PURPOSE_CREDIT,
    CatalogPrice,
    commercial_catalog,
)
from app.core.config.billing_contracts import REGIONS
from app.core.config.billing_settings import billing_settings

_OPERATION_CREATE = "create"
_OPERATION_PROPOSE = "propose"
_OPERATION_VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class CatalogRef:
    """One catalog item's regional price and the settings key that names it."""

    catalog_key: str
    region: str
    purpose: str
    currency: str
    amount_minor: int
    configured: bool

    @property
    def settings_key(self) -> str:
        return f"{self.catalog_key}:{self.region}:{self.purpose}"


def _validate_environment(environment: str) -> None:
    key_id = billing_settings.razorpay_key_id.strip()
    expected_prefix = f"rzp_{environment}_"
    if not key_id.startswith(expected_prefix):
        raise RuntimeError(
            f"configured Razorpay key does not match --environment {environment}"
        )


def _ref(
    catalog_key: str, region: str, purpose: str, price: CatalogPrice | None
) -> CatalogRef | None:
    """Project one configured price into a safe operator row (never the ref)."""
    if price is None or price.amount_minor <= 0:
        # An unpriced region is not a missing reference: config owns whether the
        # item is offered there at all.
        return None
    return CatalogRef(
        catalog_key=catalog_key,
        region=region,
        purpose=purpose,
        currency=price.currency,
        amount_minor=price.amount_minor,
        configured=bool(price.provider_price_ref),
    )


def catalog_refs() -> tuple[CatalogRef, ...]:
    """Every priced catalog item/region that needs a provider price ref."""
    catalog = commercial_catalog()
    rows: list[CatalogRef | None] = []
    for region in REGIONS:
        for plan in catalog.plans:
            rows.append(
                _ref(plan.key, region, PRICE_PURPOSE_BASE, plan.base_price(region))
            )
            rows.append(
                _ref(plan.key, region, PRICE_PURPOSE_CREDIT, plan.credit_price(region))
            )
        for addon in catalog.addons:
            rows.append(
                _ref(addon.key, region, PRICE_PURPOSE_BASE, addon.price(region))
            )
        for topup in catalog.topups:
            rows.append(
                _ref(topup.key, region, PRICE_PURPOSE_BASE, topup.price(region))
            )
    return tuple(row for row in rows if row is not None)


def _describe(row: CatalogRef) -> str:
    state = "configured" if row.configured else "MISSING"
    return f"{row.settings_key}\t{row.currency} {row.amount_minor} minor\t{state}"


def _propose(rows: tuple[CatalogRef, ...]) -> int:
    catalog = commercial_catalog()
    print(f"catalog revision: {catalog.revision}")
    missing = [row for row in rows if not row.configured]
    for row in rows:
        print(_describe(row))
    if missing:
        print(
            f"\n{len(missing)} priced item(s) have no provider price ref and are "
            "therefore UNAVAILABLE. Set BILLING_PROVIDER_PRICE_REFS entries for "
            "the keys marked MISSING above.",
            file=sys.stderr,
        )
    return 0


def _verify(rows: tuple[CatalogRef, ...]) -> int:
    missing = [row.settings_key for row in rows if not row.configured]
    if missing:
        print(
            "missing provider price refs: " + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
        return 1
    print(f"all {len(rows)} priced catalog item(s) have a provider price ref")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=(_OPERATION_PROPOSE, _OPERATION_VERIFY, _OPERATION_CREATE)
    )
    parser.add_argument("--environment", required=True, choices=("test", "live"))
    parser.add_argument("--confirm-live", default="")
    args = parser.parse_args()
    try:
        _validate_environment(args.environment)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.operation == _OPERATION_CREATE:
        print(
            "creating a provider plan is a money-moving side effect and is not "
            "automated: follow the operator runbook, then run `verify`.",
            file=sys.stderr,
        )
        return 1
    rows = catalog_refs()
    if args.operation == _OPERATION_PROPOSE:
        return _propose(rows)
    return _verify(rows)


if __name__ == "__main__":
    sys.exit(main())
