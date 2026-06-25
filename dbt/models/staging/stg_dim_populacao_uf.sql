-- IBGE state population estimates — the per-capita denominator for PIX marts.
SELECT
    uf_ibge,
    uf,
    populacao,
    ano
FROM {{ source('raw', 'dim_populacao_uf') }}
