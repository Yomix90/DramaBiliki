from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from bridge.accel import file_response

from bridge import app_settings
from bridge.auth import get_optional_user
from bridge.config import settings
from bridge.models import User
from bridge.urls import public_base_url

router = APIRouter(tags=["Mobile app"])

APK_DIR = settings.MEDIA_DIR / "apk"
LATEST_APK = APK_DIR / "dramabiliki-latest.apk"


def apk_download_url(base_url: str) -> str:
    custom = app_settings.get("app_update_url").strip()
    if custom:
        return custom if custom.startswith("http") else f"{base_url}{custom}"
    if LATEST_APK.exists():
        return f"{base_url}/download/app.apk?v={app_settings.get('app_latest_version')}"
    return ""


@router.get("/app/version")
async def check_app_version(request: Request, current: Optional[str] = Query(None, description="Installed app version")):
    """Called by the app at launch: is an update available, or required?"""
    latest = app_settings.get("app_latest_version")
    minimum = app_settings.get("app_min_version")
    installed = app_settings.parse_version(current) if current else None
    has_update = installed is not None and installed < app_settings.parse_version(latest)
    force = app_settings.get_bool("app_update_force") and has_update
    if installed is not None and installed < app_settings.parse_version(minimum):
        force = True
    url = apk_download_url(public_base_url(request))
    return {
        "latest_version": latest,
        "min_version": minimum,
        "has_update": bool(has_update and url),
        "force_update": bool(force and url),
        "download_url": url,
        "release_notes": app_settings.get("app_update_notes"),
    }


@router.get("/config/ads")
async def ads_config(current_user: Optional[User] = Depends(get_optional_user)):
    """Rewarded ad policy: one ad every N episodes, unless the account is ad-free."""
    exempt = bool(current_user and current_user.ads_free)
    unit_id = app_settings.get("ads_rewarded_unit_id").strip()
    return {
        "enabled": app_settings.get_bool("ads_enabled") and not exempt,
        "every_n_episodes": max(1, app_settings.get_int("ads_every_n_episodes", 5)),
        "rewarded_unit_id": unit_id,
    }


download_router = APIRouter(tags=["Mobile app"])


@download_router.get("/download/app.apk")
async def download_apk(request: Request):
    if not LATEST_APK.is_file():
        raise HTTPException(status_code=404, detail="No APK published yet")
    version = app_settings.get("app_latest_version")
    return file_response(
        LATEST_APK,
        request,
        "application/vnd.android.package-archive",
        {"Cache-Control": "no-cache"},
        filename=f"DramaBiliki-{version}.apk",
    )


@download_router.get("/health/accel")
async def accel_self_check(request: Request):
    """Used by docker/start.sh to check that nginx really serves files for Python."""
    probe = settings.MEDIA_DIR / ".accel-check"
    if not probe.is_file():
        raise HTTPException(status_code=404, detail="No probe file")
    return file_response(probe, request, "text/plain", {"Cache-Control": "no-store"})
