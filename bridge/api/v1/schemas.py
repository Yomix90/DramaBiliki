from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class GenreOut(BaseModel):
    id: int
    slug: str
    name: str

class EpisodeOut(BaseModel):
    id: int
    num: int
    title: str
    duration: int
    thumbnail_url: Optional[str] = None
    is_free: bool = True
    is_watched: bool = False
    watched_seconds: int = 0

class SeriesBriefOut(BaseModel):
    id: int
    source_id: str
    slug: str
    title: str
    cover_url: str
    platform: Optional[str] = ""
    total_episodes: int
    available_episodes: int
    rating: float
    genres: List[str] = []
    is_new: bool = False
    is_popular: bool = False

class SeriesDetailOut(SeriesBriefOut):
    description: str
    episodes: List[EpisodeOut] = []
    is_favorite: bool = False
    last_watched_episode: Optional[int] = None
    last_position_seconds: Optional[int] = None

class BannerOut(BaseModel):
    id: int
    title: str
    subtitle: str
    image_url: str
    target_series_id: Optional[int] = None
    target_series_slug: Optional[str] = None

class HomeSectionOut(BaseModel):
    id: str
    title: str
    series: List[SeriesBriefOut]

class HomeFeedOut(BaseModel):
    banners: List[BannerOut]
    continue_watching: List[Dict[str, Any]] = []
    sections: List[HomeSectionOut]

class DeviceAuthRequest(BaseModel):
    device_id: str
    platform_os: Optional[str] = "android"
    preferred_language: Optional[str] = "en"

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    device_id: str
    preferred_language: str
    email: Optional[str] = None
    username: Optional[str] = None
    is_guest: bool = True


class RegisterRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileOut(BaseModel):
    id: int
    email: Optional[str] = None
    username: Optional[str] = None
    is_guest: bool
    ads_free: bool = False
    preferred_language: str = "en"
    created_at: Optional[str] = None


class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    preferred_language: Optional[str] = None

class ProgressUpdateRequest(BaseModel):
    series_id: int
    episode_num: int
    position_seconds: int
    total_seconds: int = 120
    completed: bool = False

class FavoriteToggleRequest(BaseModel):
    series_id: int
