-- Raw landing table for CVM "informe diário" of investment funds.
-- Supports both CSV layouts (pre/post the 2025 fund-class reform):
-- old TP_FUNDO/CNPJ_FUNDO and new TP_FUNDO_CLASSE/CNPJ_FUNDO_CLASSE/ID_SUBCLASSE.
CREATE TABLE IF NOT EXISTS raw.cvm_inf_diario (
    cnpj           text    NOT NULL,
    id_subclasse   text    NOT NULL DEFAULT '',
    dt_comptc      date    NOT NULL,
    tp_fundo       text,
    vl_total       numeric,
    vl_quota       numeric,
    vl_patrim_liq  numeric,
    captc_dia      numeric,
    resg_dia       numeric,
    nr_cotst       integer,
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cnpj, id_subclasse, dt_comptc)
);

CREATE INDEX IF NOT EXISTS cvm_inf_diario_dt_idx ON raw.cvm_inf_diario (dt_comptc);
