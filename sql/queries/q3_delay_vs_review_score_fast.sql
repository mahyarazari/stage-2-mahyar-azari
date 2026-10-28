-- Q3 on the snapshot: averages are rebuilt from sums, so they equal the live query.
SELECT delay_band, sum(orders) AS orders,
       round(sum(score_sum) / sum(orders), 2) AS avg_score,
       round(100.0 * sum(low_score_orders) / sum(orders), 1) AS pct_score_1_2,
       round(100.0 * sum(top_score_orders) / sum(orders), 1) AS pct_score_5
FROM snap_review_delay
WHERE month >= :start AND month < :end
GROUP BY delay_band
ORDER BY delay_band
