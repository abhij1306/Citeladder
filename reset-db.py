#!/usr/bin/env python3
"""Reset the CiteLadder database: drop, recreate, and run migrations."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import asyncpg
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DOCKER_ENV_FILE = PROJECT_ROOT / "infra" / "docker" / ".env"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})
DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test", "testing"})


def _configuration() -> dict[str, str]:
    """Load repository env files, with the process environment taking priority."""
    values = _read_env_file(DOCKER_ENV_FILE)
    docker_database_url = _docker_database_url(values)
    if docker_database_url:
        values["DATABASE_URL"] = docker_database_url

    for env_file in (PROJECT_ROOT / ".env", BACKEND_DIR / ".env"):
        if env_file.is_file():
            values.update(_read_env_file(env_file))
    values.update(os.environ)
    return values


def _read_env_file(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        return {}
    return {
        key: str(value)
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }


def _docker_database_url(values: dict[str, str]) -> str:
    required = (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_HOST_PORT",
    )
    if not all(values.get(key, "").strip() for key in required):
        return ""
    user = quote(values["POSTGRES_USER"].strip(), safe="")
    password = quote(values["POSTGRES_PASSWORD"].strip(), safe="")
    database = quote(values["POSTGRES_DB"].strip(), safe="")
    host = values["POSTGRES_HOST"].strip()
    port = values["POSTGRES_HOST_PORT"].strip()
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def _database_url() -> str:
    """Resolve DATABASE_URL with the same precedence as the backend settings."""
    database_url = _configuration().get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required in the environment, .env, backend/.env, "
            "or infra/docker/.env"
        )
    return database_url


def _connection_details(database_url: str) -> tuple[str, str, str]:
    driver_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlsplit(driver_url)
    target_db = unquote(parsed.path.removeprefix("/"))
    if not target_db:
        raise RuntimeError("DATABASE_URL must name the database to reset")
    if target_db.casefold() in PROTECTED_DATABASES:
        raise RuntimeError(f"Refusing to reset protected database '{target_db}'")

    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    user = parsed.username or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = f"{user}:***@" if parsed.password is not None else f"{user}@"
    redacted_netloc = f"{credentials}{hostname}{port}" if user else f"{hostname}{port}"
    redacted = urlunsplit(parsed._replace(netloc=redacted_netloc, path="/postgres"))
    return admin_url, redacted, target_db


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


async def reset_database(database_url: str) -> None:
    """Drop and recreate the citeladder database."""
    admin_url, redacted_url, target_db = _connection_details(database_url)
    quoted_target = _quote_identifier(target_db)
    print(f"Connecting to {redacted_url}...")
    conn = await asyncpg.connect(admin_url)
    try:
        print(f"Dropping database '{target_db}' if exists...")
        await conn.execute(f"DROP DATABASE IF EXISTS {quoted_target} WITH (FORCE)")
        print(f"Creating database '{target_db}'...")
        await conn.execute(f"CREATE DATABASE {quoted_target}")
    finally:
        await conn.close()
    print("Database reset complete.")


def run_migrations(database_url: str) -> None:
    """Run alembic migrations from the backend directory."""
    print("Running alembic migrations...")
    migration_environment = os.environ.copy()
    migration_environment["DATABASE_URL"] = database_url
    timeout_value = os.environ.get("RESET_MIGRATION_TIMEOUT_SECONDS", "").strip()
    migration_timeout = float(timeout_value) if timeout_value else None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=migration_timeout,
            check=False,
            env=migration_environment,
        )
    except subprocess.TimeoutExpired as exc:
        print(
            f"Migration timed out after {exc.timeout:g} seconds.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    if result.returncode != 0:
        print(f"Migration failed:\n{result.stderr}")
        sys.exit(1)
    print(result.stdout)
    print("Migrations complete.")


def provision_dev_login(database_url: str) -> None:
    """Provision the configured local-development login after every reset."""
    configuration = _configuration()
    app_env = configuration.get("APP_ENV", "").strip().lower()
    if app_env not in DEVELOPMENT_ENVS:
        # Say so. This used to return in silence, so a reset run with APP_ENV
        # unset — or overridden in the shell, which wins over every .env file
        # here — wiped the database, printed "completed successfully", and left
        # no account to log in with. The reset still succeeds; only the login
        # is skipped, and now that is visible.
        print(
            f"APP_ENV is '{app_env or '(unset)'}', not one of "
            f"{sorted(DEVELOPMENT_ENVS)} — skipping development login "
            "provisioning. No account was created."
        )
        return

    email = configuration.get("DEV_LOGIN_EMAIL", "").strip()
    password = configuration.get("DEV_LOGIN_PASSWORD", "").strip()
    counter_allowance = configuration.get("DEV_LOGIN_COUNTER_ALLOWANCE", "").strip()
    if not email or not password or not counter_allowance:
        raise RuntimeError(
            "DEV_LOGIN_EMAIL, DEV_LOGIN_PASSWORD, and DEV_LOGIN_COUNTER_ALLOWANCE "
            "are required for a development database reset"
        )

    print("Provisioning development login...")
    provision_environment = os.environ.copy()
    provision_environment.update(configuration)
    provision_environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.provision_dev_login",
            "--email",
            email,
            "--password",
            password,
            "--counter-allowance",
            counter_allowance,
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
        env=provision_environment,
    )
    if result.returncode != 0:
        print(f"Development login provisioning failed:\n{result.stderr}")
        raise SystemExit(1)
    print(result.stdout)
    _verify_dev_login(provision_environment, email=email, password=password)
    print("Development login ready.")


# Run in the backend package so it resolves the same settings and session the
# API does. Credentials arrive through the environment, never argv, so they do
# not surface in the process list.
_VERIFY_LOGIN = """
import asyncio, os, sys

from app.core.database import SessionLocal, dispose_engine
from app.domain.auth.service import authenticate_user


async def main() -> None:
    async with SessionLocal() as session:
        # Returns ``(access_token, user)`` on success, ``None`` on failure.
        authenticated = await authenticate_user(
            session, os.environ["_VERIFY_EMAIL"], os.environ["_VERIFY_PASSWORD"]
        )
    await dispose_engine()
    if authenticated is None:
        sys.exit("credentials did not authenticate")
    _token, user = authenticated
    print(f"verified login for {user.email} (id={user.id})")


asyncio.run(main())
"""


def _verify_dev_login(environment: dict[str, str], *, email: str, password: str) -> None:
    """Prove the provisioned credentials actually authenticate.

    Provisioning reported success whenever the row was written, which is a
    weaker claim than the one the operator reads it as. This runs the API's own
    ``authenticate_user`` against the freshly written row, so "Development login
    ready" means the ``.env`` credentials were tried and worked rather than that
    a user record exists.
    """
    print("Verifying development login...")
    verify_environment = dict(environment)
    verify_environment["_VERIFY_EMAIL"] = email
    verify_environment["_VERIFY_PASSWORD"] = password
    result = subprocess.run(
        [sys.executable, "-c", _VERIFY_LOGIN],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
        env=verify_environment,
    )
    if result.returncode != 0:
        print(
            "Development login verification FAILED — the account was written "
            f"but does not authenticate:\n{result.stderr}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(result.stdout.strip())


def main() -> None:
    print("=" * 50)
    print("CiteLadder Database Reset")
    print("=" * 50)

    try:
        database_url = _database_url()
        asyncio.run(reset_database(database_url))
        run_migrations(database_url)
        provision_dev_login(database_url)
    except (RuntimeError, ValueError, OSError, asyncpg.PostgresError) as exc:
        print(f"Database reset failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    print("=" * 50)
    print("Database reset and migrations completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    main()
