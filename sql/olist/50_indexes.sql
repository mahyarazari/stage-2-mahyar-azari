-- Indexes (each one justified by a plan in the notebook):
-- orders_purchased_at_idx: refresh_month reads one month (~4% of orders); without it
--   every refresh scans all orders.
-- order_reviews_order_id_idx: the primary key starts with review_id, so finding the
--   reviews of a month's orders by order_id needs its own index.
CREATE INDEX orders_purchased_at_idx    ON orders (purchased_at);
CREATE INDEX order_reviews_order_id_idx ON order_reviews (order_id);
