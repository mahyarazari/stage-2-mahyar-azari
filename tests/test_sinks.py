"""Tests for the sink layer: CSV (offline) and PostgreSQL (needs a server, else skipped)."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_factory.exceptions import DatabaseError
from data_factory.sinks import CsvSink, PostgresSink
from data_factory.tables import read_csv_text
from tests.db_helpers import TemporarySchemaMixin, needs_database

COLUMNS = ["id", "name"]


def frames(*rows_per_chunk):
    return [pd.DataFrame(rows, columns=COLUMNS) for rows in rows_per_chunk]


class CsvSinkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.sink = CsvSink(self.folder)

    def tearDown(self):
        self._tmp.cleanup()

    def test_table_is_written_from_several_chunks(self):
        with self.sink.session() as out:
            rows = out.replace_table("items", COLUMNS, frames([(1, "a")], [(2, "b"), (3, "c")]))
        self.assertEqual(rows, 3)
        self.assertEqual(list(read_csv_text(self.folder / "items.csv")["name"]), ["a", "b", "c"])

    def test_failed_session_leaves_no_file(self):
        with self.assertRaises(RuntimeError):
            with self.sink.session() as out:
                out.replace_table("items", COLUMNS, frames([(1, "a")]))
                raise RuntimeError("stop half-way")
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_append_keeps_earlier_rows(self):
        for name in ("a", "b"):
            with self.sink.session() as out:
                out.append_rows("log", pd.DataFrame([{"id": 1, "name": name}]))
        self.assertEqual(list(read_csv_text(self.folder / "log.csv")["name"]), ["a", "b"])


@needs_database
class PostgresSinkTests(TemporarySchemaMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.ddl = Path(self._tmp.name) / "tables.sql"
        self.ddl.write_text("CREATE TABLE IF NOT EXISTS items (id integer PRIMARY KEY, name text NOT NULL);\n"
                            "CREATE TABLE IF NOT EXISTS log (id integer, name text);\n", "utf-8")
        self.sink = PostgresSink(self.engine, self.schema, before=[self.ddl])

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def names(self):
        return [row.name for row in self.query("SELECT name FROM items ORDER BY id")]

    def test_rows_are_copied_and_schema_is_created(self):
        with self.sink.session() as out:
            rows = out.replace_table("items", COLUMNS, frames([(1, "a")], [(2, "b")]))
        self.assertEqual(rows, 2)
        self.assertEqual(self.names(), ["a", "b"])

    def test_loading_twice_gives_the_same_rows(self):
        for _ in range(2):
            with self.sink.session() as out:
                out.replace_table("items", COLUMNS, frames([(1, "a"), (2, "b")]))
        self.assertEqual(self.names(), ["a", "b"])

    def test_failure_rolls_back_and_keeps_previous_content(self):
        with self.sink.session() as out:
            out.replace_table("items", COLUMNS, frames([(1, "old")]))
        with self.assertRaises(DatabaseError):
            with self.sink.session() as out:
                out.replace_table("items", COLUMNS, frames([(1, "new"), (1, "duplicate key")]))
        self.assertEqual(self.names(), ["old"])

    def test_empty_text_becomes_null(self):
        with self.sink.session() as out:
            out.append_rows("log", pd.DataFrame({"id": [1], "name": pd.array([pd.NA], dtype="string")}))
        self.assertIsNone(self.query("SELECT name FROM log")[0].name)


if __name__ == "__main__":
    unittest.main()
