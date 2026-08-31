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
        "{name}\n"
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


    # ---------- track request ----------
    "request_prompt": (
        "🎵 LYFE REQUEST\n"
        "\n"
        "Напиши трек, який хочеш почути\n"
        "{date}.\n"
        "\n"
        "Назва, виконавець або посилання."
    ),
    "request_searching": "Шукаю…",
    "request_pick": "Знайшов. Який?",
    "request_not_found": (
        "Не знайшов такий трек.\n"
        "\n"
        "Напиши у форматі «Виконавець — Назва», і я додам як є."
    ),
    "btn_manual": "✏️ Не те, впишу сам",
    "btn_cancel": "✕ Скасувати",
    "request_cancelled": "Ок, скасував.",
    "request_added": (
        "🔥 Трек прийнято.\n"
        "\n"
        "{track}\n"
        "\n"
        "Він у списку на {date}.\n"
        "{position}\n"
        "\n"
        "Якщо його поставлять — ти дізнаєшся першим."
    ),
    "request_position_first": "Ти перший, хто його попросив.",
    "request_position_nth": "Ти {n}-й, хто його попросив.",
    "request_already": (
        "Ти його вже просив 😄\n"
        "\n"
        "{track}\n"
        "\n"
        "Він у списку, його хочуть {n}."
    ),
    "request_limit": (
        "На сьогодні досить.\n"
        "\n"
        "Три треки від однієї людини — це вже вплив.\n"
        "\n"
        "Повертайся до наступної ночі."
    ),
    "request_event_closed": (
        "Ніч закінчилась.\n"
        "\n"
        "Наступна — скоро. Ми напишемо."
    ),
    "request_no_event": (
        "Поки нема куди додавати.\n"
        "\n"
        "Щойно з'явиться дата — відкриємо LYFE REQUEST."
    ),
    "people_1": "{n} людина",
    "people_2": "{n} людини",
    "people_5": "{n} людей",


    # ---------- top requests ----------
    "top_header": "🔥 TOP REQUESTS\n{event} · {date}",
    "top_empty": (
        "🔥 TOP REQUESTS\n"
        "\n"
        "Поки порожньо.\n"
        "\n"
        "Будь першим, хто обере музику на цю ніч."
    ),
    "top_hint": "Тисни номер, щоб підтримати трек.",
    "top_no_event": (
        "Поки тиша.\n"
        "\n"
        "Напишемо, щойно буде дата."
    ),
    "vote_done": "Голос зараховано 🔥",
    "vote_already": "Ти вже голосував за нього",
    "vote_own": "Це твій трек — він уже порахований",
    "vote_closed": "Голосування закрито",

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

# Plural forms for "людина": 1 людина, 2 людини, 5 людей
PEOPLE_FORMS = ("людина", "людини", "людей")
