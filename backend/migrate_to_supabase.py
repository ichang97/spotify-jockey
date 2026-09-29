import argparse
import asyncio
from datetime import datetime
import json
import os
import sys
from typing import Any, Dict, List
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import Base
from app.migrations import run_migrations
from app.models.station import Station
from app.models.auth import StationAuth
from app.models.track import TrackCache
from app.models.request import SongRequest
from app.models.chat import ChatMessage
from app.models.queue import StationQueueItem


def format_postgres_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.replace("sslmode=", "ssl=")
    return url


def find_sqlite_db(custom_path: str = "") -> str:
    if custom_path and os.path.exists(custom_path):
        return os.path.abspath(custom_path)
    candidates = [
        os.path.abspath("./data/spotify_jockey.db"),
        os.path.abspath("../data/spotify_jockey.db"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "spotify_jockey.db"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "spotify_jockey.db"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


async def prepare_target_schema(target_engine: AsyncEngine, clean: bool) -> None:
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_migrations)

    if clean:
        tables_to_truncate = [
            "station_queue",
            "chat_messages",
            "song_requests",
            "station_auth",
            "stations",
            "track_cache",
            "schema_migrations",
        ]
        async with target_engine.begin() as conn:
            for tbl in tables_to_truncate:
                await conn.execute(text(f"TRUNCATE TABLE {tbl} CASCADE;"))


def normalize_row_data(row: Dict[str, Any], table) -> Dict[str, Any]:
    json_cols = {c.name for c in table.columns if hasattr(c.type, "__visit_name__") and c.type.__visit_name__ == "json"}
    bool_cols = {c.name for c in table.columns if hasattr(c.type, "__visit_name__") and c.type.__visit_name__ == "boolean"}
    datetime_cols = {c.name for c in table.columns if hasattr(c.type, "__visit_name__") and c.type.__visit_name__ == "datetime"}

    clean_row = dict(row)
    for col in json_cols:
        val = clean_row.get(col)
        if isinstance(val, str):
            try:
                clean_row[col] = json.loads(val)
            except Exception:
                pass

    for col in bool_cols:
        val = clean_row.get(col)
        if val is not None and not isinstance(val, bool):
            clean_row[col] = bool(val)

    for col in datetime_cols:
        val = clean_row.get(col)
        if isinstance(val, str):
            try:
                clean_row[col] = datetime.fromisoformat(val)
            except Exception:
                pass

    return clean_row


async def sync_data(source_engine: AsyncEngine, target_engine: AsyncEngine) -> None:
    models_to_migrate = [
        Station,
        StationAuth,
        TrackCache,
        SongRequest,
        ChatMessage,
        StationQueueItem,
    ]

    for model in models_to_migrate:
        table = model.__table__
        table_name = table.name

        async with source_engine.connect() as s_conn:
            s_result = await s_conn.execute(select(table))
            source_rows = [normalize_row_data(dict(r), table) for r in s_result.mappings().all()]

        if source_rows:
            async with target_engine.begin() as t_conn:
                await t_conn.execute(insert(table), source_rows)

        async with target_engine.connect() as t_conn:
            t_count_res = await t_conn.execute(text(f"SELECT COUNT(*) FROM {table_name};"))
            target_count = t_count_res.scalar() or 0

        print(f"[{table_name}] Transferred: {len(source_rows)} rows | Target total: {target_count} rows")

    async with source_engine.connect() as s_conn:
        m_result = await s_conn.execute(text("SELECT version, applied_at FROM schema_migrations;"))
        m_rows = [dict(r) for r in m_result.mappings().all()]

    if m_rows:
        for r in m_rows:
            val = r.get("applied_at")
            if isinstance(val, str):
                try:
                    r["applied_at"] = datetime.fromisoformat(val)
                except Exception:
                    pass

        async with target_engine.begin() as t_conn:
            for r in m_rows:
                await t_conn.execute(
                    text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :applied_at) ON CONFLICT (version) DO NOTHING;"),
                    r
                )
        print(f"[schema_migrations] Transferred: {len(m_rows)} rows")

    seq_tables = ["stations", "station_auth", "song_requests", "chat_messages", "station_queue"]
    async with target_engine.begin() as t_conn:
        for tbl in seq_tables:
            await t_conn.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {tbl};")
            )
    print("PostgreSQL sequences have been reset successfully.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Spotify Jockey SQLite database to Supabase PostgreSQL")
    parser.add_argument("--source", type=str, default="", help="Path to local SQLite database file")
    parser.add_argument("--target", type=str, default="", help="Target Supabase connection string (URI)")
    parser.add_argument("--clean", action="store_true", help="Truncate target tables before migration")
    args = parser.parse_args()

    sqlite_path = find_sqlite_db(args.source)
    if not os.path.exists(sqlite_path):
        print(f"Error: SQLite database file not found at '{sqlite_path}'.")
        sys.exit(1)

    target_url = args.target or os.getenv("SUPABASE_DATABASE_URL") or os.getenv("TARGET_DATABASE_URL")
    if not target_url:
        target_url = input("Enter Supabase PostgreSQL connection string (URI): ").strip()

    if not target_url:
        print("Error: Target PostgreSQL URL is required.")
        sys.exit(1)

    target_pg_url = format_postgres_url(target_url)
    norm_sqlite_path = os.path.abspath(sqlite_path).replace("\\", "/")
    source_sqlite_url = f"sqlite+aiosqlite:///{norm_sqlite_path}"

    print(f"Source SQLite: {sqlite_path}")
    print(f"Target DB: {target_pg_url.split('@')[-1] if '@' in target_pg_url else target_pg_url}")

    source_engine = create_async_engine(source_sqlite_url, echo=False)
    target_engine = create_async_engine(target_pg_url, echo=False)

    try:
        print("Creating schema on Supabase...")
        await prepare_target_schema(target_engine, clean=args.clean)

        print("Transferring data...")
        await sync_data(source_engine, target_engine)

        print("Migration completed successfully!")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
