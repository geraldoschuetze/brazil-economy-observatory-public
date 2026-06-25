"""Ingest BACEN SGS time series into the brazil_economy warehouse.

Incremental and idempotent: each run fetches only observations newer than the
latest date already stored per series and upserts them — re-running any
interval never duplicates data. The very first run backfills from START_DATE.

To deepen history (e.g. so the 12-month and 24-month derived indicators exist
for the earliest displayed years), set the Airflow Variable SGS_BACKFILL_START
to an ISO date (YYYY-MM-DD). When present, each series is re-fetched from that
date regardless of what is already stored — the upsert deduplicates, so it only
adds the missing earlier observations.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Variable

from brazil_economy.alerts import notify_failure
from brazil_economy_assets import RAW_SGS

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
START_DATE = date(2020, 1, 1)
API_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
SQL_DIR = Path("/opt/airflow/include/sql")
# the SGS API caps each request at 10 years of data; chunk well below that
MAX_CHUNK_DAYS = 3600

SERIES = {
    432: "Selic target rate (% p.a.)",
    4189: "Selic effective rate, monthly accumulated annualized (% p.a.)",
    12: "CDI daily rate (% p.d.)",
    433: "IPCA monthly variation (%)",
    13522: "IPCA 12-month accumulated (%)",
    13521: "Inflation target (% p.a., annual)",
    189: "IGP-M monthly variation (%)",
    24364: "IBC-Br economic activity index",
    4466: "IPCA core, smoothed trimmed means (% monthly)",
    21379: "IPCA diffusion index (% of items rising)",
    13762: "Gross general government debt (% GDP)",
    5793: "Primary balance, NFSP 12m (% GDP; + = deficit)",
    24369: "Unemployment rate, PNADC rolling quarter (%)",
    1: "USD/BRL exchange rate (sell)",
    21619: "EUR/BRL exchange rate (sell)",
}

UPSERT_SQL = """
    INSERT INTO raw.sgs_observations (series_code, obs_date, value)
    VALUES (%s, %s, %s)
    ON CONFLICT (series_code, obs_date)
    DO UPDATE SET value = EXCLUDED.value, loaded_at = now()
"""


@dag(
    dag_id="ingest_sgs",
    description="BACEN SGS macro indicators -> raw (marts built by dbt_transform)",
    schedule="0 8 * * 1-5",  # BACEN publishes most series early morning BRT; weekdays only
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,  # concurrent runs would race on DDL and upserts
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": notify_failure,
    },
    tags=["bacen", "sgs", "ingestion"],
)
def ingest_sgs():
    @task
    def create_tables() -> None:
        PostgresHook(CONN_ID).run((SQL_DIR / "ddl" / "001_sgs.sql").read_text())

    @task
    def ingest_series(code: int) -> int:
        hook = PostgresHook(CONN_ID)
        last = hook.get_first(
            "SELECT max(obs_date) FROM raw.sgs_observations WHERE series_code = %s",
            parameters=(code,),
        )[0]
        start = last + timedelta(days=1) if last else START_DATE
        # backfill override: pull from the requested date as well, never skipping
        # forward of it — the upsert dedups the overlap with stored rows
        backfill = Variable.get("SGS_BACKFILL_START", None)
        if backfill:
            start = min(start, date.fromisoformat(backfill))
        today = date.today()
        if start > today:
            log.info("series %s already up to date", code)
            return 0

        rows: list[tuple[int, date, str]] = []
        chunk_start = start
        while chunk_start <= today:
            chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS), today)
            resp = requests.get(
                API_URL.format(code=code),
                params={
                    "formato": "json",
                    "dataInicial": chunk_start.strftime("%d/%m/%Y"),
                    "dataFinal": chunk_end.strftime("%d/%m/%Y"),
                },
                timeout=60,
            )
            if resp.status_code == 404:
                # SGS answers 404 when the window holds no observations yet
                # (e.g. today's value not published) — that is not an error
                chunk_start = chunk_end + timedelta(days=1)
                continue
            resp.raise_for_status()
            for item in resp.json():
                obs_date = datetime.strptime(item["data"], "%d/%m/%Y").date()
                rows.append((code, obs_date, item["valor"]))
            chunk_start = chunk_end + timedelta(days=1)

        if rows:
            conn = hook.get_conn()
            with conn, conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
        log.info(
            "series %s (%s): upserted %d rows from %s",
            code,
            SERIES[code],
            len(rows),
            start,
        )
        return len(rows)

    @task(outlets=[RAW_SGS])
    def publish() -> None:
        """Mark this run's raw SGS data ready — data-aware handoff to dbt."""
        log.info("raw SGS landed; dbt_transform schedules on it")

    # raw landing only — the marts are built and tested by the dbt_transform DAG
    tables = create_tables()
    ingested = ingest_series.expand(code=list(SERIES))
    tables >> ingested >> publish()


ingest_sgs()
