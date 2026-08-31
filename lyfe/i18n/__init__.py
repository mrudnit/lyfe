"""Tiny translation layer. Dicts, not gettext — the copy IS the product,
so it should be editable without a compile step.

To add a language: create `lyfe/i18n/<code>.py` with a TEXTS dict and
DAYS_FORMS tuple, then add one line to CATALOGS below. Nothing else changes.
"""
from lyfe.i18n import ru, uk

CATALOGS = {
    "ru": ru.TEXTS,
    "uk": uk.TEXTS,
}

PLURALS = {
    "ru": ru.DAYS_FORMS,
    "uk": uk.DAYS_FORMS,
}

DEFAULT_LANGUAGE = "ru"
SUPPORTED = tuple(CATALOGS.keys())

# Telegram language_code -> our language.
# Everything we do not recognise falls back to Russian.
_TELEGRAM_MAP = {
    "ru": "ru",
    "uk": "uk",
    "be": "ru",
    "kk": "ru",
}


def resolve_language(telegram_language_code: str | None) -> str:
    if not telegram_language_code:
        return DEFAULT_LANGUAGE
    return _TELEGRAM_MAP.get(telegram_language_code.split("-")[0].lower(), DEFAULT_LANGUAGE)


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Slavic plural rule: 1 день / 2 дня / 5 дней."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return forms[1]
    return forms[2]


def days_word(n: int, lang: str = DEFAULT_LANGUAGE) -> str:
    return plural(n, PLURALS.get(lang, PLURALS[DEFAULT_LANGUAGE]))


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    catalog = CATALOGS.get(lang) or CATALOGS[DEFAULT_LANGUAGE]
    template = catalog.get(key) or CATALOGS[DEFAULT_LANGUAGE].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    return template
