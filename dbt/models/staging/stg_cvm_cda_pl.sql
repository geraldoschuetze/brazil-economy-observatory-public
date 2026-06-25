-- CVM CDA month-end net worth per fund/class, CNPJ normalized to digits so it
-- joins the cotas holdings (and the daily informe) directly.
-- Data-quality guard: the CVM source occasionally ships a corrupted
-- vl_patrim_liq (e.g. CNPJ 13.401.638/0001-86 in 202403 arrived at ~R$369 tri
-- vs its real ~R$55 mi), which alone dwarfs the whole industry. No real
-- Brazilian fund is anywhere near R$1 tri (largest ~R$0.4 tri), so drop values
-- above that ceiling instead of letting one bad row spike the consolidated PL.
SELECT
    anomes,
    translate(cnpj, './-', '') AS cnpj_digits,
    vl_patrim_liq
FROM {{ source('raw', 'cvm_cda_pl') }}
WHERE vl_patrim_liq < 1e12
