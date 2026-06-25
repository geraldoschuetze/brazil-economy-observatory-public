-- National monthly PIX volume: actuals plus a 6-month linear projection, now
-- LONG by payer type (CPF/CNPJ). OLS (regr_slope/regr_intercept) is fit per type
-- over the last 24 COMPLETE months. Linear regression is additive, so SUMming
-- the two per-type projections reproduces the total projection when no filter is
-- applied; the CPF/CNPJ filter narrows it to the chosen type.
WITH hist AS (
    SELECT mes, tipo_pessoa, sum(vl_pago) AS vl_pago
    FROM {{ ref('fct_pix_pessoa_mensal') }}
    GROUP BY mes, tipo_pessoa
),
numbered AS (
    SELECT mes, tipo_pessoa, vl_pago,
           row_number() OVER (PARTITION BY tipo_pessoa ORDER BY mes)::numeric AS t
    FROM hist
    WHERE mes < date_trunc('month', current_date)  -- complete months only
),
last_24m AS (
    SELECT *
    FROM (
        SELECT *,
               row_number() OVER (PARTITION BY tipo_pessoa ORDER BY t DESC) AS rn
        FROM numbered
    ) x
    WHERE rn <= 24
),
fit AS (
    SELECT tipo_pessoa,
           regr_slope(vl_pago, t)     AS s,
           regr_intercept(vl_pago, t) AS b,
           max(t)                     AS t_max,
           max(mes)                   AS mes_max
    FROM last_24m
    GROUP BY tipo_pessoa
)
SELECT mes,
       tipo_pessoa,
       vl_pago       AS vl_realizado,
       NULL::numeric AS vl_projetado,
       false         AS projecao
FROM numbered

UNION ALL

-- g = 0 anchors the projected line on the last actual month so the series touch
SELECT (fit.mes_max + (g || ' month')::interval)::date,
       fit.tipo_pessoa,
       NULL::numeric,
       round((fit.s * (fit.t_max + g) + fit.b)::numeric, 2),
       g > 0
FROM fit, generate_series(0, 6) AS g
ORDER BY mes, tipo_pessoa
