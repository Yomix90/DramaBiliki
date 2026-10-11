import asyncio
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from bridge.database import get_db, SessionLocal
from bridge.models import Series, Episode, Banner, SyncRun, User
from bridge.sync import SyncService

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["Admin Web Panel"])

@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    q: Optional[str] = None,
    msg: Optional[str] = None,
    db: Session = Depends(get_db),
):
    series_query = db.query(Series)
    if q:
        series_query = series_query.filter(Series.title.ilike(f"%{q}%"))

    series_list = series_query.order_by(Series.id.desc()).limit(50).all()
    banners = db.query(Banner).order_by(Banner.sort_order).all()
    sync_runs = db.query(SyncRun).order_by(SyncRun.id.desc()).limit(10).all()

    last_run = sync_runs[0] if sync_runs else None
    last_sync_status = last_run.status.capitalize() if last_run else "Aucune"
    last_sync_time = last_run.started_at.strftime("%Y-%m-%d %H:%M") if last_run and last_run.started_at else "-"

    stats = {
        "series_count": db.query(Series).count(),
        "active_series_count": db.query(Series).filter(Series.status == "active").count(),
        "episodes_count": db.query(Episode).count(),
        "users_count": db.query(User).count(),
        "last_sync_status": last_sync_status,
        "last_sync_time": last_sync_time,
    }

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "series_list": series_list,
            "banners": banners,
            "sync_runs": sync_runs,
            "stats": stats,
            "search_query": q or "",
            "message": msg or "",
        },
    )


@router.post("/series/{series_id}/toggle-status")
async def toggle_series_status(series_id: int, db: Session = Depends(get_db)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if series:
        series.status = "inactive" if series.status == "active" else "active"
        db.commit()
    return RedirectResponse(url="/admin?msg=Statut+de+la+série+mis+à+jour", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/series/{series_id}/toggle-featured")
async def toggle_series_featured(series_id: int, db: Session = Depends(get_db)):
    series = db.query(Series).filter(Series.id == series_id).first()
    if series:
        series.is_featured = not series.is_featured
        db.commit()
    return RedirectResponse(url="/admin?msg=Statut+mis+en+avant+mis+à+jour", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/series/{series_id}/edit")
async def edit_series(
    series_id: int,
    title: str = Form(...),
    description: str = Form(""),
    is_popular: Optional[str] = Form(None),
    is_new: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    series = db.query(Series).filter(Series.id == series_id).first()
    if series:
        series.title = title
        series.description = description
        series.is_popular = (is_popular == "true")
        series.is_new = (is_new == "true")
        db.commit()
    return RedirectResponse(url="/admin?msg=Série+modifiée+avec+succès", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/banners/create")
async def create_banner(
    title: str = Form(...),
    subtitle: str = Form(""),
    image_url: str = Form(...),
    target_series_id: Optional[int] = Form(None),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    banner = Banner(
        title=title,
        subtitle=subtitle,
        image_url=image_url,
        target_series_id=target_series_id,
        sort_order=sort_order,
        is_active=True,
    )
    db.add(banner)
    db.commit()
    return RedirectResponse(url="/admin?msg=Bannière+ajoutée", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/banners/{banner_id}/delete")
async def delete_banner(banner_id: int, db: Session = Depends(get_db)):
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if banner:
        db.delete(banner)
        db.commit()
    return RedirectResponse(url="/admin?msg=Bannière+supprimée", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sync/trigger")
async def trigger_sync(sync_type: str = Form("light")):
    # Run sync in background task
    async def run_in_bg():
        db = SessionLocal()
        service = SyncService(db)
        try:
            await service.run_sync(sync_type=sync_type)
        finally:
            db.close()

    asyncio.create_task(run_in_bg())
    return RedirectResponse(url="/admin?msg=Synchronisation+lancée+en+arrière-plan", status_code=status.HTTP_303_SEE_OTHER)
