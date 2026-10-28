-- Q1, rewritten live query: aggregate to one row per order and category first, then per
-- month and category. count(*) of the first stage = distinct orders, so the expensive
-- count(DISTINCT) over 112k sorted rows disappears. Same result as the original.
WITH per_order AS (
    SELECT o.order_id,
           date_trunc('month', o.purchased_at)::date                          AS month,
           coalesce(c.category_name_english, p.category_name, 'uncategorized') AS category,
           sum(i.price)                                                       AS value
    FROM orders o
    JOIN order_items i              ON i.order_id = o.order_id
    JOIN products p                 ON p.product_id = i.product_id
    LEFT JOIN product_categories c  ON c.category_name = p.category_name
    WHERE o.status NOT IN ('canceled', 'unavailable')
      AND o.purchased_at >= :start
      AND o.purchased_at <  :end
    GROUP BY 1, 2, 3
)
SELECT month, category, sum(value) AS sales_value, count(*) AS orders,
       round(sum(value) / count(*), 2) AS avg_order_value
FROM per_order
GROUP BY month, category
ORDER BY month, category
