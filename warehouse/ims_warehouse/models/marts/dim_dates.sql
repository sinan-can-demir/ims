-- Dimension table: one row per calendar date, pre-generated
-- Source: dim_dates.parquet built via make warehouse

SELECT
    date_id,
    year,
    month,
    day,
    quarter,
    day_of_week,
    is_weekend
FROM read_parquet('{{ env_var("WAREHOUSE_ROOT", "..") }}/dim_dates.parquet')
