-- Cross-source mart: monthly fund flows (CVM) against the Selic level (BACEN).
-- The classic "money migrates when rates move" view. Current month excluded
-- (both sources still partial).
WITH fundos AS (
    SELECT date_trunc('month', dt_comptc)::date AS mes,
           sum(captacao_dia)     AS captacao,
           sum(resgate_dia)      AS resgates,
           sum(captacao_liquida) AS captacao_liquida
    FROM {{ ref('fct_fundos_diario') }}
    GROUP BY 1
),
selic AS (
    SELECT date_trunc('month', obs_date)::date AS mes,
           round(avg(selic_meta), 2) AS selic_media
    FROM {{ ref('fct_indicadores_macro') }}
    WHERE selic_meta IS NOT NULL
    GROUP BY 1
)
SELECT f.mes,
       f.captacao,
       f.resgates,
       f.captacao_liquida,
       s.selic_media
FROM fundos f
JOIN selic s USING (mes)
WHERE f.mes < date_trunc('month', current_date)
ORDER BY f.mes
