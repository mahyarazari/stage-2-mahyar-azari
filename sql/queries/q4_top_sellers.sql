-- Q4 Sellers: the :top_n sellers with the highest sales value (orders purchased in
-- [:start, :end), not canceled or unavailable), with their average preparation time and
-- average review score.
-- Preparation = payment approval -> handed to the carrier, in days, once per order and
-- seller; the times recorded before the approval are impossible and left out (counted).
-- Review score: mean score of the seller's orders (an order counts once).
WITH seller_orders AS (
    SELECT i.seller_id, i.order_id, sum(i.price) AS sales_value
    FROM order_items i
    JOIN orders o ON o.order_id = i.order_id
    WHERE o.status NOT IN ('canceled', 'unavailable')
      AND o.purchased_at >= :start
      AND o.purchased_at <  :end
    GROUP BY i.seller_id, i.order_id
), top_sellers AS (
    SELECT seller_id, sum(sales_value) AS sales_value, count(*) AS orders
    FROM seller_orders
    GROUP BY seller_id
    ORDER BY sales_value DESC
    LIMIT :top_n
), order_scores AS (
    SELECT order_id, avg(score) AS score FROM order_reviews GROUP BY order_id
)
SELECT t.seller_id,
       t.sales_value,
       t.orders,
       round(avg(extract(epoch FROM o.delivered_carrier_at - o.approved_at) / 86400)
             FILTER (WHERE o.delivered_carrier_at >= o.approved_at)::numeric, 2) AS avg_preparation_days,
       count(*) FILTER (WHERE o.delivered_carrier_at < o.approved_at)          AS impossible_preparations,
       round(avg(r.score), 2)                                                  AS avg_review_score
FROM top_sellers t
JOIN seller_orders s      ON s.seller_id = t.seller_id
JOIN orders o             ON o.order_id = s.order_id
LEFT JOIN order_scores r  ON r.order_id = s.order_id
GROUP BY t.seller_id, t.sales_value, t.orders
ORDER BY t.sales_value DESC
