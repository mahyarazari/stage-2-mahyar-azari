-- Q1 on the pre-computed snapshot (same result as q1_sales_by_month_category for whole
-- months: the dashboard periods start and end on the first day of a month).
SELECT month, category, sum(sales_value) AS sales_value, sum(orders) AS orders,
       round(sum(sales_value) / sum(orders), 2) AS avg_order_value
FROM snap_sales
WHERE month >= :start AND month < :end
GROUP BY month, category
ORDER BY month, category
