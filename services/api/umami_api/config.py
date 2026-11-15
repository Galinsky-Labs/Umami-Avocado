"""Runtime settings read once from the environment.

Safety switches are fail-closed: live laboratory submission cannot be enabled in
this codebase because no supervised adapter exists yet (UA-013/UA-027).
"""
import os
import re
from dataclasses import dataclass

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"", "0", "false", "no", "off"}


class ConfigurationError(ValueError):
    """Raised for unsafe or malformed configuration. Never includes the value."""


def _flag(name: str) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} must be a boolean flag.")


def normalize_database_url(url: str) -> str:
    """Accept provider URLs (postgres://, postgresql://) and select the psycopg 3 driver."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    if url.startswith("postgresql+psycopg://"):
        return url
    raise ConfigurationError("DATABASE_URL must be a PostgreSQL URL.")


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str | None
    migration_database_url: str | None
    bootstrap_token: str | None
    cors_origins: tuple[str, ...]
    lab_live_submission_enabled: bool
    max_authorized_spend_cents: int


def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "development")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", environment):
        raise ValueError("APP_ENV must be a public deployment label.")
    if _flag("LAB_LIVE_SUBMISSION_ENABLED"):
        raise ConfigurationError(
            "LAB_LIVE_SUBMISSION_ENABLED must remain false: no supervised laboratory adapter exists."
        )
    raw_url = os.getenv("DATABASE_URL", "").strip()
    database_url = normalize_database_url(raw_url) if raw_url else None
    raw_migration = os.getenv("DATABASE_MIGRATION_URL", "").strip()
    migration_url = normalize_database_url(raw_migration) if raw_migration else database_url
    bootstrap = os.getenv("UMAMI_BOOTSTRAP_TOKEN", "").strip() or None
    if bootstrap is not None and len(bootstrap) < 32:
        raise ConfigurationError("UMAMI_BOOTSTRAP_TOKEN must be at least 32 characters.")
    origins = tuple(
        origin.strip().rstrip("/") for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    )
    for origin in origins:
        if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?", origin):
            raise ConfigurationError("CORS_ALLOW_ORIGINS must list exact http(s) origins.")
    spend = os.getenv("LAB_MAX_AUTHORIZED_SPEND_USD", "0").strip() or "0"
    if not re.fullmatch(r"[0-9]{1,9}", spend):
        raise ConfigurationError("LAB_MAX_AUTHORIZED_SPEND_USD must be a whole number of dollars.")
    return Settings(
        environment=environment, database_url=database_url, migration_database_url=migration_url,
        bootstrap_token=bootstrap, cors_origins=origins, lab_live_submission_enabled=False,
        max_authorized_spend_cents=int(spend) * 100,
    )
