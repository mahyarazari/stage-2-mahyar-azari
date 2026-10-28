-- Pre-computed monthly snapshot of the dashboard (one table per question, one row per
-- month and group), filled by the procedure refresh_month. Every measure is additive
-- across months (sums and counts), so any whole-month period is a sum of rows.
-- An order belongs to its purchase month only, so counts of orders add up correctly.

CREATE TABLE snap_sales (            -- Q1
    month date NOT NULL, category text NOT NULL,
    sales_value numeric(14,2) NOT NULL, orders integer NOT NULL,
    PRIMARY KEY (month, category));

CREATE TABLE snap_delivery (         -- Q2
    month date NOT NULL, state char(2) NOT NULL,
    delivered_orders integer NOT NULL, late_orders integer NOT NULL,
    PRIMARY KEY (month, state));

CREATE TABLE snap_review_delay (     -- Q3
    month date NOT NULL, delay_band text NOT NULL,
    orders integer NOT NULL, score_sum numeric NOT NULL,
    low_score_orders integer NOT NULL, top_score_orders integer NOT NULL,
    PRIMARY KEY (month, delay_band));

CREATE TABLE snap_sellers (          -- Q4
    month date NOT NULL, seller_id uuid NOT NULL,
    sales_value numeric(14,2) NOT NULL, orders integer NOT NULL,
    preparation_days_sum double precision NOT NULL, preparations integer NOT NULL,
    impossible_preparations integer NOT NULL,
    score_sum numeric NOT NULL, scored_orders integer NOT NULL,
    PRIMARY KEY (month, seller_id));

CREATE TABLE snap_payments (         -- Q5
    month date NOT NULL, payment_type text NOT NULL,
    installments text NOT NULL, band_order smallint NOT NULL,
    payments integer NOT NULL, order_value_sum numeric(14,2) NOT NULL,
    PRIMARY KEY (month, payment_type, installments));

CREATE TABLE snapshot_months (
    month date PRIMARY KEY, refreshed_at timestamptz NOT NULL);

-- Procedure: rebuild the snapshot of the month that contains p_month.
-- Idempotent: the month is deleted, then computed again, so a second CALL changes nothing.
-- All or nothing: a CALL is one statement in the caller's transaction; if any part fails,
-- every delete and insert of the call is rolled back (no half month is left).
CREATE OR REPLACE PROCEDURE refresh_month(p_month date)
LANGUAGE plpgsql AS $$
DECLARE
    m_start timestamp;
    m_end   timestamp;
BEGIN
    IF p_month IS NULL THEN
        RAISE EXCEPTION 'refresh_month: a month is required';
    END IF;
    m_start := date_trunc('month', p_month);
    m_end   := m_start + interval '1 month';

    DELETE FROM snap_sales        WHERE month = m_start::date;
    DELETE FROM snap_delivery     WHERE month = m_start::date;
    DELETE FROM snap_review_delay WHERE month = m_start::date;
    DELETE FROM snap_sellers      WHERE month = m_start::date;
    DELETE FROM snap_payments     WHERE month = m_start::date;

    INSERT INTO snap_sales (month, category, sales_value, orders)
    SELECT m_start::date, category, sum(price), count(DISTINCT order_id)
    FROM order_lines
    WHERE purchased_at >= m_start AND purchased_at < m_end
    GROUP BY category;

    INSERT INTO snap_delivery (month, state, delivered_orders, late_orders)
    SELECT m_start::date, c.state, count(*),
           count(*) FILTER (WHERE o.delivered_customer_at::date > o.estimated_delivery_date)
    FROM orders o JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.delivered_customer_at IS NOT NULL
      AND o.purchased_at >= m_start AND o.purchased_at < m_end
    GROUP BY c.state;

    INSERT INTO snap_review_delay (month, delay_band, orders, score_sum, low_score_orders, top_score_orders)
    SELECT m_start::date, delay_band(delay_days), count(*), sum(score),
           count(*) FILTER (WHERE score <= 2), count(*) FILTER (WHERE score = 5)
    FROM (SELECT o.order_id, o.delivered_customer_at::date - o.estimated_delivery_date AS delay_days,
                 avg(r.score) AS score
          FROM orders o JOIN order_reviews r ON r.order_id = o.order_id
          WHERE o.delivered_customer_at IS NOT NULL
            AND o.purchased_at >= m_start AND o.purchased_at < m_end
          GROUP BY o.order_id) AS scored
    GROUP BY 2;

    INSERT INTO snap_sellers (month, seller_id, sales_value, orders, preparation_days_sum, preparations,
                              impossible_preparations, score_sum, scored_orders)
    SELECT m_start::date, s.seller_id, sum(s.sales_value), count(*),
           coalesce(sum(extract(epoch FROM s.delivered_carrier_at - s.approved_at) / 86400)
                    FILTER (WHERE s.delivered_carrier_at >= s.approved_at), 0),
           count(*) FILTER (WHERE s.delivered_carrier_at >= s.approved_at),
           count(*) FILTER (WHERE s.delivered_carrier_at < s.approved_at),
           coalesce(sum(r.score), 0), count(r.score)
    FROM (SELECT seller_id, order_id, approved_at, delivered_carrier_at, sum(price) AS sales_value
          FROM order_lines
          WHERE purchased_at >= m_start AND purchased_at < m_end
          GROUP BY seller_id, order_id, approved_at, delivered_carrier_at) AS s
    LEFT JOIN (SELECT order_id, avg(score) AS score FROM order_reviews GROUP BY order_id) AS r
           ON r.order_id = s.order_id
    GROUP BY s.seller_id;

    INSERT INTO snap_payments (month, payment_type, installments, band_order, payments, order_value_sum)
    SELECT m_start::date, p.payment_type,
           CASE WHEN p.installments <= 1 THEN '1' WHEN p.installments <= 3 THEN '2-3'
                WHEN p.installments <= 6 THEN '4-6' WHEN p.installments <= 10 THEN '7-10' ELSE '11+' END,
           min(CASE WHEN p.installments <= 1 THEN 1 WHEN p.installments <= 3 THEN 2
                    WHEN p.installments <= 6 THEN 3 WHEN p.installments <= 10 THEN 4 ELSE 5 END),
           count(*), sum(v.value)
    FROM order_payments p
    JOIN sold_orders o ON o.order_id = p.order_id
    JOIN (SELECT order_id, sum(price) AS value FROM order_items GROUP BY order_id) AS v
         ON v.order_id = p.order_id
    WHERE o.purchased_at >= m_start AND o.purchased_at < m_end
    GROUP BY 2, 3;

    INSERT INTO snapshot_months (month, refreshed_at) VALUES (m_start::date, now())
    ON CONFLICT (month) DO UPDATE SET refreshed_at = excluded.refreshed_at;
END
$$;

-- Every month that has orders. No COMMIT inside: it runs inside the load transaction.
CREATE OR REPLACE PROCEDURE refresh_all_months()
LANGUAGE plpgsql AS $$
DECLARE
    m date;
BEGIN
    FOR m IN SELECT DISTINCT date_trunc('month', purchased_at)::date FROM orders ORDER BY 1 LOOP
        CALL refresh_month(m);
    END LOOP;
END
$$;
