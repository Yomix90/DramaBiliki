from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from bridge.database import get_db
from bridge.models import Series, Banner, WatchHistory, Genre, User
from bridge.auth import get_optional_user
from bridge.api.v1.schemas import HomeFeedOut, BannerOut, HomeSectionOut, SeriesBriefOut
from bridge.urls import public_base_url, series_cover_url

router = APIRouter(prefix="/home", tags=["Home"])

SECTION_TITLES = {
    "trending": {"en": "🔥 Trending Now", "fr": "🔥 Tendances du moment", "ar": "🔥 الأكثر تداولاً"},
    "new": {"en": "✨ New Releases", "fr": "✨ Nouveautés", "ar": "✨ أحدث المسلسلات"},
    "top_rated": {"en": "⭐ Highly Rated", "fr": "⭐ Les Mieux Notés", "ar": "⭐ الأعلى تقييماً"},
}

def serialize_series_brief(series: Series, lang: str, request: Request) -> SeriesBriefOut:
    cover = series_cover_url(series, public_base_url(request))

    return SeriesBriefOut(
        id=series.id,
        source_id=series.source_id,
        slug=series.slug,
        title=series.get_title(lang),
        cover_url=cover,
        platform=series.platform,
        total_episodes=series.total_episodes,
        available_episodes=series.available_episodes,
        rating=series.rating or 4.8,
        genres=[g.get_name(lang) for g in series.genres[:3]],
        is_new=series.is_new,
        is_popular=series.is_popular,
    )

@router.get("", response_model=HomeFeedOut)
async def get_home_feed(
    request: Request,
    lang: str = Query("en", description="Language code: en, fr, ar, tr"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    base_url = public_base_url(request)

    # 1. Banners
    db_banners = db.query(Banner).filter(Banner.is_active == True).order_by(Banner.sort_order).limit(5).all()
    banners_out: List[BannerOut] = []
    
    if db_banners:
        for b in db_banners:
            target_slug = b.series.slug if b.series else None
            banners_out.append(BannerOut(
                id=b.id,
                title=b.title,
                subtitle=b.subtitle,
                image_url=f"{base_url}{b.image_url}" if (b.image_url or "").startswith("/") else b.image_url,
                target_series_id=b.target_series_id,
                target_series_slug=target_slug,
            ))
    else:
        # Fallback: create dynamic banners from top 3 active series
        top_series = db.query(Series).filter(Series.status == "active").order_by(Series.rating.desc(), Series.id.desc()).limit(3).all()
        for idx, s in enumerate(top_series, start=1):
            cover = series_cover_url(s, base_url)
            banners_out.append(BannerOut(
                id=idx,
                title=s.get_title(lang),
                subtitle=s.platform or "DramaBiliki Exclusive",
                image_url=cover,
                target_series_id=s.id,
                target_series_slug=s.slug,
            ))

    # 2. Continue watching
    continue_watching = []
    if current_user:
        history_rows = (
            db.query(WatchHistory)
            .filter(WatchHistory.user_id == current_user.id, WatchHistory.completed == False)
            .order_by(WatchHistory.updated_at.desc())
            .limit(10)
            .all()
        )
        for h in history_rows:
            if h.series:
                cover = series_cover_url(h.series, base_url)
                continue_watching.append({
                    "series_id": h.series.id,
                    "series_slug": h.series.slug,
                    "title": h.series.get_title(lang),
                    "cover_url": cover,
                    "episode_num": h.episode_num,
                    "position_seconds": h.position_seconds,
                    "total_seconds": h.total_seconds,
                    "progress_percent": round((h.position_seconds / max(1, h.total_seconds)) * 100),
                })

    # 3. Sections
    sections: List[HomeSectionOut] = []

    # Section A: Trending
    trending_series = (
        db.query(Series)
        .filter(Series.status == "active")
        .order_by(Series.is_popular.desc(), Series.rating.desc())
        .limit(12)
        .all()
    )
    if trending_series:
        sections.append(HomeSectionOut(
            id="trending",
            title=SECTION_TITLES["trending"].get(lang, SECTION_TITLES["trending"]["en"]),
            series=[serialize_series_brief(s, lang, request) for s in trending_series],
        ))

    # Section B: New Releases
    new_series = (
        db.query(Series)
        .filter(Series.status == "active")
        .order_by(Series.id.desc())
        .limit(12)
        .all()
    )
    if new_series:
        sections.append(HomeSectionOut(
            id="new",
            title=SECTION_TITLES["new"].get(lang, SECTION_TITLES["new"]["en"]),
            series=[serialize_series_brief(s, lang, request) for s in new_series],
        ))

    # Section C: Genre-based sections
    genres = db.query(Genre).limit(4).all()
    for g in genres:
        if g.series:
            genre_series = [s for s in g.series if s.status == "active"][:10]
            if genre_series:
                sections.append(HomeSectionOut(
                    id=f"genre_{g.slug}",
                    title=g.get_name(lang),
                    series=[serialize_series_brief(s, lang, request) for s in genre_series],
                ))

    return HomeFeedOut(
        banners=banners_out,
        continue_watching=continue_watching,
        sections=sections,
    )
