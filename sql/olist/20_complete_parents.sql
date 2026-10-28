-- Lookup rows that the data needs but the source lacks (stage-2 decisions).
-- Runs after the tables are filled, inside the same transaction; the deferred foreign
-- keys are checked at COMMIT, after these rows exist.

-- One row per zip-code prefix from the ~1 million geolocation points: the median point
-- (robust to the stray points far from the city) and the most frequent city and state.
-- mode() over an ordered input picks the first value in that order on ties: deterministic.
INSERT INTO zip_codes (zip_code_prefix, latitude, longitude, city, state, points)
SELECT zip_code_prefix,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY latitude),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY longitude),
       mode() WITHIN GROUP (ORDER BY city),
       mode() WITHIN GROUP (ORDER BY state),
       count(*)
FROM geolocation_staging
GROUP BY zip_code_prefix;

-- Zip codes of customers and sellers with no geolocation point: added without coordinates,
-- marked is_inferred; city and state come from the customers and sellers themselves.
INSERT INTO zip_codes (zip_code_prefix, city, state, points, is_inferred)
SELECT zip_code_prefix,
       mode() WITHIN GROUP (ORDER BY city),
       mode() WITHIN GROUP (ORDER BY state),
       0,
       true
FROM (SELECT zip_code_prefix, city, state FROM customers
      UNION ALL
      SELECT zip_code_prefix, city, state FROM sellers) AS people
WHERE NOT EXISTS (SELECT 1 FROM zip_codes z WHERE z.zip_code_prefix = people.zip_code_prefix)
GROUP BY zip_code_prefix;

-- Product categories with no English translation: added without one, marked is_inferred.
INSERT INTO product_categories (category_name, is_inferred)
SELECT DISTINCT p.category_name, true
FROM products p
WHERE p.category_name IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM product_categories c WHERE c.category_name = p.category_name);
