import asyncio
import math
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from bridge.api.admin.security import (
    check_credentials,
    clear_failures,
    clear_session_cookie,
    client_ip,
    current_admin,
    is_locked_out,
    register_failure,
    require_admin,
    set_session_cookie,
)
from bridge.config import settings
from bridge.database import SessionLocal, get_db
from bridge.models import Banner, Episode, Favorite, Series, SyncRun, TelegramChannel, User, WatchHistory
from bridge.telegram.client import telegram_service
from bridge.telegram.sync import run_telegram_sync
from bridge.source_session import get_session_values, save_session_values, test_source
from bridge.streamer import stream_resolver
from bridge.sync import SyncService, is_sync_running

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["Admin Web Panel"])

SERIES_PER_PAGE = 30

# Keeps references to background sync tasks so they are not garbage-collected mid-run.
_background_tasks: set = set()


def _redirect(msg: str, level: str = "success", tab: str = "series", **params) -> RedirectResponse:
    query = {"msg": msg, "level": level, "tab": tab, **{k: v for k, v in params.items() if v not in (None, "")}}
    return RedirectResponse(url=f"/admin?{urllib.parse.urlencode(query)}", status_code=status.HTTP_303_SEE_OTHER)


def _start_sync(sync_type: str, target_slug: Optional[str] = None, max_pages: Optional[int] = None) -> None:
    async def run_in_bg():
        db = SessionLocal()
        try:
            await SyncService(db).run_sync(sync_type=sync_type, target_slug=target_slug, max_pages=max_pages)
        finally:
            db.close()

    task = asyncio.create_task(run_in_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    if current_admin(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": error or "",
            "locked": not settings.admin_login_allowed,
            "version": settings.APP_VERSION,
        },
    )


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = client_ip(request)
    if is_locked_out(ip):
        return RedirectResponse(url="/admin/login?error=locked", status_code=status.HTTP_303_SEE_OTHER)
    if not check_credentials(username.strip(), password):
        register_failure(ip)
        return RedirectResponse(url="/admin/login?error=invalid", status_code=status.HTTP_303_SEE_OTHER)

    clear_failures(ip)
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, request, settings.ADMIN_USERNAME)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    msg: Optional[str] = None,
    level: str = "success",
    tab: str = "",
    tg_dialogs: int = 0,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    series_query = db.query(Series)
    if q:
        like = f"%{q}%"
        series_query = series_query.filter(
            Series.title.ilike(like) | Series.slug.ilike(like) | (Series.source_id == q)
        )
    if status_filter in ("active", "inactive"):
        series_query = series_query.filter(Series.status == status_filter)
    elif status_filter == "featured":
        series_query = series_query.filter(Series.is_featured == True)  # noqa: E712

    total = series_query.count()
    pages = max(1, math.ceil(total / SERIES_PER_PAGE))
    page = min(max(1, page), pages)
    series_list = (
        series_query.order_by(Series.id.desc())
        .offset((page - 1) * SERIES_PER_PAGE)
        .limit(SERIES_PER_PAGE)
        .all()
    )

    banners = db.query(Banner).order_by(Banner.sort_order, Banner.id).all()
    sync_runs = db.query(SyncRun).order_by(SyncRun.id.desc()).limit(15).all()
    last_run = sync_runs[0] if sync_runs else None

    stats = {
        "series_count": db.query(Series).count(),
        "active_series_count": db.query(Series).filter(Series.status == "active").count(),
        "episodes_count": db.query(Episode).count(),
        "users_count": db.query(User).count(),
        "favorites_count": db.query(Favorite).count(),
        "views_count": db.query(func.count(WatchHistory.id)).scalar() or 0,
        "last_sync_status": last_run.status if last_run else "none",
        "last_sync_time": last_run.started_at.strftime("%Y-%m-%d %H:%M") if last_run and last_run.started_at else "-",
    }

    tg_status = await telegram_service.status()
    tg_channels = db.query(TelegramChannel).order_by(TelegramChannel.id).all()
    tab = tab or ("series" if tg_channels else "telegram")
    linked_ids = {c.peer_id for c in tg_channels}
    tg_available = []
    if tg_dialogs and tg_status["authorized"]:
        try:
            tg_available = [c for c in await telegram_service.list_channels() if c["peer_id"] not in linked_ids]
        except Exception as e:
            tg_status["error"] = str(e)

    warnings = []
    if settings.admin_password_is_default:
        warnings.append("Le mot de passe admin par défaut est utilisé : définissez ADMIN_PASSWORD dans les variables d'environnement.")
    if not settings.PUBLIC_BASE_URL:
        warnings.append("PUBLIC_BASE_URL n'est pas défini : les URLs sont déduites de la requête (OK derrière Traefik/Dokploy).")

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "admin": admin,
            "series_list": series_list,
            "banners": banners,
            "sync_runs": sync_runs,
            "stats": stats,
            "search_query": q or "",
            "status_filter": status_filter or "",
            "page": page,
            "pages": pages,
            "total": total,
            "message": msg or "",
            "level": level if level in ("success", "warning", "danger", "info") else "info",
            "tab": tab,
            "sync_running": is_sync_running(),
            "warnings": warnings,
            "version": settings.APP_VERSION,
            "settings": settings,
            "tg": tg_status,
            "tg_channels": tg_channels,
            "tg_available": tg_available,
            "tg_dialogs": bool(tg_dialogs),
            "source_cookies": get_session_values()[0],
            "source_user_agent": get_session_values()[1],
        },
    )


@router.get("/api/status")
async def admin_status(db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    """Polled by the dashboard while a sync runs."""
    last_run = db.query(SyncRun).order_by(SyncRun.id.desc()).first()
    return JSONResponse({
        "sync_running": is_sync_running(),
        "last_run": None if not last_run else {
            "id": last_run.id,
            "type": last_run.sync_type,
            "status": last_run.status,
            "series_discovered": last_run.series_discovered,
            "series_updated": last_run.series_updated,
            "episodes_synced": last_run.episodes_synced,
            "errors_count": last_run.errors_count,
        },
        "series_count": db.query(Series).count(),
    })


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

@router.post("/series/{series_id}/toggle-status")
async def toggle_series_status(series_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        return _redirect("Série introuvable", "danger")
    series.status = "inactive" if series.status == "active" else "active"
    db.commit()
    return _redirect(f"« {series.title} » est maintenant {'visible' if series.status == 'active' else 'masquée'}")


@router.post("/series/{series_id}/toggle-featured")
async def toggle_series_featured(series_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        return _redirect("Série introuvable", "danger")
    series.is_featured = not series.is_featured
    db.commit()
    return _redirect(f"« {series.title} » {'mise en avant' if series.is_featured else 'retirée de la une'}")


@router.post("/series/{series_id}/resync")
async def resync_series(series_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        return _redirect("Série introuvable", "danger")
    if is_sync_running():
        return _redirect("Une synchronisation est déjà en cours", "warning")
    _start_sync("single", target_slug=series.slug)
    return _redirect(f"Resynchronisation de « {series.title} » lancée", "info", tab="sync")


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------

@router.post("/banners/create")
async def create_banner(
    title: str = Form(...),
    subtitle: str = Form(""),
    image_url: str = Form(""),
    target_series_id: str = Form(""),
    sort_order: str = Form("0"),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    series = None
    if target_series_id.strip().isdigit():
        series = db.query(Series).filter(Series.id == int(target_series_id)).first()
        if not series:
            return _redirect("La série cible n'existe pas", "danger", tab="banners")

    # Default to the series cover when no image is given.
    image = image_url.strip()
    if not image and series is not None:
        image = f"/media/covers/{series.local_cover}" if series.local_cover else series.cover_url
    if not image:
        return _redirect("Une image ou une série cible est requise", "danger", tab="banners")

    banner = Banner(
        title=title.strip(),
        subtitle=subtitle.strip(),
        image_url=image,
        target_series_id=series.id if series else None,
        sort_order=int(sort_order) if sort_order.strip().lstrip("-").isdigit() else 0,
        is_active=True,
    )
    db.add(banner)
    db.commit()
    return _redirect("Bannière ajoutée", tab="banners")


@router.post("/banners/{banner_id}/toggle")
async def toggle_banner(banner_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if not banner:
        return _redirect("Bannière introuvable", "danger", tab="banners")
    banner.is_active = not banner.is_active
    db.commit()
    return _redirect(f"Bannière {'activée' if banner.is_active else 'désactivée'}", tab="banners")


@router.post("/banners/{banner_id}/delete")
async def delete_banner(banner_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if banner:
        db.delete(banner)
        db.commit()
    return _redirect("Bannière supprimée", tab="banners")


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sync/trigger")
async def trigger_sync(
    sync_type: str = Form("light"),
    slug: str = Form(""),
    admin: str = Depends(require_admin),
):
    if is_sync_running():
        return _redirect("Une synchronisation est déjà en cours", "warning", tab="sync")

    slug = slug.strip().strip("/").split("/")[-1]
    if sync_type == "single":
        if not slug:
            return _redirect("Indiquez le slug de la série", "danger", tab="sync")
        _start_sync("single", target_slug=slug)
        return _redirect(f"Synchronisation de « {slug} » lancée", "info", tab="sync")

    if sync_type not in ("light", "full"):
        sync_type = "light"
    _start_sync(sync_type)
    return _redirect(f"Synchronisation {'complète' if sync_type == 'full' else 'légère'} lancée en arrière-plan", "info", tab="sync")


# ---------------------------------------------------------------------------
# Source session (browser cookies)
# ---------------------------------------------------------------------------

@router.post("/source/session")
async def save_source_session(
    cookies: str = Form(""),
    user_agent: str = Form(""),
    admin: str = Depends(require_admin),
):
    save_session_values(cookies, user_agent)
    await stream_resolver.reset_session()
    code, summary = await test_source()
    level = "success" if code == 200 else "danger"
    return _redirect(f"Session enregistrée. Test de la source : {summary}", level, tab="config")


@router.post("/source/test")
async def test_source_session(admin: str = Depends(require_admin)):
    code, summary = await test_source()
    return _redirect(f"Test de la source : {summary}", "success" if code == 200 else "danger", tab="config")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _tg_redirect(msg: str, level: str = "success", **params) -> RedirectResponse:
    return _redirect(msg, level, tab="telegram", **params)


def _tg_error(e: Exception) -> str:
    name = type(e).__name__
    known = {
        "PhoneNumberInvalidError": "Numéro de téléphone invalide (format international, ex. +33612345678).",
        "PhoneCodeInvalidError": "Code incorrect.",
        "PhoneCodeExpiredError": "Code expiré : demandez-en un nouveau.",
        "PasswordHashInvalidError": "Mot de passe 2FA incorrect.",
        "ApiIdInvalidError": "API ID / API hash invalides (vérifiez sur my.telegram.org).",
        "FloodWaitError": f"Telegram limite les tentatives : réessayez dans {getattr(e, 'seconds', '?')} s.",
        "UsernameNotOccupiedError": "Ce nom de chaîne n'existe pas.",
        "ChannelPrivateError": "Chaîne privée : le compte doit d'abord la rejoindre.",
    }
    return known.get(name, f"{name}: {e}")


def _start_telegram_sync(channel_id: Optional[int], full: bool = False) -> None:
    task = asyncio.create_task(run_telegram_sync(channel_id, full=full))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/telegram/credentials")
async def tg_credentials(api_id: str = Form(...), api_hash: str = Form(...), admin: str = Depends(require_admin)):
    if not api_id.strip().isdigit() or len(api_hash.strip()) < 16:
        return _tg_redirect("API ID (nombre) ou API hash invalide.", "danger")
    telegram_service.save_credentials(api_id, api_hash)
    await telegram_service.reset()
    return _tg_redirect("Identifiants API enregistrés. Connectez maintenant votre compte.")


@router.post("/telegram/send-code")
async def tg_send_code(phone: str = Form(...), admin: str = Depends(require_admin)):
    phone = phone.strip().replace(" ", "")
    try:
        await telegram_service.send_code(phone)
    except Exception as e:
        return _tg_redirect(_tg_error(e), "danger")
    return _tg_redirect(f"Code envoyé à {phone} (dans l'app Telegram ou par SMS).", "info")


@router.post("/telegram/sign-in")
async def tg_sign_in(code: str = Form(""), password: str = Form(""), admin: str = Depends(require_admin)):
    from telethon import errors as tg_errors
    try:
        await telegram_service.sign_in(code=code, password=password)
    except tg_errors.SessionPasswordNeededError:
        return _tg_redirect("Ce compte a la validation en deux étapes : entrez votre mot de passe Telegram.", "warning")
    except Exception as e:
        return _tg_redirect(_tg_error(e), "danger")
    return _tg_redirect("Compte Telegram connecté. Ajoutez maintenant vos chaînes.", tg_dialogs=1)


@router.post("/telegram/logout")
async def tg_logout(admin: str = Depends(require_admin)):
    await telegram_service.log_out()
    return _tg_redirect("Compte Telegram déconnecté.", "info")


@router.post("/telegram/channels/add")
async def tg_add_channel(
    ref: str = Form(...),
    mode: str = Form("caption"),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    from telethon import utils as tg_utils
    try:
        entity = await telegram_service.resolve_channel(ref)
    except Exception as e:
        return _tg_redirect(_tg_error(e), "danger", tg_dialogs=1)

    peer_id = tg_utils.get_peer_id(entity)
    channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == peer_id).first()
    if channel is None:
        channel = TelegramChannel(peer_id=peer_id)
        db.add(channel)
    channel.access_hash = entity.access_hash
    channel.title = entity.title or ""
    channel.username = entity.username or ""
    channel.mode = mode if mode in ("caption", "single") else "caption"
    channel.enabled = True
    db.commit()

    if not is_sync_running():
        _start_telegram_sync(channel.id)
        return _tg_redirect(f"Chaîne « {channel.title} » ajoutée : import des vidéos en cours…", "info")
    return _tg_redirect(f"Chaîne « {channel.title} » ajoutée : elle sera importée à la prochaine synchro.")


@router.post("/telegram/channels/{channel_id}/mode")
async def tg_channel_mode(channel_id: int, mode: str = Form(...), db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    channel = db.get(TelegramChannel, channel_id)
    if channel:
        channel.mode = mode if mode in ("caption", "single") else "caption"
        db.commit()
    return _tg_redirect("Mode mis à jour (appliqué aux prochaines vidéos ; « Réimporter » pour tout reclasser).")


@router.post("/telegram/channels/{channel_id}/toggle")
async def tg_channel_toggle(channel_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    channel = db.get(TelegramChannel, channel_id)
    if not channel:
        return _tg_redirect("Chaîne introuvable.", "danger")
    channel.enabled = not channel.enabled
    db.query(Series).filter(Series.tg_channel_id == channel.id).update(
        {Series.status: "active" if channel.enabled else "inactive"}, synchronize_session=False
    )
    db.commit()
    return _tg_redirect("Chaîne activée" if channel.enabled else "Chaîne désactivée (ses séries sont masquées)")


@router.post("/telegram/channels/{channel_id}/sync")
async def tg_channel_sync(channel_id: int, admin: str = Depends(require_admin)):
    if is_sync_running():
        return _tg_redirect("Une synchronisation est déjà en cours.", "warning")
    _start_telegram_sync(channel_id)
    return _tg_redirect("Synchronisation de la chaîne lancée.", "info")


@router.post("/telegram/channels/{channel_id}/reimport")
async def tg_channel_reimport(channel_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    """Deletes the channel's series/episodes and imports everything again (after a mode change)."""
    if is_sync_running():
        return _tg_redirect("Une synchronisation est déjà en cours.", "warning")
    channel = db.get(TelegramChannel, channel_id)
    if not channel:
        return _tg_redirect("Chaîne introuvable.", "danger")
    for series in db.query(Series).filter(Series.tg_channel_id == channel.id).all():
        db.delete(series)
    channel.last_message_id = 0
    channel.videos_count = 0
    db.commit()
    _start_telegram_sync(channel_id, full=True)
    return _tg_redirect(f"Réimport complet de « {channel.title} » lancé.", "info")


@router.post("/telegram/channels/{channel_id}/delete")
async def tg_channel_delete(
    channel_id: int,
    delete_series: str = Form(""),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    channel = db.get(TelegramChannel, channel_id)
    if channel:
        if delete_series == "1":
            for series in db.query(Series).filter(Series.tg_channel_id == channel.id).all():
                db.delete(series)
        db.delete(channel)
        db.commit()
    return _tg_redirect("Chaîne retirée.")


@router.post("/telegram/sync")
async def tg_sync_all(admin: str = Depends(require_admin)):
    if is_sync_running():
        return _tg_redirect("Une synchronisation est déjà en cours.", "warning")
    _start_telegram_sync(None)
    return _tg_redirect("Synchronisation de toutes les chaînes lancée.", "info")
