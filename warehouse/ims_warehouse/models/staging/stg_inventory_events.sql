SELECT
    event_id,
    product_id,
    event_type,
    quantity,
    created_at,
    organization_id,
    strftime(created_at, '%Y-%m-%d') AS date_id  -- derived from created_at
FROM {{ source('data_lake', 'inventory_events') }}
