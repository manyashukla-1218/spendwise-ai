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
    A database created earlier by `create_all` (no alembic_version table) is adopted ("stamped") instead of re-created."""
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
    """Apply migrations; create tenants and, if SEED_DEMO is on, demo users and demo API keys."""
    from . import models
    from .security import hash_api_key, hash_password

    run_migrations()
    db = SessionLocal()
    try:
        if config.SEED_DEMO:
            for tid, name, key in config.DEMO_TENANTS:
                if not db.get(models.Tenant, tid):
                    db.add(models.Tenant(id=tid, name=name))
            db.commit()
            pw_hash = None
            for tid, name, key in config.DEMO_TENANTS:
                if not db.query(models.ApiKey).filter_by(key_hash=hash_api_key(key)).first():
                    db.add(models.ApiKey(tenant_id=tid, name="demo-admin-key", prefix=key[:10],
                                         key_hash=hash_api_key(key), role="admin"))
                for role in ("admin", "analyst", "viewer"):
                    email = f"{role}@{tid}.demo"
                    if not db.query(models.User).filter_by(email=email).first():
                        pw_hash = pw_hash or hash_password(config.DEMO_USER_PASSWORD)
                        db.add(models.User(tenant_id=tid, email=email, password_hash=pw_hash, role=role))
            db.commit()
    finally:
        db.close()
