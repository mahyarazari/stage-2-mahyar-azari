-- Q2 on the snapshot.
SELECT state, month, sum(delivered_orders) AS delivered_orders, sum(late_orders) AS late_orders,
       round(100.0 * sum(late_orders) / sum(delivered_orders), 2) AS late_pct
FROM snap_delivery
WHERE month >= :start AND month < :end
GROUP BY state, month
ORDER BY state, month
