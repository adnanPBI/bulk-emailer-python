import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Type

from sqlalchemy import create_engine, text
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker

from database import (
    Base,
    SessionLocal,
    engine as postgres_engine,
    get_database_url,
    Setting,
    SMTPAccount,
    APIProvider,
    IMAPAccount,
    Campaign,
    Recipient,
    SendLog,
    BounceRecord,
    Suppression,
    EmailTemplate,
    SeedTest,
    SeedTestResult,
    create_tables,
)


MIGRATION_MARKER_KEY = "migration.sqlite_to_postgres.completed"


@dataclass(frozen=True)
class MigrationConfig:
    sqlite_path: str
    delete_source_sqlite: bool = False
    truncate_target: bool = False


MODEL_ORDER: List[Type[Any]] = [
    SMTPAccount,
    APIProvider,
    IMAPAccount,
    Campaign,
    Recipient,
    SendLog,
    BounceRecord,
    Suppression,
    EmailTemplate,
    Setting,
    SeedTest,
    SeedTestResult,
]


def _model_to_dict(obj: Any) -> Dict[str, Any]:
    mapper = sa_inspect(obj).mapper
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}


def _iter_rows(session: Session, model: Type[Any], chunk_size: int) -> Iterable[List[Dict[str, Any]]]:
    batch: List[Dict[str, Any]] = []
    for obj in session.query(model).yield_per(chunk_size):
        batch.append(_model_to_dict(obj))
        if len(batch) >= chunk_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _postgres_truncate_all(conn) -> None:
    table_names = [m.__tablename__ for m in MODEL_ORDER]
    joined = ", ".join(f'"{name}"' for name in table_names)
    conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


def _postgres_reset_sequences(conn) -> None:
    for model in MODEL_ORDER:
        table = model.__tablename__
        conn.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence(:table_name, 'id'),
                    COALESCE((SELECT MAX(id) FROM """ + f'"{table}"' + """), 1),
                    true
                )
                """
            ),
            {"table_name": table},
        )


def _target_has_any_data(db: Session) -> bool:
    # Quick signal: if any campaign exists, treat as non-empty.
    return db.query(Campaign.id).limit(1).first() is not None


def migrate_sqlite_to_postgres(
    sqlite_path: str,
    *,
    delete_source_sqlite: bool = False,
    truncate_target: bool = False,
    chunk_size: int = 1000,
) -> Dict[str, int]:
    """
    Migrate all ORM tables from a legacy SQLite database file into the configured PostgreSQL database.

    This expects the SQLite DB schema to match the SQLAlchemy models in `database.py`.
    """
    if not sqlite_path:
        raise ValueError("sqlite_path is required")
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database file not found: {sqlite_path}")

    # Ensure target tables exist.
    create_tables()

    # Create a separate session against the legacy SQLite file.
    sqlite_engine = create_engine(
        f"sqlite+pysqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SqliteSessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)

    counts: Dict[str, int] = {}

    with SessionLocal() as target_db:
        if (not truncate_target) and target_db.query(Setting).filter(Setting.key == MIGRATION_MARKER_KEY).first():
            return {"skipped": 1}

        if _target_has_any_data(target_db) and not truncate_target:
            raise RuntimeError(
                "Target PostgreSQL DB is not empty; set MIGRATE_TRUNCATE_TARGET=1 (or pass truncate_target=True) "
                "to wipe it before migration."
            )

    # Migration copy phase.
    with SqliteSessionLocal() as source_db, SessionLocal() as target_db:
        if truncate_target:
            with postgres_engine.begin() as conn:
                _postgres_truncate_all(conn)

        for model in MODEL_ORDER:
            table_name = model.__tablename__
            total_for_table = 0
            for chunk in _iter_rows(source_db, model, chunk_size=chunk_size):
                target_db.bulk_insert_mappings(model, chunk)
                target_db.commit()
                total_for_table += len(chunk)
            counts[table_name] = total_for_table

        # Marker setting (after successful copy).
        marker = target_db.query(Setting).filter(Setting.key == MIGRATION_MARKER_KEY).first()
        if not marker:
            target_db.add(
                Setting(
                    key=MIGRATION_MARKER_KEY,
                    value=json_dumps(
                        {
                            "completed_at": datetime.utcnow().isoformat(),
                            "source_sqlite_path": sqlite_path,
                            "target_database_url": get_database_url(),
                        }
                    ),
                    description="Auto-migration marker for SQLite -> PostgreSQL",
                )
            )
            target_db.commit()

    with postgres_engine.begin() as conn:
        _postgres_reset_sequences(conn)

    if delete_source_sqlite:
        os.remove(sqlite_path)

    return counts


def migrate_sqlite_to_postgres_if_configured() -> Optional[Dict[str, int]]:
    """
    Run migration on app startup if MIGRATE_FROM_SQLITE_PATH is set.

    Env vars:
      - MIGRATE_FROM_SQLITE_PATH: path to legacy bulk_email.db (or any sqlite file)
      - MIGRATE_DELETE_SOURCE: "1" to delete the sqlite file after successful migration
      - MIGRATE_TRUNCATE_TARGET: "1" to truncate the Postgres DB before migrating
    """
    sqlite_path = os.getenv("MIGRATE_FROM_SQLITE_PATH")
    if not sqlite_path:
        return None

    delete_source = os.getenv("MIGRATE_DELETE_SOURCE", "0") == "1"
    truncate_target = os.getenv("MIGRATE_TRUNCATE_TARGET", "0") == "1"
    return migrate_sqlite_to_postgres(
        sqlite_path,
        delete_source_sqlite=delete_source,
        truncate_target=truncate_target,
    )


def json_dumps(obj: Any) -> str:
    # Local helper to avoid importing json at module import time in some environments.
    import json

    return json.dumps(obj, ensure_ascii=False)
