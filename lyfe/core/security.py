"""Password hashing and signed session cookies.

Uses only the standard library: scrypt for passwords, HMAC-SHA256 for cookies.
No extra dependency, nothing to keep patched.
"""
import base64
import hashlib
import hmac
import secrets
import time

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN
    )
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except Exception:  # noqa: BLE001
        return False

    candidate = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN
    )
    return hmac.compare_digest(candidate, expected)


def sign_session(admin_id: int, secret: str, ttl_seconds: int = 60 * 60 * 24 * 7) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = f"{admin_id}.{expires}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session(token: str, secret: str) -> int | None:
    try:
        admin_id_raw, expires_raw, signature = token.split(".")
        payload = f"{admin_id_raw}.{expires_raw}"
    except (ValueError, AttributeError):
        return None

    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    if int(expires_raw) < time.time():
        return None
    return int(admin_id_raw)
