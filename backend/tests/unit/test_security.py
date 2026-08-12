"""Unit tests for core security helpers: argon2, JWT, Fernet."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.api.auth import _trusted_client_identity
from app.core.config import settings
from app.core.security import (
    TokenDecodeError,
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password_roundtrip() -> None:
    hashed = hash_password("s3cret-pw")
    assert hashed.startswith("$argon2")
    assert verify_password("s3cret-pw", hashed) is True
    assert verify_password("wrong-pw", hashed) is False


def test_verify_password_rejects_garbage_hash() -> None:
    assert verify_password("anything", "not-a-hash") is False


def test_access_token_roundtrip() -> None:
    token = create_access_token("user-uuid", token_version=1)
    claims = decode_access_token(token)
    assert claims["sub"] == "user-uuid"
    assert claims["ver"] == 1


def test_decode_rejects_tampered_token() -> None:
    token = create_access_token("user-uuid")
    with pytest.raises(TokenDecodeError):
        decode_access_token(token + "tampered")


def test_encrypt_secret_roundtrip_and_opacity() -> None:
    ciphertext = encrypt_secret("byok-api-key")
    # Ciphertext must not leak the plaintext (invariant 6).
    assert "byok-api-key" not in ciphertext
    assert decrypt_secret(ciphertext) == "byok-api-key"


def _request(*, peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/login",
            "raw_path": b"/api/v1/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 1234),
            "server": ("api", 8000),
        }
    )


def test_forwarded_identity_requires_a_trusted_direct_peer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = _request(peer="203.0.113.8", forwarded="198.51.100.7")
    assert _trusted_client_identity(request) == "203.0.113.8"


def test_forwarded_identity_skips_trusted_proxy_hops(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = _request(peer="10.0.1.20", forwarded="198.51.100.7, 10.0.2.30")
    assert _trusted_client_identity(request) == "198.51.100.7"


def test_two_clients_through_one_proxy_keep_distinct_identities(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    first = _request(peer="10.0.1.20", forwarded="198.51.100.7")
    second = _request(peer="10.0.1.20", forwarded="203.0.113.9")
    assert _trusted_client_identity(first) != _trusted_client_identity(second)
