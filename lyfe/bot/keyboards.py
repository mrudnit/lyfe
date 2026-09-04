"""Reply keyboards. Four buttons, no more — the user should understand the bot
in a few seconds, not read a menu."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from lyfe.i18n import t


def main_menu(lang: str) -> ReplyKeyboardMarkup:
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
