#!/usr/bin/env python3
"""Reset the CiteLadder database: drop, recreate, and run migrations."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import asyncpg
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})


def _database_url() -> str:
    """Resolve DATABASE_URL with the same precedence as the backend settings."""
    environment_url = os.environ.get("DATABASE_URL", "").strip()
    if environment_url:
        return environment_url

    values: dict[str, object] = {}
    for env_file in (PROJECT_ROOT / ".env", BACKEND_DIR / ".env"):
        if env_file.is_file():
            values.update(dotenv_values(env_file))

    database_url = str(values.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required in the environment, .env, or backend/.env"
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


def main() -> None:
    print("=" * 50)
    print("CiteLadder Database Reset")
    print("=" * 50)

    try:
        database_url = _database_url()
        asyncio.run(reset_database(database_url))
        run_migrations(database_url)
    except (RuntimeError, ValueError, OSError, asyncpg.PostgresError) as exc:
        print(f"Database reset failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    print("=" * 50)
    print("Database reset and migrations completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    main()
