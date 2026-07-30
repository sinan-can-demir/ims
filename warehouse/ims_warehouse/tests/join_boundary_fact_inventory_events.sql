-- Epoch 10 PR 14 (#150): fact_inventory_events.organization_id must
-- always agree with its own product's organization_id in dim_products.
-- No dbt-utils dependency exists for a multi-column relationships test,
-- so this is a plain custom singular test instead — any row this query
-- returns is a failure. Re-joins independently (not just checking the
-- already-filtered fact_inventory_events output) so it would still
-- catch a regression even if fact_inventory_events.sql's own join
-- condition (models/marts/fact_inventory_events.sql) were ever loosened.

SELECT
    f.event_id,
    f.product_id,
    f.organization_id AS fact_organization_id,
    p.organization_id AS product_organization_id
FROM {{ ref('fact_inventory_events') }} f
JOIN {{ ref('dim_products') }} p
    ON f.product_id = p.product_id
WHERE f.organization_id != p.organization_id
