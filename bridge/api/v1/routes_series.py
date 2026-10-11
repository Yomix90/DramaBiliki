from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from bridge.database import get_db
from bridge.models import Series, Episode, Genre, Favorite, WatchHistory, User
from bridge.auth import get_optional_user
from bridge.api.v1.schemas import SeriesBriefOut, SeriesDetailOut, EpisodeOut, GenreOut
from bridge.urls import public_base_url, series_cover_url

router = APIRouter(tags=["Series"])

def serialize_brief(s: Series, lang: str, base_url: str) -> SeriesBriefOut:
    cover = series_cover_url(s, base_url)
    return SeriesBriefOut(
        id=s.id,
        source_id=s.source_id,
        slug=s.slug,
        title=s.get_title(lang),
        cover_url=cover,
        platform=s.platform,
        total_episodes=s.total_episodes,
        available_episodes=s.available_episodes,
        rating=s.rating or 4.8,
        genres=[g.get_name(lang) for g in s.genres[:3]],
        is_new=s.is_new,
        is_popular=s.is_popular,
    )

@router.get("/series", response_model=List[SeriesBriefOut])
async def list_series(
    request: Request,
    genre: Optional[str] = Query(None, description="Genre slug"),
    platform: Optional[str] = Query(None, description="Platform name"),
    q: Optional[str] = Query(None, description="Search query"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    lang: str = Query("en"),
    db: Session = Depends(get_db),
):
    base_url = public_base_url(request)
    query = db.query(Series).filter(Series.status == "active")

    if genre:
        query = query.join(Series.genres).filter(Genre.slug == genre)

    if platform:
        query = query.filter(Series.platform == platform)

    if q:
        query = query.filter(
            or_(
                Series.title.ilike(f"%{q}%"),
                Series.slug.ilike(f"%{q}%"),
                Series.description.ilike(f"%{q}%"),
            )
        )

    offset = (page - 1) * limit
    series_list = query.order_by(Series.is_popular.desc(), Series.id.desc()).offset(offset).limit(limit).all()

    return [serialize_brief(s, lang, base_url) for s in series_list]


@router.get("/series/{id_or_slug}", response_model=SeriesDetailOut)
async def get_series_detail(
    id_or_slug: str,
    request: Request,
    lang: str = Query("en"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    base_url = public_base_url(request)
    
    if id_or_slug.isdigit():
        series = db.query(Series).filter((Series.id == int(id_or_slug)) | (Series.source_id == id_or_slug)).first()
    else:
        series = db.query(Series).filter(Series.slug == id_or_slug).first()

    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    # Check favorite
    is_fav = False
    watched_map = {}
    last_watched_ep = None
    last_pos = None

    if current_user:
        fav_exists = db.query(Favorite).filter(Favorite.user_id == current_user.id, Favorite.series_id == series.id).first()
        is_fav = fav_exists is not None

        history_rows = db.query(WatchHistory).filter(WatchHistory.user_id == current_user.id, WatchHistory.series_id == series.id).all()
        for h in history_rows:
            watched_map[h.episode_num] = (h.completed, h.position_seconds)
            last_watched_ep = h.episode_num
            last_pos = h.position_seconds

    # Ep out
    episodes_out: List[EpisodeOut] = []
    for ep in series.episodes:
        is_w, w_sec = watched_map.get(ep.num, (False, 0))
        episodes_out.append(EpisodeOut(
            id=ep.id,
            num=ep.num,
            title=ep.titles_json.get(lang, ep.title) if ep.titles_json else ep.title,
            duration=ep.duration,
            thumbnail_url=ep.thumbnail_url,
            is_free=ep.is_free,
            is_watched=is_w,
            watched_seconds=w_sec,
        ))

    cover = series_cover_url(series, base_url)

    return SeriesDetailOut(
        id=series.id,
        source_id=series.source_id,
        slug=series.slug,
        title=series.get_title(lang),
        description=series.get_description(lang),
        cover_url=cover,
        platform=series.platform,
        total_episodes=series.total_episodes,
        available_episodes=series.available_episodes,
        rating=series.rating or 4.8,
        genres=[g.get_name(lang) for g in series.genres],
        is_new=series.is_new,
        is_popular=series.is_popular,
        episodes=episodes_out,
        is_favorite=is_fav,
        last_watched_episode=last_watched_ep,
        last_position_seconds=last_pos,
    )


@router.get("/genres", response_model=List[GenreOut])
async def list_genres(
    lang: str = Query("en"),
    db: Session = Depends(get_db),
):
    genres = db.query(Genre).all()
    return [
        GenreOut(id=g.id, slug=g.slug, name=g.get_name(lang))
        for g in genres
    ]


@router.get("/search/suggest")
async def search_suggestions(
    q: str = Query(..., min_length=1),
    lang: str = Query("en"),
    db: Session = Depends(get_db),
):
    series_matches = (
        db.query(Series)
        .filter(Series.status == "active", Series.title.ilike(f"%{q}%"))
        .limit(8)
        .all()
    )
    return [
        {"id": s.id, "slug": s.slug, "title": s.get_title(lang), "platform": s.platform}
        for s in series_matches
    ]
