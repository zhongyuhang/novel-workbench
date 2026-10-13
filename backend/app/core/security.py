"""Single-user session tokens signed with APP_AUTH_SECRET.

Routers that expose private data must depend on ``require_session``. The health
check stays public so a local install can be verified before a password is set.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.auth")


class AuthError(Exception):
    """The session token is missing, expired, or not authentic."""


@dataclass(frozen=True)
class SessionPrincipal:
    subject: str
    expires_at: int


def _is_unusable_secret(secret: str) -> bool:
    stripped = secret.strip().lower()
    return (
        stripped == ""
        or stripped.startswith("replace-with")
        or stripped
        in {
            "changeme",
            "secret",
            "password",
        }
    )


def resolve_auth_secret(settings: Settings, *, create: bool) -> str:
    """Return the signing secret. Development may persist one under data/."""

    if not _is_unusable_secret(settings.app_auth_secret):
        return settings.app_auth_secret
    if settings.app_env == "production":
        raise AuthError("APP_AUTH_SECRET is not configured.")

    path = settings.resolved_data_dir / "dev-auth-secret"
    if path.is_file():
        stored = path.read_text(encoding="utf-8").strip()
        if not _is_unusable_secret(stored):
            return stored
    if not create:
        raise AuthError("APP_AUTH_SECRET is not configured.")

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(32)
    path.write_text(generated, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        logger.warning("Could not restrict permissions on the development auth secret file.")
    return generated


def issue_session_token(
    subject: str,
    *,
    secret: str,
    ttl_seconds: int = 12 * 60 * 60,
    now: int | None = None,
) -> str:
    if not subject.strip():
        raise AuthError("Session subject is empty.")
    if _is_unusable_secret(secret):
        raise AuthError("APP_AUTH_SECRET is not configured.")
    if ttl_seconds <= 0:
        raise AuthError("Session lifetime must be positive.")

    issued_at = int(time.time()) if now is None else now
    payload = {"sub": subject, "iat": issued_at, "exp": issued_at + ttl_seconds}
    body = _encode(payload)
    signature = _sign(body, secret)
    return f"{body}.{signature}"


def verify_session_token(token: str, *, secret: str, now: int | None = None) -> SessionPrincipal:
    if _is_unusable_secret(secret):
        raise AuthError("APP_AUTH_SECRET is not configured.")

    body, separator, signature = token.partition(".")
    if not separator or not body or not signature:
        raise AuthError("Session token is malformed.")

    expected = _sign(body, secret)
    if not hmac.compare_digest(expected, signature):
        raise AuthError("Session token signature is invalid.")

    try:
        payload = _decode(body)
    except (json.JSONDecodeError, ValueError, UnicodeError) as exc:
        raise AuthError("Session token payload is invalid.") from exc

    subject = payload.get("sub")
    expires_at = payload.get("exp")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthError("Session token subject is invalid.")
    if not isinstance(expires_at, int):
        raise AuthError("Session token expiry is invalid.")

    current = int(time.time()) if now is None else now
    if current >= expires_at:
        raise AuthError("Session token has expired.")
    return SessionPrincipal(subject=subject, expires_at=expires_at)


def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionPrincipal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="未认证。")
    try:
        secret = resolve_auth_secret(settings, create=False)
        return verify_session_token(token.strip(), secret=secret)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="登录状态无效或已过期。") from exc


def _encode(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(body: str) -> dict[str, object]:
    padding = "=" * (-len(body) % 4)
    decoded = base64.urlsafe_b64decode(body + padding)
    payload = json.loads(decoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Session payload must be an object.")
    return payload


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
