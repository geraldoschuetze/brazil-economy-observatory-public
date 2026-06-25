-- The fiscal backdrop: gross government debt and the primary balance.
-- SGS 5793 follows the NFSP convention (positive = borrowing NEED, i.e.
-- deficit); the sign is flipped so positive reads as surplus on charts.
SELECT date_trunc('month', obs_date)::date AS mes,
       max(value) FILTER (WHERE series_code = 13762) AS divida_bruta_pib,
       -max(value) FILTER (WHERE series_code = 5793) AS resultado_primario_pib
FROM {{ ref('stg_sgs_observations') }}
-- raw SGS is backfilled to 2018 as a calc base; expose only 2020-01-01 onward
WHERE series_code IN (13762, 5793)
  AND obs_date >= DATE '2020-01-01'
GROUP BY 1
ORDER BY 1
