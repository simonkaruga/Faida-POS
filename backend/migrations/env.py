"""Migrations run the same way on the counter and in the cloud."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.models import Base
from app.settings.config import get_config

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

url = context.config.attributes.get("database_url") or get_config().database_url

with create_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
