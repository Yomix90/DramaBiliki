from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session

from bridge.database import get_db
from bridge.models import User, Favorite, WatchHistory, Series
from bridge.auth import (
    create_access_token,
    get_current_user,
    get_optional_user,
    get_or_create_device_user,
    hash_password,
    verify_password,
)
from bridge.urls import public_base_url, series_cover_url
from bridge.api.v1.schemas import (
    DeviceAuthRequest,
    AuthResponse,
    ProgressUpdateRequest,
    FavoriteToggleRequest,
    LoginRequest,
    ProfileOut,
    ProfileUpdate,
    RegisterRequest,
    SeriesBriefOut,
)

router = APIRouter(tags=["User & Library"])

@router.post("/auth/device", response_model=AuthResponse)
async def auth_device(
    payload: DeviceAuthRequest,
    db: Session = Depends(get_db),
):
    """Registers a new device or retrieves existing session, issuing a JWT access token."""
    user = get_or_create_device_user(
        device_id=payload.device_id,
        platform_os=payload.platform_os or "android",
        preferred_language=payload.preferred_language or "en",
        db=db,
    )
    return _auth_response(user)


@router.post("/favorites")
async def toggle_favorite(
    payload: FavoriteToggleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggles favorite state for a series."""
    series = db.query(Series).filter(Series.id == payload.series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    existing = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.series_id == payload.series_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "removed", "is_favorite": False}
    else:
        fav = Favorite(user_id=current_user.id, series_id=payload.series_id)
        db.add(fav)
        db.commit()
        return {"status": "added", "is_favorite": True}


@router.delete("/favorites/{series_id}")
async def remove_favorite(
    series_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.series_id == series_id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    return {"status": "removed", "is_favorite": False}


@router.post("/history/progress")
async def update_progress(
    payload: ProgressUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Updates watch progress (in seconds) for a specific episode."""
    record = db.query(WatchHistory).filter(
        WatchHistory.user_id == current_user.id,
        WatchHistory.series_id == payload.series_id,
        WatchHistory.episode_num == payload.episode_num,
    ).first()

    if not record:
        record = WatchHistory(
            user_id=current_user.id,
            series_id=payload.series_id,
            episode_num=payload.episode_num,
            position_seconds=payload.position_seconds,
            total_seconds=payload.total_seconds,
            completed=payload.completed,
        )
        db.add(record)
    else:
        record.position_seconds = payload.position_seconds
        record.total_seconds = payload.total_seconds
        record.completed = payload.completed

    db.commit()
    return {"status": "ok"}


@router.get("/me/library")
async def get_my_library(
    request: Request,
    lang: Optional[str] = Query(None, description="Language code; defaults to the user's preferred language"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns user's favorites and viewing history."""
    base_url = public_base_url(request)
    lang = lang or current_user.preferred_language or "en"

    # Favorites
    favorites = []
    for fav in current_user.favorites:
        s = fav.series
        if s and s.status == "active":
            cover = series_cover_url(s, base_url)
            favorites.append({
                "id": s.id,
                "slug": s.slug,
                "title": s.get_title(lang),
                "cover_url": cover,
                "platform": s.platform,
                "total_episodes": s.total_episodes,
                "available_episodes": s.available_episodes,
                "rating": s.rating,
            })

    # Watch history
    history = []
    for h in current_user.history_entries:
        s = h.series
        if s:
            cover = series_cover_url(s, base_url)
            history.append({
                "series_id": s.id,
                "series_slug": s.slug,
                "title": s.get_title(lang),
                "cover_url": cover,
                "episode_num": h.episode_num,
                "position_seconds": h.position_seconds,
                "total_seconds": h.total_seconds,
                "completed": h.completed,
                "updated_at": h.updated_at.isoformat() if h.updated_at else "",
            })

    return {
        "favorites": favorites,
        "history": history,
    }


# ---------------------------------------------------------------------------
# User accounts (email + password). A guest device user can be upgraded in place,
# keeping its favorites and history.
# ---------------------------------------------------------------------------

import re as _re
import uuid as _uuid

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _auth_response(user: User) -> AuthResponse:
    token = create_access_token({"sub": str(user.id), "device_id": user.device_id})
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        device_id=user.device_id,
        preferred_language=user.preferred_language or "en",
        email=user.email,
        username=user.username,
        is_guest=not user.email,
    )


def _profile(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        email=user.email,
        username=user.username,
        is_guest=not user.email,
        ads_free=bool(user.ads_free),
        preferred_language=user.preferred_language or "en",
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def _merge_guest_into(guest: Optional[User], account: User, db: Session) -> None:
    """Moves a guest's favorites and progress to the account it logs into."""
    if guest is None or guest.id == account.id or guest.email:
        return
    fav_ids = {f.series_id for f in account.favorites}
    for fav in list(guest.favorites):
        if fav.series_id not in fav_ids:
            fav.user_id = account.id
    existing = {(h.series_id, h.episode_num) for h in account.history_entries}
    for entry in list(guest.history_entries):
        if (entry.series_id, entry.episode_num) not in existing:
            entry.user_id = account.id


@router.post("/auth/register", response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Adresse e-mail invalide")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 6 caractères")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet e-mail")

    if current_user is not None and not current_user.email:
        user = current_user  # upgrade the guest: keeps favorites & history
    else:
        user = User(platform_os="android")
        db.add(user)
    user.email = email
    user.username = (payload.username or email.split("@")[0]).strip()[:64]
    user.password_hash = hash_password(payload.password)
    # Free the device id so this device gets a fresh guest after logging out.
    user.device_id = f"acct-{_uuid.uuid4().hex}"
    db.commit()
    db.refresh(user)
    return _auth_response(user)


@router.post("/auth/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou mot de passe incorrect")
    if user.is_active is False:
        raise HTTPException(status_code=403, detail="Ce compte a été désactivé")
    _merge_guest_into(current_user, user, db)
    db.commit()
    return _auth_response(user)


@router.get("/me", response_model=ProfileOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return _profile(current_user)


@router.patch("/me", response_model=ProfileOut)
async def update_me(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.username is not None and payload.username.strip():
        current_user.username = payload.username.strip()[:64]
    if payload.preferred_language in ("en", "fr", "ar"):
        current_user.preferred_language = payload.preferred_language
    db.commit()
    return _profile(current_user)
