-- Fill the snapshot for every month, inside the load transaction.
CALL refresh_all_months();
ANALYZE snap_sales, snap_delivery, snap_review_delay, snap_sellers, snap_payments;
