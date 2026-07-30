-- e.organization_id = p.organization_id (Epoch 10 PR 14, #150) is the
-- actual join-boundary enforcement point in the dbt layer, mirroring
-- build_fact_table()'s equivalent DuckDB-side check (PR 13, #149) —
-- product_id is already globally unique across orgs, so this was never
-- actually capable of matching the wrong product; it's the same
-- "verify the invariant explicitly" discipline applied here too, and
-- what tests/join_boundary_fact_inventory_events.sql regression-tests.
SELECT
    e.event_id,
    e.product_id,
    e.date_id,
    e.event_type,
    e.quantity,
    e.created_at,
    e.organization_id
FROM {{ ref('stg_inventory_events') }} e
JOIN {{ ref('dim_products') }} p
    ON e.product_id = p.product_id
    AND e.organization_id = p.organization_id
