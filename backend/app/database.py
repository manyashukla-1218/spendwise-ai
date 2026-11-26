from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

_is_sqlite = config.DATABASE_URL.startswith("sqlite")
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(url: str | None = None):
    """Bring the database schema to the latest Alembic revision.
    A database created earlier by `create_all` (no alembic_version table) is adopted ("stamped") instead of re-created.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    target = url or config.DATABASE_URL
    cfg = Config(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", target.replace("%", "%%"))
    probe = create_engine(target)
    try:
        tables = set(inspect(probe).get_table_names())
    finally:
        probe.dispose()
    if "tenants" in tables and "alembic_version" not in tables:
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def init_db():
    """Apply migrations and seed demo tenants."""
    from . import models

    run_migrations()
    db = SessionLocal()
    try:
        for tid, name, key in config.DEMO_TENANTS:
            if not db.get(models.Tenant, tid):
                db.add(models.Tenant(id=tid, name=name, api_key=key))
        db.commit()
    finally:
        db.close()
