"""Reply keyboards. Four buttons, no more — the user should understand the bot
in a few seconds, not read a menu."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from lyfe.config import get_settings
from lyfe.i18n import t


def webapp_url() -> str | None:
    base = get_settings().webapp_url.strip().strip("\"'").rstrip("/")
    if not base:
        return None
    # Railway shows the domain without a scheme, and that is what gets pasted.
    # Telegram accepts only https, so add it rather than refuse to start.
    if base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    elif not base.startswith("https://"):
        base = "https://" + base
    return base if base.endswith("/app") else f"{base}/app"


def open_app_inline(lang: str) -> InlineKeyboardMarkup | None:
    url = webapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_open_app", lang), web_app=WebAppInfo(url=url))]]
    )


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    url = webapp_url()
    if url:
        # The Mini App does everything. LYFE PASS stays as a chat button because
        # the photo it sends is cached by Telegram and opens with no signal —
        # the door is usually in a basement.
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=t("btn_open_app", lang), web_app=WebAppInfo(url=url))],
                [KeyboardButton(text=t("btn_pass", lang))],
            ],
            resize_keyboard=True,
            is_persistent=True,
        )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_request", lang)), KeyboardButton(text=t("btn_top", lang))],
            [
                KeyboardButton(text=t("btn_my_lyfe", lang)),
                KeyboardButton(text=t("btn_next_event", lang)),
            ],
            [
                KeyboardButton(text=t("btn_pass", lang)),
                KeyboardButton(text=t("btn_rewards", lang)),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def button_texts(key: str) -> set[str]:
    """All localised variants of one button, so handlers can match any language."""
    from lyfe.i18n import SUPPORTED

    return {t(key, lang) for lang in SUPPORTED}
