"""
Full backup / restore of the bridge, to move to another VPS.

A backup is a .zip containing:
  - dramabiliki.db   consistent SQLite snapshot (series, episodes, users, settings,
                     Telegram session...)
  - .secret_key      so user and admin tokens stay valid on the new server
  - covers/          cached cover images (optional, small)
  - videos/          videos stored on the VPS disk (optional, can be large)
  - manifest.json    version and counts

Restoring validates the archive first, keeps a copy of the current database in
DATA_DIR/backups/, then swaps the database file in place.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from bridge.config import settings

REQUIRED_TABLES = {"series", "episodes", "users"}
BACKUP_DB_NAME = "dramabiliki.db"


class BackupError(Exception):
    pass


def sqlite_path() -> Optional[Path]:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///"):])


def _snapshot(dest: Path) -> None:
    """Consistent copy of the live database, even while it is being written."""
    source = sqlite3.connect(str(sqlite_path()))
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _counts(db_file: Path) -> dict:
    conn = sqlite3.connect(str(db_file))
    try:
        out = {}
        for table in ("series", "episodes", "users", "telegram_channels"):
            try:
                out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                out[table] = 0
        return out
    finally:
        conn.close()


def create_backup(include_covers: bool = True, include_videos: bool = False) -> Path:
    """Builds the backup archive in a temp folder and returns its path."""
    if sqlite_path() is None:
        raise BackupError("La sauvegarde intégrée ne prend en charge que SQLite.")
    work = Path(tempfile.mkdtemp(prefix="dramabiliki-backup-"))
    db_copy = work / BACKUP_DB_NAME
    _snapshot(db_copy)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    archive = work / f"dramabiliki-backup-{stamp}.zip"
    manifest = {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "counts": _counts(db_copy),
        "covers": include_covers,
        "videos": include_videos,
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.write(db_copy, BACKUP_DB_NAME)
        secret = settings.DATA_DIR / ".secret_key"
        if secret.is_file():
            zf.write(secret, ".secret_key")
        if include_covers and settings.COVERS_DIR.is_dir():
            for f in settings.COVERS_DIR.glob("*.webp"):
                zf.write(f, f"covers/{f.name}")
        videos_dir = settings.MEDIA_DIR / "videos" / "local"
        if include_videos and videos_dir.is_dir():
            for f in videos_dir.iterdir():
                if f.is_file():
                    # videos are already compressed
                    zf.write(f, f"videos/{f.name}", compress_type=zipfile.ZIP_STORED)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    db_copy.unlink(missing_ok=True)
    return archive


def _validate_db(db_file: Path) -> dict:
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise BackupError(f"Ce fichier n'est pas une base SQLite valide ({e}).")
    missing = REQUIRED_TABLES - tables
    if missing:
        raise BackupError(f"Ce n'est pas une base DramaBiliki (tables manquantes : {', '.join(sorted(missing))}).")
    if check != "ok":
        raise BackupError(f"La base est endommagée ({check}).")
    return _counts(db_file)


def restore_backup(upload: Path) -> dict:
    """Replaces the current data with the uploaded .zip (or bare .db). Returns a summary."""
    target = sqlite_path()
    if target is None:
        raise BackupError("La restauration intégrée ne prend en charge que SQLite.")

    work = Path(tempfile.mkdtemp(prefix="dramabiliki-restore-"))
    try:
        new_db = work / BACKUP_DB_NAME
        secret: Optional[bytes] = None
        covers, videos = [], []
        if zipfile.is_zipfile(upload):
            with zipfile.ZipFile(upload) as zf:
                names = zf.namelist()
                db_name = BACKUP_DB_NAME if BACKUP_DB_NAME in names else next((n for n in names if n.endswith((".db", ".sqlite", ".sqlite3"))), None)
                if db_name is None:
                    raise BackupError("Aucune base de données trouvée dans l'archive.")
                with zf.open(db_name) as src, open(new_db, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if ".secret_key" in names:
                    secret = zf.read(".secret_key").strip()
                for name in names:
                    base = Path(name).name
                    if name.startswith("covers/") and base.endswith(".webp") and "/" not in name[len("covers/"):]:
                        covers.append(name)
                    elif name.startswith("videos/") and base and "/" not in name[len("videos/"):]:
                        videos.append(name)
                counts = _validate_db(new_db)
                _swap_database(new_db, target)
                settings.COVERS_DIR.mkdir(parents=True, exist_ok=True)
                for name in covers:
                    with zf.open(name) as src, open(settings.COVERS_DIR / Path(name).name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                videos_dir = settings.MEDIA_DIR / "videos" / "local"
                if videos:
                    videos_dir.mkdir(parents=True, exist_ok=True)
                for name in videos:
                    with zf.open(name) as src, open(videos_dir / Path(name).name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            shutil.copyfile(upload, new_db)
            counts = _validate_db(new_db)
            _swap_database(new_db, target)

        if secret:
            (settings.DATA_DIR / ".secret_key").write_bytes(secret)
            settings.SECRET_KEY = secret.decode()
        return {"counts": counts, "covers": len(covers), "videos": len(videos), "secret_restored": bool(secret)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _swap_database(new_db: Path, target: Path) -> None:
    from bridge.database import engine, init_db

    backups = settings.DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    engine.dispose()  # close pooled connections to the old file
    if target.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(target, backups / f"before-restore-{stamp}.db")
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    shutil.copyfile(new_db, target)
    engine.dispose()
    init_db()  # adds columns introduced after the backup was made
