# LYFE — Step 1: foundation

Подробная инструкция по разработке и проверке на русском: [DEVELOPMENT.md](DEVELOPMENT.md)

Telegram bot foundation for LYFEPARTY: database schema, migrations, Docker setup,
and a bot that registers a guest and issues their LYFE ID.

Working after this step:

- `/start` — silently registers the user and assigns `LYFE #0842`
- `📅 NEXT EVENT` — shows the upcoming event with a countdown and ticket link
- `❤️ MY LYFE` — profile with counters (all zeros for now, that's expected)
- Russian / Ukrainian copy, language auto-detected from Telegram
- Full Phase 1 database schema, ready for steps 2–4

Not yet built: track search, TOP REQUESTS, DJ screen, LYFE PASS. Those are next.

---

## 1. Before you touch the code

**Create the bot.** Open [@BotFather](https://t.me/BotFather) in Telegram:

```
/newbot
```

Give it a name and a username. BotFather replies with a token that looks like
`8012345678:AAH...`. Keep it — it goes in `.env`, never in the code, never in git.

Then set the description guests see before pressing Start:

```
/setdescription
```
```
LYFEPARTY. Выбери трек, который хочешь услышать сегодня.
FEEL THE LYFE
```

## 2. Run it locally

You need Docker Desktop installed. Then:

```bash
cp .env.example .env
```

Open `.env` and set two things:

- `BOT_TOKEN` — the token from BotFather
- `POSTGRES_PASSWORD` — any long random string

Start the database:

```bash
docker compose up -d postgres redis
```

Create the schema. The first command generates the baseline migration from the
models, the second applies it:

```bash
docker compose run --rm bot alembic upgrade head
docker compose run --rm bot alembic revision --autogenerate -m "phase1 baseline"
docker compose run --rm bot alembic upgrade head
```

Add your event so the bot has something to show. Open `scripts/seed.py` first and
edit the date, venue and ticket URL to match reality:

```bash
docker compose run --rm bot python scripts/seed.py
```

Start the bot:

```bash
docker compose up -d bot
docker compose logs -f bot
```

You should see `LYFE bot starting as @your_bot_username`.

## 3. Test it

Open your bot in Telegram and press Start. Expected:

1. The LYFEPARTY welcome message with a four-button keyboard
2. A second message about a second later: `Твой LYFE ID: LYFE #0001`
3. The next event card with the countdown

Then check:

- Press `📅 NEXT EVENT` — the card appears again
- Press `❤️ MY LYFE` — profile with `LYFE #0001` and zeros
- Send `/start` again — you get the returning-user message, **not** a new LYFE ID
- Type random text — you get the "use the buttons" reply

If all five work, step 1 is done.

## 4. Useful commands

```bash
docker compose logs -f bot          # follow logs
docker compose restart bot          # restart after a code change
docker compose down                 # stop everything (data survives)
docker compose down -v              # stop AND wipe the database

# open a psql shell
docker compose exec postgres psql -U lyfe -d lyfe

# check registered users
docker compose exec postgres psql -U lyfe -d lyfe -c "select lyfe_id, first_name, language, created_at from users order by id;"
```

## 5. Project layout

```
lyfe/
  config.py            environment variables, typed
  db.py                async engine + session factory
  models/              database schema (full Phase 1)
    base.py            declarative base, mixins
    geo.py             cities, venues
    user.py            users
    event.py           events
    music.py           tracks / event_tracks / track_requests / track_votes
    points.py          LYFE POINTS ledger
    attendance.py      check-ins
    admin.py           admin users, audit log
  core/                ALL business logic lives here
    lyfe_id.py         LYFE ID generation
    services/          user, points, event
  i18n/                Russian and Ukrainian copy
  bot/                 thin Telegram adapter
    main.py            entry point
    middlewares.py     session + user injection
    keyboards.py       reply keyboards
    handlers/          message handlers
migrations/            Alembic
scripts/seed.py        create the first city / venue / event
```

**The rule that makes Phase 2 possible:** business logic goes in `core/services`,
never in `bot/handlers`. Handlers only translate Telegram messages into service
calls. When the Mini App arrives it becomes a second adapter over the same
services, with nothing to rewrite.

## 6. Things worth knowing

**Language detection.** A guest's language comes from their Telegram client:
`uk` → Ukrainian, everything else → Russian. The mapping lives in
`lyfe/i18n/__init__.py`. Adding a language means one new file plus one line
there — nothing else changes.

**LYFE ID.** Sequential from a Postgres sequence, zero-padded: `0001`, `0842`.
It is public and deliberately guessable. It is never used to authenticate
anything — only the Telegram user ID does that.

**Points.** Stored as a ledger of transactions, never as a single number. Every
award needs an idempotency key, so a retried call cannot pay twice.

**Track deduplication.** Handled by the schema, not by moderation: a unique
constraint on `(event_id, track_id)` means twenty people asking for the same song
produce one row for the DJ with a counter of twenty.

## 7. Next steps

- **Step 2** — track resolver (iTunes catalogue), `🎵 Добавить трек`, limits
- **Step 3** — `🔥 TOP REQUESTS` with ❤️ voting
- **Step 4** — DJ LIVE SCREEN + the `YOUR TRACK IS PLAYING NOW` push
- **Step 5** — LYFE PASS QR + the door scanner

Steps 2–4 close the loop. Do not skip ahead to step 5 until the loop works.
