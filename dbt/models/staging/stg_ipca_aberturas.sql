-- IPCA 12-month variation by expenditure group (IBGE SIDRA 7060), with the
-- numeric prefix stripped from the group label ("1.Alimentação" -> "Alimentação").
SELECT
    mes,
    grupo_cod,
    regexp_replace(grupo, '^[0-9]+\.', '') AS grupo,
    var_12m
FROM {{ source('raw', 'ipca_aberturas') }}
