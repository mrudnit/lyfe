# LYFE — как разрабатывать и проверять

Инструкция для человека, который запускает проект сам. Читать сверху вниз один
раз, дальше возвращаться к нужному разделу.

---

## 1. Что установить

| Что | Зачем | Где |
|---|---|---|
| **Docker Desktop** | Запускает базу, Redis и бота одной командой | docker.com/products/docker-desktop |
| **Git** | Хранит код и историю изменений | git-scm.com |
| **VS Code** | Редактор кода | code.visualstudio.com |

В VS Code поставь расширения: **Python**, **Docker**. Больше ничего не нужно.

Проверь, что Docker работает:

```bash
docker --version
docker compose version
```

Если обе команды что-то вывели — можно идти дальше.

---

## 2. Первый запуск

### 2.1 Создать бота

Открой в Telegram [@BotFather](https://t.me/BotFather):

```
/newbot
```

Он спросит имя (видят люди) и username (должен заканчиваться на `bot`).
В ответ придёт токен вида `8012345678:AAH...`.

**Этот токен — пароль от бота.** Кто его получит, тот управляет ботом. Он идёт
только в файл `.env`, который никогда не попадает в git.

Пока ты у BotFather, задай описание — его видят до нажатия Start:

```
/setdescription
```
```
LYFEPARTY. Выбери трек, который хочешь услышать сегодня.
FEEL THE LYFE
```

И короткое описание для профиля:

```
/setabouttext
```
```
LYFE — твоя часть ночи. FEEL THE LYFE
```

### 2.2 Подготовить проект

Распакуй архив, открой папку в терминале:

```bash
cd lyfe
cp .env.example .env
```

Открой `.env` в редакторе и заполни два поля:

```
BOT_TOKEN=8012345678:AAH...          ← токен от BotFather
POSTGRES_PASSWORD=длинная_случайная_строка
```

Пароль придумай длинный, например сгенерируй:

```bash
openssl rand -base64 24
```

### 2.3 Поднять базу

```bash
docker compose up -d postgres redis
```

Проверь, что поднялось:

```bash
docker compose ps
```

Обе строки должны быть в статусе `running` или `healthy`.

### 2.4 Создать схему базы

Три команды подряд. Первая создаёт последовательность LYFE ID, вторая генерирует
описание всех таблиц из моделей, третья применяет его.

```bash
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot alembic revision --autogenerate -m "phase1 baseline"
docker compose run --rm bot alembic upgrade head
```

После второй команды в `migrations/versions/` появится новый файл. Открой его и
убедись, что там есть `op.create_table("users", ...)` и остальные 11 таблиц.
Этот файл нужно закоммитить в git — он часть проекта.

### 2.5 Завести свой ивент

Открой `scripts/seed.py` и поставь реальные данные: дату, название, площадку,
город, ссылку на билеты. Время указывается местное, не UTC.

```bash
docker compose run --rm bot python scripts/seed.py
```

### 2.6 Запустить бота

```bash
docker compose up -d bot
docker compose logs -f bot
```

В логах должно появиться:

```
LYFE bot starting as @твой_бот
```

Нажми `Ctrl+C` — это закроет только просмотр логов, бот продолжит работать.

---

## 3. Приёмка шага 1

Открой своего бота в Telegram и пройди все семь пунктов. Если хоть один не
проходит — не двигайся дальше, сначала чини.

| # | Что делаешь | Что должно быть |
|---|---|---|
| 1 | Нажимаешь **Start** | Приветствие LYFEPARTY + клавиатура из четырёх кнопок |
| 2 | Ждёшь секунду | Отдельным сообщением: `Твой LYFE ID: LYFE #0001` |
| 3 | Ждёшь ещё | Карточка ивента с датой, площадкой и «Осталось N дней» |
| 4 | Жмёшь **📅 NEXT EVENT** | Карточка появляется снова |
| 5 | Жмёшь **❤️ MY LYFE** | Профиль с твоим LYFE ID и нулями |
| 6 | Отправляешь `/start` ещё раз | «С возвращением» — **новый LYFE ID не выдаётся** |
| 7 | Пишешь любой текст | «Не понял. Нажми кнопку внизу.» |

Отдельно проверь склонения: если до ивента 21 день — должно быть «21 день», если
22 — «22 дня», если 25 — «25 дней». Это видно на карточке.

Дай боту второму человеку. У него должен появиться `LYFE #0002`. Проверь в базе:

```bash
docker compose exec postgres psql -U lyfe -d lyfe -c "select lyfe_id, first_name, language from users order by id;"
```

---

## 3b. Запуск без Docker (когда Docker не пускает в интернет)

Docker нужен для базы, но бота можно держать прямо на Mac. Так даже удобнее:
логи идут в терминал, перезапуск быстрее.

База по-прежнему в Docker:

```bash
docker compose up -d postgres redis
```

В `.env` поменяй одну строку — теперь бот обращается к базе не по имени
контейнера, а по локальному адресу:

```
POSTGRES_HOST=localhost
```

Дальше один раз создаёшь окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Миграции и запуск — уже без `docker compose run`:

```bash
alembic upgrade head
alembic revision --autogenerate -m "phase1 baseline"
alembic upgrade head
python scripts/seed.py
python -m lyfe.bot.main
```

Останавливать бота — `Ctrl+C`, запускать заново — той же последней командой.

**В каждом новом окне терминала не забывай:**

```bash
source .venv/bin/activate
```

Без этого Python не увидит установленные пакеты и напишет `ModuleNotFoundError`.

Когда дело дойдёт до сервера, вернём `POSTGRES_HOST=postgres` и всё поедет
в Docker как задумано.

---

## 4. Ежедневный цикл разработки

Код примонтирован в контейнер (файл `docker-compose.override.yml`), поэтому
пересобирать образ после каждой правки не нужно.

```
изменил файл  →  docker compose restart bot  →  проверил в Telegram
```

Смотреть логи во время проверки:

```bash
docker compose logs -f bot
```

Оставь второе окно терминала с логами открытым, пока тестируешь. Все ошибки
падают туда.

**Пересобирать образ нужно только если ты поменял `requirements.txt`:**

```bash
docker compose build bot
docker compose up -d bot
```

---

## 5. Что где лежит

| Хочешь поменять | Файл |
|---|---|
| Любой текст, который видит человек | `lyfe/i18n/ru.py`, `lyfe/i18n/uk.py` |
| Названия кнопок | там же |
| Логику: что происходит при действии | `lyfe/core/services/` |
| Как бот реагирует на сообщение | `lyfe/bot/handlers/` |
| Структуру базы | `lyfe/models/` + новая миграция |
| Настройки, лимиты, баллы | `.env` |

**Правило, которое нельзя нарушать:** логика живёт в `core/services`, а
`bot/handlers` только переводит сообщения Telegram в вызовы сервисов. Если
начать писать логику прямо в хендлерах, Mini App во второй фазе придётся делать
с нуля. Когда сомневаешься, куда положить код, — клади в сервис.

---

## 6. Как менять тексты

Самая частая правка и самая безопасная. Миграции не нужны, база не трогается.

1. Открой `lyfe/i18n/ru.py`
2. Поменяй строку
3. `docker compose restart bot`
4. Проверь в Telegram

Если добавляешь новый текст — добавь ключ **во все языковые файлы**. Если забыл,
бот не упадёт, а покажет русский вариант.

Проверить, что нигде не забыл ключ:

```bash
docker compose run --rm bot python -c "
from lyfe.i18n import CATALOGS
base = set(CATALOGS['ru'])
for lang, cat in CATALOGS.items():
    missing = base - set(cat)
    print(lang, 'missing:', sorted(missing) if missing else 'ok')
"
```

---

## 7. Как менять структуру базы

Три шага, порядок важен.

**1. Правишь модель** в `lyfe/models/`. Например, добавляешь поле:

```python
instagram: Mapped[str | None] = mapped_column(String(120))
```

**2. Генерируешь миграцию:**

```bash
docker compose run --rm bot alembic revision --autogenerate -m "add instagram to users"
```

**3. Открываешь получившийся файл в `migrations/versions/` и читаешь его.**
Не пропускай этот шаг. Alembic иногда угадывает неправильно — особенно при
переименованиях, которые он видит как «удалить колонку и создать новую», то есть
как потерю данных.

**4. Применяешь:**

```bash
docker compose run --rm bot alembic upgrade head
```

Откатить последнюю миграцию:

```bash
docker compose run --rm bot alembic downgrade -1
```

Посмотреть, на какой версии сейчас база:

```bash
docker compose run --rm bot alembic current
```

---

## 8. Работа с базой напрямую

Открыть консоль Postgres:

```bash
docker compose exec postgres psql -U lyfe -d lyfe
```

Внутри: `\dt` — список таблиц, `\d users` — структура таблицы, `\q` — выход.

Полезные запросы:

```sql
-- сколько людей зарегистрировалось
select count(*) from users;

-- последние 20 пользователей
select lyfe_id, first_name, tg_username, language, created_at
from users order by id desc limit 20;

-- сколько заявок на треки по ивентам
select e.title, count(tr.id) as requests
from events e
left join event_tracks et on et.event_id = e.id
left join track_requests tr on tr.event_track_id = et.id
group by e.title;

-- топ треков текущего ивента
select t.artist_name, t.title, et.requests_count, et.votes_count, et.status
from event_tracks et
join tracks t on t.id = et.track_id
order by et.requests_count + et.votes_count desc
limit 20;

-- баланс баллов конкретного человека
select sum(delta) from point_transactions where user_id = 1;

-- история его баллов
select delta, reason_code, created_at from point_transactions
where user_id = 1 order by id;
```

---

## 9. Типичные ошибки

| Ошибка в логах | Что это значит | Что делать |
|---|---|---|
| `Field required: bot_token` | Нет файла `.env` или в нём нет токена | Скопируй `.env.example` в `.env`, заполни |
| `Unauthorized` | Токен неверный или отозван | Проверь токен у BotFather, `/mybots` → API Token |
| `Connection refused` к postgres | База не поднялась | `docker compose up -d postgres`, потом `docker compose ps` |
| `relation "users" does not exist` | Миграции не применены | `docker compose run --rm bot alembic upgrade head` |
| `Target database is not up to date` | Есть неприменённая миграция | `alembic upgrade head` перед созданием новой |
| `Conflict: terminated by other getUpdates` | Бот запущен в двух местах | `docker compose down`, потом заново. Один токен — один процесс |
| Бот молчит, в логах пусто | Контейнер не запущен | `docker compose ps`, потом `docker compose up -d bot` |
| Правка кода не применилась | Не перезапустил | `docker compose restart bot` |
| `ResolutionImpossible` при установке | Версии пакетов конфликтуют между собой | Не подбирай вручную — присылай вывод, поправлю `requirements.txt` |
| `Network is unreachable` внутри контейнера | У контейнеров нет выхода в интернет | Смени сеть или работай по разделу 3b |
| `ModuleNotFoundError` при локальном запуске | Не активировано окружение | `source .venv/bin/activate` |
| `ModuleNotFoundError: No module named 'lyfe'` в скрипте | Python считает корнем папку скрипта | `PYTHONPATH=. .venv/bin/python scripts/seed.py` |
| `alembic` берётся из Anaconda | Её `PATH` перекрывает `.venv` | Запускай через `.venv/bin/python -m alembic ...` |
| `Unable to locate package build-essential` | Сборка образа лезет в интернет за системными пакетами | Их не должно быть в Dockerfile. Проверь, что там нет `apt-get` |
| `failed to solve: process /bin/sh -c ...` | Упал какой-то шаг сборки образа | Смотри строку выше `ERROR` — там настоящая причина |

Посмотреть последние 100 строк логов:

```bash
docker compose logs --tail=100 bot
```

Полный сброс, если всё сломалось (**удаляет базу**):

```bash
docker compose down -v
docker compose up -d postgres redis
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot python scripts/seed.py
docker compose up -d bot
```

---

## 10. Git

Заведи репозиторий сразу, до первой правки.

```bash
git init
git add .
git commit -m "step 1: foundation"
```

**Никогда не коммить `.env`.** Он уже в `.gitignore`, но проверь перед первым
пушем:

```bash
git status --short | grep -i env
```

Если видишь `.env` — останови и разберись. Токен бота в публичном репозитории
означает, что бота уводят в течение часа.

Делай коммит после каждого работающего шага. Это твоя единственная кнопка
«отменить», когда что-то сломается в три часа ночи перед ивентом.

```bash
git add .
git commit -m "step 2: track search"
```

---

## 11. Два правила безопасности

**Токен и пароли — только в `.env`.** Никогда в коде, никогда в скриншотах,
никогда в переписке. Если токен утёк: BotFather → `/mybots` → бот → API Token →
Revoke.

**Порт базы наружу не открывается.** В `docker-compose.yml` стоит
`127.0.0.1:5432:5432` — это значит «только с этой машины». Не меняй на
`5432:5432`, иначе база станет доступна из интернета.

---

## 12. Как тестировать перед 22.09

Автотесты пойдут позже. Пока главный инструмент — живые люди.

**За неделю до ивента** дай бота 15–20 друзьям с одной формулировкой:

> Попробуйте сломать нашего бота. Ищите места, где непонятно, что делать.

Смотри не на то, что они говорят, а на то, что делают:

- где останавливаются и не понимают, какую кнопку жать
- сколько секунд проходит от Start до первого реквеста
- сколько человек дошло до реквеста, а сколько бросило
- какие треки пишут текстом так, что резолвер не находит
- пытается ли кто-то отправить 20 заявок

Проверь и это:

- отправить очень длинный текст
- отправить эмодзи, стикер, голосовое, фото
- нажать одну кнопку десять раз подряд
- заблокировать бота, потом разблокировать и написать снова
- у человека без username в Telegram — всё должно работать

**Отдельно проверь связь в Luna Club.** Иди на площадку, встань там, где будет
вход и где будет диджейская будка, и открой любой сайт с телефона. Если грузится
медленно или не грузится — сканер и DJ-экран нужно строить офлайн-устойчивыми.
Это надо знать до того, как я начну их писать, а не после.

**Прогон DJ-экрана нужен обязательно, до ивента.** Посади человека, который
будет жать PLAYED, за экран на десять минут и попроси отметить двадцать треков.
Если ему неудобно — переделываем, пока есть время.

---

## 12b. Приёмка шага 2 — LYFE REQUEST

Сначала проверь сам резолвер, без Telegram. Это занимает пять секунд и сразу
показывает, работает ли каталог:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_resolver.py "travis scott fein"
PYTHONPATH=. .venv/bin/python scripts/check_resolver.py "монатик кружит"
PYTHONPATH=. .venv/bin/python scripts/check_resolver.py "https://open.spotify.com/track/..."
```

Должны напечататься найденные треки с артистом, альбомом и обложкой. Если
печатает `No results` — бот предложит вписать трек вручную, это штатное
поведение, а не поломка.

Дальше в Telegram:

| # | Что делаешь | Что должно быть |
|---|---|---|
| 1 | **🎵 Добавить трек** | Приглашение написать трек + кнопка отмены |
| 2 | Пишешь `travis scott fein` | Список кнопок с найденными треками |
| 3 | Жмёшь нужный | «🔥 Трек принят», название, дата, «Ты первый, кто его попросил» |
| 4 | Добавляешь тот же трек снова | «Ты его уже просил 😄», счётчик не растёт |
| 5 | Добавляешь ещё три разных | На четвёртом — «На сегодня хватит» |
| 6 | Пишешь бессмыслицу вроде `йцукен` | Предложение вписать вручную |
| 7 | Вписываешь `Артист — Название` | Трек принят, в базе `provider = manual` |
| 8 | Жмёшь **Отмена** | «Ок, отменил», возврат в меню |
| 9 | Кидаешь ссылку на YouTube | Находит трек по названию из ссылки |

Главная проверка — с другого аккаунта. Попроси кого-то добавить **тот же самый**
трек. В базе должна появиться одна строка со счётчиком 2, а не две строки:

```bash
docker compose exec postgres psql -U lyfe -d lyfe -c "
select t.artist_name, t.title, et.requests_count, t.provider
from event_tracks et join tracks t on t.id = et.track_id
order by et.requests_count desc;"
```

И проверь, что за реквесты начислились баллы:

```bash
docker compose exec postgres psql -U lyfe -d lyfe -c "
select u.lyfe_id, sum(pt.delta) as points
from point_transactions pt join users u on u.id = pt.user_id
group by u.lyfe_id;"
```

**Известное ограничение.** Если два человека впишут трек вручную по-разному —
латиницей и кириллицей, или с опечаткой, — получатся две строки. Каталожный
поиск это закрывает, ручной ввод нет. Объединение дублей руками появится
в админке во второй фазе.

---

## 12c. Приёмка шага 3 — TOP REQUESTS

| # | Что делаешь | Что должно быть |
|---|---|---|
| 1 | **🔥 TOP REQUESTS** на пустой базе | «Пока пусто. Будь первым» |
| 2 | Добавляешь трек, открываешь TOP | Трек в списке, рядом 🎵 — это твой |
| 3 | Жмёшь номер своего трека | Всплывает «Это твой трек — он уже посчитан» |
| 4 | Со второго аккаунта жмёшь номер | «Голос засчитан 🔥», счётчик +1, появляется ❤️ |
| 5 | Тот же аккаунт жмёт ещё раз | «Ты уже голосовал за него», счётчик не растёт |
| 6 | Обновляешь TOP | Порядок пересортирован по сумме заявок и голосов |

Проверка в базе — заявки и голоса считаются отдельно, а сортировка идёт по сумме:

```bash
docker compose exec postgres psql -U lyfe -d lyfe -c "
select t.artist_name, t.title, et.requests_count, et.votes_count,
       et.requests_count + et.votes_count as score
from event_tracks et join tracks t on t.id = et.track_id
order by score desc;"
```

**Почему заявка и лайк не складываются у одного человека.** Тот, кто предложил
трек, уже отдал свой голос — поэтому лайкнуть его повторно нельзя. Иначе один
человек считался бы дважды и цифры у DJ перестали бы отражать реальный спрос.

---

## 13. Что дальше

| Шаг | Что делаем | Проверка |
|---|---|---|
| **2** | Резолвер треков + кнопка «Добавить трек» | Человек пишет «travis scott fein» и получает кнопки с треками |
| **3** | TOP REQUESTS + ❤️ | Список обновляется, повторный лайк не проходит |
| **4** | DJ LIVE SCREEN + PLAYED + пуш | Нажал PLAYED — всем, кто просил, пришло уведомление |
| **5** | LYFE PASS QR + сканер на входе | Скан даёт +10, повторный скан ловится |

Шаги 2–4 закрывают петлю. Пока она не работает целиком, к шагу 5 не переходим —
LYFE PASS без работающей петли не имеет смысла.

---

**LYFEPARTY. FEEL THE LYFE.**
