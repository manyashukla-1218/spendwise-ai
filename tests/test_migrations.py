import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from backend.app import config
from backend.app import models  # noqa: F401
from backend.app.database import Base, run_migrations


def _url():
    return f"sqlite:///{tempfile.mkdtemp()}/m.db"


def _cfg(url):
    cfg = Config(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tables(url):
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migrations_create_every_model_table():
    url = _url()
    run_migrations(url)
    assert set(Base.metadata.tables) <= _tables(url)


def test_migrations_match_models_no_drift():
    """If someone edits models.py without writing a migration, this fails (alembic check)."""
    url = _url()
    run_migrations(url)
    command.check(_cfg(url))


def test_downgrade_then_upgrade_roundtrip():
    url = _url()
    run_migrations(url)
    command.downgrade(_cfg(url), "base")
    assert _tables(url) <= {"alembic_version"}
    run_migrations(url)
    assert set(Base.metadata.tables) <= _tables(url)


def test_existing_create_all_database_is_adopted_not_recreated():
    url = _url()
    eng = create_engine(url)
    Base.metadata.create_all(eng)  # a database from before migrations existed
    eng.dispose()
    run_migrations(url)  # must not fail with "table already exists"
    assert "alembic_version" in _tables(url)
