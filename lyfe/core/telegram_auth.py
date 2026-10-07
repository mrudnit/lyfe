"""Who is talking to the Mini App.

Telegram hands the Mini App a string called initData, signed with the bot token.
The signature is checked here, server side, on every request; the user id inside
it is then trusted exactly as much as a message to the bot is. Nothing the page
says about itself is believed otherwise.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

# A Mini App left open in the background for a weekend should re-open, not act.
MAX_AGE_SECONDS = 60 * 60 * 24


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str | None
    username: str | None
    language_code: str | None


def verify_init_data(init_data: str, bot_token: str, now: float | None = None) -> TelegramUser | None:
    if not init_data:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None

    received = fields.pop("hash", None)
    if not received:
        return None

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        return None
    if (now or time.time()) - auth_date > MAX_AGE_SECONDS:
        return None

    try:
        user = json.loads(fields.get("user") or "{}")
        return TelegramUser(
            id=int(user["id"]),
            first_name=user.get("first_name"),
            username=user.get("username"),
            language_code=user.get("language_code"),
        )
    except (ValueError, KeyError, TypeError):
        return None


# --------------------------------------------------------------------------
# Search results travel through the page and come back when a track is picked.
# They are signed so the page cannot invent a "catalogue" track of its own.
# --------------------------------------------------------------------------


def sign_payload(payload: dict, secret: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ).decode().rstrip("=")
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{signature}"


def read_payload(token: str, secret: str) -> dict | None:
    try:
        body, signature = (token or "").rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
