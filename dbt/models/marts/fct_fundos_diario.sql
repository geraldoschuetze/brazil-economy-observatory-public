-- Daily aggregates of the CVM investment-fund universe, by fund type.
-- Sparse days (weekends/holidays when only a fraction of funds report) are
-- dropped: net worth is a stock metric and partial coverage renders as
-- misleading cliffs in level charts.
WITH diario AS (
    SELECT dt_comptc,
           coalesce(tp_fundo, 'N/D')          AS tp_fundo,
           count(DISTINCT cnpj)               AS n_fundos,
           sum(vl_patrim_liq)                 AS patrimonio_liquido,
           sum(captc_dia)                     AS captacao_dia,
           sum(resg_dia)                      AS resgate_dia,
           sum(captc_dia) - sum(resg_dia)     AS captacao_liquida,
           sum(nr_cotst)                      AS cotistas
    FROM {{ ref('stg_cvm_inf_diario') }}
    GROUP BY dt_comptc, coalesce(tp_fundo, 'N/D')
),
cobertura AS (
    SELECT dt_comptc, sum(n_fundos) AS fundos_no_dia,
           max(sum(n_fundos)) OVER () AS max_fundos
    FROM diario
    GROUP BY dt_comptc
)
SELECT d.*
FROM diario d
JOIN cobertura c USING (dt_comptc)
WHERE c.fundos_no_dia >= c.max_fundos * 0.5
ORDER BY d.dt_comptc, d.tp_fundo
