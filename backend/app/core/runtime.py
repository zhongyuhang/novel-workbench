"""Fail closed when production or LAN configuration would expose data or secrets."""

from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.passwords import MIN_PRODUCTION_ITERATIONS, is_weak_password, parse_password_hash

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_placeholder(value: str) -> bool:
    stripped = value.strip().lower()
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


def _is_loopback(host: str) -> bool:
    return host.strip().lower() in _LOOPBACK_HOSTS


def auth_is_required(settings: Settings) -> bool:
    """Production always requires auth. Other environments do too when not on loopback."""

    if settings.app_env == "production":
        return True
    return not _is_loopback(settings.app_host)


def validate_runtime_configuration(settings: Settings) -> None:
    explicit_hash = settings.app_access_password_hash.strip()
    if explicit_hash and parse_password_hash(explicit_hash) is None:
        raise RuntimeError("APP_ACCESS_PASSWORD_HASH must be a pbkdf2_sha256 hash.")

    if auth_is_required(settings):
        _require_auth_material(settings, production=settings.app_env == "production")

    _require_encryption_key(settings.app_secret_encryption_key)

    if settings.app_env != "production":
        return

    if _is_placeholder(settings.app_secret_encryption_key):
        raise RuntimeError("Production requires a non-placeholder APP_SECRET_ENCRYPTION_KEY.")
    if not settings.cors_origin_list or any(origin == "*" for origin in settings.cors_origin_list):
        raise RuntimeError(
            "Production CORS_ORIGINS must list explicit origins and must not use '*'."
        )
    hosts = settings.allowed_host_list
    if not hosts or any(host == "*" for host in hosts):
        raise RuntimeError(
            "Production ALLOWED_HOSTS must list explicit hosts and must not use '*'."
        )


def _require_encryption_key(key: str) -> None:
    stripped = key.strip()
    if stripped == "" or stripped.lower().startswith("replace-with"):
        raise RuntimeError(
            "APP_SECRET_ENCRYPTION_KEY is not configured. "
            "Refusing to start so model API keys are never stored in plaintext."
        )
    try:
        Fernet(stripped.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "APP_SECRET_ENCRYPTION_KEY is not a valid Fernet key. "
            "Refusing to start so model API keys are never stored in plaintext."
        ) from exc


def _require_auth_material(settings: Settings, *, production: bool) -> None:
    secret = settings.app_auth_secret.strip()
    if _is_placeholder(secret) or len(secret) < 32:
        if production:
            raise RuntimeError("Production requires a non-placeholder APP_AUTH_SECRET.")
        raise RuntimeError("LAN bind requires a non-placeholder APP_AUTH_SECRET.")

    explicit_hash = settings.app_access_password_hash.strip()
    if explicit_hash:
        parsed = parse_password_hash(explicit_hash)
        if parsed is None:
            raise RuntimeError("APP_ACCESS_PASSWORD_HASH must be a pbkdf2_sha256 hash.")
        if production and parsed[0] < MIN_PRODUCTION_ITERATIONS:
            raise RuntimeError("Production APP_ACCESS_PASSWORD_HASH uses too few iterations.")
        return

    password = settings.app_access_password
    if _is_placeholder(password) or is_weak_password(password):
        if production:
            raise RuntimeError("Production requires a non-placeholder APP_ACCESS_PASSWORD.")
        raise RuntimeError("LAN bind requires a non-placeholder APP_ACCESS_PASSWORD.")
