"""Session token scaffold."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import (
    AuthError,
    issue_session_token,
    require_session,
    verify_session_token,
)

SECRET = "test-auth-secret-value"


def test_issue_and_verify_roundtrip() -> None:
    token = issue_session_token("owner", secret=SECRET, now=1_700_000_000)

    principal = verify_session_token(token, secret=SECRET, now=1_700_000_100)

    assert principal.subject == "owner"
    assert principal.expires_at > 1_700_000_100


def test_tampered_token_is_rejected() -> None:
    token = issue_session_token("owner", secret=SECRET, now=1_700_000_000)
    body, signature = token.split(".", maxsplit=1)
    flipped = "0" if signature[-1] != "0" else "1"
    tampered = f"{body}.{signature[:-1]}{flipped}"

    with pytest.raises(AuthError):
        verify_session_token(tampered, secret=SECRET, now=1_700_000_100)


def test_expired_token_is_rejected() -> None:
    token = issue_session_token("owner", secret=SECRET, ttl_seconds=10, now=1_000)

    with pytest.raises(AuthError):
        verify_session_token(token, secret=SECRET, now=1_011)


def test_placeholder_secret_is_rejected() -> None:
    with pytest.raises(AuthError):
        issue_session_token("owner", secret="replace-with-a-long-random-secret")


def test_require_session_missing_header() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }

    with pytest.raises(HTTPException) as caught:
        require_session(Request(scope), get_settings())

    assert caught.value.status_code == 401


def test_require_session_accepts_bearer_token() -> None:
    token = issue_session_token("owner", secret=SECRET)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
    }

    principal = require_session(Request(scope), get_settings())

    assert principal.subject == "owner"
