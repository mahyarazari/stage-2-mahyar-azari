-- Tables of the olist schema (stage 2).
-- Run by the load stage inside its transaction, with search_path set to the target
-- schema; names are unqualified. Every load rebuilds the tables (CASCADE also drops the
-- views, which later files recreate). load_runs is a log and is never dropped.
--
-- Type choices (the reasons are in docs/decisions.md):
--   ids        uuid: the keys are 32 hex characters, which uuid stores in 16 bytes
--              instead of 33 for char(32); smaller rows and smaller indexes. Shown
--              with dashes, but the value is the same.
--   zip codes  char(5): leading zeros matter (01037), so not an integer.
--   money      numeric(10,2): exact; a sum of prices must not drift as floats do.
--   times      timestamp without time zone: the source has local times and no zone.
--   counts     smallint/integer by their real range.
-- Foreign keys are DEFERRABLE INITIALLY DEFERRED: they are checked at COMMIT, after the
-- missing lookup rows have been added (20_complete_parents.sql), so the load order does
-- not matter and a real orphan still makes the whole load roll back.

DROP TABLE IF EXISTS order_reviews, order_payments, order_items, orders, products, sellers,
                     customers, zip_codes, product_categories, quarantine, snap_sales, snap_delivery,
                     snap_review_delay, snap_sellers, snap_payments, snapshot_months CASCADE;

CREATE TEMP TABLE geolocation_staging (       -- raw points, only for building zip_codes
    zip_code_prefix char(5) NOT NULL,
    latitude        double precision,
    longitude       double precision,
    city            text,
    state           char(2)
) ON COMMIT DROP;

CREATE TABLE product_categories (
    category_name         text    PRIMARY KEY,
    category_name_english text,
    is_inferred           boolean NOT NULL DEFAULT false   -- added because a product uses it
);

CREATE TABLE zip_codes (
    zip_code_prefix char(5)          PRIMARY KEY CHECK (zip_code_prefix ~ '^[0-9]{5}$'),
    latitude        double precision CHECK (latitude BETWEEN -90 AND 90),
    longitude       double precision CHECK (longitude BETWEEN -180 AND 180),
    city            text,
    state           char(2),
    points          integer          NOT NULL CHECK (points >= 0),  -- geolocation rows behind it
    is_inferred     boolean          NOT NULL DEFAULT false         -- used by a customer/seller, no points
);

CREATE TABLE customers (
    customer_id        uuid    PRIMARY KEY,
    customer_unique_id uuid    NOT NULL,          -- the person; one per customer_id order
    zip_code_prefix    char(5) NOT NULL REFERENCES zip_codes DEFERRABLE INITIALLY DEFERRED,
    city               text    NOT NULL,
    state              char(2) NOT NULL
);

CREATE TABLE sellers (
    seller_id       uuid    PRIMARY KEY,
    zip_code_prefix char(5) NOT NULL REFERENCES zip_codes DEFERRABLE INITIALLY DEFERRED,
    city            text    NOT NULL,
    state           char(2) NOT NULL
);

CREATE TABLE products (
    product_id         uuid     PRIMARY KEY,
    category_name      text     REFERENCES product_categories DEFERRABLE INITIALLY DEFERRED,
    name_length        smallint CHECK (name_length >= 0),
    description_length integer  CHECK (description_length >= 0),
    photos_qty         smallint CHECK (photos_qty >= 0),
    weight_g           integer  CHECK (weight_g >= 0),
    length_cm          smallint CHECK (length_cm >= 0),
    height_cm          smallint CHECK (height_cm >= 0),
    width_cm           smallint CHECK (width_cm >= 0)
);

CREATE TABLE orders (
    order_id                uuid      PRIMARY KEY,
    customer_id             uuid      NOT NULL UNIQUE REFERENCES customers DEFERRABLE INITIALLY DEFERRED,
    status                  text      NOT NULL CHECK (status IN ('approved', 'canceled', 'created',
                                          'delivered', 'invoiced', 'processing', 'shipped', 'unavailable')),
    purchased_at            timestamp NOT NULL,
    approved_at             timestamp,
    delivered_carrier_at    timestamp,
    delivered_customer_at   timestamp,
    estimated_delivery_date date      NOT NULL,
    -- Suspicious but possible dates are flagged, not rejected (as in stage 1, D13).
    flag_approved_before_purchase  boolean GENERATED ALWAYS AS (coalesce(approved_at < purchased_at, false)) STORED,
    flag_carrier_before_purchase   boolean GENERATED ALWAYS AS (coalesce(delivered_carrier_at < purchased_at, false)) STORED,
    flag_delivered_before_carrier  boolean GENERATED ALWAYS AS (coalesce(delivered_customer_at < delivered_carrier_at, false)) STORED,
    flag_status_delivery_mismatch  boolean GENERATED ALWAYS AS (
        (status = 'delivered') <> (delivered_customer_at IS NOT NULL)) STORED,
    CONSTRAINT orders_delivered_after_purchase CHECK (delivered_customer_at >= purchased_at)
);

CREATE TABLE order_items (
    order_id          uuid          NOT NULL REFERENCES orders DEFERRABLE INITIALLY DEFERRED,
    order_item_id     smallint      NOT NULL CHECK (order_item_id >= 1),
    product_id        uuid          NOT NULL REFERENCES products DEFERRABLE INITIALLY DEFERRED,
    seller_id         uuid          NOT NULL REFERENCES sellers DEFERRABLE INITIALLY DEFERRED,
    shipping_limit_at timestamp     NOT NULL,
    price             numeric(10,2) NOT NULL CHECK (price > 0),
    freight_value     numeric(10,2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE order_payments (
    order_id           uuid          NOT NULL REFERENCES orders DEFERRABLE INITIALLY DEFERRED,
    payment_sequential smallint      NOT NULL CHECK (payment_sequential >= 1),
    payment_type       text          NOT NULL CHECK (payment_type IN ('boleto', 'credit_card',
                                         'debit_card', 'not_defined', 'voucher')),
    installments       smallint      NOT NULL CHECK (installments >= 0),
    payment_value      numeric(10,2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE order_reviews (
    review_id       uuid      NOT NULL,
    order_id        uuid      NOT NULL REFERENCES orders DEFERRABLE INITIALLY DEFERRED,
    score           smallint  NOT NULL CHECK (score BETWEEN 1 AND 5),
    comment_title   text,
    comment_message text,
    created_at      timestamp NOT NULL,
    answered_at     timestamp NOT NULL CHECK (answered_at >= created_at),
    PRIMARY KEY (review_id, order_id)       -- one review can cover several orders
);

CREATE TABLE quarantine (
    source_table text    NOT NULL,
    source_row   integer NOT NULL,          -- data row number in the source file (1 = first)
    record       jsonb   NOT NULL,          -- raw values as received
    reason_codes text[]  NOT NULL CHECK (cardinality(reason_codes) > 0),
    PRIMARY KEY (source_table, source_row)
);

CREATE TABLE IF NOT EXISTS load_runs (
    load_id        text      PRIMARY KEY,   -- run_id of the run manifest
    loaded_at_utc  timestamp NOT NULL,
    snapshot       text      NOT NULL,
    config_sha256  text      NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    git_commit     text      NOT NULL,
    files          jsonb     NOT NULL
);
