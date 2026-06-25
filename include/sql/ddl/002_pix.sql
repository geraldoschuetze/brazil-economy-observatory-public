-- Raw landing table for BACEN Olinda "TransacoesPixPorMunicipio".
-- One row per (month, municipality); values revised by BACEN are upserted.
CREATE TABLE IF NOT EXISTS raw.pix_transacoes_municipio (
    anomes           integer NOT NULL,
    municipio_ibge   integer NOT NULL,
    municipio        text,
    estado_ibge      integer,
    estado           text,
    sigla_regiao     text,
    regiao           text,
    vl_pagador_pf    numeric,
    qt_pagador_pf    bigint,
    vl_pagador_pj    numeric,
    qt_pagador_pj    bigint,
    vl_recebedor_pf  numeric,
    qt_recebedor_pf  bigint,
    vl_recebedor_pj  numeric,
    qt_recebedor_pj  bigint,
    qt_pes_pagador_pf   bigint,
    qt_pes_pagador_pj   bigint,
    qt_pes_recebedor_pf bigint,
    qt_pes_recebedor_pj bigint,
    loaded_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (anomes, municipio_ibge)
);
