-- Share of funds beating the CDI over rolling 12 months, BROKEN DOWN BY CLASS.
-- Robust companion to fct_fundos_vs_cdi (which only carries the industry-wide
-- aggregate): it shows WHICH KINDS of funds — equities, multimarket, fixed
-- income, FX — tend to outperform, and is immune to the noisy return tail of
-- individual illiquid funds because it only ever reports a share, never a level.
-- inf_diario already exposes digits-only CNPJs (cnpj_digits), joining the
-- registry directly.
WITH cotas_mensais AS (
    SELECT DISTINCT ON (cnpj_digits, date_trunc('month', dt_comptc))
           cnpj_digits                          AS cnpj,
           date_trunc('month', dt_comptc)::date AS mes,
           vl_quota
    FROM {{ ref('stg_cvm_inf_diario') }}
    WHERE vl_quota > 0
    ORDER BY cnpj_digits, date_trunc('month', dt_comptc), dt_comptc DESC
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
),
classificado AS (
    SELECT r.mes,
           r.ret_12m,
           c.cdi_ret_12m,
           coalesce(nullif(trim(cad.classe), ''), 'Outros') AS classe
    FROM retornos r
    JOIN cdi_12m c USING (mes)
    -- registered funds only: a class breakdown needs a class
    JOIN {{ ref('stg_cvm_cad_fi') }} cad ON cad.cnpj = r.cnpj
    WHERE r.ret_12m IS NOT NULL
      AND c.n_meses = 12
      AND r.mes < date_trunc('month', current_date)
)
SELECT mes,
       classe,
       count(*)                                              AS n_fundos,
       round(100.0 * avg((ret_12m > cdi_ret_12m)::int), 1)   AS pct_acima_cdi
FROM classificado
GROUP BY mes, classe
-- drop thin class-months that would make a jumpy, unreliable line
HAVING count(*) >= 30
ORDER BY mes, classe
