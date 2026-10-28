-- Indexes beyond the primary keys and UNIQUE constraints (evidence: data-factory index-evidence).
-- orders_purchased_at_idx: kept. refresh_month reads one month (~7% of the orders); the plan
--   becomes an Index Only Scan instead of a Seq Scan over every order.
-- order_reviews_order_id_idx: built, then dropped. The plan for a month's reviews stays a
--   Hash Join over a Seq Scan of order_reviews with or without it (the month still needs
--   ~7k of 99k reviews, cheaper to hash), and it costs ~3 MB and slower inserts.
CREATE INDEX orders_purchased_at_idx ON orders (purchased_at);
