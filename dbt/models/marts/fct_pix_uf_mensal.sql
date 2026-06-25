-- Monthly PIX activity per state (UF): values, counts and average ticket.
SELECT t.anomes,
       to_date(t.anomes::text, 'YYYYMM')              AS mes,
       t.estado_ibge,
       t.estado,
       -- ISO 3166-2 code ("BR-SP"): what Superset's Brazil country map keys on
       'BR-' || CASE t.estado_ibge
           WHEN 11 THEN 'RO' WHEN 12 THEN 'AC' WHEN 13 THEN 'AM'
           WHEN 14 THEN 'RR' WHEN 15 THEN 'PA' WHEN 16 THEN 'AP'
           WHEN 17 THEN 'TO' WHEN 21 THEN 'MA' WHEN 22 THEN 'PI'
           WHEN 23 THEN 'CE' WHEN 24 THEN 'RN' WHEN 25 THEN 'PB'
           WHEN 26 THEN 'PE' WHEN 27 THEN 'AL' WHEN 28 THEN 'SE'
           WHEN 29 THEN 'BA' WHEN 31 THEN 'MG' WHEN 32 THEN 'ES'
           WHEN 33 THEN 'RJ' WHEN 35 THEN 'SP' WHEN 41 THEN 'PR'
           WHEN 42 THEN 'SC' WHEN 43 THEN 'RS' WHEN 50 THEN 'MS'
           WHEN 51 THEN 'MT' WHEN 52 THEN 'GO' WHEN 53 THEN 'DF'
       END                                            AS uf_iso,
       t.sigla_regiao,
       t.regiao,
       sum(vl_pagador_pf + vl_pagador_pj)             AS vl_pago,
       sum(qt_pagador_pf + qt_pagador_pj)             AS qt_pago,
       sum(vl_recebedor_pf + vl_recebedor_pj)         AS vl_recebido,
       sum(qt_recebedor_pf + qt_recebedor_pj)         AS qt_recebido,
       sum(vl_pagador_pf)                             AS vl_pago_pf,
       sum(vl_pagador_pj)                             AS vl_pago_pj,
       round(sum(vl_pagador_pf + vl_pagador_pj)
             / nullif(sum(qt_pagador_pf + qt_pagador_pj), 0), 2) AS ticket_medio,
       sum(qt_pes_pagador_pf)                         AS pessoas_pagadoras_pf,
       max(p.populacao)                               AS populacao,
       -- per-capita normalization (IBGE estimates); NULL for the sentinel
       -- "NAO INFORMADO" bucket (estado_ibge = -1), which has no population
       round((sum(vl_pagador_pf + vl_pagador_pj)
              / nullif(max(p.populacao), 0))::numeric, 2) AS vl_pago_per_capita
FROM {{ ref('stg_pix_transacoes_municipio') }} t
LEFT JOIN {{ ref('stg_dim_populacao_uf') }} p ON p.uf_ibge = t.estado_ibge
GROUP BY t.anomes, t.estado_ibge, t.estado, t.sigla_regiao, t.regiao
ORDER BY t.anomes, t.estado_ibge
