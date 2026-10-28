-- Q5 on the pre-computed snapshot. The median of the live query is not additive across
-- months, so the snapshot gives the mean order value only (the price of pre-computing).
SELECT payment_type, installments, sum(payments) AS payments,
       round(100.0 * sum(payments) / sum(sum(payments)) OVER (), 2) AS pct_of_payments,
       round(sum(order_value_sum) / sum(payments), 2)              AS avg_order_value
FROM snap_payments
WHERE month >= :start AND month < :end
GROUP BY payment_type, installments
ORDER BY payment_type, min(band_order)
