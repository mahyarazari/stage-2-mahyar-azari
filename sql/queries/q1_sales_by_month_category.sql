-- Q1 Basket and revenue: per purchase month and product category, total sales value,
-- distinct orders and average order value, for orders purchased in [:start, :end).
-- Sales = orders that were not canceled and not unavailable (stage-2 decision).
-- Sales value = item price, without freight (freight is not revenue of a category).
-- Average order value = category sales / orders containing that category: an order with
-- items of two categories counts once in each.
SELECT date_trunc('month', o.purchased_at)::date                        AS month,
       coalesce(c.category_name_english, p.category_name, 'uncategorized') AS category,
       sum(i.price)                                                     AS sales_value,
       count(DISTINCT o.order_id)                                       AS orders,
       round(sum(i.price) / count(DISTINCT o.order_id), 2)              AS avg_order_value
FROM orders o
JOIN order_items i              ON i.order_id = o.order_id
JOIN products p                 ON p.product_id = i.product_id
LEFT JOIN product_categories c  ON c.category_name = p.category_name
WHERE o.status NOT IN ('canceled', 'unavailable')
  AND o.purchased_at >= :start
  AND o.purchased_at <  :end
GROUP BY 1, 2
ORDER BY 1, 2
