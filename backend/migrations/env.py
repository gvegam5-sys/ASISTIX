"""Run migrations using explicitly selected SQLAlchemy metadata and connection."""
import os

from alembic import context
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app import models

url_value = os.environ.get("DATABASE_URL")
if not url_value:
    raise RuntimeError("Set DATABASE_URL explicitly before running Alembic.")

url = make_url(url_value)
metadata = models.Base.metadata


def migrate_offline():
    context.configure(
        url=url, target_metadata=metadata, literal_binds=True, compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_online():
    engine = create_engine(url, poolclass=NullPool)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=metadata, compare_server_default=True
            )
            with context.begin_transaction():
                if connection.dialect.name == "postgresql":
                    # Serialize Alembic commands until this migration transaction ends.
                    connection.execute(text("SELECT pg_advisory_xact_lock(1685174369, 1)"))
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    migrate_offline()
else:
    migrate_online()
