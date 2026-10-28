"""The dashboard queries on small, controlled data (needs PostgreSQL, else skipped),
and the timing helpers (offline)."""
import dataclasses
import logging
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from data_factory import olist_pipeline, pipeline
from data_factory.benchmark import percentile, plan_nodes, query_text
from data_factory.config import load_config
from tests.db_helpers import PROJECT_CONFIG, TemporarySchemaMixin, needs_database
from tests.olist_fixtures import base_rows, hexid, write_files

PROJECT_ROOT = PROJECT_CONFIG.parent
PERIOD = {"start": datetime(2016, 1, 1), "end": datetime(2019, 1, 1)}


class TimingHelperTests(unittest.TestCase):
    def test_percentile_is_an_observed_value(self):
        times = [float(v) for v in range(1, 21)]           # 1..20
        self.assertEqual(percentile(times, 0.95), 19.0)
        self.assertEqual(percentile(times, 0.5), 10.0)

    def test_plan_nodes_multiply_rows_by_loops(self):
        plan = {"Plan": {"Node Type": "Nested Loop", "Plan Rows": 5, "Actual Rows": 5, "Actual Loops": 1,
                         "Actual Total Time": 2.0, "Plans": [
                             {"Node Type": "Index Scan", "Relation Name": "orders", "Index Name": "orders_pkey",
                              "Plan Rows": 1, "Actual Rows": 1, "Actual Loops": 5, "Actual Total Time": 0.1}]}}
        nodes = list(plan_nodes(plan))
        self.assertEqual([n["depth"] for n in nodes], [0, 1])
        self.assertEqual((nodes[1]["index"], nodes[1]["actual_rows"]), ("orders_pkey", 5))

    def test_query_files_take_values_only_as_parameters(self):
        for name in ("q1_sales_by_month_category", "q2_late_delivery_by_state_month",
                     "q3_delay_vs_review_score", "q4_top_sellers", "q5_payments_by_installments"):
            sql_text = query_text(name)
            self.assertIn(":start", sql_text)
            self.assertNotIn("2017-", sql_text)


@needs_database
class DashboardQueryTests(TemporarySchemaMixin, unittest.TestCase):
    """Fixture (tests/olist_fixtures.py): order 31 delivered on time, 29.99 of perfumery,
    review 4; order 32 shipped, 100.00 of a category without translation, no review."""

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

    def run_query(self, name, **extra):
        with self.engine.connect() as connection:
            connection.execute(text("SELECT set_config('search_path', :path, false)"), {"path": self.schema})
            return connection.execute(text(query_text(name)), {**PERIOD, **extra}).all()

    def test_q1_sales_per_month_and_category(self):
        rows = self.run_query("q1_sales_by_month_category")
        self.assertEqual([(str(r.month), r.category, r.sales_value, r.orders) for r in rows],
                         [("2017-10-01", "perfumery", Decimal("29.99"), 1),
                          ("2018-01-01", "pc_gamer", Decimal("100.00"), 1)])   # no translation: own name

    def test_q2_only_delivered_orders_are_measured(self):
        rows = self.run_query("q2_late_delivery_by_state_month")
        self.assertEqual([(r.state, r.delivered_orders, r.late_orders) for r in rows], [("SP", 1, 0)])

    def test_q3_delay_band(self):
        rows = self.run_query("q3_delay_vs_review_score")
        self.assertEqual([(r.delay_band, r.orders, r.avg_score) for r in rows],
                         [("2. 1-2 weeks early", 1, Decimal("4.00"))])        # 8 days early

    def test_q4_preparation_and_score(self):
        rows = self.run_query("q4_top_sellers", top_n=20)
        self.assertEqual(len(rows), 1)
        seller = rows[0]
        self.assertEqual(str(seller.seller_id).replace("-", ""), hexid(11))
        self.assertEqual((seller.sales_value, seller.orders), (Decimal("129.99"), 2))
        self.assertEqual(seller.avg_preparation_days, Decimal("2.37"))     # 02 11:07:15 -> 04 19:55
        self.assertEqual(seller.avg_review_score, Decimal("4.00"))         # order 32 has no review

    def test_q5_payment_shares(self):
        rows = {r.payment_type: r for r in self.run_query("q5_payments_by_installments")}
        self.assertEqual(rows["boleto"].pct_of_payments, Decimal("50.00"))
        self.assertEqual(rows["credit_card"].avg_order_value, Decimal("29.99"))


if __name__ == "__main__":
    unittest.main()
