-- Views and the function shared by the dashboard queries and the snapshot procedure.

-- Function: the readable delay band of Q3. IMMUTABLE (same input -> same output, no table
-- read), so it can be used inside SELECT, GROUP BY, and even in an index expression.
CREATE OR REPLACE FUNCTION delay_band(delay_days integer) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN delay_days IS NULL THEN NULL
                WHEN delay_days < -14 THEN '1. more than 2 weeks early'
                WHEN delay_days <  -7 THEN '2. 1-2 weeks early'
                WHEN delay_days <   0 THEN '3. up to 1 week early'
                WHEN delay_days =   0 THEN '4. on the promised day'
                WHEN delay_days <=  3 THEN '5. 1-3 days late'
                WHEN delay_days <=  7 THEN '6. 4-7 days late'
                WHEN delay_days <= 14 THEN '7. 1-2 weeks late'
                ELSE                       '8. more than 2 weeks late' END
$$;

-- Simple single-table view: hides the definition of a sale (stage-2 decision).
CREATE VIEW sold_orders AS
SELECT * FROM orders WHERE status NOT IN ('canceled', 'unavailable');

-- Multi-table view: the join every sales question repeats (one row per sold item).
CREATE VIEW order_lines AS
SELECT o.order_id, o.purchased_at, date_trunc('month', o.purchased_at)::date AS month,
       o.approved_at, o.delivered_carrier_at,
       i.order_item_id, i.seller_id, i.product_id, i.price, i.freight_value,
       coalesce(c.category_name_english, p.category_name, 'uncategorized') AS category
FROM sold_orders o
JOIN order_items i             ON i.order_id = o.order_id
JOIN products p                ON p.product_id = i.product_id
LEFT JOIN product_categories c ON c.category_name = p.category_name;

-- The heaviest analysis (Q1) as a view computed at every read: compared with the
-- pre-computed table snap_sales in the notebook (view vs snapshot decision).
CREATE VIEW sales_monthly_live AS
SELECT month, category, sum(price) AS sales_value, count(DISTINCT order_id) AS orders
FROM order_lines
GROUP BY month, category;
