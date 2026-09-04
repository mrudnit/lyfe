"""DJ LIVE SCREEN — the only admin interface built by hand.

Everything else an admin needs is CRUD and can wait. This screen cannot: it is
used in the dark, one-handed, next to a mixer, by someone who has about two
seconds to spare. So it is server-rendered, has no build step, and keeps working
when the venue's wifi does not.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.core import pass_token
from lyfe.core.security import read_session, sign_session, verify_password
from lyfe.core.services import (
    admin_event_service,
    attendance_service,
    dj_service,
    reward_service,
)
from lyfe.core.services.attendance_service import CheckinResult
from lyfe.db import SessionFactory
from lyfe.models import AdminRole, AdminUser, City, Event, EventStatus
from lyfe.web import notifier

logger = logging.getLogger(__name__)
settings = get_settings()

COOKIE_NAME = "lyfe_admin"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ALLOWED_ROLES = (AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.DJ, AdminRole.MODERATOR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await notifier.close()


app = FastAPI(title="LYFE DJ", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_admin(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AdminUser | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    admin_id = read_session(token, settings.admin_secret_key)
    if admin_id is None:
        return None
    admin = await session.get(AdminUser, admin_id)
    if admin is None or not admin.is_active or admin.role not in ALLOWED_ROLES:
        return None
    return admin


async def require_admin(admin: AdminUser | None = Depends(current_admin)) -> AdminUser:
    if admin is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return admin


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str | None = None):
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    admin = await session.scalar(select(AdminUser).where(AdminUser.login == login.strip()))
    if (
        admin is None
        or not admin.is_active
        or admin.role not in ALLOWED_ROLES
        or not verify_password(password, admin.password_hash)
    ):
        logger.warning("Failed admin login for %r", login)
        return TEMPLATES.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        sign_session(admin.id, settings.admin_secret_key),
        httponly=True,
        samesite="lax",
        secure=settings.env == "prod",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# --------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def live(
    request: Request,
    admin: AdminUser | None = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    if admin is None:
        return RedirectResponse("/login", status_code=303)

    event = await dj_service.current_event(session)
    return TEMPLATES.TemplateResponse(
        request,
        "live.html",
        {
            "admin": admin,
            "event": event,
            "can_play": admin.role in (AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.DJ),
        },
    )


@app.get("/api/board")
async def api_board(
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await dj_service.current_event(session)
    if event is None:
        return JSONResponse({"event": None, "tracks": []})

    rows = await dj_service.board(session, event_id=event.id)
    return JSONResponse(
        {
            "event": {"id": event.id, "title": event.title, "status": event.status},
            "tracks": [row.__dict__ for row in rows],
        }
    )


@app.post("/api/tracks/{event_track_id}/played")
async def api_played(
    event_track_id: int,
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if admin.role not in (AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.DJ):
        raise HTTPException(status_code=403, detail="not allowed")

    changed, tg_ids = await dj_service.mark_played(
        session, event_track_id=event_track_id, admin_id=admin.id
    )
    await session.commit()

    if changed:
        notifier.schedule_played_notification(event_track_id, tg_ids)
    return {"ok": True, "changed": changed, "notify": len(tg_ids)}


@app.post("/api/tracks/{event_track_id}/undo")
async def api_undo(
    event_track_id: int,
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cancelled = notifier.cancel_pending(event_track_id)
    changed = await dj_service.undo_played(
        session, event_track_id=event_track_id, admin_id=admin.id
    )
    return {"ok": True, "changed": changed, "push_cancelled": cancelled}


@app.post("/api/tracks/{event_track_id}/reject")
async def api_reject(
    event_track_id: int,
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    changed = await dj_service.reject(session, event_track_id=event_track_id, admin_id=admin.id)
    return {"ok": True, "changed": changed}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# --------------------------------------------------------------------------
# Door scanner
# --------------------------------------------------------------------------

SCAN_ROLES = (AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.MODERATOR)


@app.get("/scan", response_class=HTMLResponse)
async def scan_screen(
    request: Request,
    admin: AdminUser | None = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    if admin is None:
        return RedirectResponse("/login", status_code=303)

    event = await dj_service.current_event(session)
    checked_in = (
        await attendance_service.count_checked_in(session, event_id=event.id) if event else 0
    )
    return TEMPLATES.TemplateResponse(
        request,
        "scan.html",
        {"admin": admin, "event": event, "checked_in": checked_in},
    )


@app.post("/api/checkin")
async def api_checkin(
    payload: dict = Body(...),
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if admin.role not in SCAN_ROLES:
        raise HTTPException(status_code=403, detail="not allowed")

    event = await dj_service.current_event(session)
    if event is None:
        return {"status": CheckinResult.NO_EVENT}

    token = (payload.get("token") or "").strip()
    lyfe_id = (payload.get("lyfe_id") or "").strip()
    device = (payload.get("device") or "")[:64]

    if token:
        user_id = pass_token.parse(token, settings.admin_secret_key)
        if user_id is None:
            return {"status": CheckinResult.INVALID_TOKEN}
    elif lyfe_id:
        user = await attendance_service.find_by_lyfe_id(session, lyfe_id)
        if user is None:
            return {"status": CheckinResult.UNKNOWN_USER}
        user_id = user.id
    else:
        return {"status": CheckinResult.INVALID_TOKEN}

    outcome = await attendance_service.check_in(
        session, event=event, user_id=user_id, admin_id=admin.id, device=device
    )
    await session.commit()

    if outcome.status == CheckinResult.OK and outcome.tg_user_id:
        notifier.schedule_checkin_notification(
            outcome.tg_user_id, outcome.language, outcome.points
        )

    total = await attendance_service.count_checked_in(session, event_id=event.id)

    # Whatever this guest has bought is shown on the same scan. One person,
    # one device, one screen — no separate redemption flow at the door.
    pending = [
        {"id": r.id, "code": r.code, "name": r.reward.name}
        for r in await reward_service.held_by_user(
            session, user_id=user_id, event_id=event.id
        )
    ]

    return {
        "status": outcome.status,
        "lyfe_id": outcome.lyfe_id,
        "name": outcome.name,
        "points": outcome.points,
        "checked_in_at": outcome.checked_in_at,
        "total": total,
        "pending": pending,
    }


@app.post("/api/redemptions/{redemption_id}/use")
async def api_use_redemption(
    redemption_id: int,
    admin: AdminUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if admin.role not in SCAN_ROLES:
        raise HTTPException(status_code=403, detail="not allowed")

    status, redemption = await reward_service.mark_used(
        session, redemption_id=redemption_id, admin_id=admin.id
    )
    return {
        "status": status,
        "name": redemption.reward.name if redemption else None,
    }


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

MANAGE_ROLES = (AdminRole.SUPER_ADMIN, AdminRole.ADMIN)


async def require_manager(admin: AdminUser | None = Depends(current_admin)) -> AdminUser:
    if admin is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    if admin.role not in MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="not allowed")
    return admin


@app.get("/events", response_class=HTMLResponse)
async def events_page(
    request: Request,
    admin: AdminUser | None = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    edit: int | None = None,
    saved: int | None = None,
):
    if admin is None:
        return RedirectResponse("/login", status_code=303)
    if admin.role not in MANAGE_ROLES:
        return TEMPLATES.TemplateResponse(
            request, "events.html",
            {"admin": admin, "denied": True, "events": [], "venues": []},
            status_code=403,
        )

    events = await admin_event_service.list_events(session)
    venues = await admin_event_service.list_venues(session)

    editing = None
    if edit:
        editing = await session.get(Event, edit)

    # Dates are shown in each venue's own timezone, because "21:00" on a poster
    # means 21:00 in that club, not in UTC.
    from zoneinfo import ZoneInfo

    cities = await session.execute(select(City))
    zones = {}
    for city in cities.scalars():
        try:
            zones[city.id] = ZoneInfo(city.timezone)
        except Exception:  # noqa: BLE001
            zones[city.id] = ZoneInfo("Europe/Bratislava")

    def local(moment, city_id):
        return admin_event_service.local_value(
            moment, zones.get(city_id, ZoneInfo("Europe/Bratislava"))
        )

    return TEMPLATES.TemplateResponse(
        request,
        "events.html",
        {
            "admin": admin,
            "events": events,
            "venues": venues,
            "editing": editing,
            "statuses": EventStatus.ALL,
            "local": local,
            "saved": saved,
            "denied": False,
        },
    )


@app.post("/events/save")
async def events_save(
    event_id: int = Form(0),
    title: str = Form(...),
    starts_at_local: str = Form(...),
    status: str = Form(...),
    venue_id: int = Form(...),
    ticket_url: str = Form(""),
    request_hours_before: int = Form(336),
    request_hours_after: int = Form(4),
    checkin_hours_before: int = Form(2),
    checkin_hours_after: int = Form(8),
    admin: AdminUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
):
    form = admin_event_service.EventForm(
        title=title,
        starts_at_local=starts_at_local,
        status=status,
        venue_id=venue_id,
        ticket_url=ticket_url,
        request_hours_before=request_hours_before,
        request_hours_after=request_hours_after,
        checkin_hours_before=checkin_hours_before,
        checkin_hours_after=checkin_hours_after,
    )

    if event_id:
        event = await session.get(Event, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        await admin_event_service.apply_form(
            session, event=event, form=form, admin_id=admin.id
        )
    else:
        await admin_event_service.create_event(session, form=form, admin_id=admin.id)

    return RedirectResponse("/events?saved=1", status_code=303)


@app.post("/events/{event_id}/status")
async def events_status(
    event_id: int,
    status: str = Form(...),
    admin: AdminUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    await admin_event_service.set_status(
        session, event=event, status=status, admin_id=admin.id
    )
    return RedirectResponse("/events?saved=1", status_code=303)
