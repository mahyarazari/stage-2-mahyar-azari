-- Q1 on the view sales_monthly_live (computed at every read), for the view-vs-snapshot
-- comparison. Periods are whole months.
SELECT month, category, sales_value, orders, round(sales_value / orders, 2) AS avg_order_value
FROM sales_monthly_live
WHERE month >= :start AND month < :end
ORDER BY month, category
