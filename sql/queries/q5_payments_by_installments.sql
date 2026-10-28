-- Q5 Payment: distribution of payment types and numbers of installments, with the value
-- of the orders paid that way, for orders purchased in [:start, :end) that were sold
-- (not canceled or unavailable). Order value = item prices of the order (the same sales
-- value as Q1); an order paid two ways (e.g. voucher + card) appears in both rows.
WITH order_value AS (
    SELECT i.order_id, sum(i.price) AS value
    FROM order_items i
    GROUP BY i.order_id
)
SELECT p.payment_type,
       CASE WHEN p.installments <= 1  THEN '1'
            WHEN p.installments <= 3  THEN '2-3'
            WHEN p.installments <= 6  THEN '4-6'
            WHEN p.installments <= 10 THEN '7-10'
            ELSE '11+' END                                              AS installments,
       count(*)                                                         AS payments,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2)               AS pct_of_payments,
       round(avg(v.value), 2)                                           AS avg_order_value,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY v.value)             AS median_order_value
FROM order_payments p
JOIN orders o       ON o.order_id = p.order_id
JOIN order_value v  ON v.order_id = p.order_id
WHERE o.status NOT IN ('canceled', 'unavailable')
  AND o.purchased_at >= :start
  AND o.purchased_at <  :end
GROUP BY 1, 2
ORDER BY 1, min(p.installments)
