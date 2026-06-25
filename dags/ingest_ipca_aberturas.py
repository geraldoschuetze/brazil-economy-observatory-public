"""Ingest IPCA decomposition by expenditure group (IBGE SIDRA table 7060).

Which price groups are driving inflation: food, housing, transport, health,
education — 12-month accumulated variation per group plus the headline index.
Table 7060 starts in 2020 and is tiny (hundreds of rows), so each run does a
full refresh in a single API call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook

from brazil_economy import transforms
from brazil_economy.alerts import notify_failure
from brazil_economy_assets import RAW_IPCA

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
SQL_DIR = "/opt/airflow/include/sql"
# c315 classification: headline + the nine expenditure groups
GRUPOS = "7169,7170,7445,7486,7558,7625,7660,7712,7766,7786"
API_URL = (
    "https://apisidra.ibge.gov.br/values/t/7060/n1/all/v/2265"
    f"/p/all/c315/{GRUPOS}/d/v2265%202"
)


@dag(
    dag_id="ingest_ipca_aberturas",
    description="IBGE SIDRA IPCA by expenditure group -> raw (marts built by dbt)",
    schedule="45 8 * * 1-5",  # weekdays only (no IBGE/BCB publish on weekends)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": notify_failure,
    },
    tags=["ibge", "ipca", "ingestion"],
)
def ingest_ipca_aberturas():
    @task
    def create_tables() -> None:
        hook = PostgresHook(CONN_ID)
        with open(f"{SQL_DIR}/ddl/007_ipca_aberturas.sql") as f:
            hook.run(f.read())

    @task
    def ingest() -> int:
        resp = requests.get(API_URL, timeout=120)
        resp.raise_for_status()
        payload = resp.json()
        rows = []
        for item in payload[1:]:  # row 0 is the header
            valor = item["V"]
            if not transforms.is_ipca_value_published(valor):
                continue
            rows.append(
                (
                    transforms.sidra_period_to_date(item["D3C"]),  # D3C = YYYYMM
                    int(item["D4C"]),
                    item["D4N"],
                    valor,
                )
            )
        hook = PostgresHook(CONN_ID)
        conn = hook.get_conn()
        with conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw.ipca_aberturas (mes, grupo_cod, grupo, var_12m) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (mes, grupo_cod) DO UPDATE SET "
                "var_12m = EXCLUDED.var_12m, grupo = EXCLUDED.grupo, "
                "loaded_at = now()",
                rows,
            )
        log.info("upserted %d group-month rows", len(rows))
        return len(rows)

    @task(outlets=[RAW_IPCA])
    def publish() -> None:
        """Mark this run's raw IPCA data ready — data-aware handoff to dbt."""
        log.info("raw IPCA landed; dbt_transform schedules on it")

    # raw landing only — the IPCA mart is built and tested by dbt_transform
    create_tables() >> ingest() >> publish()


ingest_ipca_aberturas()
