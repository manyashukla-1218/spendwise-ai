"""Alembic environment. Uses the app's models and DATABASE_URL, so `alembic upgrade head`,
`alembic revision --autogenerate` and the app's own start-up migration all see the same schema.
"""

from alembic import context
from sqlalchemy import create_engine

from backend.app import config as app_config
from backend.app import models  # noqa: F401  (registers all tables on Base.metadata)
from backend.app.database import Base

alembic_config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return alembic_config.get_main_option("sqlalchemy.url") or app_config.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=_url().startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
