-- Monthly fund flows split by class (CVM registries, both regimes):
-- where the money migrates — fixed income vs equities vs multimarket.
-- Staging already exposes digits-only CNPJs, joining the registry directly.
-- Registered rows without a classification (FIDC/FII/FIP classes) -> 'Outros';
-- no registry match at all -> 'Sem cadastro'.
WITH diario AS (
    SELECT cnpj_digits,
           date_trunc('month', dt_comptc)::date AS mes,
           captc_dia, resg_dia
    FROM {{ ref('stg_cvm_inf_diario') }}
    WHERE dt_comptc < date_trunc('month', current_date)
)
SELECT f.mes,
       CASE
           WHEN c.cnpj IS NULL THEN 'Sem cadastro'
           ELSE coalesce(nullif(trim(c.classe), ''), 'Outros')
       END                                     AS classe,
       count(DISTINCT f.cnpj_digits)           AS n_fundos,
       sum(f.captc_dia)                        AS captacao,
       sum(f.resg_dia)                         AS resgates,
       sum(f.captc_dia) - sum(f.resg_dia)      AS captacao_liquida
FROM diario f
LEFT JOIN {{ ref('stg_cvm_cad_fi') }} c ON c.cnpj = f.cnpj_digits
GROUP BY 1, 2
ORDER BY 1, 2
