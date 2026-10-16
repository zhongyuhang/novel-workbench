"""PBKDF2 password hashes for the single-user access passphrase.

The process compares a candidate against a hash. A plaintext passphrase supplied
in the environment is hashed in memory and is not written back to disk.
"""

import base64
import hashlib
import hmac
import secrets

HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
MIN_PRODUCTION_ITERATIONS = 100_000

_WEAK_PASSWORDS = {
    "password",
    "passw0rd",
    "123456",
    "12345678",
    "123456789",
    "qwerty",
    "admin",
    "administrator",
    "letmein",
    "changeme",
    "secret",
    "iloveyou",
}


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    if iterations < 1:
        raise ValueError("Password hash iterations must be positive.")
    if password == "":
        raise ValueError("Password hash input is empty.")
    salt_bytes = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
    salt_b64 = base64.urlsafe_b64encode(salt_bytes).decode("ascii")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{HASH_SCHEME}${iterations}${salt_b64}${digest_b64}"


def parse_password_hash(stored: str) -> tuple[int, bytes, bytes] | None:
    scheme, separator, rest = stored.partition("$")
    if separator == "" or scheme != HASH_SCHEME:
        return None
    iteration_text, separator, rest = rest.partition("$")
    salt_text, separator, digest_text = rest.partition("$")
    if separator == "" or not iteration_text or not salt_text or not digest_text:
        return None
    if "$" in digest_text:
        return None
    try:
        iterations = int(iteration_text)
        salt = base64.urlsafe_b64decode(salt_text)
        digest = base64.urlsafe_b64decode(digest_text)
    except (ValueError, TypeError):
        return None
    if iterations < 1 or not salt or not digest:
        return None
    return iterations, salt, digest


def verify_password(password: str, stored_hash: str) -> bool:
    parsed = parse_password_hash(stored_hash)
    if parsed is None:
        return False
    iterations, salt, digest = parsed
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, digest)


def is_weak_password(password: str) -> bool:
    stripped = password.strip()
    folded = stripped.casefold()
    if len(stripped) < 12:
        return True
    if folded in _WEAK_PASSWORDS or folded.startswith("replace-with"):
        return True
    return stripped.isdigit()
