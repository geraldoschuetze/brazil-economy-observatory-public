-- IPCA decomposition by expenditure group (IBGE SIDRA table 7060).
CREATE TABLE IF NOT EXISTS raw.ipca_aberturas (
    mes       date NOT NULL,
    grupo_cod int  NOT NULL,
    grupo     text NOT NULL,
    var_12m   numeric,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mes, grupo_cod)
);
