from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from bridge.config import settings

# Engine configuration with foreign keys support in SQLite
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Columns added after the first release: create_all() does not alter existing tables.
_ADDED_COLUMNS = {
    "series": {
        "source_type": "VARCHAR(32) DEFAULT 'web'",
        "tg_channel_id": "INTEGER",
    },
    "episodes": {
        "tg_peer_id": "BIGINT",
        "tg_message_id": "BIGINT",
        "file_size": "BIGINT DEFAULT 0",
        "mime_type": "VARCHAR(64) DEFAULT ''",
    },
}


def _migrate():
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db():
    from bridge import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate()
