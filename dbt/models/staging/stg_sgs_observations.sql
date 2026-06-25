-- Typed BACEN SGS observations: values arrive as text (comma decimal sep) in
-- raw and become numeric here, ready for analytical queries.
SELECT
    series_code,
    obs_date,
    replace(value, ',', '.')::numeric AS value
FROM {{ source('raw', 'sgs_observations') }}
