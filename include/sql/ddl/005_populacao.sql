-- State population dimension (IBGE estimates) to normalize PIX volumes.
CREATE TABLE IF NOT EXISTS raw.dim_populacao_uf (
    uf_ibge   int PRIMARY KEY,
    uf        text NOT NULL,
    populacao bigint NOT NULL,
    ano       int NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
