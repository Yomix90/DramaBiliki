import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from bridge.config import settings
from bridge.database import init_db
from bridge.scheduler import start_scheduler, stop_scheduler
from bridge.streamer import stream_resolver
from bridge.api.v1.routes_home import router as home_router
from bridge.api.v1.routes_series import router as series_router
from bridge.api.v1.routes_user import router as user_router
from bridge.api.v1.routes_stream import router as stream_router
from bridge.api.v1.routes_media import router as media_router
from bridge.api.admin.routes_admin import router as admin_router

logger = logging.getLogger("bridge.app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting DramaBiliki Bridge Server...")
    init_db()
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f"Could not start background scheduler: {e}")
    yield
    # Shutdown
    logger.info("Stopping DramaBiliki Bridge Server...")
    try:
        stop_scheduler()
    except Exception:
        pass
    await stream_resolver.close()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="High-performance Bridge & Streaming Server for DramaBiliki Mobile App",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API v1
app.include_router(home_router, prefix="/api/v1")
app.include_router(series_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")

# Mount Stream and Media endpoints
app.include_router(stream_router)
app.include_router(media_router)

# Mount Admin Web Panel
app.include_router(admin_router)

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": "1.0.0",
    }
