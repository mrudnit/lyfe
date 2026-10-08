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
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import (  # noqa: E402
    AdminRole, AdminUser, Event, EventStatus, PointTransaction, User, Venue,
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


async def setup() -> int:
    async with SessionFactory() as s:
        # clean previous runs
        ids = select(User.id).where(User.tg_user_id >= TG_BASE)
        await s.execute(delete(PointTransaction).where(PointTransaction.user_id.in_(ids)))
        await s.execute(text("DELETE FROM users WHERE tg_user_id >= :b"), {"b": TG_BASE})
        await s.execute(text("DELETE FROM admin_users WHERE login = 'e2e_admin'"))
        # every other event out of the way, one fresh party two days ahead
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

    print("\n[top + votes]")
    top = (await c.get("/api/app/top", headers=guest(5))).json()
    first = top["items"][0]
    check("top ordered by score", first["title"].startswith("Blinding") and first["score"] == 3, first)
    check("own track → OWN_TRACK", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(1))).json()["status"] == "OWN_TRACK")
    check("vote", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(5))).json()["status"] == "VOTED")
    check("vote again → ALREADY", (await c.post(f"/api/app/vote/{first['id']}", headers=guest(5))).json()["status"] == "ALREADY_VOTED")
    others = [i["id"] for i in top["items"][1:]]
    results = await asyncio.gather(*(c.post(f"/api/app/vote/{i}", headers=guest(6)) for i in others * 3))
    statuses = [x.json()["status"] for x in results]
    check("parallel duplicate votes: one per track", statuses.count("VOTED") == len(others), statuses)

    print("\n[boost — incl. 12 parallel taps]")
    check("no points → NOT_ENOUGH", (await c.post(f"/api/app/boost/{first['id']}", headers=guest(5))).json()["status"] == "NOT_ENOUGH_POINTS")
    await give(5, 100, "e2e:give:5")
    results = await asyncio.gather(*(c.post(f"/api/app/boost/{first['id']}", headers=guest(5)) for _ in range(12)))
    st = [x.json()["status"] for x in results]
    check("only 3 boosts go through", st.count("BOOSTED") == 3 and st.count("LIMIT_REACHED") == 9, st)
    me5 = (await c.get("/api/app/me", headers=guest(5))).json()
    expected5 = 100 + settings.points_vote - 15      # gift, one paid like, three boosts
    check("balance charged exactly 15", me5["user"]["points"] == expected5, (me5["user"]["points"], expected5))

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
    good = [{"id": p["id"], "t": p["at"] + 0.2} for p in g2["pieces"] if p["value"] > 0]
    forged = [{"id": 9999, "t": 1}, {"id": g2["pieces"][0]["id"], "t": 99}, {"id": "x", "t": "y"}]
    expected = sum(p["value"] for p in g2["pieces"] if p["value"] > 0)
    r = (await c.post(f"/api/app/game/{g2['id']}/finish", headers=guest(6), json={"hits": good + good + forged})).json()
    check("server score: duplicates and forged taps ignored", r["score"] == expected and r["place"] == 1, (r, expected))

    print("\n[tickets]")
    check("bad code → FORMAT", (await c.post("/api/app/ticket", headers=guest(1), json={"code": "<script>"})).json()["status"] == "FORMAT")
    check("attach", (await c.post("/api/app/ticket", headers=guest(1), json={"code": "GO-E2E-001"})).json()["status"] == "OK")
    check("same code by another → TAKEN", (await c.post("/api/app/ticket", headers=guest(2), json={"code": "GO-E2E-001"})).json()["status"] == "TAKEN")
    check("change own code", (await c.post("/api/app/ticket", headers=guest(1), json={"code": "GO-E2E-002"})).json()["status"] == "OK")
    me1 = (await c.get("/api/app/me", headers=guest(1))).json()
    check("ticket in /me", me1["ticket"] == {"code": "GO-E2E-002"}, me1["ticket"])
    check("ticket QR in pass", (await c.get("/api/app/pass", headers=guest(1))).json()["ticket"]["code"] == "GO-E2E-002")

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
    check("scan shows the GoOut ticket", ok["ticket"] == "GO-E2E-002", ok)
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

    print("\n[between parties]")
    await db("UPDATE events SET status='ENDED', starts_at=now() - interval '1 day' WHERE id=:id", id=event_id)
    me = (await c.get("/api/app/me", headers=guest(3))).json()
    check("no event, season + game still on", me["event"] is None and me["season"]["game"] is not None, me["season"])
    check("adding a track → 409", (await c.post("/api/app/request", headers=guest(3), json={"manual": "A - B"})).status_code == 409)
    check("top empty, no crash", (await c.get("/api/app/top", headers=guest(3))).json()["items"] == [])
    check("rewards empty, no crash", (await c.get("/api/app/rewards", headers=guest(3))).status_code == 200)
    check("pass works", (await c.get("/api/app/pass", headers=guest(3))).status_code == 200)
    check("page served with asset version", "__ASSET_V__" not in (await c.get("/app")).text)

    await c.aclose()
    await adm.aclose()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
