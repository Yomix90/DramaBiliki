from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from bridge.database import get_db
from bridge.models import User, Favorite, WatchHistory, Series
from bridge.auth import (
    create_access_token,
    get_or_create_device_user,
    get_current_user,
)
from bridge.api.v1.schemas import (
    DeviceAuthRequest,
    AuthResponse,
    ProgressUpdateRequest,
    FavoriteToggleRequest,
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
    token = create_access_token({"sub": str(user.id), "device_id": user.device_id})
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        device_id=user.device_id,
        preferred_language=user.preferred_language or "en",
    )


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns user's favorites and viewing history."""
    base_url = str(request.base_url).rstrip("/")
    lang = current_user.preferred_language or "en"

    # Favorites
    favorites = []
    for fav in current_user.favorites:
        s = fav.series
        if s and s.status == "active":
            cover = f"{base_url}/media/covers/{s.local_cover}" if s.local_cover else s.cover_url
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
            cover = f"{base_url}/media/covers/{s.local_cover}" if s.local_cover else s.cover_url
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
