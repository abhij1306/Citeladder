"""Provision one development-only owner with every issuable capability.

The command fails closed unless ``APP_ENV`` is development-like and the
database host is local. Credentials and counter allowances are required CLI
inputs so no reusable password or capacity knob lives in service code.

Usage (from backend/):
    uv run python -m scripts.provision_dev_login \
        --email dev@citeladder.com \
        --password "..." \
        --counter-allowance 1000000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.config.entitlements import CAPABILITY_REGISTRY, CapabilityType
from app.core.database import SessionLocal, dispose_engine
from app.domain.auth.service import authenticate_user, get_user_by_email, register_user
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.entitlements.grants import issue_override_bundle
from app.domain.entitlements.types import GrantSpec
from app.domain.workspaces.service import ensure_personal_workspace
from app.models.workspace import Workspace, WorkspaceMember

_DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test", "testing"})
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _require_local_development_target() -> None:
    env = str(settings.app_env or "").strip().lower()
    url = make_url(settings.database_url)
    if env not in _DEVELOPMENT_ENVS or url.host not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing to provision a fixed dev login outside a local "
            "development database"
        )


def _full_access_grants(counter_allowance: int) -> tuple[GrantSpec, ...]:
    grants: list[GrantSpec] = []
    for capability in CAPABILITY_REGISTRY.entries:
        if not capability.issuable:
            continue
        if capability.capability_type is CapabilityType.FLAG:
            value = 1
        elif capability.capability_type is CapabilityType.LEVEL:
            value = len(capability.ordered_values) - 1
        else:
            value = counter_allowance
        grants.append(GrantSpec(key=capability.key, value=value))
    return tuple(grants)


async def _run(email: str, password: str, counter_allowance: int) -> None:
    _require_local_development_target()
    try:
        async with SessionLocal() as session:
            user = await get_user_by_email(session, email)
            if user is None:
                user = await register_user(session, email, password, role="admin")
                if user is None:
                    user = await get_user_by_email(session, email)
                if user is None:
                    raise RuntimeError("Development login registration did not persist")
            if user.role != "admin":
                raise RuntimeError("Existing development login is not an admin account")
            workspace = await ensure_personal_workspace(session, user)
            if workspace is None:
                workspace = await session.scalar(
                    select(Workspace)
                    .join(
                        WorkspaceMember,
                        WorkspaceMember.workspace_id == Workspace.id,
                    )
                    .where(WorkspaceMember.user_id == user.id)
                    .order_by(Workspace.created_at.asc(), Workspace.id.asc())
                )
            if workspace is None:
                raise RuntimeError("Development user has no workspace membership")
            account = await ensure_user_billing(
                session, user, workspace_ids=(workspace.id,)
            )
            await issue_override_bundle(
                session,
                operator_user=user,
                account_id=account.id,
                grants=_full_access_grants(counter_allowance),
                reason="local development full-access account",
                valid_from=datetime.now(UTC),
                valid_until=None,
                idempotency_key=f"dev-full-access:{user.id}",
            )
            await session.commit()
            print(f"email={user.email}")
            print(f"workspace_id={workspace.id}")
            print("role=admin capabilities=all_issuable")

            # Authenticate while this backend process is already warm. Starting a
            # second process just for this check made a reset appear to hang on a
            # cold Windows filesystem even though password verification is fast.
            print("Verifying development login...")
            authenticated = await authenticate_user(session, email, password)
            if authenticated is None:
                raise RuntimeError(
                    "Development account was written but its credentials did not "
                    "authenticate"
                )
            _token, authenticated_user = authenticated
            print(
                f"verified login for {authenticated_user.email} "
                f"(id={authenticated_user.id})"
            )
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--counter-allowance", required=True, type=int)
    args = parser.parse_args(argv)
    if args.counter_allowance < 1:
        parser.error("--counter-allowance must be positive")
    asyncio.run(_run(args.email, args.password, args.counter_allowance))
    return 0


if __name__ == "__main__":
    sys.exit(main())
