from alembic import context

from ml_criterion.config import Settings
from ml_criterion.persistence.db import create_sessions
from ml_criterion.persistence.models import Base


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=Settings().metadata_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    migrate(context.config.attributes["connection"])
else:
    engine, _ = create_sessions(Settings().metadata_url)
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()
