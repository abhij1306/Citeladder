"""One-shot manual reconciliation of pending billing activations.

Ships in PR1 and must be runnable on day one: without it a single missed
webhook leaves a paying customer with no grants and no recovery path.

It is a BOUNDED, IDEMPOTENT one-shot: it claims at most one batch, settles from
the provider's own authoritative record through the SAME activation transaction
the webhook uses (so a late webhook racing this sweep still creates exactly one
grant bundle), prints safe counts, and exits. All logic lives in the testable
``app.domain.billing.reconciliation`` service.

It accepts NO secrets on argv — Razorpay credentials and every window come from
normal settings (invariant 1). Exit status is nonzero only for a RUN-LEVEL
failure; a per-row provider problem is reported as a count and leaves the row
pending for the next run. Deliberately not a scheduler and not a worker loop;
cron invocation is deferred.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from app.connectors.billing.factory import get_billing_provider
from app.connectors.billing.http_client import aclose_shared_billing_clients
from app.core.config.billing_settings import billing_settings
from app.core.database import SessionLocal
from app.domain.billing.reconciliation import reconcile_pending_activations


async def _run(batch_size: int) -> dict[str, int]:
    try:
        summary = await reconcile_pending_activations(
            SessionLocal,
            get_billing_provider(),
            now=datetime.now(UTC),
            batch_size=batch_size,
        )
    finally:
        await aclose_shared_billing_clients()
    return summary.as_counts()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=billing_settings.reconciliation_batch_size,
        help="Maximum pending activations claimed in this one-shot run.",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        print("--batch-size must be >= 1", file=sys.stderr)
        return 2
    try:
        counts = asyncio.run(_run(args.batch_size))
    except Exception as exc:  # noqa: BLE001 - run-level failure only
        print(f"reconciliation run failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    # Safe counts only: no account id, provider id, amount, or message.
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
