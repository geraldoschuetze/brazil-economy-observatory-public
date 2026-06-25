-- Raw landing table for BACEN SGS observations.
-- Values are kept as delivered by the API (text) — typing happens downstream
-- in the dbt staging model `stg_sgs_observations`.
CREATE TABLE IF NOT EXISTS raw.sgs_observations (
    series_code integer     NOT NULL,
    obs_date    date        NOT NULL,
    value       text        NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, obs_date)
);
