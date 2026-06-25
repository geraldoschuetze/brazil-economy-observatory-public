-- Daily wide table of Brazilian macro indicators, one row per observation date.
-- juro_real_12m (ex-post real interest rate) = Selic target − 12-month IPCA.
-- IPCA series are monthly, so they are forward-filled to align with daily series.
-- FX statistics (30d moving average and 30d annualized volatility of daily log
-- returns) are computed over business days only (dates with a USD quote).
WITH pivot AS (
    SELECT obs_date,
           max(value) FILTER (WHERE series_code = 432)   AS selic_meta,
           max(value) FILTER (WHERE series_code = 4189)  AS selic_efetiva,
           max(value) FILTER (WHERE series_code = 12)    AS cdi_diario,
           max(value) FILTER (WHERE series_code = 433)   AS ipca_mensal,
           max(value) FILTER (WHERE series_code = 13522) AS ipca_12m,
           max(value) FILTER (WHERE series_code = 1)     AS usd_brl,
           max(value) FILTER (WHERE series_code = 21619) AS eur_brl
    FROM {{ ref('stg_sgs_observations') }}
    GROUP BY obs_date
),
-- forward-fill trick: count() over ignores NULLs, so each non-NULL observation
-- starts a new group; first_value within the group propagates it forward
grouped AS (
    SELECT *,
           count(ipca_12m)   OVER w AS grp_ipca_12m,
           count(ipca_mensal) OVER w AS grp_ipca_mensal
    FROM pivot
    WINDOW w AS (ORDER BY obs_date)
),
ffilled AS (
    SELECT *,
           first_value(ipca_12m)    OVER (PARTITION BY grp_ipca_12m    ORDER BY obs_date) AS ipca_12m_ff,
           first_value(ipca_mensal) OVER (PARTITION BY grp_ipca_mensal ORDER BY obs_date) AS ipca_mensal_ff
    FROM grouped
),
fx_returns AS (
    SELECT obs_date,
           ln(usd_brl / lag(usd_brl) OVER (ORDER BY obs_date)) AS usd_ret
    FROM ffilled
    WHERE usd_brl IS NOT NULL
),
fx_stats AS (
    SELECT f.obs_date,
           avg(f.usd_brl)        OVER w30 AS usd_mm30,
           stddev_samp(r.usd_ret) OVER w30 * sqrt(252) * 100 AS usd_vol_30d_aa
    FROM ffilled f
    JOIN fx_returns r USING (obs_date)
    WHERE f.usd_brl IS NOT NULL
    WINDOW w30 AS (ORDER BY f.obs_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
)
SELECT f.obs_date,
       f.selic_meta,
       f.selic_efetiva,
       f.cdi_diario,
       f.ipca_mensal,
       f.ipca_12m,
       f.ipca_mensal_ff,
       f.ipca_12m_ff,
       f.usd_brl,
       f.eur_brl,
       round(s.usd_mm30::numeric, 4)        AS usd_mm30,
       round(s.usd_vol_30d_aa::numeric, 2)  AS usd_vol_30d_aa,
       round(f.selic_meta - f.ipca_12m_ff, 2) AS juro_real_12m
FROM ffilled f
LEFT JOIN fx_stats s USING (obs_date)
-- raw SGS is backfilled to 2018 so the 30d windows above have a full lookback;
-- floor the exposed rows at 2020-01-01 (dashboard start) only after the windows
-- are computed, so early-2020 moving averages/vol are still correct
WHERE f.obs_date >= DATE '2020-01-01'
ORDER BY f.obs_date
