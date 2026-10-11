import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # App info
    APP_NAME: str = "DramaBiliki Bridge"
    APP_ENV: str = os.getenv("APP_ENV", "production")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dramabiliki-super-secret-key-change-in-production-2026")

    # Source site
    SOURCE_BASE_URL: str = os.getenv("SOURCE_BASE_URL", "https://dramadunyam.com")
    SOURCE_CDN_PRIMARY: str = os.getenv("SOURCE_CDN_PRIMARY", "cdn2.dramaflix.net")
    SOURCE_CDN_FAILOVER: str = os.getenv("SOURCE_CDN_FAILOVER", "cdn.dramaflix.net")
    SOURCE_USER_AGENT: str = os.getenv(
        "SOURCE_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'dramabiliki.db'}")

    # Media storage
    MEDIA_DIR: Path = Path(os.getenv("MEDIA_DIR", str(BASE_DIR / "media")))
    COVERS_DIR: Path = Path(os.getenv("COVERS_DIR", str(BASE_DIR / "media" / "covers")))

    # Streaming options
    STREAM_CACHE_TTL_SECONDS: int = int(os.getenv("STREAM_CACHE_TTL_SECONDS", "600"))  # 10 mins
    PROXY_SEGMENTS: bool = os.getenv("PROXY_SEGMENTS", "false").lower() == "true"

    # Scanner & Sync rate limiting
    SCANNER_MAX_CONCURRENT_REQUESTS: int = int(os.getenv("SCANNER_MAX_CONCURRENT_REQUESTS", "2"))
    SCANNER_REQUEST_DELAY_MIN: float = float(os.getenv("SCANNER_REQUEST_DELAY_MIN", "0.4"))
    SCANNER_REQUEST_DELAY_MAX: float = float(os.getenv("SCANNER_REQUEST_DELAY_MAX", "1.2"))
    SCANNER_MAX_RETRIES: int = int(os.getenv("SCANNER_MAX_RETRIES", "3"))
    SCANNER_TIMEOUT_SECONDS: float = float(os.getenv("SCANNER_TIMEOUT_SECONDS", "15.0"))

    # Security & JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_DAYS: int = 365

    # Admin Panel Credentials
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "DramaBiliki2026!")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Ensure directories exist
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
settings.COVERS_DIR.mkdir(parents=True, exist_ok=True)
