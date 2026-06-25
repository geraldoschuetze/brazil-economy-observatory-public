-- PIX transactions per municipality. Sentinel -1 marks BACEN's monthly
-- "NAO INFORMADO" bucket (transactions not attributable to a municipality);
-- kept so national totals stay correct, flagged for downstream filtering.
SELECT
    anomes,
    municipio_ibge,
    municipio,
    estado_ibge,
    estado,
    sigla_regiao,
    regiao,
    vl_pagador_pf,
    qt_pagador_pf,
    vl_pagador_pj,
    qt_pagador_pj,
    vl_recebedor_pf,
    qt_recebedor_pf,
    vl_recebedor_pj,
    qt_recebedor_pj,
    qt_pes_pagador_pf,
    qt_pes_pagador_pj,
    qt_pes_recebedor_pf,
    qt_pes_recebedor_pj,
    (estado_ibge = -1) AS is_nao_informado
FROM {{ source('raw', 'pix_transacoes_municipio') }}
