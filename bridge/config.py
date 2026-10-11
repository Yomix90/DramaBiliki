import logging
import os
import secrets
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent

# Values shipped in the public repository: never trust them in production.
DEFAULT_SECRET_KEY = "dramabiliki-super-secret-key-change-in-production-2026"
DEFAULT_ADMIN_PASSWORD = "DramaBiliki2026!"

logger = logging.getLogger("bridge.config")


class Settings(BaseSettings):
    # App info
    APP_NAME: str = "DramaBiliki Bridge"
    APP_VERSION: str = "1.1.0"
    APP_ENV: str = os.getenv("APP_ENV", "production")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)

    # Public URL of the bridge as seen by the apps (e.g. https://api.example.com).
    # When empty, it is derived from the request (honoring X-Forwarded-* headers).
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

    # Source site
    SOURCE_BASE_URL: str = os.getenv("SOURCE_BASE_URL", "https://dramadunyam.com")
    SOURCE_CDN_PRIMARY: str = os.getenv("SOURCE_CDN_PRIMARY", "cdn2.dramaflix.net")
    SOURCE_CDN_FAILOVER: str = os.getenv("SOURCE_CDN_FAILOVER", "cdn.dramaflix.net")
    SOURCE_USER_AGENT: str = os.getenv(
        "SOURCE_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    # Optional outbound proxy for every request to the source and its CDNs, e.g.
    # http://user:pass@host:port or socks5://host:port. Needed when the source
    # (behind Cloudflare) blocks the VPS datacenter IP with HTTP 403.
    SOURCE_PROXY: str = os.getenv("SOURCE_PROXY", "").strip()

    # Persistent data (database, generated secret)
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR)))

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{Path(os.getenv('DATA_DIR', str(BASE_DIR))) / 'dramabiliki.db'}",
    )

    # Media storage
    MEDIA_DIR: Path = Path(os.getenv("MEDIA_DIR", str(BASE_DIR / "media")))
    COVERS_DIR: Path = Path(os.getenv("COVERS_DIR", str(BASE_DIR / "media" / "covers")))

    # Streaming options
    STREAM_CACHE_TTL_SECONDS: int = int(os.getenv("STREAM_CACHE_TTL_SECONDS", "600"))  # 10 mins
    PROXY_SEGMENTS: bool = os.getenv("PROXY_SEGMENTS", "false").lower() == "true"

    # Background jobs
    ENABLE_SCHEDULER: bool = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"
    LIGHT_SYNC_INTERVAL_MINUTES: int = int(os.getenv("LIGHT_SYNC_INTERVAL_MINUTES", "30"))
    FULL_SYNC_HOUR_UTC: int = int(os.getenv("FULL_SYNC_HOUR_UTC", "3"))
    # Runs a light sync right after boot when the catalog is empty (fresh VPS).
    SYNC_ON_STARTUP_IF_EMPTY: bool = os.getenv("SYNC_ON_STARTUP_IF_EMPTY", "true").lower() == "true"

    # Scanner & Sync rate limiting
    SCANNER_MAX_CONCURRENT_REQUESTS: int = int(os.getenv("SCANNER_MAX_CONCURRENT_REQUESTS", "2"))
    SCANNER_REQUEST_DELAY_MIN: float = float(os.getenv("SCANNER_REQUEST_DELAY_MIN", "0.4"))
    SCANNER_REQUEST_DELAY_MAX: float = float(os.getenv("SCANNER_REQUEST_DELAY_MAX", "1.2"))
    SCANNER_MAX_RETRIES: int = int(os.getenv("SCANNER_MAX_RETRIES", "3"))
    SCANNER_TIMEOUT_SECONDS: float = float(os.getenv("SCANNER_TIMEOUT_SECONDS", "15.0"))

    # Security & JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_DAYS: int = 365
    ADMIN_SESSION_HOURS: int = int(os.getenv("ADMIN_SESSION_HOURS", "12"))

    # Admin Panel Credentials
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    class Config:
        env_file = ".env"
        extra = "ignore"

    def source_client_kwargs(self) -> dict:
        """Common httpx.AsyncClient options for outbound requests to the source."""
        return {"proxy": self.SOURCE_PROXY} if self.SOURCE_PROXY else {}

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def admin_password_is_default(self) -> bool:
        return self.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD

    @property
    def admin_login_allowed(self) -> bool:
        """The public default password is refused in production."""
        return bool(self.ADMIN_PASSWORD) and not (self.is_production and self.admin_password_is_default)


def _load_or_create_secret(data_dir: Path) -> Optional[str]:
    """Persists a random secret in the data volume so tokens survive restarts."""
    path = data_dir / ".secret_key"
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = secrets.token_urlsafe(48)
        path.write_text(value, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return value
    except OSError as e:
        logger.warning(f"Could not persist a generated SECRET_KEY in {data_dir}: {e}")
        return None


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
settings.COVERS_DIR.mkdir(parents=True, exist_ok=True)

if not settings.SECRET_KEY or settings.SECRET_KEY == DEFAULT_SECRET_KEY:
    if settings.is_production:
        # The default key is public: generate a private one instead of signing forgeable tokens.
        settings.SECRET_KEY = _load_or_create_secret(settings.DATA_DIR) or secrets.token_urlsafe(48)
    else:
        settings.SECRET_KEY = DEFAULT_SECRET_KEY
