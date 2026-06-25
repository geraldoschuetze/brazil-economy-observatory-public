-- Monthly view of inflation against its classic drivers, all on the same
-- 12-month-variation scale, plus the official inflation target band:
--   IPCA 12m   — headline inflation (SGS 13522)
--   IGP-M 12m  — wholesale prices, tends to LEAD the IPCA (compounded from 189)
--   USD 12m    — exchange-rate pass-through (yoy variation of monthly average)
--   IBC-Br 12m — economic activity / demand pressure (yoy variation of index)
--   target     — annual inflation target (SGS 13521) ± 1.5pp tolerance band
WITH mensal AS (
    SELECT date_trunc('month', obs_date)::date AS mes,
           max(value) FILTER (WHERE series_code = 13522) AS ipca_12m,
           max(value) FILTER (WHERE series_code = 189)   AS igpm_mensal,
           max(value) FILTER (WHERE series_code = 13521) AS meta_inflacao_raw,
           avg(value) FILTER (WHERE series_code = 1)     AS usd_medio,
           max(value) FILTER (WHERE series_code = 24364) AS ibcbr,
           max(value) FILTER (WHERE series_code = 4466)  AS nucleo_mensal,
           max(value) FILTER (WHERE series_code = 21379) AS difusao,
           max(value) FILTER (WHERE series_code = 24369) AS desemprego
    FROM {{ ref('stg_sgs_observations') }}
    GROUP BY 1
),
-- forward-fill the annual target across the year (count-over trick)
meta_ff AS (
    SELECT *,
           first_value(meta_inflacao_raw) OVER (
               PARTITION BY grp ORDER BY mes
           ) AS meta_inflacao
    FROM (
        SELECT *, count(meta_inflacao_raw) OVER (ORDER BY mes) AS grp
        FROM mensal
    ) g
),
calc AS (
    SELECT mes,
           ipca_12m,
           meta_inflacao,
           meta_inflacao + 1.5 AS meta_teto,
           meta_inflacao - 1.5 AS meta_piso,
           -- compound the last 12 monthly IGP-M readings (needs full window)
           CASE
               WHEN count(igpm_mensal) OVER w12 = 12 THEN
                   round(((exp(sum(ln(1 + igpm_mensal / 100.0)) OVER w12) - 1)
                          * 100)::numeric, 2)
           END AS igpm_12m,
           -- core inflation (smoothed trimmed means), compounded the same way
           CASE
               WHEN count(nucleo_mensal) OVER w12 = 12 THEN
                   round(((exp(sum(ln(1 + nucleo_mensal / 100.0)) OVER w12) - 1)
                          * 100)::numeric, 2)
           END AS nucleo_12m,
           difusao,
           desemprego,
           round(((usd_medio / nullif(lag(usd_medio, 12) OVER (ORDER BY mes), 0)
                   - 1) * 100)::numeric, 2) AS usd_var_12m,
           round(((ibcbr / nullif(lag(ibcbr, 12) OVER (ORDER BY mes), 0)
                   - 1) * 100)::numeric, 2) AS ibcbr_var_12m
    FROM meta_ff
    WINDOW w12 AS (ORDER BY mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
SELECT *
FROM calc
-- raw SGS is backfilled to 2018 only to give the 12m/24m windows a lookback
-- base; the dashboard starts in 2020, so expose only 2020-01-01 onward
WHERE mes >= DATE '2020-01-01'
  AND mes < date_trunc('month', current_date)
ORDER BY mes
