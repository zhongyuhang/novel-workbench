"""Encrypt model API keys with the env master key. Never log or return plaintext."""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


class SecretStorageError(Exception):
    """The master key is missing or a ciphertext cannot be used."""


def encrypt_api_key(plaintext: str, *, master_key: str | None = None) -> str:
    if not plaintext:
        raise SecretStorageError("Refusing to encrypt an empty API key.")
    token = _fernet(master_key).encrypt(plaintext.encode("utf-8"))
    encoded = token.decode("ascii")
    if plaintext in encoded:
        raise SecretStorageError("Ciphertext unexpectedly contained the plaintext key.")
    return encoded


def decrypt_api_key(ciphertext: str, *, master_key: str | None = None) -> str:
    if not ciphertext:
        raise SecretStorageError("Stored API key ciphertext is empty.")
    try:
        raw = _fernet(master_key).decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise SecretStorageError("Stored API key ciphertext could not be decrypted.") from exc
    return raw.decode("utf-8")


def mask_api_key(plaintext: str) -> str:
    """Return a configured hint. Short values are not partially revealed."""

    if len(plaintext) < 8:
        return "configured" if plaintext else ""
    return f"••••{plaintext[-4:]}"


def master_key_from_settings(settings: Settings | None = None) -> str:
    active = settings if settings is not None else get_settings()
    return active.app_secret_encryption_key


def _fernet(master_key: str | None) -> Fernet:
    key = master_key if master_key is not None else get_settings().app_secret_encryption_key
    stripped = key.strip()
    if stripped == "" or stripped.lower().startswith("replace-with"):
        raise SecretStorageError(
            "APP_SECRET_ENCRYPTION_KEY is not configured. "
            "Set a Fernet key before storing model API keys."
        )
    try:
        return Fernet(stripped.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretStorageError("APP_SECRET_ENCRYPTION_KEY is not a valid Fernet key.") from exc
