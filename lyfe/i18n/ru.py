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
        "{name}\n"
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


    # ---------- track request ----------
    "request_prompt": (
        "🎵 LYFE REQUEST\n"
        "\n"
        "Напиши трек, который хочешь услышать\n"
        "{date}.\n"
        "\n"
        "Название, артист или ссылка."
    ),
    "request_searching": "Ищу…",
    "request_pick": "Нашёл. Какой?",
    "request_not_found": (
        "Не нашёл такой трек.\n"
        "\n"
        "Напиши в формате «Артист — Название», и я добавлю как есть."
    ),
    "btn_manual": "✏️ Не то, впишу сам",
    "btn_cancel": "✕ Отмена",
    "request_cancelled": "Ок, отменил.",
    "request_added": (
        "🔥 Трек принят.\n"
        "\n"
        "{track}\n"
        "\n"
        "Он в списке на {date}.\n"
        "{position}\n"
        "\n"
        "Если его поставят — ты узнаешь первым."
    ),
    "request_position_first": "Ты первый, кто его попросил.",
    "request_position_nth": "Ты {n}-й, кто его попросил.",
    "request_already": (
        "Ты его уже просил 😄\n"
        "\n"
        "{track}\n"
        "\n"
        "Он в списке, его хотят {n}."
    ),
    "request_limit": (
        "На сегодня хватит.\n"
        "\n"
        "Три трека от одного человека — это уже влияние.\n"
        "\n"
        "Возвращайся к следующей ночи."
    ),
    "request_event_closed": (
        "Ночь закончилась.\n"
        "\n"
        "Следующая — скоро. Мы напишем."
    ),
    "request_no_event": (
        "Пока некуда добавлять.\n"
        "\n"
        "Как только появится дата — откроем LYFE REQUEST."
    ),
    "people_1": "{n} человек",
    "people_2": "{n} человека",
    "people_5": "{n} человек",


    # ---------- top requests ----------
    "top_header": "🔥 TOP REQUESTS\n{event} · {date}",
    "top_empty": (
        "🔥 TOP REQUESTS\n"
        "\n"
        "Пока пусто.\n"
        "\n"
        "Будь первым, кто выберет музыку на эту ночь."
    ),
    "top_hint": "Жми номер, чтобы поддержать трек.",
    "top_no_event": (
        "Пока тишина.\n"
        "\n"
        "Напишем, как только будет дата."
    ),
    "vote_done": "Голос засчитан 🔥",
    "vote_already": "Ты уже голосовал за него",
    "vote_own": "Это твой трек — он уже посчитан",
    "vote_closed": "Голосование закрыто",


    # ---------- the moment everything exists for ----------
    "track_played": (
        "🔥 ТВОЙ ТРЕК СЕЙЧАС ИГРАЕТ.\n"
        "\n"
        "{track}\n"
        "\n"
        "Ты его выбрал.\n"
        "Мы его поставили.\n"
        "\n"
        "FEEL THE LYFE"
    ),


    # ---------- lyfe pass ----------
    "btn_pass": "🎟 LYFE PASS",
    "lyfe_pass": (
        "🎟 LYFE PASS\n"
        "\n"
        "{name}\n"
        "LYFE #{lyfe_id}\n"
        "\n"
        "Ночей: {nights}\n"
        "LYFE POINTS: {points}\n"
        "\n"
        "Покажи этот код на входе."
    ),
    "checked_in": (
        "✓ Ты на LYFEPARTY.\n"
        "\n"
        "+{points} LYFE POINTS\n"
        "\n"
        "Хорошей ночи."
    ),


    # ---------- rewards ----------
    "btn_rewards": "⭐ НАГРАДЫ",
    "rewards_header": "⭐ НАГРАДЫ\n\nУ тебя {points} LYFE POINTS.",
    "rewards_empty": (
        "⭐ НАГРАДЫ\n"
        "\n"
        "У тебя {points} LYFE POINTS.\n"
        "\n"
        "Пока тратить не на что.\n"
        "Копи — скоро откроем."
    ),
    "rewards_no_event": "Пока тишина. Награды откроются к следующей ночи.",
    "rewards_held": "Уже твоё:",
    "reward_bought": (
        "⭐ {name}\n"
        "\n"
        "Код: {code}\n"
        "\n"
        "Покажи его на входе вместе с LYFE PASS.\n"
        "\n"
        "Осталось {points} LYFE POINTS."
    ),
    "reward_not_enough": "Нужно {need} LYFE POINTS, у тебя {have}.",
    "reward_sold_out": "Разобрали. Попробуй в следующий раз.",
    "reward_limit": "Это можно взять только один раз за ночь.",
    "reward_unavailable": "Сейчас недоступно.",
    "priority_pick": (
        "🎯 ГАРАНТИЯ ТРЕКА — {cost} LYFE POINTS\n"
        "\n"
        "Выбери свой трек. Он прозвучит — без «если»."
    ),
    "priority_done": (
        "🎯 Готово.\n"
        "\n"
        "Твой трек закреплён у DJ.\n"
        "Он прозвучит этой ночью.\n"
        "\n"
        "Осталось {points} LYFE POINTS.\n"
        "\n"
        "FEEL THE LYFE"
    ),
    "priority_no_tracks": "Сначала предложи трек — гарантия ставится на свой.",
    "priority_full": "На эту ночь гарантии разобрали. Их всего две.",

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

# Plural forms for "человек": 1 человек, 2 человека, 5 человек
PEOPLE_FORMS = ("человек", "человека", "человек")
