import datetime
from typing import Dict, Any, Optional
from sqlalchemy import (
    BigInteger, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, Table, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from bridge.database import Base

# Association table between Series and Genres
series_genres = Table(
    "series_genres",
    Base.metadata,
    Column("series_id", Integer, ForeignKey("series.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)

class Series(Base):
    __tablename__ = "series"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(String(64), unique=True, index=True, nullable=False)  # source numeric/string id, e.g. "319823"
    slug = Column(String(255), unique=True, index=True, nullable=False)
    
    # Multilingual titles
    title = Column(String(255), nullable=False, index=True)  # Primary title (usually English or original)
    titles_json = Column(JSON, default=dict)  # {"en": "...", "fr": "...", "ar": "...", "tr": "..."}
    
    # Multilingual descriptions
    description = Column(Text, default="")
    descriptions_json = Column(JSON, default=dict)  # {"en": "...", "fr": "...", "ar": "...", "tr": "..."}
    
    # Media
    cover_url = Column(String(512), default="")
    local_cover = Column(String(255), default="")  # e.g. "319823.webp"
    
    # Metadata
    platform = Column(String(64), index=True, default="")  # e.g. DramaBox, ShortMax, ReelShort
    source_type = Column(String(32), default="web", index=True)  # web (legacy site) | telegram
    tg_channel_id = Column(Integer, ForeignKey("telegram_channels.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), default="active", index=True)  # active, inactive
    is_featured = Column(Boolean, default=False, index=True)
    is_popular = Column(Boolean, default=False, index=True)
    is_new = Column(Boolean, default=True, index=True)
    
    total_episodes = Column(Integer, default=0)
    available_episodes = Column(Integer, default=0)
    source_total = Column(Integer, default=0)
    
    rating = Column(Float, default=4.8)
    view_count = Column(Integer, default=0)
    release_year = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    episodes = relationship("Episode", back_populates="series", cascade="all, delete-orphan", order_by="Episode.num")
    genres = relationship("Genre", secondary=series_genres, back_populates="series")
    favorites = relationship("Favorite", back_populates="series", cascade="all, delete-orphan")
    history_entries = relationship("WatchHistory", back_populates="series", cascade="all, delete-orphan")
    telegram_channel = relationship("TelegramChannel")

    def get_title(self, lang: str = "en") -> str:
        if self.titles_json and lang in self.titles_json and self.titles_json[lang]:
            return self.titles_json[lang]
        if self.titles_json and "en" in self.titles_json and self.titles_json["en"]:
            return self.titles_json["en"]
        return self.title or ""

    def get_description(self, lang: str = "en") -> str:
        if self.descriptions_json and lang in self.descriptions_json and self.descriptions_json[lang]:
            return self.descriptions_json[lang]
        if self.descriptions_json and "en" in self.descriptions_json and self.descriptions_json["en"]:
            return self.descriptions_json["en"]
        return self.description or ""


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    num = Column(Integer, nullable=False, index=True)  # 1, 2, 3...
    
    title = Column(String(255), default="")  # e.g. "Episode 1"
    titles_json = Column(JSON, default=dict)
    
    duration = Column(Integer, default=120)  # estimated or exact in seconds
    thumbnail_url = Column(String(512), default="")
    local_thumbnail = Column(String(255), default="")
    
    is_free = Column(Boolean, default=True)  # All episodes free or configurable by admin

    # Telegram source (when the episode is a video posted in a channel)
    tg_peer_id = Column(BigInteger, nullable=True, index=True)
    tg_message_id = Column(BigInteger, nullable=True, index=True)
    file_size = Column(BigInteger, default=0)
    mime_type = Column(String(64), default="")
    # Video stored on the VPS disk (relative to MEDIA_DIR/videos), used instead of Telegram
    local_file = Column(String(255), default="")
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    series = relationship("Series", back_populates="episodes")


class Genre(Base):
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(64), nullable=False)
    names_json = Column(JSON, default=dict)  # {"en": "Romance", "fr": "Romance", "ar": "رومانسية"}

    series = relationship("Series", secondary=series_genres, back_populates="genres")

    def get_name(self, lang: str = "en") -> str:
        if self.names_json and lang in self.names_json and self.names_json[lang]:
            return self.names_json[lang]
        return self.name


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(128), unique=True, index=True, nullable=False)
    username = Column(String(64), nullable=True)
    email = Column(String(128), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=True)
    platform_os = Column(String(32), default="android")  # android, ios, web
    preferred_language = Column(String(10), default="en")  # en, fr, ar
    is_active = Column(Boolean, default=True)  # False = banned by an admin
    ads_free = Column(Boolean, default=False)  # True = never shown rewarded ads
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    history_entries = relationship("WatchHistory", back_populates="user", cascade="all, delete-orphan")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="favorites")
    series = relationship("Series", back_populates="favorites")


class WatchHistory(Base):
    __tablename__ = "watch_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    episode_num = Column(Integer, default=1)
    position_seconds = Column(Integer, default=0)
    total_seconds = Column(Integer, default=120)
    completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="history_entries")
    series = relationship("Series", back_populates="history_entries")


class Banner(Base):
    __tablename__ = "banners"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), default="")
    subtitle = Column(String(255), default="")
    image_url = Column(String(512), default="")
    target_series_id = Column(Integer, ForeignKey("series.id", ondelete="SET NULL"), nullable=True)
    action_url = Column(String(512), default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    series = relationship("Series")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String(32), default="full")  # full, light, single
    target_slug = Column(String(255), nullable=True)
    status = Column(String(32), default="running")  # running, completed, failed
    series_discovered = Column(Integer, default=0)
    series_updated = Column(Integer, default=0)
    episodes_synced = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    log_messages = Column(Text, default="")
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class TelegramAccount(Base):
    """A Telegram user account linked from the admin (several can be connected)."""
    __tablename__ = "telegram_accounts"

    id = Column(Integer, primary_key=True, index=True)
    session = Column(Text, default="")  # Telethon StringSession (secret)
    name = Column(String(255), default="")
    phone = Column(String(32), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TelegramChannel(Base):
    """A Telegram channel whose videos are imported as series/episodes."""
    __tablename__ = "telegram_channels"

    id = Column(Integer, primary_key=True, index=True)
    peer_id = Column(BigInteger, unique=True, index=True, nullable=False)  # e.g. -1001234567890
    access_hash = Column(BigInteger, nullable=True)  # only valid for the account below
    account_id = Column(Integer, nullable=True)  # TelegramAccount used to read this channel
    title = Column(String(255), default="")
    username = Column(String(64), default="")
    # caption: series & episode parsed from each caption | single: the whole channel is one series
    mode = Column(String(16), default="caption")
    enabled = Column(Boolean, default=True)
    last_message_id = Column(BigInteger, default=0)
    videos_count = Column(Integer, default=0)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TelegramChannelAccess(Base):
    """Accounts that can read a linked channel (each one has its own access hash).
    Downloads of the channel's videos are spread between them."""
    __tablename__ = "telegram_channel_access"
    __table_args__ = (UniqueConstraint("peer_id", "account_id", name="uq_channel_access"),)

    id = Column(Integer, primary_key=True)
    peer_id = Column(BigInteger, index=True, nullable=False)
    account_id = Column(Integer, index=True, nullable=False)
    access_hash = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
