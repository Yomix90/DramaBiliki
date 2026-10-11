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
from bridge.models import Banner, Episode, Favorite, Series, SyncRun, User, WatchHistory
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
    tab: str = "series",
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


@router.post("/series/{series_id}/edit")
async def edit_series(
    series_id: int,
    title: str = Form(...),
    description: str = Form(""),
    title_fr: str = Form(""),
    title_ar: str = Form(""),
    platform: str = Form(""),
    rating: str = Form(""),
    is_popular: Optional[str] = Form(None),
    is_new: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        return _redirect("Série introuvable", "danger")

    series.title = title.strip() or series.title
    series.description = description
    titles = dict(series.titles_json or {})
    titles["en"] = series.title
    for lang, value in (("fr", title_fr), ("ar", title_ar)):
        if value.strip():
            titles[lang] = value.strip()
        else:
            titles.pop(lang, None)
    series.titles_json = titles
    descriptions = dict(series.descriptions_json or {})
    descriptions["en"] = description
    series.descriptions_json = descriptions
    series.platform = platform.strip()
    try:
        series.rating = max(0.0, min(5.0, float(rating.replace(",", "."))))
    except ValueError:
        pass
    series.is_popular = is_popular == "true"
    series.is_new = is_new == "true"
    db.commit()
    return _redirect(f"« {series.title} » modifiée")


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
