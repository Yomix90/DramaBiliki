import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bridge.database import SessionLocal
from bridge.sync import SyncService

logger = logging.getLogger("bridge.scheduler")

scheduler = AsyncIOScheduler()

async def scheduled_light_sync():
    """Runs light sync every 30 minutes to capture newly published episodes and series."""
    logger.info("Executing scheduled light sync (30-minute interval)...")
    db = SessionLocal()
    service = SyncService(db)
    try:
        await service.run_sync(sync_type="light", max_pages=3)
    except Exception as e:
        logger.error(f"Error in scheduled light sync: {e}")
    finally:
        db.close()

async def scheduled_full_sync():
    """Runs complete catalog sync daily at 03:00 UTC."""
    logger.info("Executing scheduled full catalog sync (daily 03:00 UTC)...")
    db = SessionLocal()
    service = SyncService(db)
    try:
        await service.run_sync(sync_type="full", max_pages=25)
    except Exception as e:
        logger.error(f"Error in scheduled full sync: {e}")
    finally:
        db.close()

def start_scheduler():
    """Initializes and starts the background job scheduler."""
    if not scheduler.running:
        scheduler.add_job(
            scheduled_light_sync,
            trigger=IntervalTrigger(minutes=30),
            id="job_light_sync",
            replace_existing=True,
        )
        scheduler.add_job(
            scheduled_full_sync,
            trigger=CronTrigger(hour=3, minute=0),
            id="job_full_sync",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Background sync scheduler successfully started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background sync scheduler stopped.")
