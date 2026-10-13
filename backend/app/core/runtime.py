"""Fail closed when production configuration would expose data or secrets."""

from app.core.config import Settings


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


def validate_runtime_configuration(settings: Settings) -> None:
    if settings.app_env != "production":
        return

    if _is_placeholder(settings.app_auth_secret):
        raise RuntimeError("Production requires a non-placeholder APP_AUTH_SECRET.")
    if _is_placeholder(settings.app_secret_encryption_key):
        raise RuntimeError("Production requires a non-placeholder APP_SECRET_ENCRYPTION_KEY.")
    if _is_placeholder(settings.app_access_password):
        raise RuntimeError("Production requires a non-placeholder APP_ACCESS_PASSWORD.")
    if not settings.cors_origin_list or any(origin == "*" for origin in settings.cors_origin_list):
        raise RuntimeError(
            "Production CORS_ORIGINS must list explicit origins and must not use '*'."
        )
