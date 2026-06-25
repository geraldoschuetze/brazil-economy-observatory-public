-- Does the market see inflation coming? Monthly median Focus expectation for
-- the IPCA of the current and the next calendar year, against the realized
-- IPCA 12m and the official target (both from SGS).
-- Also derives the senior-economist policy gauges:
--   exp_12m       — 12-month-ahead expectation, calendar-weighted blend of
--                   current/next year medians (Focus "suavizada" approximation)
--   juro_real_ex_ante  — Fisher: (1+Selic)/(1+E[IPCA 12m]) − 1 (policy stance)
--   juro_real_ex_post  — Fisher against realized IPCA 12m
--   desancoragem  — next-year expectation minus target (credibility gauge)
WITH focus AS (
    SELECT date_trunc('month', data)::date AS mes,
           avg(mediana) FILTER (
               WHERE data_referencia = extract(year FROM data)::int
           ) AS exp_ano_corrente,
           avg(mediana) FILTER (
               WHERE data_referencia = extract(year FROM data)::int + 1
           ) AS exp_ano_seguinte
    FROM {{ ref('stg_focus_expectativas') }}
    WHERE indicador = 'IPCA'
    GROUP BY 1
),
sgs AS (
    SELECT date_trunc('month', obs_date)::date AS mes,
           max(value) FILTER (WHERE series_code = 13522) AS ipca_12m,
           max(value) FILTER (WHERE series_code = 13521) AS meta_raw,
           avg(value) FILTER (WHERE series_code = 432)   AS selic
    FROM {{ ref('stg_sgs_observations') }}
    WHERE series_code IN (13522, 13521, 432)
    GROUP BY 1
),
meta_ff AS (
    SELECT mes, ipca_12m, selic,
           first_value(meta_raw) OVER (PARTITION BY grp ORDER BY mes) AS meta
    FROM (SELECT *, count(meta_raw) OVER (ORDER BY mes) AS grp FROM sgs) g
),
base AS (
    SELECT f.mes,
           f.exp_ano_corrente,
           f.exp_ano_seguinte,
           s.ipca_12m,
           s.meta,
           s.selic,
           -- from month m, the next 12 months span (12−m) months of the
           -- current year and m of the next: weight the two medians
           ((12 - extract(month FROM f.mes)) * f.exp_ano_corrente
            + extract(month FROM f.mes) * f.exp_ano_seguinte) / 12.0 AS exp_12m
    FROM focus f
    LEFT JOIN meta_ff s USING (mes)
    -- dashboard starts in 2020; floor the marts there uniformly
    WHERE f.mes >= DATE '2020-01-01'
      AND f.mes < date_trunc('month', current_date)
)
SELECT mes,
       round(exp_ano_corrente::numeric, 2) AS exp_ano_corrente,
       round(exp_ano_seguinte::numeric, 2) AS exp_ano_seguinte,
       ipca_12m,
       meta,
       round(exp_12m::numeric, 2)                    AS exp_12m,
       round((exp_ano_seguinte - meta)::numeric, 2)  AS desancoragem,
       round((((1 + selic / 100) / (1 + exp_12m / 100) - 1)
              * 100)::numeric, 2)                    AS juro_real_ex_ante,
       round((((1 + selic / 100) / (1 + ipca_12m / 100) - 1)
              * 100)::numeric, 2)                    AS juro_real_ex_post,
       4.75                                          AS juro_neutro
FROM base
ORDER BY mes
