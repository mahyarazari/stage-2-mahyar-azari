-- Q2 Delivery: share of delivered orders that arrived after the promised date, per
-- customer state and purchase month, for orders purchased in [:start, :end).
-- Late = delivery date (day) after the estimated delivery date; orders without a
-- delivery date are not measured (they cannot be late or on time yet).
SELECT c.state,
       date_trunc('month', o.purchased_at)::date AS month,
       count(*)                                  AS delivered_orders,
       count(*) FILTER (WHERE o.delivered_customer_at::date > o.estimated_delivery_date) AS late_orders,
       round(100.0 * count(*) FILTER (WHERE o.delivered_customer_at::date > o.estimated_delivery_date)
             / count(*), 2)                      AS late_pct
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.delivered_customer_at IS NOT NULL
  AND o.purchased_at >= :start
  AND o.purchased_at <  :end
GROUP BY 1, 2
ORDER BY 1, 2
