import asyncio
from typing import Callable, List, Tuple
from sqlalchemy import inspect, text, Connection
from app.database import engine


def migration_001_add_current_track_to_stations(conn: Connection) -> None:
    inspector = inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("stations")}
    if "current_track" not in existing_columns:
        conn.execute(text("ALTER TABLE stations ADD COLUMN current_track JSON;"))


def run_migrations(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(128) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    )
    result = conn.execute(text("SELECT version FROM schema_migrations;"))
    applied = {row[0] for row in result.fetchall()}

    migrations: List[Tuple[str, Callable[[Connection], None]]] = [
        ("001_add_current_track_to_stations", migration_001_add_current_track_to_stations),
    ]

    for version, migration_fn in migrations:
        if version not in applied:
            migration_fn(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version);"),
                {"version": version}
            )


async def run_async_migrations() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)


if __name__ == "__main__":
    asyncio.run(run_async_migrations())
