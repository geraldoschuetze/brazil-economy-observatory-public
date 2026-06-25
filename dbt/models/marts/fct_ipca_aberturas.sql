-- IPCA 12m by expenditure group, with clean labels for charting.
-- 'destaque' keeps dashboards readable: headline + the five heavyweight
-- groups; the full breakdown stays queryable.
SELECT mes,
       grupo_cod,
       grupo,
       var_12m,
       grupo_cod IN (7169, 7170, 7445, 7625, 7660, 7766) AS destaque
FROM {{ ref('stg_ipca_aberturas') }}
ORDER BY mes, grupo_cod
