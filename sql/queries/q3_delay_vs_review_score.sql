-- Q3 Satisfaction: review score by delivery delay, for orders purchased in [:start, :end).
-- delay_days = delivery day - promised day (negative = early). Orders are grouped into
-- readable delay bands. An order with several reviews counts once (its mean score).
WITH scored AS (
    SELECT o.order_id,
           o.delivered_customer_at::date - o.estimated_delivery_date AS delay_days,
           avg(r.score)                                               AS score
    FROM orders o
    JOIN order_reviews r ON r.order_id = o.order_id
    WHERE o.delivered_customer_at IS NOT NULL
      AND o.purchased_at >= :start
      AND o.purchased_at <  :end
    GROUP BY o.order_id, o.delivered_customer_at, o.estimated_delivery_date
)
SELECT CASE WHEN delay_days < -14 THEN '1. more than 2 weeks early'
            WHEN delay_days <  -7 THEN '2. 1-2 weeks early'
            WHEN delay_days <   0 THEN '3. up to 1 week early'
            WHEN delay_days =   0 THEN '4. on the promised day'
            WHEN delay_days <=  3 THEN '5. 1-3 days late'
            WHEN delay_days <=  7 THEN '6. 4-7 days late'
            WHEN delay_days <= 14 THEN '7. 1-2 weeks late'
            ELSE                       '8. more than 2 weeks late' END       AS delay_band,
       count(*)                                                              AS orders,
       round(avg(score), 2)                                                  AS avg_score,
       round(100.0 * count(*) FILTER (WHERE score <= 2) / count(*), 1)       AS pct_score_1_2,
       round(100.0 * count(*) FILTER (WHERE score = 5) / count(*), 1)        AS pct_score_5
FROM scored
GROUP BY 1
ORDER BY 1
