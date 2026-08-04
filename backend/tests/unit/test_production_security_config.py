"""Production startup policy for independent high-entropy secrets and DB TLS."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings, validate_production_security

_VALID = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"


def _production_settings(**updates: object) -> Settings:
    values = {
        "app_env": "production",
        "jwt_secret_key": _VALID + "jwt",
        "encryption_key": _VALID + "enc",
        "referral_hash_salt": _VALID + "ref",
        "order_hash_salt": _VALID + "order",
        "database_url": (
            f"postgresql+asyncpg://citeladder:{_VALID}db@database.example.com/citeladder"
        ),
        "db_ssl_mode": "require",
    }
    values.update(updates)
    return settings.model_copy(update=values)


def test_valid_independent_production_secrets_pass() -> None:
    assert validate_production_security(_production_settings()) == []


@pytest.mark.parametrize("weak", ["", "x", "password", "a" * 64])
def test_weak_application_secrets_are_rejected_without_echoing_value(
    weak: str,
) -> None:
    issues = validate_production_security(_production_settings(jwt_secret_key=weak))
    assert any("jwt_secret_key" in issue for issue in issues)
    assert all(weak not in issue for issue in issues) if weak else True


def test_duplicated_secrets_and_database_password_are_rejected() -> None:
    duplicated = _VALID + "same"
    candidate = _production_settings(
        jwt_secret_key=duplicated,
        encryption_key=duplicated,
        database_url=(
            "postgresql+asyncpg://citeladder:"
            f"{duplicated}@database.example.com/citeladder"
        ),
    )
    issues = validate_production_security(candidate)
    assert "application secrets must be independent" in issues
    assert "database password must be independent of application secrets" in issues


def test_production_requires_database_tls() -> None:
    issues = validate_production_security(_production_settings(db_ssl_mode="disable"))
    assert "db_ssl_mode must be require in production" in issues


def test_dev_test_login_platform_gate_defaults_false() -> None:
    # The escape hatch fails CLOSED by default (T11): the field default is
    # false regardless of the ambient environment.
    assert (
        Settings.model_fields["dev_test_login_allow_platform_credentials"].default
        is False
    )


def test_dev_test_login_platform_gate_rejected_in_production() -> None:
    issues = validate_production_security(
        _production_settings(dev_test_login_allow_platform_credentials=True)
    )
    assert any("dev_test_login_allow_platform_credentials" in issue for issue in issues)


@pytest.mark.parametrize("dev_env", ["development", "test"])
def test_dev_test_login_platform_gate_allowed_in_development_and_test(
    dev_env: str,
) -> None:
    issues = validate_production_security(
        _production_settings(
            app_env=dev_env, dev_test_login_allow_platform_credentials=True
        )
    )
    assert not any(
        "dev_test_login_allow_platform_credentials" in issue for issue in issues
    )


def test_jwt_algorithm_is_pinned_to_hs256() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"JWT_ALGORITHM": "HS512"})
