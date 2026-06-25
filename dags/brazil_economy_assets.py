"""Data-aware scheduling Assets — the handoff points between this project's DAGs.

Each ingestion DAG marks its ``raw_*`` Asset when a run finishes successfully;
``dbt_transform`` is scheduled on ALL of them (``RAW_ALL``), so the marts rebuild
only once the day's raw data has actually landed — not on a fixed clock. dbt then
emits ``MARTS``, and ``om_ingest`` reacts to that. This replaces fragile
time-based coordination (ingest at 08:00, dbt at 10:00 and hope it finished) with
data-aware triggering, and surfaces the dependency graph in Airflow's Assets view.

This module lives in the dags folder because Assets are Airflow objects; it is
kept out of DAG parsing via ``.airflowignore`` so Airflow never treats it as a
DAG file. The ``brazil_economy`` package under include/ stays airflow-free (and
unit-testable without Airflow installed), so the Assets do not belong there.
"""

from __future__ import annotations

from airflow.sdk import Asset

RAW_SGS = Asset(name="raw_sgs", uri="warehouse://raw/sgs")
RAW_PIX = Asset(name="raw_pix", uri="warehouse://raw/pix")
RAW_FOCUS = Asset(name="raw_focus", uri="warehouse://raw/focus")
RAW_CVM_FUNDS = Asset(name="raw_cvm_funds", uri="warehouse://raw/cvm_funds")
RAW_CVM_CDA = Asset(name="raw_cvm_cda", uri="warehouse://raw/cvm_cda")
RAW_IPCA = Asset(name="raw_ipca_aberturas", uri="warehouse://raw/ipca_aberturas")

# dbt_transform schedules on ALL raw sources: it rebuilds the marts once every
# source has landed its data for the day (AssetAll — the `&` of all six).
RAW_ALL = RAW_SGS & RAW_PIX & RAW_FOCUS & RAW_CVM_FUNDS & RAW_CVM_CDA & RAW_IPCA

# the marts layer dbt builds; om_ingest refreshes the catalog when it updates.
MARTS = Asset(name="marts", uri="warehouse://marts")
