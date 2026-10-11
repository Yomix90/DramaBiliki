import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from bridge.config import settings
from bridge.database import SessionLocal, init_db
from bridge.scheduler import scheduled_telegram_sync, start_scheduler, startup_sync_if_empty, stop_scheduler
from bridge.sync import mark_interrupted_runs
from bridge.telegram.client import telegram_service
from bridge.uploads import cleanup_tmp_dir
from bridge.streamer import stream_resolver
from bridge.api.v1.routes_home import router as home_router
from bridge.api.v1.routes_series import router as series_router
from bridge.api.v1.routes_user import router as user_router
from bridge.api.v1.routes_stream import router as stream_router
from bridge.api.v1.routes_media import router as media_router
from bridge.api.v1.routes_app import download_router, router as app_router
from bridge.api.admin.routes_admin import router as admin_router
from bridge.api.admin.routes_content import router as admin_content_router

logger = logging.getLogger("bridge.app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting DramaBiliki Bridge Server...")
    init_db()
    db = SessionLocal()
    try:
        interrupted = mark_interrupted_runs(db)
        if interrupted:
            logger.info(f"Marked {interrupted} interrupted sync run(s) as failed.")
    finally:
        db.close()

    cleanup_tmp_dir()

    if not settings.admin_login_allowed:
        logger.warning("Admin panel is LOCKED: set a non-default ADMIN_PASSWORD environment variable to enable it.")

    startup_task = None
    if settings.ENABLE_SCHEDULER:
        try:
            start_scheduler()
        except Exception as e:
            logger.warning(f"Could not start background scheduler: {e}")
        if settings.SYNC_ON_STARTUP_IF_EMPTY and settings.LEGACY_SOURCE_ENABLED:
            startup_task = asyncio.create_task(startup_sync_if_empty())
        else:
            startup_task = asyncio.create_task(scheduled_telegram_sync())
    yield
    # Shutdown
    logger.info("Stopping DramaBiliki Bridge Server...")
    if startup_task and not startup_task.done():
        startup_task.cancel()
    try:
        stop_scheduler()
    except Exception:
        pass
    await stream_resolver.close()
    await telegram_service.close()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="High-performance Bridge & Streaming Server for DramaBiliki Mobile App",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS configuration (the API uses bearer tokens, not cookies, so credentials are not needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API v1
app.include_router(home_router, prefix="/api/v1")
app.include_router(series_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
app.include_router(app_router, prefix="/api/v1")
app.include_router(download_router)

# Mount Stream and Media endpoints
app.include_router(stream_router)
app.include_router(media_router)

# Mount Admin Web Panel
app.include_router(admin_router)
app.include_router(admin_content_router)

@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "api": "/api/v1",
        "docs": "/docs",
        "admin": "/admin",
        "health": "/health",
    }

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
