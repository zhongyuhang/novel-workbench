"""Single-user session issuance. Passphrases are checked against a hash."""

from app.core.config import Settings
from app.core.errors import InvalidPassword, PasswordRequired
from app.core.passwords import hash_password, parse_password_hash, verify_password
from app.core.runtime import auth_is_required
from app.core.security import _is_unusable_secret, issue_session_token, resolve_auth_secret
from app.schemas.catalog import SessionResponse

_DERIVED_HASHES: dict[str, str] = {}


def access_password_hash(settings: Settings) -> str | None:
    """Return the configured hash. A plaintext env passphrase is hashed in memory."""

    explicit = settings.app_access_password_hash.strip()
    if explicit:
        if parse_password_hash(explicit) is None:
            raise PasswordRequired("访问口令哈希无法使用。")
        return explicit
    password = settings.app_access_password
    if _is_unusable_secret(password):
        return None
    cached = _DERIVED_HASHES.get(password)
    if cached is None:
        cached = hash_password(password)
        _DERIVED_HASHES[password] = cached
    return cached


def open_local_session(settings: Settings, *, password: str) -> SessionResponse:
    stored = access_password_hash(settings)
    if stored is None:
        if auth_is_required(settings):
            raise PasswordRequired()
    elif password == "":
        raise PasswordRequired()
    elif not verify_password(password, stored):
        raise InvalidPassword()

    secret = resolve_auth_secret(settings, create=True)
    token = issue_session_token("owner", secret=secret)
    return SessionResponse(access_token=token)
