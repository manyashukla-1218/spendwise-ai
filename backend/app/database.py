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


def init_db():
    """Create tables and seed demo tenants."""
    from . import models  # noqa: F401  (register models)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for tid, name, key in config.DEMO_TENANTS:
            if not db.get(models.Tenant, tid):
                db.add(models.Tenant(id=tid, name=name, api_key=key))
        db.commit()
    finally:
        db.close()
