"""Ukrainian copy — second language. Brand words stay in English."""

TEXTS = {
    # ---------- onboarding ----------
    "start_new": (
        "LYFEPARTY 🎧\n"
        "\n"
        "Це LYFE — твоя частина ночі.\n"
        "\n"
        "Ти обираєш музику.\n"
        "Ми робимо ніч.\n"
        "\n"
        "FEEL THE LYFE"
    ),
    "start_returning": (
        "З поверненням, {name}.\n"
        "\n"
        "LYFE #{lyfe_id}"
    ),
    "lyfe_id_assigned": (
        "Твій LYFE ID:\n"
        "\n"
        "LYFE #{lyfe_id}\n"
        "\n"
        "Тепер ти частина LYFEPARTY."
    ),

    # ---------- menu ----------
    "btn_request": "🎵 Додати трек",
    "btn_top": "🔥 TOP REQUESTS",
    "btn_my_lyfe": "❤️ MY LYFE",
    "btn_next_event": "📅 NEXT EVENT",
    "btn_settings": "⚙️ Налаштування",
    "btn_back": "← Назад",

    # ---------- events ----------
    "next_event_none": (
        "Поки тиша.\n"
        "\n"
        "Напишемо, щойно буде дата."
    ),
    "next_event_card": (
        "LYFEPARTY\n"
        "{title}\n"
        "\n"
        "{date} · {venue} · {city}\n"
        "\n"
        "{countdown}"
    ),
    "countdown_days": "Залишилось {days} {days_word}.",
    "countdown_tomorrow": "Завтра.",
    "countdown_today": "Сьогодні вночі.",
    "btn_ticket": "🎟 Квиток",

    # ---------- profile ----------
    "my_lyfe": (
        "{name}'S LYFE\n"
        "\n"
        "LYFE #{lyfe_id}\n"
        "\n"
        "Реквестів: {requests}\n"
        "Зіграли: {played}\n"
        "Ночей: {nights}\n"
        "LYFE POINTS: {points}"
    ),

    # ---------- settings ----------
    "settings": "⚙️ Налаштування\n\nМова: {language}",
    "btn_lang_ru": "🇷🇺 Русский",
    "btn_lang_uk": "🇺🇦 Українська",
    "language_changed": "Готово. Далі українською.",
    "language_name": "Українська",

    # ---------- generic ----------
    "unknown_input": (
        "Не зрозумів.\n"
        "\n"
        "Натисни кнопку внизу."
    ),
    "error": "Щось пішло не так. Спробуй за хвилину.",
}

# Plural forms for "день": 1 день, 2 дні, 5 днів
DAYS_FORMS = ("день", "дні", "днів")
