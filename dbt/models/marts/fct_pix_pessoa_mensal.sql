-- Monthly PIX paid value PER STATE, UNPIVOTED by payer type (CPF = pessoa
-- física, CNPJ = pessoa jurídica). The wide source keeps PF/PJ in separate
-- columns; a native select filter needs a DIMENSION with those as values, so
-- this long shape exposes `tipo_pessoa`. It is the per-state-per-type base for
-- every PIX chart that should react to the CPF/CNPJ filter — region totals,
-- national ticket, per-capita ranking/map and the projection all derive from it.
-- `regiao` is kept so the PIX region filter still cross-applies.
WITH long AS (
    SELECT to_date(anomes::text, 'YYYYMM')::date AS mes, anomes,
           estado_ibge, estado, sigla_regiao, regiao,
           'CPF (pessoa física)' AS tipo_pessoa,
           vl_pagador_pf AS vl_pago, qt_pagador_pf AS qt_pago
    FROM {{ ref('stg_pix_transacoes_municipio') }}
    UNION ALL
    SELECT to_date(anomes::text, 'YYYYMM')::date, anomes,
           estado_ibge, estado, sigla_regiao, regiao,
           'CNPJ (pessoa jurídica)',
           vl_pagador_pj, qt_pagador_pj
    FROM {{ ref('stg_pix_transacoes_municipio') }}
),
agg AS (
    SELECT mes, anomes, estado_ibge, estado, sigla_regiao, regiao, tipo_pessoa,
           sum(vl_pago) AS vl_pago,
           sum(qt_pago) AS qt_pago
    FROM long
    GROUP BY mes, anomes, estado_ibge, estado, sigla_regiao, regiao, tipo_pessoa
)
SELECT a.mes,
       a.anomes,
       a.estado_ibge,
       a.estado,
       -- ISO 3166-2 ("BR-SP") for Superset's Brazil country map
       'BR-' || CASE a.estado_ibge
           WHEN 11 THEN 'RO' WHEN 12 THEN 'AC' WHEN 13 THEN 'AM'
           WHEN 14 THEN 'RR' WHEN 15 THEN 'PA' WHEN 16 THEN 'AP'
           WHEN 17 THEN 'TO' WHEN 21 THEN 'MA' WHEN 22 THEN 'PI'
           WHEN 23 THEN 'CE' WHEN 24 THEN 'RN' WHEN 25 THEN 'PB'
           WHEN 26 THEN 'PE' WHEN 27 THEN 'AL' WHEN 28 THEN 'SE'
           WHEN 29 THEN 'BA' WHEN 31 THEN 'MG' WHEN 32 THEN 'ES'
           WHEN 33 THEN 'RJ' WHEN 35 THEN 'SP' WHEN 41 THEN 'PR'
           WHEN 42 THEN 'SC' WHEN 43 THEN 'RS' WHEN 50 THEN 'MS'
           WHEN 51 THEN 'MT' WHEN 52 THEN 'GO' WHEN 53 THEN 'DF'
       END                                          AS uf_iso,
       a.sigla_regiao,
       a.regiao,
       a.tipo_pessoa,
       a.vl_pago,
       a.qt_pago,
       p.populacao
FROM agg a
LEFT JOIN {{ ref('stg_dim_populacao_uf') }} p ON p.uf_ibge = a.estado_ibge
ORDER BY a.mes, a.estado_ibge, a.tipo_pessoa
