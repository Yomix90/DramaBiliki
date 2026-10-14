"""
Admin pages for content managed by hand: series (with cover upload), episodes,
batch video uploads, user accounts, mobile app updates and rewarded ads.
"""
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from bridge import app_settings, uploads
from bridge.api.admin.security import require_admin
from bridge.api.v1.routes_app import APK_DIR, LATEST_APK
from bridge.config import settings
from bridge.database import get_db
from bridge.media import save_cover_image
from bridge.models import Episode, Favorite, Genre, Series, TelegramChannel, User, WatchHistory
from bridge.telegram.client import telegram_service
from bridge.video_check import HEADER_BYTES, check_header
from bridge.video_tools import ffmpeg_available

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["Admin Web Panel"])

MAX_COVER_BYTES = 8 * 1024 * 1024


def _back(url: str, msg: str, level: str = "success") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    from urllib.parse import quote
    return RedirectResponse(f"{url}{sep}msg={quote(msg)}&level={level}", status_code=status.HTTP_303_SEE_OTHER)


def _page(request: Request, name: str, **context) -> HTMLResponse:
    context.setdefault("msg", request.query_params.get("msg", ""))
    level = request.query_params.get("level", "success")
    context.setdefault("level", level if level in ("success", "info", "warning", "danger") else "info")
    context.setdefault("version", settings.APP_VERSION)
    return templates.TemplateResponse(request=request, name=name, context=context)


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def _genres_from_text(db: Session, text: str):
    genres = []
    for name in [n.strip() for n in (text or "").split(",") if n.strip()][:8]:
        slug = re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-")[:60]
        if not slug:
            continue
        genre = db.query(Genre).filter_by(slug=slug).first()
        if genre is None:
            genre = Genre(slug=slug, name=name[:64], names_json={"en": name[:64]})
            db.add(genre)
            db.flush()
        genres.append(genre)
    return genres


async def _apply_cover(series: Series, cover: Optional[UploadFile], cover_url: str) -> Optional[str]:
    """Saves an uploaded cover (or remembers a URL). Returns an error message, if any."""
    if cover is not None and cover.filename:
        data = await cover.read(MAX_COVER_BYTES + 1)
        if len(data) > MAX_COVER_BYTES:
            return "Image trop lourde (8 Mo maximum)"
        name = save_cover_image(series.source_id, data)
        if not name:
            return "Image illisible (JPG, PNG ou WEBP)"
        series.local_cover = name
    elif cover_url.strip():
        series.cover_url = cover_url.strip()
        series.local_cover = ""
    return None


def _apply_series_form(db: Session, series: Series, form: dict) -> None:
    title = form["title"].strip() or series.title
    series.title = title
    series.titles_json = {k: v for k, v in {"en": title, "fr": form["title_fr"].strip(), "ar": form["title_ar"].strip()}.items() if v}
    series.description = form["description"]
    series.descriptions_json = {k: v for k, v in {"en": form["description"], "fr": form["description_fr"], "ar": form["description_ar"]}.items() if v.strip()}
    series.platform = form["platform"].strip()[:64]
    try:
        series.rating = max(0.0, min(5.0, float((form["rating"] or "4.8").replace(",", "."))))
    except ValueError:
        pass
    year = form["release_year"].strip()
    series.release_year = int(year) if year.isdigit() else None
    series.status = "active" if form["status"] != "inactive" else "inactive"
    series.is_popular = form["is_popular"] == "true"
    series.is_new = form["is_new"] == "true"
    series.is_featured = form["is_featured"] == "true"
    series.genres = _genres_from_text(db, form["genres"])


def _series_form(
    title: str = Form(...),
    title_fr: str = Form(""),
    title_ar: str = Form(""),
    description: str = Form(""),
    description_fr: str = Form(""),
    description_ar: str = Form(""),
    genres: str = Form(""),
    platform: str = Form(""),
    rating: str = Form("4.8"),
    release_year: str = Form(""),
    status_value: str = Form("active", alias="status"),
    is_popular: Optional[str] = Form(None),
    is_new: Optional[str] = Form(None),
    is_featured: Optional[str] = Form(None),
    cover_url: str = Form(""),
) -> dict:
    return {
        "title": title, "title_fr": title_fr, "title_ar": title_ar,
        "description": description, "description_fr": description_fr, "description_ar": description_ar,
        "genres": genres, "platform": platform, "rating": rating, "release_year": release_year,
        "status": status_value, "is_popular": is_popular, "is_new": is_new, "is_featured": is_featured,
        "cover_url": cover_url,
    }


@router.get("/series/new", response_class=HTMLResponse)
async def new_series_page(request: Request, admin: str = Depends(require_admin)):
    return _page(request, "series_form.html", series=None, episodes=[], admin=admin)


@router.post("/series/new")
async def create_series(
    form: dict = Depends(_series_form),
    cover: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    if not form["title"].strip():
        return _back("/admin/series/new", "Le titre est obligatoire", "danger")
    series = uploads.create_series(db, form["title"].strip())
    _apply_series_form(db, series, form)
    error = await _apply_cover(series, cover, form["cover_url"])
    db.commit()
    return _back(f"/admin/series/{series.id}", error or "Série créée. Ajoutez maintenant ses épisodes.", "warning" if error else "success")


async def _episode_problem(db: Session, episode: Episode) -> Optional[str]:
    """Reads the first bytes of an episode (VPS file or Telegram) to spot unplayable videos."""
    local = uploads.local_video_path(episode)
    if local is not None:
        if not local.is_file():
            return "Fichier absent du serveur"
        with open(local, "rb") as fh:
            return check_header(fh.read(HEADER_BYTES))
    if episode.tg_message_id:
        channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == episode.tg_peer_id).first()
        try:
            message = await telegram_service.get_message(episode.tg_peer_id, channel.access_hash if channel else None, episode.tg_message_id)
            head = b""
            async for chunk in telegram_service.iter_bytes(message, 0, HEADER_BYTES - 1):
                head += chunk
            return check_header(head)
        except FileNotFoundError:
            return "Vidéo supprimée de la chaîne Telegram"
        except Exception as e:
            return f"Telegram indisponible ({type(e).__name__})"
    return None


@router.get("/series/{series_id}", response_class=HTMLResponse)
async def series_page(series_id: int, request: Request, check: int = 0, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    episodes = db.query(Episode).filter(Episode.series_id == series_id).order_by(Episode.num).all()
    problems = {}
    if check:
        for episode in episodes:
            problem = await _episode_problem(db, episode)
            if problem:
                problems[episode.id] = problem
    return _page(request, "series_form.html", series=series, episodes=episodes, admin=admin,
                 genres_text=", ".join(g.name for g in series.genres), checked=bool(check), problems=problems)


async def _remove_episodes(db: Session, episodes, delete_telegram: bool):
    """Deletes episodes (local files, and their Telegram messages when asked). Returns (count, telegram_note)."""
    by_peer = {}
    for episode in episodes:
        uploads.remove_local_video(episode)
        if delete_telegram and episode.tg_peer_id and episode.tg_message_id:
            by_peer.setdefault(episode.tg_peer_id, []).append(episode.tg_message_id)
        db.delete(episode)
    note, total = "", 0
    for peer_id, message_ids in by_peer.items():
        channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == peer_id).first()
        deleted, error = await telegram_service.delete_messages(peer_id, channel.access_hash if channel else None, message_ids)
        total += deleted
        if error:
            note = error
    if by_peer:
        note = note or f"{total} vidéo(s) supprimée(s) de Telegram"
    return len(episodes), note


@router.post("/series/{series_id}/delete-episodes")
async def delete_episodes(series_id: int, request: Request, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    form = await request.form()
    ids = [int(v) for v in form.getlist("episode_id") if str(v).isdigit()]
    episodes = db.query(Episode).filter(Episode.series_id == series_id, Episode.id.in_(ids)).all()
    if not episodes:
        return _back(f"/admin/series/{series_id}", "Aucun épisode sélectionné", "warning")
    removed, note = await _remove_episodes(db, episodes, form.get("delete_telegram") == "1")
    db.flush()
    uploads.refresh_series_counts(db, series_id)
    db.commit()
    return _back(f"/admin/series/{series_id}", f"{removed} épisode(s) supprimé(s)" + (f" — {note}" if note else ""))


@router.post("/series/{series_id}/save")
async def save_series(
    series_id: int,
    form: dict = Depends(_series_form),
    cover: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    _apply_series_form(db, series, form)
    error = await _apply_cover(series, cover, form["cover_url"])
    db.commit()
    return _back(f"/admin/series/{series_id}", error or "Série enregistrée", "warning" if error else "success")


@router.post("/series/{series_id}/delete")
async def delete_series(
    series_id: int,
    delete_telegram: str = Form(""),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    series = db.get(Series, series_id)
    if series is None:
        return _back("/admin?tab=series", "Série introuvable", "danger")
    title = series.title
    _, note = await _remove_episodes(db, list(series.episodes), delete_telegram == "1")
    db.delete(series)
    db.commit()
    return _back("/admin?tab=series", f"Série « {title} » supprimée" + (f" — {note}" if note else ""))


@router.post("/episodes/{episode_id}/delete")
async def delete_episode(
    episode_id: int,
    delete_telegram: str = Form(""),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    episode = db.get(Episode, episode_id)
    if episode is None:
        return _back("/admin?tab=series", "Épisode introuvable", "danger")
    series_id = episode.series_id
    _, note = await _remove_episodes(db, [episode], delete_telegram == "1")
    db.flush()
    uploads.refresh_series_counts(db, series_id)
    db.commit()
    return _back(f"/admin/series/{series_id}", "Épisode supprimé" + (f" — {note}" if note else ""))


@router.post("/episodes/{episode_id}/number")
async def renumber_episode(episode_id: int, num: int = Form(...), db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        return _back("/admin?tab=series", "Épisode introuvable", "danger")
    clash = db.query(Episode).filter(Episode.series_id == episode.series_id, Episode.num == num, Episode.id != episode.id).first()
    if clash:
        clash.num, episode.num = episode.num, num  # swap
    else:
        episode.num = num
    episode.title = f"Episode {episode.num}"
    episode.titles_json = {"en": f"Episode {episode.num}", "fr": f"Épisode {episode.num}", "ar": f"الحلقة {episode.num}"}
    if clash:
        clash.title = f"Episode {clash.num}"
        clash.titles_json = {"en": f"Episode {clash.num}", "fr": f"Épisode {clash.num}", "ar": f"الحلقة {clash.num}"}
    db.commit()
    return _back(f"/admin/series/{episode.series_id}", "Numéro modifié")


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, series_id: Optional[int] = None, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    tg = await telegram_service.status()
    channels = db.query(TelegramChannel).order_by(TelegramChannel.title).all()
    series = db.get(Series, series_id) if series_id else None
    all_series = db.query(Series.id, Series.title).order_by(Series.title).limit(2000).all()
    return _page(
        request, "upload.html", admin=admin, tg=tg, channels=channels, target_series=series,
        all_series=all_series, cfg=app_settings.get_all(), ffmpeg=ffmpeg_available(),
        free_gb=round(shutil.disk_usage(settings.MEDIA_DIR).free / 1024 ** 3, 1),
    )


@router.post("/upload/settings")
async def upload_settings(
    destination: str = Form("telegram"),
    channel_id: str = Form(""),
    convert_ts: Optional[str] = Form(None),
    admin: str = Depends(require_admin),
):
    app_settings.set_many({
        "upload_destination": destination if destination in ("telegram", "local") else "telegram",
        "upload_channel_id": channel_id if channel_id.isdigit() else "",
        "upload_convert_ts": "true" if convert_ts == "true" else "false",
    })
    return _back("/admin/upload", "Réglages de téléversement enregistrés")


@router.post("/uploads/detect")
async def uploads_detect(request: Request, admin: str = Depends(require_admin)):
    payload = await request.json()
    names = [str(n) for n in (payload.get("filenames") or [])][:500]
    return JSONResponse([uploads.detect(n) for n in names])


@router.post("/uploads/init")
async def uploads_init(request: Request, admin: str = Depends(require_admin)):
    payload = await request.json()
    try:
        job = uploads.create_job(
            filename=str(payload.get("filename", "")),
            size=int(payload.get("size", 0)),
            mode=str(payload.get("mode", "auto")),
            series_id=int(payload["series_id"]) if str(payload.get("series_id") or "").isdigit() else None,
            episode=int(payload["episode"]) if str(payload.get("episode") or "").isdigit() else None,
            title=str(payload.get("title") or ""),
            meta_id=str(payload.get("meta_id") or ""),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"id": job.id})


@router.put("/uploads/{job_id}")
async def uploads_chunk(job_id: str, request: Request, offset: int = 0, admin: str = Depends(require_admin)):
    job = uploads.get_job(job_id)
    if job is None:
        return JSONResponse({"error": "Téléversement inconnu"}, status_code=404)
    data = await request.body()
    try:
        await uploads.write_chunk(job, offset, data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"received": job.received})


@router.post("/uploads/{job_id}/complete")
async def uploads_complete(job_id: str, admin: str = Depends(require_admin)):
    job = uploads.get_job(job_id)
    if job is None:
        return JSONResponse({"error": "Téléversement inconnu"}, status_code=404)
    try:
        uploads.complete_job(job)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(job.public())


@router.delete("/uploads/{job_id}")
async def uploads_cancel(job_id: str, admin: str = Depends(require_admin)):
    job = uploads.get_job(job_id)
    if job is not None:
        uploads.cancel_job(job)
    return JSONResponse({"ok": True})


@router.get("/uploads/jobs")
async def uploads_jobs(admin: str = Depends(require_admin)):
    return JSONResponse(uploads.list_jobs())


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, q: str = "", kind: str = "accounts", page: int = 1,
                     db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    query = db.query(User)
    if kind == "accounts":
        query = query.filter(User.email.isnot(None))
    elif kind == "guests":
        query = query.filter(User.email.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.email.ilike(like), User.username.ilike(like)))
    total = query.count()
    per_page = 50
    page = max(1, page)
    users = query.order_by(User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    ids = [u.id for u in users]
    fav_counts = dict(db.query(Favorite.user_id, func.count(Favorite.id)).filter(Favorite.user_id.in_(ids)).group_by(Favorite.user_id).all()) if ids else {}
    watch_counts = dict(db.query(WatchHistory.user_id, func.count(WatchHistory.id)).filter(WatchHistory.user_id.in_(ids)).group_by(WatchHistory.user_id).all()) if ids else {}
    stats = {
        "accounts": db.query(User).filter(User.email.isnot(None)).count(),
        "guests": db.query(User).filter(User.email.is_(None)).count(),
        "banned": db.query(User).filter(User.is_active == False).count(),  # noqa: E712
        "ads_free": db.query(User).filter(User.ads_free == True).count(),  # noqa: E712
    }
    return _page(request, "users.html", admin=admin, users=users, total=total, page=page,
                 pages=max(1, -(-total // per_page)), q=q, kind=kind, stats=stats,
                 fav_counts=fav_counts, watch_counts=watch_counts)


@router.post("/users/{user_id}/toggle")
async def users_toggle(user_id: int, field: str = Form(...), db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    user = db.get(User, user_id)
    if user and field in ("is_active", "ads_free"):
        setattr(user, field, not bool(getattr(user, field)))
        db.commit()
    return _back("/admin/users", "Utilisateur mis à jour")


@router.post("/users/{user_id}/delete")
async def users_delete(user_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    user = db.get(User, user_id)
    if user:
        db.delete(user)
        db.commit()
    return _back("/admin/users", "Utilisateur supprimé")


# ---------------------------------------------------------------------------
# Mobile app: updates & ads
# ---------------------------------------------------------------------------

@router.get("/app", response_class=HTMLResponse)
async def app_page(request: Request, admin: str = Depends(require_admin)):
    return _page(request, "app_settings.html", admin=admin, cfg=app_settings.get_all(), apk=_published_apk())


def _published_apk() -> Optional[dict]:
    """Size, date and fingerprint of the APK currently served to the apps."""
    import datetime
    import hashlib
    if not LATEST_APK.is_file():
        return None
    stat = LATEST_APK.stat()
    digest = hashlib.sha256()
    with open(LATEST_APK, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "size_mb": round(stat.st_size / 1024 ** 2, 1),
        "uploaded_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        "sha": digest.hexdigest()[:12],
    }


# Chunked APK upload: a single 60 MB request exceeds the reverse proxy timeout
# (Traefik cuts requests after 60 s -> "Bad Gateway").
_apk_uploads: dict = {}


@router.post("/app/apk/init")
async def apk_upload_init(request: Request, admin: str = Depends(require_admin)):
    payload = await request.json()
    size = int(payload.get("size") or 0)
    if size < 1024 or size > 500 * 1024 * 1024:
        return JSONResponse({"error": "Taille d'APK invalide"}, status_code=400)
    APK_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    part = APK_DIR / f"upload-{upload_id}.part"
    part.touch()
    _apk_uploads[upload_id] = {"size": size, "chunks": {}, "path": part}
    return JSONResponse({"id": upload_id})


@router.put("/app/apk/{upload_id}")
async def apk_upload_chunk(upload_id: str, request: Request, offset: int = 0, admin: str = Depends(require_admin)):
    import asyncio
    up = _apk_uploads.get(upload_id)
    if up is None:
        return JSONResponse({"error": "Envoi inconnu"}, status_code=404)
    data = await request.body()
    if offset < 0 or offset + len(data) > up["size"]:
        return JSONResponse({"error": "Morceau hors limites"}, status_code=400)

    def _write():
        with open(up["path"], "r+b") as fh:
            fh.seek(offset)
            fh.write(data)

    await asyncio.to_thread(_write)
    up["chunks"][offset] = len(data)
    return JSONResponse({"received": sum(up["chunks"].values())})


@router.post("/app/apk/{upload_id}/complete")
async def apk_upload_complete(upload_id: str, admin: str = Depends(require_admin)):
    up = _apk_uploads.pop(upload_id, None)
    if up is None:
        return JSONResponse({"error": "Envoi inconnu"}, status_code=404)
    path = up["path"]
    if sum(up["chunks"].values()) < up["size"]:
        path.unlink(missing_ok=True)
        return JSONResponse({"error": "Fichier incomplet, recommencez"}, status_code=400)
    with open(path, "rb") as fh:
        is_apk = fh.read(2) == b"PK"
    if not is_apk:
        path.unlink(missing_ok=True)
        return JSONResponse({"error": "Ce fichier n'est pas un APK valide"}, status_code=400)
    path.replace(LATEST_APK)
    return JSONResponse({"ok": True, "apk": _published_apk()})


@router.post("/app/update")
async def app_update(
    latest_version: str = Form(...),
    min_version: str = Form("1.0.0"),
    notes: str = Form(""),
    force: Optional[str] = Form(None),
    update_url: str = Form(""),
    apk: Optional[UploadFile] = File(None),
    admin: str = Depends(require_admin),
):
    version_re = re.compile(r"^\d+(\.\d+){0,2}$")
    if not version_re.match(latest_version.strip()) or not version_re.match(min_version.strip()):
        return _back("/admin/app", "Version invalide (format 1.3.0)", "danger")
    message = "Réglages de mise à jour enregistrés"
    if apk is not None and apk.filename:
        if not apk.filename.lower().endswith(".apk"):
            return _back("/admin/app", "Seuls les fichiers .apk sont acceptés", "danger")
        APK_DIR.mkdir(parents=True, exist_ok=True)
        tmp = APK_DIR / f"upload-{uuid.uuid4().hex}.apk"
        with open(tmp, "wb") as fh:
            while chunk := await apk.read(4 * 1024 * 1024):
                fh.write(chunk)
        with open(tmp, "rb") as fh:
            if fh.read(2) != b"PK":
                tmp.unlink(missing_ok=True)
                return _back("/admin/app", "Ce fichier n'est pas un APK valide", "danger")
        tmp.replace(LATEST_APK)
        message = f"APK {latest_version} publié"
    app_settings.set_many({
        "app_latest_version": latest_version.strip(),
        "app_min_version": min_version.strip(),
        "app_update_notes": notes.strip(),
        "app_update_force": "true" if force == "true" else "false",
        "app_update_url": update_url.strip(),
    })
    return _back("/admin/app", message)


@router.post("/app/ads")
async def app_ads(
    enabled: Optional[str] = Form(None),
    every_n: int = Form(5),
    unit_id: str = Form(""),
    admin: str = Depends(require_admin),
):
    app_settings.set_many({
        "ads_enabled": "true" if enabled == "true" else "false",
        "ads_every_n_episodes": str(max(1, min(50, every_n))),
        "ads_rewarded_unit_id": unit_id.strip(),
    })
    return _back("/admin/app", "Réglages publicitaires enregistrés")


# ---------------------------------------------------------------------------
# Genres (the category tabs of the app)
# ---------------------------------------------------------------------------

@router.get("/genres", response_class=HTMLResponse)
async def genres_page(request: Request, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    rows = []
    for genre in db.query(Genre).order_by(Genre.name).all():
        visible = sum(1 for s in genre.series if s.status == "active")
        rows.append({"genre": genre, "total": len(genre.series), "visible": visible})
    return _page(request, "genres.html", admin=admin, rows=rows)


@router.post("/genres/new")
async def genre_create(name: str = Form(...), db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    created = _genres_from_text(db, name)
    db.commit()
    return _back("/admin/genres", "Genre créé" if created else "Nom invalide", "success" if created else "danger")


@router.post("/genres/{genre_id}/save")
async def genre_save(
    genre_id: int,
    name: str = Form(...),
    name_fr: str = Form(""),
    name_ar: str = Form(""),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    genre = db.get(Genre, genre_id)
    if genre is None:
        return _back("/admin/genres", "Genre introuvable", "danger")
    genre.name = name.strip()[:64] or genre.name
    genre.names_json = {k: v.strip()[:64] for k, v in {"en": genre.name, "fr": name_fr, "ar": name_ar}.items() if v.strip()}
    db.commit()
    return _back("/admin/genres", f"Genre « {genre.name} » enregistré")


@router.post("/genres/{genre_id}/delete")
async def genre_delete(genre_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    genre = db.get(Genre, genre_id)
    if genre is not None:
        genre.series = []
        db.delete(genre)
        db.commit()
    return _back("/admin/genres", "Genre supprimé (les séries sont conservées)")


# ---------------------------------------------------------------------------
# Backup / restore (moving to another VPS)
# ---------------------------------------------------------------------------

@router.get("/backup", response_class=HTMLResponse)
async def backup_page(request: Request, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    from bridge import backup
    db_file = backup.sqlite_path()
    videos_dir = settings.MEDIA_DIR / "videos" / "local"
    stats = {
        "db_mb": round(db_file.stat().st_size / 1024 ** 2, 1) if db_file and db_file.exists() else None,
        "covers": len(list(settings.COVERS_DIR.glob("*.webp"))) if settings.COVERS_DIR.is_dir() else 0,
        "covers_mb": round(sum(f.stat().st_size for f in settings.COVERS_DIR.glob("*.webp")) / 1024 ** 2, 1) if settings.COVERS_DIR.is_dir() else 0,
        "videos": len([f for f in videos_dir.iterdir() if f.is_file()]) if videos_dir.is_dir() else 0,
        "videos_mb": round(sum(f.stat().st_size for f in videos_dir.iterdir() if f.is_file()) / 1024 ** 2, 1) if videos_dir.is_dir() else 0,
        "series": db.query(Series).count(),
        "users": db.query(User).count(),
        "sqlite": db_file is not None,
    }
    previous = sorted((settings.DATA_DIR / "backups").glob("before-restore-*.db"), reverse=True)[:5] if (settings.DATA_DIR / "backups").is_dir() else []
    return _page(request, "backup.html", admin=admin, stats=stats, previous=[p.name for p in previous])


@router.get("/backup/download")
async def backup_download(covers: int = 0, videos: int = 0, admin: str = Depends(require_admin)):
    import asyncio
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    from bridge import backup
    try:
        archive = await asyncio.to_thread(backup.create_backup, bool(covers), bool(videos))
    except backup.BackupError as e:
        return _back("/admin/backup", str(e), "danger")
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=archive.name,
        background=BackgroundTask(lambda: shutil.rmtree(archive.parent, ignore_errors=True)),
    )


@router.post("/backup/restore")
async def backup_restore(
    file: UploadFile = File(...),
    confirm: Optional[str] = Form(None),
    admin: str = Depends(require_admin),
):
    import asyncio
    import tempfile
    from bridge import backup
    from bridge.database import SessionLocal
    from bridge.sync import is_sync_running, mark_interrupted_runs

    if confirm != "yes":
        return _back("/admin/backup", "Cochez la case de confirmation pour remplacer les données.", "warning")
    if is_sync_running():
        return _back("/admin/backup", "Une synchronisation est en cours : réessayez dans un instant.", "warning")
    if not file.filename:
        return _back("/admin/backup", "Choisissez un fichier de sauvegarde (.zip ou .db).", "danger")

    tmp = Path(tempfile.mkdtemp(prefix="dramabiliki-upload-")) / "upload.bin"
    try:
        with open(tmp, "wb") as fh:
            while chunk := await file.read(8 * 1024 * 1024):
                fh.write(chunk)
        await telegram_service.close()
        summary = await asyncio.to_thread(backup.restore_backup, tmp)
    except backup.BackupError as e:
        return _back("/admin/backup", f"Restauration refusée : {e}", "danger")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)

    db = SessionLocal()
    try:
        mark_interrupted_runs(db)
    finally:
        db.close()
    app_settings.set_many({})  # drop cached settings
    c = summary["counts"]
    response = _back(
        "/admin/backup",
        f"Restauration terminée : {c.get('series', 0)} séries, {c.get('episodes', 0)} épisodes, "
        f"{c.get('users', 0)} utilisateurs, {summary['covers']} affiches, {summary['videos']} vidéos."
        + (" Reconnectez-vous à l'admin." if summary["secret_restored"] else ""),
    )
    return response


# ---------------------------------------------------------------------------
# Series information files (title, synopsis, genres...) sent with the episodes
# ---------------------------------------------------------------------------

@router.post("/metadata/parse")
async def metadata_parse(file: UploadFile = File(...), admin: str = Depends(require_admin)):
    """Reads an info file and returns its fields (used to pre-fill the series form)."""
    from bridge.metadata import parse_metadata
    try:
        meta = parse_metadata(file.filename or "", await file.read(512 * 1024 + 1))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(meta)


@router.post("/uploads/metadata")
async def uploads_metadata(
    file: UploadFile = File(...),
    cover: Optional[UploadFile] = File(None),
    admin: str = Depends(require_admin),
):
    """Registers the info file (and optional poster) of an upload batch."""
    from bridge.metadata import parse_metadata
    try:
        meta = parse_metadata(file.filename or "", await file.read(512 * 1024 + 1))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from bridge.metadata import download_cover
    cover_bytes, cover_source = None, ""
    if cover is not None and cover.filename:
        cover_bytes = await cover.read(MAX_COVER_BYTES + 1)
        if len(cover_bytes) > MAX_COVER_BYTES:
            return JSONResponse({"error": "Affiche trop lourde (8 Mo maximum)"}, status_code=400)
        cover_source = cover.filename
    elif meta.get("cover_url"):
        cover_bytes = await download_cover(str(meta["cover_url"]))
        cover_source = "téléchargée depuis « Couverture »" if cover_bytes else ""
    return JSONResponse({
        "id": uploads.register_metadata(meta, cover_bytes),
        "meta": meta,
        "has_cover": bool(cover_bytes),
        "cover_source": cover_source,
        "cover_url_failed": bool(meta.get("cover_url") and not cover_bytes),
    })


@router.post("/series/{series_id}/metadata")
async def series_metadata(
    series_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Applies an info file directly to an existing series."""
    from bridge.metadata import apply_metadata, parse_metadata
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    try:
        meta = parse_metadata(file.filename or "", await file.read(512 * 1024 + 1))
    except ValueError as e:
        return _back(f"/admin/series/{series_id}", str(e), "danger")
    apply_metadata(db, series, meta)
    if meta.get("cover_url"):
        from bridge.metadata import download_cover
        data = await download_cover(str(meta["cover_url"]))
        name = save_cover_image(series.source_id, data) if data else None
        if name:
            series.local_cover = name
    db.commit()
    return _back(f"/admin/series/{series_id}", "Informations importées depuis le fichier : " + ", ".join(sorted(meta)))


# ---------------------------------------------------------------------------
# Telegram videos that belong to no series
# ---------------------------------------------------------------------------

def _parse_items(values) -> dict:
    """'peer:message' form values -> {peer_id: [message ids]}."""
    out = {}
    for value in values:
        try:
            peer, mid = str(value).split(":")
            out.setdefault(int(peer), []).append(int(mid))
        except ValueError:
            continue
    return out


@router.get("/telegram/orphans", response_class=HTMLResponse)
async def tg_orphans(request: Request, limit: int = 2000, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    from bridge.telegram.sync import _is_video, detect_series_and_episode
    tg = await telegram_service.status()
    channels = db.query(TelegramChannel).order_by(TelegramChannel.title).all()
    known = {
        (p, m) for p, m in db.query(Episode.tg_peer_id, Episode.tg_message_id).filter(Episode.tg_message_id.isnot(None))
    }
    rows, problems = [], []
    client = await telegram_service.authorized_client() if tg["authorized"] else None
    if client is not None:
        for channel in channels:
            peer = telegram_service.input_peer(channel.peer_id, channel.access_hash)
            try:
                async for message in client.iter_messages(peer, limit=max(50, min(limit, 20000))):
                    if not _is_video(message) or (channel.peer_id, message.id) in known:
                        continue
                    name = getattr(message.file, "name", None) or ""
                    title, ep = detect_series_and_episode(message.message or "", name)
                    rows.append({
                        "key": f"{channel.peer_id}:{message.id}",
                        "channel": channel.title,
                        "message_id": message.id,
                        "name": name or f"message #{message.id}",
                        "caption": (message.message or "").strip().splitlines()[0][:120] if message.message else "",
                        "size_mb": round((message.file.size or 0) / 1024 ** 2, 1),
                        "duration": int(getattr(message.file, "duration", None) or 0),
                        "date": message.date.strftime("%d/%m/%Y %H:%M") if getattr(message, "date", None) else "",
                        "title": title or "",
                        "episode": ep,
                    })
            except Exception as e:
                problems.append(f"{channel.title} : {type(e).__name__} {e}")
    all_series = db.query(Series.id, Series.title).order_by(Series.title).limit(3000).all()
    return _page(request, "tg_orphans.html", admin=admin, tg=tg, channels=channels, rows=rows,
                 problems=problems, all_series=all_series, limit=limit)


@router.post("/telegram/orphans/delete")
async def tg_orphans_delete(request: Request, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    form = await request.form()
    groups = _parse_items(form.getlist("item"))
    if not groups:
        return _back("/admin/telegram/orphans", "Aucune vidéo sélectionnée", "warning")
    total, errors = 0, []
    for peer_id, ids in groups.items():
        channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == peer_id).first()
        deleted, error = await telegram_service.delete_messages(peer_id, channel.access_hash if channel else None, ids)
        total += deleted
        if error:
            errors.append(error)
    if errors:
        return _back("/admin/telegram/orphans", f"{total} vidéo(s) supprimée(s). {errors[0]}", "warning")
    return _back("/admin/telegram/orphans", f"{total} vidéo(s) supprimée(s) de Telegram")


@router.post("/telegram/orphans/attach")
async def tg_orphans_attach(request: Request, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    """Turns the selected Telegram videos into episodes of an existing or new series."""
    from bridge.telegram.sync import _mime_type, detect_series_and_episode
    form = await request.form()
    groups = _parse_items(form.getlist("item"))
    if not groups:
        return _back("/admin/telegram/orphans", "Aucune vidéo sélectionnée", "warning")
    target = str(form.get("series_id") or "")
    if target == "new":
        title = str(form.get("new_title") or "").strip()
        if not title:
            return _back("/admin/telegram/orphans", "Donnez un titre à la nouvelle série", "danger")
        series = uploads.create_series(db, title)
        db.commit()
    elif target.isdigit():
        series = db.get(Series, int(target))
    else:
        series = None
    if series is None:
        return _back("/admin/telegram/orphans", "Choisissez une série", "danger")

    client = await telegram_service.authorized_client()
    if client is None:
        return _back("/admin/telegram/orphans", "Compte Telegram non connecté", "danger")
    found = []
    for peer_id, ids in groups.items():
        channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == peer_id).first()
        messages = await client.get_messages(telegram_service.input_peer(peer_id, channel.access_hash if channel else None), ids=ids)
        for message in messages:
            if message is not None and message.file is not None:
                _, ep = detect_series_and_episode(message.message or "", getattr(message.file, "name", None) or "")
                found.append((ep, message.id, peer_id, message))
    found.sort(key=lambda x: (x[0] is None, x[0] or 0, x[1]))  # detected episode numbers first, then posting order

    used = {n for (n,) in db.query(Episode.num).filter(Episode.series_id == series.id)}
    added = 0
    for ep, _, peer_id, message in found:
        num = ep if ep and ep not in used else ((max(used) + 1) if used else 1)
        used.add(num)
        db.add(Episode(
            series_id=series.id, num=num, title=f"Episode {num}",
            titles_json={"en": f"Episode {num}", "fr": f"Épisode {num}", "ar": f"الحلقة {num}"},
            duration=int(getattr(message.file, "duration", None) or 0) or 120, is_free=True,
            tg_peer_id=peer_id, tg_message_id=message.id,
            file_size=message.file.size or 0, mime_type=_mime_type(message),
        ))
        added += 1
    db.flush()
    uploads.refresh_series_counts(db, series.id)
    db.commit()
    return _back(f"/admin/series/{series.id}", f"{added} vidéo(s) ajoutée(s) à « {series.title} »")
