"""Shared helpers for tests that need a PostgreSQL server.

These tests use the server of the project configuration (factory.toml, PGPASSWORD,
PGPORT or DATABASE_URL) but never its real schemas: every test works in its own
temporary schema, dropped afterwards. Without a reachable server they are skipped, so
the rest of the suite still runs anywhere, offline.
"""
import functools
import unittest
import uuid
from pathlib import Path

from psycopg import sql
from sqlalchemy import text

from data_factory.config import load_config
from data_factory.db import make_engine, server_version
from data_factory.exceptions import DatabaseError

PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "factory.toml"


@functools.lru_cache(maxsize=1)
def database_reachable() -> bool:
    engine = make_engine(load_config(PROJECT_CONFIG).database)
    try:
        server_version(engine)
        return True
    except DatabaseError:
        return False
    finally:
        engine.dispose()


needs_database = unittest.skipUnless(database_reachable(), "no PostgreSQL server reachable")


class TemporarySchemaMixin:
    """self.engine and self.schema: a fresh schema for each test, dropped in tearDown."""

    def setUp(self):
        super().setUp()
        self.engine = make_engine(load_config(PROJECT_CONFIG).database)
        self.schema = f"test_{uuid.uuid4().hex[:10]}"

    def tearDown(self):
        with self.engine.begin() as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema)))
        self.engine.dispose()
        super().tearDown()

    def query(self, statement, **params):
        with self.engine.connect() as connection:
            connection.execute(text("SELECT set_config('search_path', :path, false)"), {"path": self.schema})
            return connection.execute(text(statement), params).all()
