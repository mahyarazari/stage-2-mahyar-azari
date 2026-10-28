-- Q1 on the pre-computed snapshot (refresh_month). Periods are whole months.
SELECT month, category, sum(sales_value) AS sales_value, sum(orders) AS orders,
       round(sum(sales_value) / sum(orders), 2) AS avg_order_value
FROM snap_sales
WHERE month >= :start AND month < :end
GROUP BY month, category
ORDER BY month, category
