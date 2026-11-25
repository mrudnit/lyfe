"""End-to-end check of the whole guest and staff flow against a LOCAL server.

It creates its own event, users and admin, plays every feature through the
real HTTP API (Mini App, door scanner, DJ screen), fires concurrent requests
at everything that spends or awards points, and checks the ledger at the end.

Writes test data — refuses to run against anything but localhost.

    .venv/bin/python -m uvicorn lyfe.web.app:app --port 8000 &
    .venv/bin/python scripts/e2e_check.py
"""
import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import delete, func, select, text  # noqa: E402

from lyfe.config import get_settings  # noqa: E402
from lyfe.core import pass_token  # noqa: E402
from lyfe.core.security import hash_password  # noqa: E402
from lyfe.core.services import gang_service, hack_service, season_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import (  # noqa: E402
    AdminRole, AdminUser, Event, EventStatus, GameSession, PointTransaction, User, Venue,
)

BASE = "http://127.0.0.1:8000"
TG_BASE = 9_100_000_000
settings = get_settings()

passed = failed = 0


def check(name: str, condition: bool, detail=None) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}  {detail!r}"[:400])


def init_data(tg_id: int, name: str, age: int = 0, tamper: bool = False) -> str:
    fields = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": tg_id, "first_name": name, "language_code": "ru"}, separators=(",", ":")),
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields["user"] = fields["user"].replace(name, name + "x")
    return urlencode(fields)


def guest(n: int) -> dict:
    return {"X-Telegram-Init-Data": init_data(TG_BASE + n, f"E2E{n}")}


async def db(sql: str, **params):
    async with SessionFactory() as s:
        r = await s.execute(text(sql), params)
        await s.commit()
        try:
            return r.all()
        except Exception:  # noqa: BLE001
            return None


SAVED_EVENTS: list = []


async def restore_events() -> None:
    """Give the real local events back the status they had before the check."""
    if not SAVED_EVENTS:
        return
    async with SessionFactory() as s:
        await s.execute(text("UPDATE events SET status = 'ENDED' WHERE slug = 'e2e-party'"))
        for event_id, status in SAVED_EVENTS:
            await s.execute(text("UPDATE events SET status = :st WHERE id = :id"), {"st": status, "id": event_id})
        await s.commit()
    print(f"restored {len(SAVED_EVENTS)} local event(s)")


async def setup() -> int:
    async with SessionFactory() as s:
        # clean previous runs
        ids = select(User.id).where(User.tg_user_id >= TG_BASE)
        await s.execute(delete(PointTransaction).where(PointTransaction.user_id.in_(ids)))
        await s.execute(text("DELETE FROM users WHERE tg_user_id >= :b"), {"b": TG_BASE})
        await s.execute(text("DELETE FROM admin_users WHERE login = 'e2e_admin'"))
        await s.execute(text("DELETE FROM gangs WHERE event_id IN (SELECT id FROM events WHERE slug = 'e2e-party')"))
        # gangs whose test members were just deleted would keep their names taken
        await s.execute(text("DELETE FROM gangs g WHERE NOT EXISTS (SELECT 1 FROM gang_members m WHERE m.gang_id = g.id)"))
        # every other event out of the way, one fresh party two days ahead; their
        # statuses are remembered and put back when the check ends (restore_events)
        SAVED_EVENTS.extend((await s.execute(text(
            "SELECT id, status FROM events WHERE slug <> 'e2e-party' AND status <> 'ENDED'"))).all())
        await s.execute(text("UPDATE events SET status = 'ENDED' WHERE slug <> 'e2e-party'"))
        venue = await s.scalar(select(Venue).limit(1))
        event = await s.scalar(select(Event).where(Event.slug == "e2e-party"))
        if event is None:
            event = Event(slug="e2e-party", title="E2E Party", city_id=venue.city_id, venue_id=venue.id,
                          status=EventStatus.UPCOMING, starts_at=func.now())
            s.add(event)
            await s.flush()
        await s.execute(text("""
            UPDATE events SET status='UPCOMING', starts_at=now() + interval '2 days',
                requests_open_from=now() - interval '1 day', requests_open_until=now() + interval '3 days',
                checkin_open_from=now() - interval '1 day', checkin_open_until=now() + interval '3 days',
                ticket_url='https://goout.net/sk/'
            WHERE id=:id"""), {"id": event.id})
        await s.execute(text("DELETE FROM event_tracks WHERE event_id=:id"), {"id": event.id})
        await s.execute(text("DELETE FROM game_sessions WHERE event_id=:id"), {"id": event.id})
        await s.execute(text("DELETE FROM reward_redemptions WHERE event_id=:id"), {"id": event.id})
        s.add(AdminUser(login="e2e_admin", password_hash=hash_password("e2e-pass"), role=AdminRole.SUPER_ADMIN))
        await s.commit()
        return event.id


async def give(n: int, points: int, key: str) -> None:
    await db("""
        INSERT INTO point_transactions (user_id, delta, reason_code, idempotency_key, created_at, updated_at)
        SELECT id, :p, 'MANUAL_ADJUSTMENT', :k, now(), now() FROM users WHERE tg_user_id=:t
        ON CONFLICT (idempotency_key) DO NOTHING""", p=points, k=key, t=TG_BASE + n)


async def main() -> None:
    if "127.0.0.1" not in BASE and "localhost" not in BASE:
        sys.exit("local only")
    event_id = await setup()
    c = httpx.AsyncClient(base_url=BASE, timeout=40)

    print("\n[auth]")
    check("no initData → 401", (await c.get("/api/app/me")).status_code == 401)
    check("tampered initData → 401", (await c.get("/api/app/me", headers={"X-Telegram-Init-Data": init_data(TG_BASE + 1, "E2E1", tamper=True)})).status_code == 401)
    check("expired initData → 401", (await c.get("/api/app/me", headers={"X-Telegram-Init-Data": init_data(TG_BASE + 1, "E2E1", age=90000)})).status_code == 401)
    me = (await c.get("/api/app/me", headers=guest(1))).json()
    check("new guest registered with LYFE ID", bool(me["user"]["lyfe_id"]), me["user"])
    check("event visible", me["event"] and me["event"]["id"] == event_id, me["event"])
    check("season on", me["season"] and me["season"]["game"]["attempts_left"] == 2, me["season"])
    for n in range(2, 7):
        await c.get("/api/app/me", headers=guest(n))

    print("\n[search + links]")
    r = (await c.post("/api/app/search", headers=guest(1), json={"q": "the weeknd blinding lights"})).json()
    check("text search finds it", r["status"] == "ok" and r["candidates"][0]["artist"] == "The Weeknd", r)
    token_bl = r["candidates"][0]["token"]
    r = (await c.post("/api/app/search", headers=guest(1), json={"q": "https://www.youtube.com/watch?v=4NRXx6U8ABQ"})).json()
    check("YouTube link → text, exact first", r["link_text"] == "The Weeknd - Blinding Lights" and r["exact_first"], r.get("link_text"))
    r = (await c.post("/api/app/search", headers=guest(1), json={"q": "https://vk.com/audio-1_2"})).json()
    check("unreadable link reported", r["status"] == "link_unreadable", r)
    r = (await c.post("/api/app/search", headers=guest(1), json={"q": "a"})).json()
    check("1-char query ignored", r["status"] == "empty", r)

    print("\n[requests]")
    r = (await c.post("/api/app/request", headers=guest(1), json={"token": token_bl})).json()
    check("add track", r["status"] == "ADDED" and r["points"] == 1, r)
    r = (await c.post("/api/app/request", headers=guest(1), json={"token": token_bl})).json()
    check("same track twice → ALREADY", r["status"] == "ALREADY_REQUESTED", r)
    r2 = (await c.post("/api/app/search", headers=guest(2), json={"q": "https://www.deezer.com/track/908604612"})).json()
    check("other source shows 'already in list'", r2["candidates"][0]["in_event"] is not None, r2["candidates"][0])
    r = (await c.post("/api/app/request", headers=guest(2), json={"token": r2["candidates"][0]["token"]})).json()
    check("Deezer copy joins the same row (2 requests)", r["status"] == "ADDED" and r["requests_count"] == 2, r)
    r = (await c.post("/api/app/request", headers=guest(3), json={"manual": "The Weekend - Blinding Lights"})).json()
    check("hand-typed typo joins too (3 requests)", r.get("requests_count") == 3, r)
    check("manual link refused", (await c.post("/api/app/request", headers=guest(3), json={"manual": "https://x.y/z"})).json()["status"] == "MANUAL_IS_LINK")
    check("manual without dash refused", (await c.post("/api/app/request", headers=guest(3), json={"manual": "just words"})).json()["status"] == "MANUAL_FORMAT")
    check("forged token → 400", (await c.post("/api/app/request", headers=guest(3), json={"token": token_bl[:-3] + "abc"})).status_code == 400)
    for i, t in enumerate(["Rick Astley - Never Gonna Give You Up", "Daft Punk - One More Time", "Eminem - Lose Yourself"]):
        r = (await c.post("/api/app/request", headers=guest(4), json={"manual": t})).json()
    check("3 tracks max", r["status"] == "ADDED")
    r = (await c.post("/api/app/request", headers=guest(4), json={"manual": "Queen - Bohemian Rhapsody"})).json()
    check("4th track → LIMIT_REACHED", r["status"] == "LIMIT_REACHED", r)
    # enough tracks on the night to hit the like and dislike caps (5 each)
    for t in ["Kavinsky - Nightcall", "Jan Hammer - Miami Vice Theme"]:
        r = (await c.post("/api/app/request", headers=guest(2), json={"manual": t})).json()
        check(f"extra track for the caps: {t}", r["status"] == "ADDED", r)

    print("\n[top + votes]")
    top = (await c.get("/api/app/top", headers=guest(5))).json()
    first = top["items"][0]
    check("top ordered by score", first["title"].startswith("Blinding") and first["score"] == 3, first)
    check("own track → OWN_TRACK", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(1))).json()["status"] == "OWN_TRACK")
    check("vote", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(5))).json()["status"] == "VOTED")
    check("vote again → ALREADY", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(5))).json()["status"] == "ALREADY_VOTED")
    others = [i["id"] for i in top["items"][1:]]
    cap = settings.max_votes_per_event
    check(f"enough tracks to test the like cap ({len(others)} others)", len(others) >= cap, len(others))
    for i in others[:cap - 1]:
        check("like within the cap", (await c.post(f"/api/app/vote/{i}", headers=guest(5))).json()["status"] == "VOTED")
    check(f"like #{cap + 1} → LIMIT", (await c.post(f"/api/app/vote/{others[cap - 1]}", headers=guest(5))).json()["status"] == "LIMIT")
    me5v = (await c.get("/api/app/me", headers=guest(5))).json()
    check(f"/me shows {cap} of {cap} likes used", me5v["tonight"]["votes_used"] == cap and me5v["rules"]["votes_max"] == cap, me5v["tonight"])
    results = await asyncio.gather(*(c.post(f"/api/app/vote/{i}", headers=guest(6)) for i in others * 3))
    statuses = [x.json()["status"] for x in results]
    check(f"parallel likes on every track: exactly {cap} go through", statuses.count("VOTED") == cap, statuses)

    print("\n[dislikes «В розыск» — own cap, no points, one reaction per track]")
    check("dislike own track → OWN_TRACK", (await c.post(f"/api/app/dislike/{first['id']}", headers=guest(1))).json()["status"] == "OWN_TRACK")
    check("liked track can't be disliked too → ALREADY_VOTED", (await c.post(f"/api/app/dislike/{first['id']}", headers=guest(5))).json()["status"] == "ALREADY_VOTED")
    target = others[0]
    score_before = next(i for i in (await c.get("/api/app/top", headers=guest(7))).json()["items"] if i["id"] == target)["score"]
    pts_before = (await c.get("/api/app/me", headers=guest(7))).json()["user"]["points"]
    check("dislike", (await c.post(f"/api/app/dislike/{target}", headers=guest(7))).json()["status"] == "VOTED")
    row = next(i for i in (await c.get("/api/app/top", headers=guest(7))).json()["items"] if i["id"] == target)
    check("dislike takes 1 off the score and is marked", row["score"] == score_before - 1 and row["disliked"] and row["dislikes"] >= 1, (score_before, row))
    check("dislike earns nothing", (await c.get("/api/app/me", headers=guest(7))).json()["user"]["points"] == pts_before)
    check("dislike again → ALREADY_VOTED", (await c.post(f"/api/app/dislike/{target}", headers=guest(7))).json()["status"] == "ALREADY_VOTED")
    check("like after dislike → ALREADY_VOTED", (await c.post(f"/api/app/vote/{target}", headers=guest(7))).json()["status"] == "ALREADY_VOTED")
    dcap = settings.max_dislikes_per_event
    results = await asyncio.gather(*(c.post(f"/api/app/dislike/{i}", headers=guest(8)) for i in others * 3))
    statuses = [x.json()["status"] for x in results]
    check(f"parallel dislikes on every track: exactly {min(dcap, len(others))} go through", statuses.count("VOTED") == min(dcap, len(others)), statuses)
    me8 = (await c.get("/api/app/me", headers=guest(8))).json()
    check("/me shows dislikes used and the cap", me8["tonight"]["dislikes_used"] == min(dcap, len(others)) and me8["rules"]["dislikes_max"] == dcap, me8["tonight"])
    check("likes stay free after dislikes (own caps)", me8["tonight"]["votes_used"] == 0)

    print("\n[boost — own track only, incl. 12 parallel taps]")
    check("boost someone else's track → NOT_OWN", (await c.post(f"/api/app/boost/{first['id']}", headers=guest(5))).json()["status"] == "NOT_OWN")
    await give(5, 100, "e2e:give:5")
    check("NOT_OWN even with points", (await c.post(f"/api/app/boost/{first['id']}", headers=guest(5))).json()["status"] == "NOT_OWN")
    await give(1, 20, "e2e:give:1b")                     # guest 1 requested the first track
    before1 = (await c.get("/api/app/me", headers=guest(1))).json()["user"]["points"]
    results = await asyncio.gather(*(c.post(f"/api/app/boost/{first['id']}", headers=guest(1)) for _ in range(12)))
    st = [x.json()["status"] for x in results]
    cap = settings.max_boosts_per_event
    check(f"own track: only {cap} boosts go through", st.count("BOOSTED") == cap and st.count("LIMIT_REACHED") == 12 - cap, st)
    after1 = (await c.get("/api/app/me", headers=guest(1))).json()["user"]["points"]
    check(f"balance charged exactly {cap * settings.cost_boost}", before1 - after1 == cap * settings.cost_boost, (before1, after1))
    me5 = (await c.get("/api/app/me", headers=guest(5))).json()
    expected5 = 100 + settings.points_vote * min(settings.max_votes_per_event, settings.max_paid_votes_per_event)   # gift + paid likes, no boosts
    check("nothing charged for refused boosts", me5["user"]["points"] == expected5, (me5["user"]["points"], expected5))

    print("\n[guarantee]")
    await give(1, 100, "e2e:give:1")
    await give(2, 100, "e2e:give:2")
    await give(4, 100, "e2e:give:4")
    p1 = (await c.get("/api/app/priority", headers=guest(1))).json()
    check("own tracks offered", len(p1["tracks"]) == 1, p1)
    foreign = [i["id"] for i in (await c.get("/api/app/top", headers=guest(1))).json()["items"] if not i["mine"]][0]
    check("foreign track → NO_TRACK", (await c.post(f"/api/app/priority/{foreign}", headers=guest(1))).json()["status"] == "NO_TRACK")
    results = await asyncio.gather(*(c.post(f"/api/app/priority/{p1['tracks'][0]['id']}", headers=guest(1)) for _ in range(5)))
    st = [x.json()["status"] for x in results]
    check("parallel guarantee: charged once", st.count("OK") == 1, st)
    t4 = (await c.get("/api/app/priority", headers=guest(4))).json()["tracks"]
    check("second guarantee of the night OK", (await c.post(f"/api/app/priority/{t4[0]['id']}", headers=guest(4))).json()["status"] == "OK")
    t2 = (await c.get("/api/app/priority", headers=guest(2))).json()
    check("third → none left", t2["left"] == 0, t2)

    print("\n[door rewards]")
    rw = (await c.get("/api/app/rewards", headers=guest(2))).json()
    drink = next(i for i in rw["items"] if i["cost"] == 40)
    results = await asyncio.gather(*(c.post(f"/api/app/rewards/{drink['id']}/buy", headers=guest(2)) for _ in range(5)))
    st = [x.json()["status"] for x in results]
    check("parallel drink buy: once", st.count("OK") == 1, st)
    held = (await c.get("/api/app/pass", headers=guest(2))).json()["held"]
    check("code shown under LYFE PASS", len(held) == 1 and held[0]["code"].startswith("LYFE-"), held)
    check("no points → NOT_ENOUGH", (await c.post(f"/api/app/rewards/{drink['id']}/buy", headers=guest(3))).json()["status"] == "NOT_ENOUGH_POINTS")

    print("\n[pumpkins]")
    results = await asyncio.gather(*(c.post("/api/app/pumpkin/home", headers=guest(3)) for _ in range(6)))
    st = [x.json()["status"] for x in results]
    check("parallel same pumpkin: paid once", st.count("FOUND") == 1, st)
    for pid in ("add", "top", "me", "points"):
        r = (await c.post(f"/api/app/pumpkin/{pid}", headers=guest(3))).json()
    check("all five → bonus", r["bonus"] == 5, r)
    check("unknown pumpkin", (await c.post("/api/app/pumpkin/nope", headers=guest(3))).json()["status"] == "UNKNOWN")

    print("\n[PUMPKIN RUSH — incl. parallel starts]")
    results = await asyncio.gather(*(c.post("/api/app/game/start", headers=guest(6)) for _ in range(6)))
    started = [x.json() for x in results if x.json()["status"] == "OK"]
    check("6 parallel starts → only 2 attempts", len(started) == 2, [x.json()["status"] for x in results])
    g1, g2 = started
    check("finish someone else's round → UNKNOWN", (await c.post(f"/api/app/game/{g1['id']}/finish", headers=guest(5), json={"hits": []})).json()["status"] == "UNKNOWN")
    early = (await c.post(f"/api/app/game/{g1['id']}/finish", headers=guest(6), json={"hits": [{"id": p["id"], "t": p["at"]} for p in g1["pieces"]]})).json()
    check("finished too early → 0", early["score"] == 0, early)
    check("finish twice → UNKNOWN", (await c.post(f"/api/app/game/{g1['id']}/finish", headers=guest(6), json={"hits": []})).json()["status"] == "UNKNOWN")
    print("       (waiting 19 s for a real round)")
    await asyncio.sleep(19)
    # a perfect fast player: every pumpkin tapped quickly, ghosts left alone
    good = [{"id": p["id"], "t": round(p["at"] + 0.1, 3)} for p in g2["pieces"] if p["value"] > 0]
    forged = [{"id": 9999, "t": 1}, {"id": g2["pieces"][0]["id"], "t": 99}, {"id": "x", "t": "y"}]
    async with SessionFactory() as s:
        seed = await s.scalar(select(GameSession.seed).where(GameSession.id == g2["id"]))
    expected = season_service.score_hits(seed, good)
    flat = sum(p["value"] for p in g2["pieces"] if p["value"] > 0)
    r = (await c.post(f"/api/app/game/{g2['id']}/finish", headers=guest(6), json={"hits": good + good + forged})).json()
    check("server score: duplicates and forged taps ignored", r["score"] == expected and r["place"] == 1, (r, expected))
    check(f"streak + fast taps pay off ({expected} vs {flat} flat)", expected > flat * 2, (expected, flat))
    # sloppy player: slow taps, every 3rd pumpkin missed, one ghost — far below
    slow = [{"id": p["id"], "t": round(p["at"] + p["ttl"] * 0.9, 3)} for i, p in enumerate(g2["pieces"]) if p["value"] > 0 and i % 3]
    ghost = next(p for p in g2["pieces"] if p["value"] < 0)
    sloppy = season_service.score_hits(seed, slow + [{"id": ghost["id"], "t": ghost["at"] + 0.1}])
    check(f"sloppy round scores much less ({sloppy})", sloppy < expected / 2, (sloppy, expected))

    print("\n[free entry for the top 5]")
    me6 = (await c.get("/api/app/me", headers=guest(6))).json()
    check("GoOut link for the Buy button", me6["event"]["ticket_url"] == "https://goout.net/sk/", me6["event"])
    check("game open, not waiting", me6["season"]["game"]["waiting"] is False, me6["season"]["game"])
    check("game open two days ahead, top 5 announced", me6["season"]["game"]["open"] and me6["season"]["game"]["places"] == 5, me6["season"]["game"])
    check("GoOut code endpoint is gone", (await c.post("/api/app/ticket", headers=guest(1), json={"code": "GO-1"})).status_code in (404, 405))
    async with SessionFactory() as s:
        ev = await s.get(Event, event_id)
        won = await season_service.award_free_entries(s, event=ev)
        again = await season_service.award_free_entries(s, event=ev)
        await s.commit()
    check("winner marked once", len(won) == 1 and again == [], (won, again))
    check("FREE ENTRY in /me", (await c.get("/api/app/me", headers=guest(6))).json()["free_entry"] == "PUMPKIN RUSH #1")
    check("FREE ENTRY on the LYFE PASS", (await c.get("/api/app/pass", headers=guest(6))).json()["free_entry"] == "PUMPKIN RUSH #1")
    check("no free entry for others", (await c.get("/api/app/me", headers=guest(1))).json()["free_entry"] is None)

    print("\n[door scanner]")
    adm = httpx.AsyncClient(base_url=BASE, timeout=40)
    login = await adm.post("/login", data={"login": "e2e_admin", "password": "e2e-pass"})
    check("admin login", login.status_code in (200, 303) and "lyfe_admin" in adm.cookies, login.status_code)
    async with SessionFactory() as s:
        u1 = await s.scalar(select(User).where(User.tg_user_id == TG_BASE + 1))
        u2 = await s.scalar(select(User).where(User.tg_user_id == TG_BASE + 2))
    results = await asyncio.gather(*(adm.post("/api/checkin", json={"token": pass_token.build(u1.id, settings.admin_secret_key)}) for _ in range(4)))
    st = [x.json()["status"] for x in results]
    check("4 parallel scans → 1 check-in", st.count("OK") == 1 and st.count("ALREADY") == 3, st)
    ok = next(x.json() for x in results if x.json()["status"] == "OK")
    check("scan: no free entry for guest 1", ok["free_entry"] is None, ok)
    async with SessionFactory() as s:
        u6 = await s.scalar(select(User).where(User.tg_user_id == TG_BASE + 6))
    r6 = (await adm.post("/api/checkin", json={"token": pass_token.build(u6.id, settings.admin_secret_key)})).json()
    check("scan shows FREE ENTRY for the winner", r6["free_entry"] == "PUMPKIN RUSH #1", r6)
    r = (await adm.post("/api/checkin", json={"token": "LYFE:1:deadbeef"})).json()
    check("forged pass → INVALID_TOKEN", r["status"] == "INVALID_TOKEN", r)
    r = (await adm.post("/api/checkin", json={"lyfe_id": u2.lyfe_id})).json()
    check("manual LYFE ID check-in + drink pending", r["status"] == "OK" and len(r["pending"]) == 1, r)
    use = (await adm.post(f"/api/redemptions/{r['pending'][0]['id']}/use")).json()
    check("hand over drink", use["status"] == "OK", use)
    check("hand over twice → ALREADY_USED", (await adm.post(f"/api/redemptions/{r['pending'][0]['id']}/use")).json()["status"] == "ALREADY_USED")
    me1 = (await c.get("/api/app/me", headers=guest(1))).json()
    check("night counted in MY LYFE", me1["user"]["nights"] == 1, me1["user"])

    print("\n[DJ screen]")
    board = (await adm.get("/api/board")).json()
    check("board lists tracks, priority first", board["tracks"] and board["tracks"][0]["is_priority"], board["tracks"][:1])
    tid = board["tracks"][0]["id"]
    check("PLAYED", (await adm.post(f"/api/tracks/{tid}/played")).json()["changed"])
    check("undo cancels push", (await adm.post(f"/api/tracks/{tid}/undo")).json()["push_cancelled"])
    check("reject toggles", (await adm.post(f"/api/tracks/{board['tracks'][-1]['id']}/reject")).json()["changed"])
    check("DJ API needs login", (await c.get("/api/board")).status_code == 401)

    print("\n[Банда — up to 5, one gang per person, races, leaving]")
    g0 = (await c.get("/api/app/gang", headers=guest(11))).json()
    check("gang screen: no gang yet, 5 max, top 2 free", g0["gang"] is None and g0["max"] == 5 and g0["free_places"] == 2 and g0["hack"]["open"], g0)
    check("link in the name → BAD_NAME", (await c.post("/api/app/gang/create", headers=guest(11), json={"name": "t.me/spam"})).json()["status"] == "BAD_NAME")
    check("one letter → BAD_NAME", (await c.post("/api/app/gang/create", headers=guest(11), json={"name": "Я"})).json()["status"] == "BAD_NAME")
    r = (await c.post("/api/app/gang/create", headers=guest(11), json={"name": "  Ночные   Лисы "})).json()
    check("create gang, name tidied, leader", r["status"] == "CREATED" and r["gang"]["gang"]["name"] == "Ночные Лисы" and r["gang"]["gang"]["my_role"] == "leader", r)
    code = r["gang"]["gang"]["code"]
    check("invite link carries the code", r["gang"]["gang"]["link"].endswith("startapp=gang_" + code), r["gang"]["gang"]["link"])
    check("same name in other case → NAME_TAKEN", (await c.post("/api/app/gang/create", headers=guest(12), json={"name": "ночные лисы"})).json()["status"] == "NAME_TAKEN")
    check("second gang for the leader → ALREADY_IN_GANG", (await c.post("/api/app/gang/create", headers=guest(11), json={"name": "Другая"})).json()["status"] == "ALREADY_IN_GANG")
    check("unknown code → NOT_FOUND", (await c.post("/api/app/gang/join", headers=guest(12), json={"code": "NOPE1234"})).json()["status"] == "NOT_FOUND")
    check("own link → ALREADY_HERE", (await c.post("/api/app/gang/join", headers=guest(11), json={"code": "gang_" + code})).json()["status"] == "ALREADY_HERE")
    for n in range(12, 20):
        await c.get("/api/app/me", headers=guest(n))
    results = await asyncio.gather(*(c.post("/api/app/gang/join", headers=guest(n), json={"code": code}) for n in range(12, 20)))
    st = [x.json()["status"] for x in results]
    check("8 friends open the link at once: exactly 4 get in, 4 → FULL", st.count("JOINED") == 4 and st.count("FULL") == 4, st)
    gv = (await c.get("/api/app/gang", headers=guest(11))).json()["gang"]
    roles = [m["role"] for m in gv["members"]]
    check("5 members, every role once, in order", roles == ["leader", "driver", "hacker", "muscle", "scout"], roles)
    joined = [n for n, x in zip(range(12, 20), st) if x == "JOINED"]
    outsider = [n for n, x in zip(range(12, 20), st) if x == "FULL"][0]
    r = (await c.post("/api/app/gang/create", headers=guest(20), json={"name": "Бетонные Пальмы"})).json()
    check("second gang", r["status"] == "CREATED", r)
    code2 = r["gang"]["gang"]["code"]
    check("member of one gang can't join another → ALREADY_IN_GANG", (await c.post("/api/app/gang/join", headers=guest(joined[0]), json={"code": code2})).json()["status"] == "ALREADY_IN_GANG")
    results = await asyncio.gather(*(c.post("/api/app/gang/create", headers=guest(21), json={"name": f"Банда {i}"}) for i in range(4)))
    st = [x.json()["status"] for x in results]
    check("4 parallel creates by one person → one gang", st.count("CREATED") == 1 and st.count("ALREADY_IN_GANG") == 3, st)
    driver = next(int(m["name"][3:]) for m in gv["members"] if m["role"] == "driver")
    check("driver leaves", (await c.post("/api/app/gang/leave", headers=guest(driver))).json()["status"] == "LEFT")
    r = (await c.post("/api/app/gang/join", headers=guest(outsider), json={"code": code})).json()
    check("freed place taken, the freed role handed out", r["status"] == "JOINED" and any(m["role"] == "driver" and m["me"] for m in r["gang"]["gang"]["members"]), r["gang"]["gang"])
    r = (await c.post("/api/app/gang/leave", headers=guest(11))).json()
    check("leader leaves", r["status"] == "LEFT" and r["gang"]["gang"] is None, r)
    gv = (await c.get("/api/app/gang", headers=guest(joined[1]))).json()["gang"]
    check("the next one in becomes leader, still 4", len(gv["members"]) == 4 and gv["members"][0]["role"] == "leader", gv["members"])
    check("not in a gang → leave NOT_IN_GANG", (await c.post("/api/app/gang/leave", headers=guest(11))).json()["status"] == "NOT_IN_GANG")
    check("ex-leader can join back", (await c.post("/api/app/gang/join", headers=guest(11), json={"code": code})).json()["status"] == "JOINED")
    r = (await c.post("/api/app/gang/create", headers=guest(22), json={"name": "Одиночки"})).json()
    check("lone gang leaves → gang gone", (await c.post("/api/app/gang/leave", headers=guest(22))).json()["status"] == "LEFT"
          and (await c.post("/api/app/gang/join", headers=guest(23), json={"code": r["gang"]["gang"]["code"]})).json()["status"] == "NOT_FOUND")
    print("\n[Банда: open gangs, «Найти банду»]")
    check("not the leader → can't open the gang", (await c.post("/api/app/gang/public", headers=guest(11), json={"open": True})).json()["status"] == "NOT_LEADER")
    check("no gang → can't open one", (await c.post("/api/app/gang/public", headers=guest(22), json={"open": True})).json()["status"] == "NOT_IN_GANG")
    r = (await c.post("/api/app/gang/public", headers=guest(20), json={"open": True})).json()
    check("leader opens the gang", r["status"] == "OPENED" and r["gang"]["gang"]["public"] is True, r)
    check("second leader opens too", (await c.post("/api/app/gang/public", headers=guest(21), json={"open": True})).json()["status"] == "OPENED")
    for n in range(23, 32):
        await c.get("/api/app/me", headers=guest(n))
    og = (await c.get("/api/app/gang", headers=guest(23))).json()["open_gangs"]
    check("no gang: sees the open gangs, not the closed full one", len(og) == 2 and "Ночные Лисы" not in [o["name"] for o in og], og)
    check("a closed gang can't be joined by id", (await c.post("/api/app/gang/join-open/99999999", headers=guest(23))).json()["status"] == "NOT_FOUND")
    palms = next(o["id"] for o in og if o["name"] == "Бетонные Пальмы")
    check("join an open gang from the list", (await c.post(f"/api/app/gang/join-open/{palms}", headers=guest(23))).json()["status"] == "JOINED")
    r = (await c.post("/api/app/gang/find", headers=guest(24))).json()
    check("«Найти банду» puts you in the fullest open gang", r["status"] == "JOINED" and r["name"] == "Бетонные Пальмы", r)
    results = await asyncio.gather(*(c.post("/api/app/gang/find", headers=guest(n)) for n in range(25, 32)))
    st = [x.json()["status"] for x in results]
    check("7 people press «Найти банду» at once with 6 places → 6 in, 1 NONE_OPEN", st.count("JOINED") == 6 and st.count("NONE_OPEN") == 1, st)
    sizes = [b["size"] for b in (await c.get("/api/app/gang", headers=guest(20))).json()["board"]]
    check("no gang went over 5", max(sizes) <= 5, sizes)
    check("full gangs drop off the open list", (await c.get("/api/app/gang", headers=guest(22))).json()["open_gangs"] == [])
    board = (await c.get("/api/app/gang", headers=guest(22))).json()["board"]
    check("the rating shows who is in each gang", all(len(b["crew"]) == b["size"] for b in board), board)
    leader21 = (await c.get("/api/app/gang", headers=guest(21))).json()["gang"]
    check("leader closes the gang", leader21 and (await c.post("/api/app/gang/public", headers=guest(21), json={"open": False})).json()["status"] == "CLOSED")
    r = (await c.post("/api/app/gang/find", headers=guest(22))).json()
    check("nothing open → NONE_OPEN, still no gang", r["status"] == "NONE_OPEN" and r["gang"]["gang"] is None, r)
    saved_until = gang_service.settings.gang_changes_until
    gang_service.settings.gang_changes_until = "2020-01-01T00:00:00+00:00"
    try:
        async with SessionFactory() as s:
            u = await s.scalar(select(User).where(User.tg_user_id == TG_BASE + 23))
            locked = (await gang_service.join_gang(s, user=u, code=code)).status
            await s.rollback()
    finally:
        gang_service.settings.gang_changes_until = saved_until
    check("after the lock date nobody joins → LOCKED", locked == "LOCKED", locked)

    print("\n[Взлом — the server replays every tap]")
    r = (await c.post("/api/app/hack/start", headers=guest(22))).json()
    check("no gang → can't play (NO_GANG), no attempt used", r["status"] == "NO_GANG"
          and (await c.get("/api/app/gang", headers=guest(22))).json()["hack"]["attempts_left"] == hack_service.settings.hack_attempts_per_day, r)
    def perfect(lock):
        target = lock["start"] + lock["width"] / 2
        t = (target if lock["dir"] == 1 else 360 - target) / lock["speed"]
        return t if t >= 0.3 else t + 360 / lock["speed"]     # a human waits for the next turn
    def wrong(lock):
        target = lock["start"] + lock["width"] + 40
        return (target if lock["dir"] == 1 else 360 - target) / lock["speed"]
    h = (await c.post("/api/app/hack/start", headers=guest(joined[1]))).json()
    check("start: 10 locks, each narrower and faster", h["status"] == "OK" and len(h["locks"]) == 10
          and h["locks"][0]["width"] > h["locks"][-1]["width"] and h["locks"][0]["speed"] < h["locks"][-1]["speed"], h.get("locks", [])[:2])
    taps = [perfect(l) for l in h["locks"]]
    r = (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[1]), json={"taps": taps})).json()
    check("perfect taps sent too fast → no loot", r["status"] == "OK" and r["score"] == 0, r)
    check("same run twice → NOT_FOUND", (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[1]), json={"taps": taps})).json()["status"] == "NOT_FOUND")
    h = (await c.post("/api/app/hack/start", headers=guest(joined[1]))).json()
    taps = [perfect(l) for l in h["locks"]]
    check("someone else's run → NOT_FOUND", (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[2]), json={"taps": taps})).json()["status"] == "NOT_FOUND")
    await asyncio.sleep(sum(taps) + 0.3)
    r = (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[1]), json={"taps": taps})).json()
    full = sum(hack_service.lock_loot(l, t) for l, t in zip([hack_service.Lock(**x) for x in h["locks"]], taps))
    check("all 10 locks → base + aim + speed, as the replay says", r["levels"] == 10 and r["score"] == full and r["score"] > hack_service.loot_for(10), (r, full))
    best1 = r["score"]
    h = (await c.post("/api/app/hack/start", headers=guest(joined[2]))).json()
    taps = [perfect(l) for l in h["locks"][:2]] + [wrong(h["locks"][2])] + [perfect(l) for l in h["locks"][3:]]
    await asyncio.sleep(sum(taps[:3]) + 0.3)
    r = (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[2]), json={"taps": taps})).json()
    two = sum(hack_service.lock_loot(hack_service.Lock(**l), t) for l, t in zip(h["locks"][:2], taps[:2]))
    check("miss on lock 3 → WASTED after 2, loot of those 2", r["levels"] == 2 and r["score"] == two and r["score"] >= 300, (r, two))
    h = (await c.post("/api/app/hack/start", headers=guest(joined[2]))).json()
    r = (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(joined[2]), json={"taps": ["x", None]})).json()
    check("garbage taps → nothing, best kept", r["score"] == 0 and r["best"] == two, r)
    h = (await c.post("/api/app/hack/start", headers=guest(20))).json()
    t2 = [perfect(l) for l in h["locks"][:1]] + [wrong(h["locks"][1])]
    await asyncio.sleep(sum(t2) + 0.3)
    r = (await c.post(f"/api/app/hack/{h['id']}/finish", headers=guest(20), json={"taps": t2})).json()
    one = hack_service.lock_loot(hack_service.Lock(**h["locks"][0]), t2[0])
    check("other gang: 1 lock, its loot", r["levels"] == 1 and r["score"] == one, (r, one))
    gv = (await c.get("/api/app/gang", headers=guest(20))).json()
    names = [(b["name"], b["loot"]) for b in gv["board"]]
    check("rating: gang loot = sum of members' best runs", names[:2] == [("Ночные Лисы", best1 + two), ("Бетонные Пальмы", one)], names)
    check("my gang is marked in the rating", any(b["mine"] and b["name"] == "Бетонные Пальмы" for b in gv["board"]), gv["board"])
    # joined[2] has played 2 of 3 today: one more, then the day is over
    gl = (await c.get("/api/app/gang", headers=guest(joined[2]))).json()["hack"]
    check("2 runs played → 1 left today, 18 of 20 for the party", gl["attempts_left"] == 1 and gl["attempts_total_left"] == 18
          and gl["per_day"] == 3 and gl["total"] == 20, gl)
    results = await asyncio.gather(*(c.post("/api/app/hack/start", headers=guest(joined[2])) for _ in range(5)))
    st = [x.json()["status"] for x in results]
    check("5 parallel starts with 1 left today → 1 OK, 4 NO_ATTEMPTS", st.count("OK") == 1 and st.count("NO_ATTEMPTS") == 4, st)
    saved_total = hack_service.settings.hack_attempts_total
    hack_service.settings.hack_attempts_total = 1
    try:
        async with SessionFactory() as s:
            u = await s.scalar(select(User).where(User.tg_user_id == TG_BASE + 20))
            ev = await s.get(Event, event_id)
            no = await hack_service.start(s, user=u, event=ev)
            await s.rollback()
    finally:
        hack_service.settings.hack_attempts_total = saved_total
    check("all runs for the party used → NO_ATTEMPTS_LEFT", no == "NO_ATTEMPTS_LEFT", no)

    print("\n[top 2 gangs get in free]")
    async with SessionFactory() as s:
        ev = await s.get(Event, event_id)
        won = await gang_service.award_free_entries(s, event=ev)
        again = await gang_service.award_free_entries(s, event=ev)
        await s.commit()
    check("both top gangs, every member marked once (5 + 5)", len(won) == 10 and again == [], [(u.name, g, p) for u, g, p in won])
    check("FREE ENTRY for a member of the first gang", (await c.get("/api/app/me", headers=guest(joined[3]))).json()["free_entry"].startswith("Банда «Ночные Лисы» #1 · LYFE "))
    check("FREE ENTRY for the second gang", (await c.get("/api/app/pass", headers=guest(20))).json()["free_entry"].startswith("Банда «Бетонные Пальмы» #2 · LYFE "))
    check("nobody else", (await c.get("/api/app/me", headers=guest(21))).json()["free_entry"] is None)

    print("\n[ledger integrity]")
    rows = await db("""
        SELECT u.tg_user_id, coalesce(sum(pt.delta), 0) FROM users u
        LEFT JOIN point_transactions pt ON pt.user_id = u.id
        WHERE u.tg_user_id >= :b GROUP BY u.tg_user_id""", b=TG_BASE)
    check("no negative balance", all(b >= 0 for _, b in rows), rows)
    for n in range(1, 7):
        api_pts = (await c.get("/api/app/me", headers=guest(n))).json()["user"]["points"]
        ledger = dict(rows)[TG_BASE + n]
        check(f"guest {n}: app balance == ledger ({ledger})", api_pts == ledger, (api_pts, ledger))

    print("\n[game closes a day before the party]")
    await db("UPDATE events SET starts_at=now() + interval '12 hours' WHERE id=:id", id=event_id)
    me5 = (await c.get("/api/app/me", headers=guest(5))).json()
    check("closed in /me", me5["season"]["game"]["open"] is False, me5["season"]["game"])
    check("start after close → CLOSED", (await c.post("/api/app/game/start", headers=guest(5))).json()["status"] == "CLOSED")
    check("Взлом closes too → CLOSED", (await c.post("/api/app/hack/start", headers=guest(20))).json()["status"] == "CLOSED")
    check("gang screen says the game is closed", (await c.get("/api/app/gang", headers=guest(20))).json()["hack"]["open"] is False)

    print("\n[between parties]")
    await db("UPDATE events SET status='ENDED', starts_at=now() - interval '1 day' WHERE id=:id", id=event_id)
    me = (await c.get("/api/app/me", headers=guest(3))).json()
    check("no event, season + game still on", me["event"] is None and me["season"]["game"] is not None, me["season"])
    check("between parties the game waits for the next one", me["season"]["game"]["waiting"] and not me["season"]["game"]["open"], me["season"]["game"])
    check("start between parties → CLOSED", (await c.post("/api/app/game/start", headers=guest(3))).json()["status"] == "CLOSED")
    check("adding a track → 409", (await c.post("/api/app/request", headers=guest(3), json={"manual": "A - B"})).status_code == 409)
    check("top empty, no crash", (await c.get("/api/app/top", headers=guest(3))).json()["items"] == [])
    check("rewards empty, no crash", (await c.get("/api/app/rewards", headers=guest(3))).status_code == 200)
    check("pass works", (await c.get("/api/app/pass", headers=guest(3))).status_code == 200)
    check("page served with asset version", "__ASSET_V__" not in (await c.get("/app")).text)
    root = await c.get("/", follow_redirects=True)
    check("site root (bot 'Open' without /app) → login page that forwards Telegram to /app",
          root.status_code == 200 and "tgWebAppData=" in root.text and "location.replace('/app'" in root.text, root.url)

    await c.aclose()
    await adm.aclose()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


async def run() -> None:
    try:
        await main()
    finally:
        await restore_events()


if __name__ == "__main__":
    asyncio.run(run())
