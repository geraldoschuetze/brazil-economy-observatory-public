-- Classic macro models read on Brazilian data:
--   selic_taylor — Taylor (1993) prescription: r* + E[pi] + 0.5(E[pi]-target)
--                  + 0.5*output gap. r* = 4.75 (BCB estimates ~4.6-5.0),
--                  E[pi] = Focus 12m-ahead blend, gap = IBC-Br deviation from
--                  its 24-month moving-average trend (poor man's HP filter).
--   r vs g       — the debt-dynamics / fiscal-dominance gauge: ex-ante real
--                  rate vs 12m real growth (IBC-Br). r > g with 80% GDP debt
--                  means the debt ratio grows without primary surpluses.
WITH sgs AS (
    SELECT date_trunc('month', obs_date)::date AS mes,
           avg(value) FILTER (WHERE series_code = 432)   AS selic,
           max(value) FILTER (WHERE series_code = 24364) AS ibcbr
    FROM {{ ref('stg_sgs_observations') }}
    WHERE series_code IN (432, 24364)
    GROUP BY 1
),
trend AS (
    SELECT *,
           avg(ibcbr)   OVER w24 AS ibcbr_trend,
           count(ibcbr) OVER w24 AS n24,
           lag(ibcbr, 12) OVER (ORDER BY mes) AS ibcbr_lag12
    FROM sgs
    WINDOW w24 AS (ORDER BY mes ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
),
calc AS (
    SELECT t.mes,
           t.selic,
           CASE WHEN t.n24 = 24
                THEN (t.ibcbr / t.ibcbr_trend - 1) * 100 END AS hiato,
           (t.ibcbr / nullif(t.ibcbr_lag12, 0) - 1) * 100    AS g,
           f.exp_12m,
           f.meta,
           f.juro_real_ex_ante                               AS r
    FROM trend t
    JOIN {{ ref('fct_focus_ipca_mensal') }} f USING (mes)
)
SELECT mes,
       round(selic::numeric, 2)                            AS selic,
       round((4.75 + exp_12m + 0.5 * (exp_12m - meta)
              + 0.5 * hiato)::numeric, 2)                   AS selic_taylor,
       round(hiato::numeric, 2)                             AS hiato,
       r                                                    AS juro_real_ex_ante,
       round(g::numeric, 2)                                 AS crescimento_12m,
       round((r - g)::numeric, 2)                           AS r_menos_g
FROM calc
-- raw SGS is backfilled to 2018 only to feed the 12m/24m windows; expose only
-- 2020-01-01 onward (the dashboard's start), consistent across the marts
WHERE mes >= DATE '2020-01-01'
  AND mes < date_trunc('month', current_date)
ORDER BY mes
