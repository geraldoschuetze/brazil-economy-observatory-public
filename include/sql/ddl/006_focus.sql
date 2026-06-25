-- BACEN Focus survey: median market expectations for annual indicators.
CREATE TABLE IF NOT EXISTS raw.focus_expectativas (
    indicador       text NOT NULL,
    data            date NOT NULL,
    data_referencia int  NOT NULL,
    mediana         numeric,
    respondentes    int,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (indicador, data, data_referencia)
);
