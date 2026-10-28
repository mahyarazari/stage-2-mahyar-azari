-- Q4 on the pre-computed snapshot: monthly sums per seller, then the top :top_n.
SELECT seller_id, sum(sales_value) AS sales_value, sum(orders) AS orders,
       round((sum(preparation_days_sum) / nullif(sum(preparations), 0))::numeric, 2) AS avg_preparation_days,
       sum(impossible_preparations)                                                AS impossible_preparations,
       round(sum(score_sum) / nullif(sum(scored_orders), 0), 2)                     AS avg_review_score
FROM snap_sellers
WHERE month >= :start AND month < :end
GROUP BY seller_id
ORDER BY sales_value DESC
LIMIT :top_n
