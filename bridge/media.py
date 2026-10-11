import io
import logging
from pathlib import Path
from typing import Optional
import httpx
from PIL import Image
from bridge.config import settings

logger = logging.getLogger(__name__)

async def download_and_cache_cover(
    source_id: str,
    cover_url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """
    Downloads cover image from source, converts to WebP, generates 300px and 600px variants,
    and saves to settings.COVERS_DIR. Returns the filename e.g. '{source_id}.webp'.
    """
    if not cover_url or not source_id:
        return None

    filename = f"{source_id}.webp"
    target_path = settings.COVERS_DIR / filename
    
    # If already cached and non-empty, skip download
    if target_path.exists() and target_path.stat().st_size > 0:
        return filename

    own_client = False
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": settings.SOURCE_USER_AGENT},
            timeout=15.0,
            follow_redirects=True,
            **settings.source_client_kwargs(),
        )
        own_client = True

    try:
        response = await client.get(cover_url)
        if response.status_code != 200:
            logger.warning(f"Failed to download cover from {cover_url}: HTTP {response.status_code}")
            return None

        image_data = response.content
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB (in case of RGBA or palette mode)
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGBA")
        else:
            image = image.convert("RGB")

        # Save main WebP
        image.save(target_path, "WEBP", quality=85, method=6)

        # Generate 300px and 600px widths keeping aspect ratio
        for width in [300, 600]:
            if image.width > width:
                height = int(image.height * (width / image.width))
                resized = image.resize((width, height), Image.Resampling.LANCZOS)
                variant_path = settings.COVERS_DIR / f"{source_id}_{width}.webp"
                resized.save(variant_path, "WEBP", quality=82)

        logger.info(f"Successfully cached cover for series {source_id} -> {filename}")
        return filename

    except Exception as e:
        logger.error(f"Error processing cover image for series {source_id}: {e}")
        return None
    finally:
        if own_client:
            await client.aclose()


def get_cover_path(source_id: str, size: Optional[int] = None) -> Optional[Path]:
    """Returns local Path to the cached cover or size variant."""
    if size in [300, 600]:
        variant_path = settings.COVERS_DIR / f"{source_id}_{size}.webp"
        if variant_path.exists():
            return variant_path

    main_path = settings.COVERS_DIR / f"{source_id}.webp"
    if main_path.exists():
        return main_path

    return None
