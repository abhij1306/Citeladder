from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "reset-db.py"


def _load_reset_db_module():
    spec = importlib.util.spec_from_file_location("reset_db", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_database_url_falls_back_to_root_env(monkeypatch, tmp_path: Path) -> None:
    reset_db = _load_reset_db_module()
    docker_env = tmp_path / "docker.env"
    docker_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:password@127.0.0.1:55432/app\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", docker_env)
    monkeypatch.setattr(reset_db, "PROJECT_ROOT", tmp_path / "missing-root")
    monkeypatch.setattr(reset_db, "BACKEND_DIR", tmp_path / "missing-backend")

    assert reset_db._database_url().endswith("@127.0.0.1:55432/app")


def test_database_url_is_derived_from_docker_postgres_components(
    monkeypatch, tmp_path: Path
) -> None:
    reset_db = _load_reset_db_module()
    docker_env = tmp_path / "docker.env"
    docker_env.write_text(
        "\n".join(
            (
                "POSTGRES_USER=postgres",
                "POSTGRES_PASSWORD=password!with@symbols",
                "POSTGRES_DB=citeladder",
                "POSTGRES_HOST=127.0.0.1",
                "POSTGRES_HOST_PORT=55432",
            )
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", docker_env)
    monkeypatch.setattr(reset_db, "PROJECT_ROOT", tmp_path / "missing-root")
    monkeypatch.setattr(reset_db, "BACKEND_DIR", tmp_path / "missing-backend")

    assert reset_db._database_url() == (
        "postgresql+asyncpg://postgres:password%21with%40symbols"
        "@127.0.0.1:55432/citeladder"
    )


def test_database_url_environment_has_highest_precedence(
    monkeypatch, tmp_path: Path
) -> None:
    reset_db = _load_reset_db_module()
    docker_env = tmp_path / "docker.env"
    docker_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:password@docker:5432/app\n",
        encoding="utf-8",
    )
    environment_url = "postgresql+asyncpg://user:password@localhost:55432/app"

    monkeypatch.setenv("DATABASE_URL", environment_url)
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", docker_env)

    assert reset_db._database_url() == environment_url


def test_database_url_uses_final_merged_postgres_components(
    monkeypatch, tmp_path: Path
) -> None:
    reset_db = _load_reset_db_module()
    root_env = tmp_path / ".env"
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    root_env.write_text(
        "\n".join(
            (
                "POSTGRES_USER=root-user",
                "POSTGRES_PASSWORD=root-password",
                "POSTGRES_DB=root-db",
                "POSTGRES_HOST=root-host",
                "POSTGRES_HOST_PORT=5432",
            )
        ),
        encoding="utf-8",
    )
    (backend_dir / ".env").write_text(
        "POSTGRES_HOST=backend-host\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST_PORT", "55432")
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", root_env)
    monkeypatch.setattr(reset_db, "BACKEND_DIR", backend_dir)

    assert reset_db._database_url() == (
        "postgresql+asyncpg://root-user:root-password@backend-host:55432/root-db"
    )


def test_database_url_reports_every_supported_source(
    monkeypatch, tmp_path: Path
) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", tmp_path / "missing-root.env")
    monkeypatch.setattr(reset_db, "PROJECT_ROOT", tmp_path / "missing-root")
    monkeypatch.setattr(reset_db, "BACKEND_DIR", tmp_path / "missing-backend")

    with pytest.raises(
        RuntimeError,
        match=r"^DATABASE_URL is required in the environment, \.env, or backend/\.env$",
    ):
        reset_db._database_url()


def test_reset_refuses_outside_development(monkeypatch) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(reset_db, "_configuration", lambda: {"APP_ENV": "production"})

    with pytest.raises(RuntimeError, match="Refusing to drop the database"):
        reset_db.authorize_reset()


def test_reset_refuses_when_app_env_is_unset(monkeypatch) -> None:
    # The dangerous default: nothing exported, so nothing declares the database
    # disposable and the drop must not proceed on silence alone.
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(reset_db, "_configuration", dict)

    with pytest.raises(RuntimeError, match=r"\(unset\)"):
        reset_db.authorize_reset()


def test_reset_is_authorized_by_development_or_explicit_token(monkeypatch) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(reset_db, "_configuration", lambda: {"APP_ENV": "development"})
    reset_db.authorize_reset()

    monkeypatch.setattr(
        reset_db,
        "_configuration",
        lambda: {
            "APP_ENV": "staging",
            reset_db.DESTRUCTIVE_RESET_VARIABLE: reset_db.DESTRUCTIVE_RESET_TOKEN,
        },
    )
    reset_db.authorize_reset()


def test_connection_details_redact_credentials_in_query_and_userinfo() -> None:
    reset_db = _load_reset_db_module()
    _admin, redacted, target = reset_db._connection_details(
        "postgresql+asyncpg://user:hunter2@db.example.com:5432/citeladder"
        "?password=hunter2&sslmode=require#hunter2"
    )

    assert target == "citeladder"
    assert "hunter2" not in redacted
    assert redacted == "postgresql://user:***@db.example.com:5432/postgres"


def test_migration_timeout_reads_env_files(monkeypatch) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(
        reset_db,
        "_configuration",
        lambda: {"RESET_MIGRATION_TIMEOUT_SECONDS": "7"},
    )
    monkeypatch.delenv("RESET_MIGRATION_TIMEOUT_SECONDS", raising=False)
    seen: dict[str, float | None] = {}

    def capture(*_args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired("alembic", kwargs["timeout"])

    monkeypatch.setattr(reset_db.subprocess, "run", capture)

    with pytest.raises(SystemExit):
        reset_db.run_migrations("postgresql://localhost/app")

    assert seen["timeout"] == 7.0


def test_development_reset_requires_dev_login_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(reset_db, "ROOT_ENV_FILE", tmp_path / "missing-root.env")
    monkeypatch.setattr(reset_db, "PROJECT_ROOT", tmp_path / "missing-root")
    monkeypatch.setattr(reset_db, "BACKEND_DIR", tmp_path / "missing-backend")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DEV_LOGIN_EMAIL", raising=False)
    monkeypatch.delenv("DEV_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("DEV_LOGIN_COUNTER_ALLOWANCE", raising=False)

    with pytest.raises(RuntimeError, match="DEV_LOGIN_EMAIL"):
        reset_db.provision_dev_login("postgresql://localhost/app")


def test_development_login_provisioning_timeout_exits_cleanly(monkeypatch) -> None:
    reset_db = _load_reset_db_module()
    monkeypatch.setattr(
        reset_db,
        "_configuration",
        lambda: {
            "APP_ENV": "development",
            "DEV_LOGIN_EMAIL": "dev@example.com",
            "DEV_LOGIN_PASSWORD": "password123",
            "DEV_LOGIN_COUNTER_ALLOWANCE": "100",
            "RESET_PROVISION_TIMEOUT_SECONDS": "12",
        },
    )

    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired("provision", kwargs["timeout"])

    monkeypatch.setattr(reset_db.subprocess, "run", timeout)

    with pytest.raises(SystemExit) as exc:
        reset_db.provision_dev_login("postgresql://localhost/app")

    assert exc.value.code == 1
