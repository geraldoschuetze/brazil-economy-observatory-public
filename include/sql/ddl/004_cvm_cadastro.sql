-- Fund registry dimension (CVM cad_fi): class and manager per CNPJ.
CREATE TABLE IF NOT EXISTS raw.cvm_cad_fi (
    cnpj          text PRIMARY KEY,
    denom_social  text,
    sit           text,
    classe        text,
    gestor        text,
    administrador text,
    loaded_at     timestamptz NOT NULL DEFAULT now()
);
