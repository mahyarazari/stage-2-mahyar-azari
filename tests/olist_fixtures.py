"""A tiny but complete set of the nine Olist files, for tests. Each test can change rows."""
import csv
from pathlib import Path

from data_factory.olist_contract import TABLES


def hexid(n: int) -> str:
    return f"{n:032x}"


def base_rows() -> dict[str, list[dict]]:
    """Valid rows: 2 customers, 2 orders, 2 items, payments, reviews. The product category
    'pc_gamer' is missing from the translations and zip 99999 from the geolocation, as in
    the real data; both are lookups the database completes."""
    return {
        "product_categories": [{"product_category_name": "perfumaria", "product_category_name_english": "perfumery"}],
        "geolocation_staging": [
            {"geolocation_zip_code_prefix": "01037", "geolocation_lat": "-23.54", "geolocation_lng": "-46.63",
             "geolocation_city": "sao paulo", "geolocation_state": "SP"},
            {"geolocation_zip_code_prefix": "01037", "geolocation_lat": "-23.56", "geolocation_lng": "-46.65",
             "geolocation_city": "sao paulo", "geolocation_state": "SP"},
            {"geolocation_zip_code_prefix": "01037", "geolocation_lat": "45.0", "geolocation_lng": "121.1",
             "geolocation_city": "sao paulo", "geolocation_state": "SP"},          # outside Brazil
        ],
        "customers": [
            {"customer_id": hexid(1), "customer_unique_id": hexid(101), "customer_zip_code_prefix": "01037",
             "customer_city": "sao paulo", "customer_state": "SP"},
            {"customer_id": hexid(2), "customer_unique_id": hexid(102), "customer_zip_code_prefix": "99999",
             "customer_city": "itu", "customer_state": "SP"},
        ],
        "sellers": [{"seller_id": hexid(11), "seller_zip_code_prefix": "01037", "seller_city": "sao paulo",
                     "seller_state": "SP"}],
        "products": [
            {"product_id": hexid(21), "product_category_name": "perfumaria", "product_name_lenght": "40",
             "product_description_lenght": "287", "product_photos_qty": "1", "product_weight_g": "225",
             "product_length_cm": "16", "product_height_cm": "10", "product_width_cm": "14"},
            {"product_id": hexid(22), "product_category_name": "pc_gamer", "product_name_lenght": "",
             "product_description_lenght": "", "product_photos_qty": "", "product_weight_g": "",
             "product_length_cm": "", "product_height_cm": "", "product_width_cm": ""},
        ],
        "orders": [
            {"order_id": hexid(31), "customer_id": hexid(1), "order_status": "delivered",
             "order_purchase_timestamp": "2017-10-02 10:56:33", "order_approved_at": "2017-10-02 11:07:15",
             "order_delivered_carrier_date": "2017-10-04 19:55:00",
             "order_delivered_customer_date": "2017-10-10 21:25:13",
             "order_estimated_delivery_date": "2017-10-18 00:00:00"},
            {"order_id": hexid(32), "customer_id": hexid(2), "order_status": "shipped",
             "order_purchase_timestamp": "2018-01-05 09:00:00", "order_approved_at": "",
             "order_delivered_carrier_date": "", "order_delivered_customer_date": "",
             "order_estimated_delivery_date": "2018-01-25 00:00:00"},
        ],
        "order_items": [
            {"order_id": hexid(31), "order_item_id": "1", "product_id": hexid(21), "seller_id": hexid(11),
             "shipping_limit_date": "2017-10-06 11:07:15", "price": "29.99", "freight_value": "8.72"},
            {"order_id": hexid(32), "order_item_id": "1", "product_id": hexid(22), "seller_id": hexid(11),
             "shipping_limit_date": "2018-01-10 09:00:00", "price": "100", "freight_value": "0"},
        ],
        "order_payments": [
            {"order_id": hexid(31), "payment_sequential": "1", "payment_type": "credit_card",
             "payment_installments": "1", "payment_value": "38.71"},
            {"order_id": hexid(32), "payment_sequential": "1", "payment_type": "boleto",
             "payment_installments": "1", "payment_value": "100.00"},
        ],
        "order_reviews": [
            {"review_id": hexid(41), "order_id": hexid(31), "review_score": "4", "review_comment_title": "",
             "review_comment_message": "bom, \"rapido\"\nchegou", "review_creation_date": "2017-10-11 00:00:00",
             "review_answer_timestamp": "2017-10-12 03:43:48"},
        ],
    }


def write_files(raw_dir: Path, rows: dict[str, list[dict]], drop_column: tuple[str, str] | None = None) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for spec in TABLES:
        header = [c.source for c in spec.columns]
        if drop_column and drop_column[0] == spec.table:
            header.remove(drop_column[1])
        with (raw_dir / spec.file).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows[spec.table])
