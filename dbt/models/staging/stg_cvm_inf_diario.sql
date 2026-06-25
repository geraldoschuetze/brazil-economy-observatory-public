-- CVM daily fund report, conformed. `cnpj_digits` strips punctuation so it
-- joins the registry dimension (which stores digits-only CNPJs) directly.
SELECT
    cnpj,
    translate(cnpj, './-', '') AS cnpj_digits,
    id_subclasse,
    dt_comptc,
    tp_fundo,
    vl_total,
    vl_quota,
    vl_patrim_liq,
    captc_dia,
    resg_dia,
    nr_cotst
FROM {{ source('raw', 'cvm_inf_diario') }}
