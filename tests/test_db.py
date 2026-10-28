"""Tests for the database settings and connection helpers. No database server is needed."""
import os
import unittest
from pathlib import Path
from unittest import mock

from data_factory import cli
from data_factory.config import DATABASE_URL_ENV, DatabaseConfig, load_config
from data_factory.db import database, make_engine, safe_url, server_version
from data_factory.exceptions import ConfigError, DatabaseError, ExitCode
from tests.test_config import ConfigFileMixin, PROJECT_CONFIG

# Nothing listens on port 1: connecting fails at once, without any network.
UNREACHABLE = "postgresql+psycopg://someone:secret@127.0.0.1:1/nothing?connect_timeout=2"


class DatabaseSettingsTests(ConfigFileMixin, unittest.TestCase):
    def test_url_comes_from_the_configuration_file(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DATABASE_URL_ENV, None)
            settings = load_config(PROJECT_CONFIG).database
        self.assertTrue(settings.url.startswith("postgresql+psycopg://"))
        self.assertEqual(settings.source, "factory.toml")

    def test_environment_variable_replaces_the_url(self):
        url = "postgresql+psycopg://evaluator@db.example:5433/other"
        with mock.patch.dict(os.environ, {DATABASE_URL_ENV: url}):
            settings = load_config(PROJECT_CONFIG).database
        self.assertEqual((settings.url, settings.source), (url, DATABASE_URL_ENV))

    def test_other_driver_is_refused(self):
        text = self.original.replace('url = "postgresql+psycopg://', 'url = "postgresql+psycopg2://')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DATABASE_URL_ENV, None)
            self.assert_config_error(text, "must start with")

    def test_missing_section_is_a_config_error(self):
        text = self.original.split("[database]")[0]
        self.assert_config_error(text, "missing section [database]")


class ConnectionHelperTests(unittest.TestCase):
    def test_safe_url_hides_the_password(self):
        shown = safe_url(UNREACHABLE)
        self.assertNotIn("secret", shown)
        self.assertIn("someone", shown)

    def test_engine_is_created_without_connecting(self):
        engine = make_engine(DatabaseConfig(url=UNREACHABLE, source="test"))
        try:
            self.assertEqual(engine.dialect.driver, "psycopg")
        finally:
            engine.dispose()

    def test_unreachable_server_is_a_database_error_without_password(self):
        with database(DatabaseConfig(url=UNREACHABLE, source="test")) as engine:
            with self.assertRaises(DatabaseError) as caught:
                server_version(engine)
        self.assertEqual(caught.exception.exit_code, ExitCode.DATABASE)
        self.assertNotIn("secret", str(caught.exception))

    def test_check_db_command_exits_with_the_database_code(self):
        with mock.patch.dict(os.environ, {DATABASE_URL_ENV: UNREACHABLE}):
            code = cli.main(["--config", str(PROJECT_CONFIG), "check-db"])
        self.assertEqual(code, ExitCode.DATABASE)


if __name__ == "__main__":
    unittest.main()
