from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from umami_api.models import Base


def test_migrations_match_models_exactly(database_url):
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        tables = set(inspect(connection).get_table_names())
    engine.dispose()
    assert {"alembic_version", *Base.metadata.tables} == tables


def test_requirements_export_matches_lock():
    """Render installs services/api/requirements.txt; it must be the frozen lock export."""
    import subprocess
    from pathlib import Path
    api = Path(__file__).resolve().parents[1]
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
         "--no-header", "--project", str(api)],
        check=True, capture_output=True, text=True).stdout
    assert (api / "requirements.txt").read_text() == exported
