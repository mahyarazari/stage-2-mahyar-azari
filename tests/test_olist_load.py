"""Olist validate + load into a temporary schema (needs PostgreSQL, else skipped)."""
import dataclasses
import logging
import tempfile
import unittest
from pathlib import Path

from data_factory import olist_pipeline, pipeline
from data_factory.config import load_config
from tests.db_helpers import PROJECT_CONFIG, TemporarySchemaMixin, needs_database
from tests.olist_fixtures import base_rows, write_files

PROJECT_ROOT = PROJECT_CONFIG.parent


@needs_database
class OlistLoadTests(TemporarySchemaMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "factory.toml").write_text(PROJECT_CONFIG.read_text("utf-8"), "utf-8")
        config = load_config(root / "factory.toml")
        load = config.olist.load
        moved = lambda paths: tuple(PROJECT_ROOT / p.relative_to(root) for p in paths)   # noqa: E731
        self.config = dataclasses.replace(config, olist=dataclasses.replace(config.olist, load=dataclasses.replace(
            load, schema=self.schema, before_load=moved(load.before_load), after_load=moved(load.after_load))))
        write_files(olist_pipeline.raw_dir(self.config), base_rows())

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)
        super().tearDown()

    def run_stages(self, stages):
        context = pipeline.RunContext(config=self.config)
        olist_pipeline.run(context, stages)
        return context.record

    def test_tables_are_typed_and_missing_lookups_are_completed(self):
        record = self.run_stages(["validate", "load"])
        self.assertEqual(record.load["inferred_parents"], {"categories": 1, "zip_codes": 1})
        zips = {r.zip_code_prefix: r for r in self.query(
            "SELECT zip_code_prefix, latitude, points, is_inferred FROM zip_codes")}
        self.assertEqual(zips["01037"].points, 3)
        self.assertAlmostEqual(zips["01037"].latitude, -23.55)      # median of the two points in Brazil
        self.assertTrue(zips["99999"].is_inferred)
        review = self.query("SELECT comment_message FROM order_reviews")[0]
        self.assertEqual(review.comment_message, 'bom, "rapido"\nchegou')   # quotes and newline survive COPY
        money = self.query("SELECT sum(price) AS total FROM order_items")[0].total
        self.assertEqual(str(money), "129.99")                       # numeric: exact

    def test_loading_twice_keeps_the_same_rows(self):
        self.run_stages(["validate", "load"])
        first = self.query("SELECT order_id, status FROM orders ORDER BY order_id")
        self.run_stages(["load"])
        self.assertEqual(self.query("SELECT order_id, status FROM orders ORDER BY order_id"), first)
        self.assertEqual(self.query("SELECT count(*) AS n FROM load_runs")[0].n, 2)

    def test_flags_are_computed_by_the_database(self):
        rows = base_rows()
        rows["orders"][0]["order_delivered_carrier_date"] = "2017-10-01 00:00:00"   # before purchase
        write_files(olist_pipeline.raw_dir(self.config), rows)
        self.run_stages(["validate", "load"])
        flagged = self.query("SELECT count(*) AS n FROM orders WHERE flag_carrier_before_purchase")[0].n
        self.assertEqual(flagged, 1)


if __name__ == "__main__":
    unittest.main()
