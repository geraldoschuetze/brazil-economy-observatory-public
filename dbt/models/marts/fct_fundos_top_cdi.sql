-- The actual funds that beat the CDI by the widest margin in the latest
-- complete 12-month window — name, class and number of investors from the
-- registry/daily report, so the dashboard can answer "WHICH funds outperformed".
-- Only ACCESSIBLE funds are kept: at least 100 cotistas and R$10mn net worth.
-- That deliberately excludes the single-investor exclusive vehicles (1-8
-- cotistas) that otherwise dominate the top — their returns are real (verified
-- against the CVM source) but they are private structures the public can't buy.
-- Returns are still capped at +100% to drop genuine quota glitches (a handful of
-- funds report millions of percent), and only funds in normal operation are kept.
WITH cotas_mensais AS (
    SELECT DISTINCT ON (cnpj_digits, date_trunc('month', dt_comptc))
           cnpj_digits                          AS cnpj,
           date_trunc('month', dt_comptc)::date AS mes,
           vl_quota,
           nr_cotst,
           vl_patrim_liq
    FROM {{ ref('stg_cvm_inf_diario') }}
    WHERE vl_quota > 0
    ORDER BY cnpj_digits, date_trunc('month', dt_comptc), dt_comptc DESC
),
retornos AS (
    SELECT mes, cnpj, nr_cotst, vl_patrim_liq,
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
ultimo AS (
    SELECT max(mes) AS mes
    FROM cdi_12m
    WHERE n_meses = 12
      AND mes < date_trunc('month', current_date)
)
-- plain-language column names so the table reads for non-economists
SELECT cad.denom_social                                       AS "Fundo",
       -- digits-only CNPJ formatted back to the familiar 00.000.000/0001-00
       regexp_replace(r.cnpj, '(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})',
                      '\1.\2.\3/\4-\5')                        AS "CNPJ",
       coalesce(nullif(trim(cad.classe), ''), 'Outros')       AS "Classe",
       r.nr_cotst                                             AS "Cotistas",
       round((r.ret_12m * 100)::numeric, 1)                   AS "Rendimento 12 meses (%)",
       round((c.cdi_ret_12m * 100)::numeric, 1)               AS "CDI 12 meses (%)",
       round(((r.ret_12m - c.cdi_ret_12m) * 100)::numeric, 1) AS "Acima do CDI (p.p.)"
FROM retornos r
JOIN ultimo u USING (mes)
JOIN cdi_12m c USING (mes)
JOIN {{ ref('stg_cvm_cad_fi') }} cad ON cad.cnpj = r.cnpj
WHERE r.ret_12m IS NOT NULL
  AND r.ret_12m > c.cdi_ret_12m
  AND r.ret_12m < 1.0                       -- drop quota-glitch outliers
  AND cad.sit ILIKE 'em funcionamento normal'
  -- accessible funds only: broadly held (not a 1-investor exclusive vehicle)
  -- and with meaningful size
  AND r.nr_cotst >= 100
  AND r.vl_patrim_liq >= 1e7
ORDER BY "Acima do CDI (p.p.)" DESC
