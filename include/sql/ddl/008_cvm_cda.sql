-- Raw landing for CVM CDA (Composição e Diversificação das Aplicações) —
-- monthly fund portfolios. Used to de-duplicate fund-of-funds: the daily
-- informe sums every class's net worth, double-counting the slice a feeder
-- holds in cotas of other funds. CDA's "Cotas de Fundos" block (BLC_2) tells us
-- exactly that slice, so the consolidated industry PL = sum(PL) − cotas held in
-- funds that are themselves in the universe.
--
-- NOTE: CDA files use DOT as the decimal separator (unlike the daily informe,
-- which uses comma) — parsed accordingly in the ingestion DAG.

-- Month-end net worth per fund/class (cda_fi_PL_AAAAMM.csv): the gross PL and
-- the universe of funds whose cotas count as double-counting.
CREATE TABLE IF NOT EXISTS raw.cvm_cda_pl (
    anomes        integer     NOT NULL,
    cnpj          text        NOT NULL,
    vl_patrim_liq numeric,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (anomes, cnpj)
);

-- Holdings in cotas of other funds (cda_fi_BLC_2_AAAAMM.csv): per investor
-- class, the market value invested in a target fund/class.
CREATE TABLE IF NOT EXISTS raw.cvm_cda_cotas (
    anomes          integer     NOT NULL,
    cnpj_investidor text        NOT NULL,
    cnpj_investido  text,
    vl_mercado      numeric,
    loaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cvm_cda_cotas_anomes_idx ON raw.cvm_cda_cotas (anomes);
