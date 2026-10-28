"""Function, procedure, views and snapshot queries on controlled data (needs PostgreSQL)."""
import dataclasses
import logging
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from data_factory import olist_pipeline, pipeline
from data_factory.benchmark import DASHBOARD_QUERIES, query_text
from data_factory.config import load_config
from tests.db_helpers import PROJECT_CONFIG, TemporarySchemaMixin, needs_database
from tests.olist_fixtures import base_rows, write_files

PROJECT_ROOT = PROJECT_CONFIG.parent
PERIOD = {"start": datetime(2016, 1, 1), "end": datetime(2019, 1, 1), "top_n": 20}
COUNTS = {"snap_sales": "SELECT count(*) FROM snap_sales",
          "snap_delivery": "SELECT count(*) FROM snap_delivery",
          "snap_review_delay": "SELECT count(*) FROM snap_review_delay",
          "snap_sellers": "SELECT count(*) FROM snap_sellers",
          "snap_payments": "SELECT count(*) FROM snap_payments"}


@needs_database
class SnapshotTests(TemporarySchemaMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "factory.toml").write_text(PROJECT_CONFIG.read_text("utf-8"), "utf-8")
        config = load_config(root / "factory.toml")
        load = config.olist.load
        moved = lambda paths: tuple(PROJECT_ROOT / p.relative_to(root) for p in paths)   # noqa: E731
        config = dataclasses.replace(config, olist=dataclasses.replace(config.olist, load=dataclasses.replace(
            load, schema=self.schema, before_load=moved(load.before_load), after_load=moved(load.after_load))))
        write_files(olist_pipeline.raw_dir(config), base_rows())
        olist_pipeline.run(pipeline.RunContext(config=config), ["validate", "load"])

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)
        super().tearDown()

    def connect(self):
        connection = self.engine.connect()
        connection.execute(text("SELECT set_config('search_path', :path, false)"), {"path": self.schema})
        return connection

    def counts(self, connection):
        return {name: connection.execute(text(sql)).scalar_one() for name, sql in COUNTS.items()}

    def test_function_returns_the_band_inside_select(self):
        with self.connect() as c:
            bands = c.execute(text("SELECT delay_band(:a), delay_band(:b), delay_band(:c)"),
                              {"a": -8, "b": 0, "c": 20}).one()
        self.assertEqual(tuple(bands), ("2. 1-2 weeks early", "4. on the promised day",
                                        "8. more than 2 weeks late"))

    def test_procedure_twice_adds_nothing(self):
        with self.connect() as c:
            before = self.counts(c)
            c.execute(text("CALL refresh_month(:m)"), {"m": date(2017, 10, 1)})
            c.execute(text("CALL refresh_month(:m)"), {"m": date(2017, 10, 15)})   # same month
            c.commit()
            self.assertEqual(self.counts(c), before)

    def test_failure_inside_the_procedure_leaves_the_month_untouched(self):
        with self.connect() as c:
            before = self.counts(c)
            c.execute(text("ALTER TABLE snap_payments ADD CONSTRAINT fail_on_insert CHECK (payments < 0) NOT VALID"))
            c.commit()
            with self.assertRaises(DBAPIError):          # sales/delivery/... were already deleted
                c.execute(text("CALL refresh_month(:m)"), {"m": date(2017, 10, 1)})
            c.rollback()
            self.assertEqual(self.counts(c), before)

    def test_snapshot_queries_return_the_live_results(self):
        with self.connect() as c:
            for name in DASHBOARD_QUERIES:
                live = [tuple(map(str, r)) for r in c.execute(text(query_text(name)), PERIOD).all()]
                snap = [tuple(map(str, r)) for r in c.execute(text(query_text(f"{name}_snapshot")), PERIOD).all()]
                width = len(snap[0]) if snap else 0
                with self.subTest(query=name):
                    self.assertEqual([row[:width] for row in live], snap)

    def test_rewrite_and_view_return_the_original_q1(self):
        with self.connect() as c:
            results = [c.execute(text(query_text(n)), PERIOD).all() for n in (
                "q1_sales_by_month_category", "q1_sales_by_month_category_rewrite", "q1_sales_by_month_category_view")]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])


if __name__ == "__main__":
    unittest.main()
