"""End-to-end test of the load stage: the stage-1 factory runs on a tiny raw snapshot, then
its outputs are loaded into a temporary PostgreSQL schema (skipped without a server)."""
import dataclasses
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data_factory import pipeline
from data_factory.exceptions import DatabaseError
from data_factory.manifest import MANIFEST_FILE
from data_factory.publish import CASES_FILE
from tests.db_helpers import PROJECT_CONFIG, TemporarySchemaMixin, needs_database
from tests.test_manifest import FakeSource, tiny_factory

PROJECT_ROOT = PROJECT_CONFIG.parent


@needs_database
class LoadStageTests(TemporarySchemaMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.config = tiny_factory(Path(self._tmp.name))
        load = self.config.load
        self.config = dataclasses.replace(self.config, load=dataclasses.replace(
            load, schema=self.schema,
            before_load=tuple(PROJECT_ROOT / p.relative_to(self.config.path.parent) for p in load.before_load),
            after_load=tuple(PROJECT_ROOT / p.relative_to(self.config.path.parent) for p in load.after_load)))
        with mock.patch.object(pipeline, "SocrataSource", FakeSource):
            pipeline.run(pipeline.RunContext(config=self.config), list(pipeline.FILE_STAGES))

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)
        super().tearDown()

    def load(self):
        pipeline.run(pipeline.RunContext(config=self.config), ["load"])
        return json.loads((self.config.paths.curated / MANIFEST_FILE).read_text("utf-8"))

    COUNTS = {"cases": "SELECT count(*) AS n FROM cases",
              "quarantine": "SELECT count(*) AS n FROM quarantine",
              "load_runs": "SELECT count(*) AS n FROM load_runs"}

    def count(self, table):
        return self.query(self.COUNTS[table])[0].n

    def test_outputs_are_loaded_with_types_and_a_run_row(self):
        manifest = self.load()
        with (self.config.paths.curated / CASES_FILE).open("rb") as handle:
            published = sum(1 for _ in handle) - 1
        self.assertEqual(self.count("cases"), published)
        self.assertEqual(self.count("quarantine"), 0)
        row = self.query("SELECT load_id, files FROM load_runs")[0]
        self.assertEqual(row.load_id, manifest["run"]["run_id"])
        self.assertEqual(row.files["cases"]["rows"], published)
        self.assertEqual(manifest["load"]["rows"]["cases"], published)
        month = self.query("SELECT DISTINCT created_month FROM cases")[0].created_month
        self.assertEqual(month.day, 1)

    def test_second_load_replaces_data_and_logs_a_second_run(self):
        self.load()
        first = self.query("SELECT * FROM cases ORDER BY unique_key")
        self.load()
        self.assertEqual(self.query("SELECT * FROM cases ORDER BY unique_key"), first)
        self.assertEqual(self.count("load_runs"), 2)

    def test_row_breaking_a_constraint_rolls_back_the_whole_load(self):
        self.load()
        before = self.count("cases")
        path = self.config.paths.curated / CASES_FILE
        text = path.read_text("utf-8")
        path.write_text(text.replace(",BRONX,", ",NOWHERE,", 1), "utf-8")
        with self.assertRaises(DatabaseError) as caught:
            pipeline.run(pipeline.RunContext(config=self.config), ["load"])
        self.assertIn("cases_borough_known", str(caught.exception))
        self.assertEqual(self.count("cases"), before)
        self.assertEqual(self.count("load_runs"), 1)


if __name__ == "__main__":
    unittest.main()
