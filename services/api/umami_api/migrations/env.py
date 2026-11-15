"""Alembic environment. The URL is supplied by umami_api.migrate, never from a file."""
from alembic import context

from umami_api.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    from sqlalchemy import create_engine
    engine = create_engine(config.get_main_option("sqlalchemy.url"),
                           connect_args={"prepare_threshold": None})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline SQL generation is not supported; review migrations in source.")
run_migrations_online()
