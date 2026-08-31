"""
Russian copy — primary language.

Brand words are NEVER translated: LYFE, LYFEPARTY, LYFE REQUEST, TOP REQUESTS,
MY LYFE, LYFE PASS, LYFE POINTS, SECRET LYFE, NEXT EVENT, FEEL THE LYFE.
They are the identity. Everything around them is localised.

Tone: short lines, plenty of air, no slang, no corporate politeness,
never "Выберите пункт меню".
"""

TEXTS = {
    # ---------- onboarding ----------
    "start_new": (
        "LYFEPARTY 🎧\n"
        "\n"
        "Это LYFE — твоя часть ночи.\n"
        "\n"
        "Ты выбираешь музыку.\n"
        "Мы делаем ночь.\n"
        "\n"
        "FEEL THE LYFE"
    ),
    "start_returning": (
        "С возвращением, {name}.\n"
        "\n"
        "LYFE #{lyfe_id}"
    ),
    "lyfe_id_assigned": (
        "Твой LYFE ID:\n"
        "\n"
        "LYFE #{lyfe_id}\n"
        "\n"
        "Теперь ты часть LYFEPARTY."
    ),

    # ---------- menu ----------
    "btn_request": "🎵 Добавить трек",
    "btn_top": "🔥 TOP REQUESTS",
    "btn_my_lyfe": "❤️ MY LYFE",
    "btn_next_event": "📅 NEXT EVENT",
    "btn_settings": "⚙️ Настройки",
    "btn_back": "← Назад",

    # ---------- events ----------
    "next_event_none": (
        "Пока тишина.\n"
        "\n"
        "Напишем, как только будет дата."
    ),
    "next_event_card": (
        "LYFEPARTY\n"
        "{title}\n"
        "\n"
        "{date} · {venue} · {city}\n"
        "\n"
        "{countdown}"
    ),
    "countdown_days": "Осталось {days} {days_word}.",
    "countdown_tomorrow": "Завтра.",
    "countdown_today": "Сегодня ночью.",
    "btn_ticket": "🎟 Билет",

    # ---------- profile ----------
    "my_lyfe": (
        "{name}'S LYFE\n"
        "\n"
        "LYFE #{lyfe_id}\n"
        "\n"
        "Реквестов: {requests}\n"
        "Сыграли: {played}\n"
        "Ночей: {nights}\n"
        "LYFE POINTS: {points}"
    ),

    # ---------- settings ----------
    "settings": "⚙️ Настройки\n\nЯзык: {language}",
    "btn_lang_ru": "🇷🇺 Русский",
    "btn_lang_uk": "🇺🇦 Українська",
    "language_changed": "Готово. Дальше по-русски.",
    "language_name": "Русский",

    # ---------- generic ----------
    "unknown_input": (
        "Не понял.\n"
        "\n"
        "Нажми кнопку внизу."
    ),
    "error": "Что-то пошло не так. Попробуй через минуту.",
}

# Plural forms for "день": 1 день, 2 дня, 5 дней
DAYS_FORMS = ("день", "дня", "дней")
