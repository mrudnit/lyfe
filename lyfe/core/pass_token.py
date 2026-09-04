"""LYFE PASS tokens.

The QR a guest shows at the door contains a signed token, never a raw user id
and never any personal data. The signature is checked server side, so a forged
or edited code is rejected.

Design note — the token is static, not rotating. A rotating code would be
harder to share, but it would require the guest's phone to be online at the
moment of scanning, and a club basement is exactly where that fails. A static
token is rendered once, cached in the Telegram chat, and works with the phone in
airplane mode. The trade-off is that a screenshot can be forwarded; it is
mitigated by showing the holder's name to the door staff and by refusing a
second check-in for the same person.
"""
import hashlib
import hmac

PREFIX = "LYFE"
SIGNATURE_LENGTH = 16


def build(user_id: int, secret: str) -> str:
    payload = f"{PREFIX}:{user_id}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature[:SIGNATURE_LENGTH]}"


def parse(token: str, secret: str) -> int | None:
    try:
        prefix, user_id_raw, signature = token.strip().split(":")
    except (ValueError, AttributeError):
        return None
    if prefix != PREFIX:
        return None

    payload = f"{prefix}:{user_id_raw}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected[:SIGNATURE_LENGTH], signature):
        return None
    try:
        return int(user_id_raw)
    except ValueError:
        return None
