import argparse
import asyncio
import datetime
import logging
import sys
from typing import Optional, List
from sqlalchemy.orm import Session

from bridge.config import settings
from bridge.database import SessionLocal, init_db
from bridge.models import Series, Episode, Genre, SyncRun
from bridge.scanner import SourceScanner
from bridge.media import download_and_cache_cover

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bridge.sync")

# One sync at a time per process: admin-triggered and scheduled runs would
# otherwise hammer the source and fight over the SQLite write lock.
_sync_lock = asyncio.Lock()


def is_sync_running() -> bool:
    return _sync_lock.locked()


def mark_interrupted_runs(db: Session) -> int:
    """Flags runs left in 'running' state by a previous process (crash/redeploy)."""
    stale = db.query(SyncRun).filter(SyncRun.status == "running").all()
    for run in stale:
        run.status = "failed"
        run.finished_at = run.finished_at or datetime.datetime.utcnow()
        run.log_messages = ((run.log_messages or "") + "\nInterrupted by a server restart.").strip()
    if stale:
        db.commit()
    return len(stale)

class SyncService:
    def __init__(self, db: Session):
        self.db = db
        self.scanner = SourceScanner()

    async def sync_single_series(self, slug: str) -> Optional[Series]:
        """Fetches and syncs a single series by its slug."""
        logger.info(f"Syncing single series: {slug}")
        detail = await self.scanner.fetch_series_multilingual(slug)
        if not detail:
            logger.error(f"Series with slug '{slug}' could not be fetched from source.")
            return None

        series = await self._upsert_series(detail)
        self.db.commit()
        return series

    async def _upsert_series(self, data: dict) -> Series:
        source_id = str(data.get("id"))
        slug = data.get("slug")
        if not source_id or not slug:
            raise ValueError("Series missing id or slug")

        series = self.db.query(Series).filter(
            (Series.source_id == source_id) | (Series.slug == slug)
        ).first()

        titles_json = data.get("multilingual_titles", {})
        descriptions_json = data.get("multilingual_descriptions", {})

        title_primary = data.get("title") or titles_json.get("en") or titles_json.get("tr") or "Untitled"
        desc_primary = data.get("description") or descriptions_json.get("en") or ""

        cover_url = data.get("cover") or ""
        total_eps = int(data.get("total_episodes") or 0)
        avail_eps = int(data.get("available_episodes") or total_eps or 1)
        platform = data.get("platform") or ""
        is_new = bool(data.get("is_new", False))
        is_popular = bool(data.get("is_popular", False))

        if not series:
            series = Series(
                source_id=source_id,
                slug=slug,
                title=title_primary,
                titles_json=titles_json,
                description=desc_primary,
                descriptions_json=descriptions_json,
                cover_url=cover_url,
                platform=platform,
                status="active",
                total_episodes=total_eps,
                available_episodes=avail_eps,
                source_total=int(data.get("source_total") or total_eps),
                is_new=is_new,
                is_popular=is_popular,
            )
            self.db.add(series)
            self.db.flush()
            logger.info(f"Discovered new series: {series.title} (ID {source_id})")
        else:
            # Update existing
            series.title = title_primary
            series.titles_json = {**(series.titles_json or {}), **titles_json}
            series.description = desc_primary or series.description
            series.descriptions_json = {**(series.descriptions_json or {}), **descriptions_json}
            series.cover_url = cover_url or series.cover_url
            series.platform = platform or series.platform
            series.status = "active"
            series.total_episodes = max(series.total_episodes, total_eps)
            series.available_episodes = max(series.available_episodes, avail_eps)
            series.is_new = is_new
            series.is_popular = is_popular
            self.db.flush()

        # Download & cache cover locally
        if cover_url and not series.local_cover:
            local_name = await download_and_cache_cover(source_id, cover_url)
            if local_name:
                series.local_cover = local_name

        # Sync genres / tags
        tags = data.get("tags") or []
        for tag in tags:
            tag_slug = tag.get("slug")
            tag_name = tag.get("name")
            if tag_slug and tag_name:
                genre = self.db.query(Genre).filter_by(slug=tag_slug).first()
                if not genre:
                    genre = Genre(slug=tag_slug, name=tag_name, names_json={"en": tag_name})
                    self.db.add(genre)
                    self.db.flush()
                if genre not in series.genres:
                    series.genres.append(genre)

        # Sync episodes incrementally
        existing_ep_nums = {ep.num for ep in series.episodes}
        target_count = series.available_episodes if series.available_episodes > 0 else 1
        for ep_num in range(1, target_count + 1):
            if ep_num not in existing_ep_nums:
                ep = Episode(
                    series_id=series.id,
                    num=ep_num,
                    title=f"Episode {ep_num}",
                    titles_json={
                        "en": f"Episode {ep_num}",
                        "fr": f"Épisode {ep_num}",
                        "ar": f"الحلقة {ep_num}",
                    },
                    duration=120,
                    is_free=True,  # Default free, can be customized
                )
                self.db.add(ep)

        return series

    async def run_sync(
        self,
        sync_type: str = "light",
        max_pages: Optional[int] = None,
        target_slug: Optional[str] = None,
    ) -> Optional[SyncRun]:
        """Executes a synchronization run (full, light, or single). Returns None if one is already running."""
        if _sync_lock.locked():
            logger.info(f"Skipping {sync_type} sync: another sync is already running.")
            await self.scanner.close()
            return None
        async with _sync_lock:
            return await self._run_sync_locked(sync_type, max_pages, target_slug)

    async def _run_sync_locked(
        self,
        sync_type: str,
        max_pages: Optional[int],
        target_slug: Optional[str],
    ) -> SyncRun:
        run = SyncRun(
            sync_type=sync_type,
            target_slug=target_slug,
            status="running",
            started_at=datetime.datetime.utcnow(),
        )
        self.db.add(run)
        self.db.commit()

        try:
            if target_slug:
                s = await self.sync_single_series(target_slug)
                if s:
                    run.series_discovered = 1
                    run.series_updated = 1
                    run.episodes_synced = len(s.episodes)
                    run.status = "completed"
                else:
                    run.status = "failed"
                    run.errors_count = 1
                    run.log_messages = f"Series '{target_slug}' could not be fetched from the source."
            else:
                # Page limit based on sync type
                if sync_type == "light":
                    # Light sync: first 2 pages (~96 newest/updated series)
                    pages_to_crawl = max_pages or 2
                else:
                    # Full sync: crawl catalog pages (default 20 pages or configured max)
                    pages_to_crawl = max_pages or 20

                logger.info(f"Starting {sync_type} sync across {pages_to_crawl} pages...")
                
                discovered_source_ids = set()

                for page in range(1, pages_to_crawl + 1):
                    logger.info(f"Scanning catalog page {page}/{pages_to_crawl}...")
                    catalog_data = await self.scanner.fetch_catalog_page(page=page, limit=48, lang="en")
                    if not catalog_data or "data" not in catalog_data:
                        if page == 1:
                            raise RuntimeError(
                                "Source catalog unreachable (HTTP 403 = the source blocks this server's IP). "
                                "Set the SOURCE_PROXY environment variable to route requests through another IP."
                            )
                        logger.warning(f"No catalog data received for page {page}")
                        break

                    items = catalog_data.get("data", [])
                    if not items:
                        break

                    for item in items:
                        slug = item.get("slug")
                        source_id = str(item.get("id"))
                        discovered_source_ids.add(source_id)
                        try:
                            # Quick check: if series already exists and available_episodes matches, skip full detail fetch
                            existing = self.db.query(Series).filter_by(source_id=source_id).first()
                            new_avail = int(item.get("available_episodes") or item.get("total_episodes") or 0)
                            
                            if existing and existing.available_episodes >= new_avail and existing.local_cover:
                                run.series_updated += 1
                                continue

                            # Fetch full detail and multilingual info
                            detail = await self.scanner.fetch_series_multilingual(slug)
                            if detail:
                                series_obj = await self._upsert_series(detail)
                                run.series_discovered += 1
                                run.episodes_synced += len(series_obj.episodes)
                                self.db.commit()
                        except Exception as item_err:
                            logger.error(f"Error syncing series {slug}: {item_err}")
                            run.errors_count += 1

                run.status = "completed"
                logger.info(f"Sync completed: {run.series_discovered} processed, {run.errors_count} errors.")

        except Exception as e:
            logger.error(f"Sync run failed: {e}", exc_info=True)
            run.status = "failed"
            run.log_messages = str(e)
        finally:
            run.finished_at = datetime.datetime.utcnow()
            self.db.commit()
            await self.scanner.close()

        return run


async def main():
    parser = argparse.ArgumentParser(description="DramaBiliki Bridge Sync CLI")
    parser.add_argument("--full", action="store_true", help="Run full catalog synchronization")
    parser.add_argument("--light", action="store_true", help="Run light sync (first pages for latest series)")
    parser.add_argument("--series", type=str, help="Sync a specific series by its slug")
    parser.add_argument("--pages", type=int, default=None, help="Maximum number of pages to sync")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    service = SyncService(db)

    try:
        if args.series:
            await service.run_sync(sync_type="single", target_slug=args.series)
        elif args.full:
            await service.run_sync(sync_type="full", max_pages=args.pages or 15)
        else:
            # Default to light sync
            await service.run_sync(sync_type="light", max_pages=args.pages or 2)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
