"""Apply database migrations: ``python -m umami_api.migrate`` (run before the API starts).

Uses DATABASE_MIGRATION_URL (direct, non-pooled) when set, else DATABASE_URL.
A PostgreSQL advisory lock serialises concurrent starts.
"""
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from umami_api.config import load_settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
LOCK_KEY = 74_210_003


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    engine = create_engine(url, connect_args={"prepare_threshold": None, "connect_timeout": 15})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
            try:
                config = alembic_config(url)
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
                connection.commit()
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                connection.commit()
    finally:
        engine.dispose()


def main() -> int:
    settings = load_settings()
    if not settings.migration_database_url:
        print("DATABASE_URL is not configured; skipping migrations (foundation-only mode).")
        return 0
    upgrade(settings.migration_database_url)
    print("Database migrations applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
