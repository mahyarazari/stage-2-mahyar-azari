"""Database connection: one place that creates the engine and opens connections.

Rules (stage 2, part 8 of the task):
  - Connections are always opened with a context manager, so none is left open, even
    when a statement fails.
  - The engine is disposed when its owner is done with it (`database()` does this).
  - The password never appears in the code, the configuration or the logs (D39).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from data_factory.config import DatabaseConfig
from data_factory.exceptions import ConfigError, DatabaseError

log = logging.getLogger(__name__)


def safe_url(url: str) -> str:
    """The URL with any password hidden, for logs and error messages."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<unreadable database url>"


def make_engine(settings: DatabaseConfig) -> Engine:
    """Create the engine. Nothing connects yet: SQLAlchemy connects on first use."""
    try:
        return create_engine(settings.url, pool_pre_ping=True)
    except Exception as error:   # malformed URL, unknown driver
        raise ConfigError(f"cannot use database url {safe_url(settings.url)}: {error}") from None


@contextmanager
def database(settings: DatabaseConfig) -> Iterator[Engine]:
    """An engine for the duration of a `with` block; its connection pool is closed afterwards."""
    engine = make_engine(settings)
    try:
        yield engine
    finally:
        engine.dispose()


def server_version(engine: Engine) -> str:
    """Connect once and return the server's version text; a clear DatabaseError if it fails."""
    try:
        with engine.connect() as connection:
            return connection.execute(text("select version()")).scalar_one()
    except SQLAlchemyError as error:
        raise DatabaseError(f"cannot connect to {safe_url(str(engine.url))}: "
                            f"{error.__class__.__name__}: {error.orig or error}") from None


def ensure_database(settings: DatabaseConfig) -> bool:
    """Create the database of the URL if the server does not have it yet. True if created.

    CREATE DATABASE cannot run inside a transaction or while connected to that database,
    so it runs in autocommit mode from the maintenance database. The name is composed as
    an identifier (psycopg.sql), never pasted into the statement.
    """
    url = make_url(settings.url)
    admin = create_engine(url.set(database=settings.maintenance_database), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            found = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"),
                                       {"name": url.database}).first()
            if found:
                return False
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))
            log.info("created database %s", url.database)
            return True
    except (SQLAlchemyError, psycopg.Error) as error:
        raise DatabaseError(f"cannot create database {url.database} on {safe_url(settings.url)}: "
                            f"{error.__class__.__name__}: {getattr(error, 'orig', None) or error}") from None
    finally:
        admin.dispose()
