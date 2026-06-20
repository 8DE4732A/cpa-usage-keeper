"""Database initialization and session management."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import event, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Config
from .models import Base

_engine = None
_SessionLocal = None

# ── Lightweight auto-migration ──────────────────────────────────────────────
# Keyed by table name; each entry is a list of (column_name, sql_type_def).
# Only nullable or default-valued columns can be added this way.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "model_price_settings": [
        ("openrouter_model_id", "VARCHAR"),
        ("openrouter_prompt_price_per_1m", "FLOAT"),
        ("openrouter_completion_price_per_1m", "FLOAT"),
        ("openrouter_cache_price_per_1m", "FLOAT"),
    ],
}


def _auto_migrate(engine) -> None:
    """Add missing columns for known tables without dropping existing data."""
    with engine.connect() as conn:
        for table_name, columns in _MIGRATIONS.items():
            # Get existing column names from SQLite pragma
            existing = {
                row[1]
                for row in conn.execute(
                    text(f"PRAGMA table_info({table_name})")
                ).fetchall()
            }
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {col_name} {col_type} NULL"
                        )
                    )
        conn.commit()


# ── Initialization ──────────────────────────────────────────────────────────

def init_database(cfg: Config) -> None:
    """Initialize the SQLite database with WAL mode and auto-migrate."""
    global _engine, _SessionLocal

    db_path = Path(cfg.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    dsn = f"sqlite:///{db_path}?check_same_thread=False"
    _engine = create_engine(dsn, pool_size=1, max_overflow=0, echo=False)

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=_engine)
    _auto_migrate(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_session() -> Session:
    """Get a new database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized")
    return _SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    """Get the SQLAlchemy engine."""
    return _engine


def close_database() -> None:
    """Close the database engine."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None
