-- CVM CDA holdings in cotas of other funds (BLC_2), CNPJs normalized to digits.
-- cnpj_investido_digits is the target fund — the side that may double-count when
-- the target is itself in the PL universe.
SELECT
    anomes,
    translate(cnpj_investidor, './-', '')              AS cnpj_investidor_digits,
    translate(coalesce(cnpj_investido, ''), './-', '') AS cnpj_investido_digits,
    vl_mercado
FROM {{ source('raw', 'cvm_cda_cotas') }}
-- same data-quality guard as stg_cvm_cda_pl: the 202403 corruption hit this
-- side too (one holding at ~R$369 tri), which would over-subtract and push the
-- consolidated PL negative. No real cota holding approaches R$1 tri.
WHERE vl_mercado < 1e12
