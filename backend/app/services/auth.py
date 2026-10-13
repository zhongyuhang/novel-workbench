"""Single-user session issuance."""

import hmac

from app.core.config import Settings
from app.core.errors import InvalidPassword, PasswordRequired
from app.core.security import _is_unusable_secret, issue_session_token, resolve_auth_secret
from app.schemas.catalog import SessionResponse


def open_local_session(settings: Settings, *, password: str) -> SessionResponse:
    if _is_unusable_secret(settings.app_access_password):
        if settings.app_env not in {"development", "test"}:
            raise PasswordRequired()
    elif not hmac.compare_digest(password, settings.app_access_password):
        raise InvalidPassword()

    secret = resolve_auth_secret(settings, create=True)
    token = issue_session_token("owner", secret=secret)
    return SessionResponse(access_token=token)
