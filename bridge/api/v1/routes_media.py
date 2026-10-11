from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from bridge.config import settings
from bridge.media import get_cover_path

router = APIRouter(prefix="/media", tags=["Media"])

@router.get("/covers/{filename}")
async def get_cover_file(
    filename: str,
    w: Optional[int] = Query(None, description="Requested width: 300 or 600"),
):
    """
    Serves optimized WebP cover images with long HTTP caching.
    Supports size variants e.g. w=300 or w=600.
    """
    source_id = filename.replace(".webp", "").split("_")[0]

    # Try size variant first
    cover_path = get_cover_path(source_id, size=w)
    if not cover_path or not cover_path.exists():
        # Fallback to main webp
        cover_path = settings.COVERS_DIR / filename
        if not cover_path.exists():
            raise HTTPException(status_code=404, detail="Cover image not found")

    return FileResponse(
        path=cover_path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=2592000, immutable",  # 30 days
            "Access-Control-Allow-Origin": "*",
        },
    )
