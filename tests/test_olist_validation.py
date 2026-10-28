"""Tests for the Olist contract and the table validation engine (offline)."""
import json
import logging
import tempfile
import unittest
from pathlib import Path

from data_factory.exceptions import QuarantineThresholdError, SourceSchemaChangedError
from data_factory.olist_contract import TABLES
from data_factory.table_validation import QUARANTINE_FILE, validate_tables
from data_factory.tables import read_csv_text
from tests.olist_fixtures import base_rows, hexid, write_files

BOUNDS = {"latitude": (-34.0, 5.5), "longitude": (-74.5, -34.5)}


class OlistValidationTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.raw, self.work, self.quarantine = root / "raw", root / "work", root / "quarantine"
        self.rows = base_rows()

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def run_engine(self, chunk_rows=1000, max_ratio=1.0, drop_column=None):
        write_files(self.raw, self.rows, drop_column)
        return validate_tables(TABLES, self.raw, self.work, self.quarantine, chunk_rows, max_ratio, BOUNDS)

    def accepted(self, table):
        return read_csv_text(self.work / f"{table}.csv")

    def quarantined(self):
        frame = read_csv_text(self.quarantine / QUARANTINE_FILE)
        return {(row.source_table, row.reason_codes) for row in frame.itertuples()}

    def test_clean_files_pass_with_database_names_and_dates(self):
        stats = self.run_engine()
        self.assertEqual(stats["quarantined_records"], 0)
        products = self.accepted("products")
        self.assertIn("name_length", products.columns)            # source: product_name_lenght
        self.assertEqual(self.accepted("orders")["estimated_delivery_date"].iloc[0], "2017-10-18")

    def test_lookups_to_complete_are_counted_not_quarantined(self):
        stats = self.run_engine()
        self.assertEqual(stats["tables"]["products"]["completed_parents"]["category_name"],
                         {"rows": 1, "missing_parents": 1})
        self.assertEqual(stats["tables"]["customers"]["completed_parents"]["zip_code_prefix"],
                         {"rows": 1, "missing_parents": 1})

    def test_point_outside_brazil_loses_its_coordinates_but_is_kept(self):
        self.run_engine()
        points = self.accepted("geolocation_staging")
        self.assertEqual(len(points), 3)
        self.assertEqual(points["latitude"].isna().sum(), 1)

    def test_malformed_and_missing_values(self):
        self.rows["sellers"][0]["seller_id"] = "not-a-key"
        self.rows["order_payments"][0]["payment_type"] = ""
        self.run_engine()
        found = self.quarantined()
        self.assertIn(("sellers", "INVALID_VALUE"), found)
        self.assertIn(("order_payments", "MISSING_REQUIRED"), found)

    def test_duplicate_key_is_found_across_chunks(self):
        self.rows["order_payments"].append(dict(self.rows["order_payments"][0]))
        stats = self.run_engine(chunk_rows=1)
        self.assertEqual(stats["tables"]["order_payments"]["reasons"]["DUPLICATE_KEY"], 1)
        self.assertEqual(len(self.accepted("order_payments")), 2)

    def test_quarantined_order_takes_its_children_with_it(self):
        self.rows["orders"][0]["customer_id"] = hexid(999)              # customer does not exist
        self.run_engine()
        found = self.quarantined()
        self.assertIn(("orders", "ORPHAN_FOREIGN_KEY"), found)
        self.assertIn(("order_items", "ORPHAN_FOREIGN_KEY"), found)
        self.assertIn(("order_reviews", "ORPHAN_FOREIGN_KEY"), found)
        self.assertEqual(list(self.accepted("orders")["order_id"]), [hexid(32)])

    def test_delivery_before_purchase_is_impossible(self):
        self.rows["orders"][0]["order_delivered_customer_date"] = "2017-10-01 08:00:00"
        self.run_engine()
        self.assertIn(("orders", "IMPOSSIBLE_DATES"), self.quarantined())

    def test_quarantine_keeps_raw_values_and_row_number(self):
        self.rows["sellers"][0]["seller_city"] = ""
        self.run_engine()
        row = read_csv_text(self.quarantine / QUARANTINE_FILE).iloc[0]
        self.assertEqual(row["source_row"], "1")
        self.assertIsNone(json.loads(row["record"])["seller_city"])

    def test_missing_source_column_stops_the_run(self):
        with self.assertRaises(SourceSchemaChangedError):
            self.run_engine(drop_column=("orders", "order_status"))

    def test_too_many_rejections_fail_and_publish_nothing(self):
        self.rows["orders"][0]["customer_id"] = hexid(999)
        with self.assertRaises(QuarantineThresholdError):
            self.run_engine(max_ratio=0.01)
        self.assertTrue((self.quarantine / QUARANTINE_FILE).exists())
        self.assertFalse((self.work / "orders.csv").exists())


if __name__ == "__main__":
    unittest.main()
