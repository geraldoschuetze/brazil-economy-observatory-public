-- CVM fund/class registry dimension (CNPJ already normalized to digits-only
-- by the ingestion DAG, unifying the pre/post CVM-175 regimes).
SELECT
    cnpj,
    denom_social,
    sit,
    classe,
    gestor,
    administrador
FROM {{ source('raw', 'cvm_cad_fi') }}
