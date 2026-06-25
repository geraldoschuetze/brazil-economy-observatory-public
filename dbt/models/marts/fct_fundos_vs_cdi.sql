-- What share of funds beats the CDI over rolling 12 months?
-- Fund returns: last quota of each month, 12-month change per CNPJ.
-- Benchmark: CDI daily rates compounded into the same 12-month window.
WITH cotas_mensais AS (
    SELECT DISTINCT ON (cnpj, date_trunc('month', dt_comptc))
           cnpj,
           date_trunc('month', dt_comptc)::date AS mes,
           vl_quota
    FROM {{ ref('stg_cvm_inf_diario') }}
    WHERE vl_quota > 0
    ORDER BY cnpj, date_trunc('month', dt_comptc), dt_comptc DESC
),
retornos AS (
    SELECT mes, cnpj,
           vl_quota / nullif(
               lag(vl_quota, 12) OVER (PARTITION BY cnpj ORDER BY mes), 0
           ) - 1 AS ret_12m
    FROM cotas_mensais
),
cdi_mensal AS (
    SELECT date_trunc('month', obs_date)::date AS mes,
           exp(sum(ln(1 + value / 100.0))) AS fator_mes
    FROM {{ ref('stg_sgs_observations') }}
    WHERE series_code = 12
    GROUP BY 1
),
cdi_12m AS (
    SELECT mes,
           exp(sum(ln(fator_mes)) OVER w12) - 1 AS cdi_ret_12m,
           count(*) OVER w12 AS n_meses
    FROM cdi_mensal
    WINDOW w12 AS (ORDER BY mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
SELECT r.mes,
       count(*) FILTER (WHERE r.ret_12m IS NOT NULL)          AS n_fundos,
       round(100.0 * avg((r.ret_12m > c.cdi_ret_12m)::int)
             FILTER (WHERE r.ret_12m IS NOT NULL), 1)         AS pct_acima_cdi,
       round((c.cdi_ret_12m * 100)::numeric, 2)               AS cdi_12m_pct
FROM retornos r
JOIN cdi_12m c USING (mes)
WHERE c.n_meses = 12
  AND r.mes < date_trunc('month', current_date)
GROUP BY r.mes, c.cdi_ret_12m
HAVING count(*) FILTER (WHERE r.ret_12m IS NOT NULL) > 100
ORDER BY r.mes
