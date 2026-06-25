"""Ingest BACEN Focus survey expectations (Olinda OData API).

Median market expectations for IPCA and Selic, by survey date and reference
year. Same Olinda platform as PIX, hence the same quirks: literal @/$/' in the
query string and NO $skip support — so requests are chunked by (indicator,
survey year), each safely under the page cap. Incremental by max survey date.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook

from brazil_economy.alerts import notify_failure
from brazil_economy_assets import RAW_FOCUS

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
FIRST_YEAR = 2020
PAGE_SIZE = 10_000
API_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
    "odata/ExpectativasMercadoAnuais"
)
SQL_DIR = "/opt/airflow/include/sql"
INDICATORS = ["IPCA", "Selic"]

UPSERT_SQL = """
    INSERT INTO raw.focus_expectativas
        (indicador, data, data_referencia, mediana, respondentes)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (indicador, data, data_referencia) DO UPDATE SET
        mediana = EXCLUDED.mediana,
        respondentes = EXCLUDED.respondentes,
        loaded_at = now()
"""


def _get_with_backoff(url: str, attempts: int = 5) -> requests.Response:
    for attempt in range(attempts):
        resp = requests.get(url, timeout=120)
        if resp.status_code not in (429, 500, 502, 503):
            resp.raise_for_status()
            return resp
        wait = 2**attempt * 3
        log.warning("Olinda returned %s, retrying in %ss", resp.status_code, wait)
        time.sleep(wait)
    resp.raise_for_status()
    return resp


@dag(
    dag_id="ingest_focus",
    description="BACEN Focus market expectations -> raw (marts built by dbt_transform)",
    schedule="15 8 * * 1-5",  # Focus is published Monday mornings; weekdays only (no BCB publish on weekends)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": notify_failure,
    },
    tags=["bacen", "focus", "ingestion"],
)
def ingest_focus():
    @task
    def create_tables() -> None:
        hook = PostgresHook(CONN_ID)
        with open(f"{SQL_DIR}/ddl/006_focus.sql") as f:
            hook.run(f.read())

    @task
    def chunks_to_load() -> list[dict]:
        """One chunk per (indicator, survey year) still missing or current."""
        hook = PostgresHook(CONN_ID)
        this_year = date.today().year
        chunks = []
        for indicador in INDICATORS:
            last = hook.get_first(
                "SELECT max(data) FROM raw.focus_expectativas WHERE indicador = %s",
                parameters=(indicador,),
            )[0]
            start_year = last.year if last else FIRST_YEAR
            for year in range(start_year, this_year + 1):
                chunks.append({"indicador": indicador, "ano": year})
        log.info("loading %d chunks", len(chunks))
        return chunks

    # sequential: Olinda rate-limits parallel bursts into 500s
    @task(max_active_tis_per_dag=1)
    def ingest_chunk(chunk: dict) -> int:
        indicador, ano = chunk["indicador"], chunk["ano"]
        query = urlencode(
            {
                "$filter": (
                    f"Indicador eq '{indicador}' and baseCalculo eq 0 "
                    f"and Data ge '{ano}-01-01' and Data lt '{ano + 1}-01-01'"
                ),
                "$select": "Indicador,Data,DataReferencia,Mediana,numeroRespondentes",
                "$top": PAGE_SIZE,
                "$format": "json",
            },
            quote_via=quote,
            safe="@$'",
        )
        resp = _get_with_backoff(f"{API_URL}?{query}")
        batch = resp.json()["value"]
        if len(batch) >= PAGE_SIZE:
            raise ValueError(
                f"chunk {indicador}/{ano} hit the {PAGE_SIZE}-row page cap and "
                "Olinda does not support $skip — refusing to silently truncate"
            )
        rows = [
            (
                item["Indicador"],
                item["Data"],
                int(item["DataReferencia"]),
                item["Mediana"],
                item["numeroRespondentes"],
            )
            for item in batch
        ]
        time.sleep(1)
        if rows:
            hook = PostgresHook(CONN_ID)
            conn = hook.get_conn()
            with conn, conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
        log.info("%s/%s: upserted %d expectations", indicador, ano, len(rows))
        return len(rows)

    @task(outlets=[RAW_FOCUS])
    def publish() -> None:
        """Mark this run's raw Focus data ready — data-aware handoff to dbt."""
        log.info("raw Focus landed; dbt_transform schedules on it")

    # raw landing only — the Focus/Taylor marts are built and tested by dbt_transform
    tables = create_tables()
    chunks = chunks_to_load()
    ingested = ingest_chunk.expand(chunk=chunks)
    tables >> chunks >> ingested >> publish()


ingest_focus()
