"""Ingest CVM CDA (fund portfolios) to de-duplicate fund-of-funds in the PL.

The daily informe sums every class's net worth, double-counting the slice a
feeder holds in cotas of other funds. The CDA "Cotas de Fundos" block (BLC_2)
quantifies exactly that, so downstream (dbt) the consolidated industry PL =
sum(PL) − cotas held in funds that are themselves in the universe.

Monthly source with a publication lag. Each run loads months not yet present
plus the two most recent (subject to revision); months not published yet answer
404 and are skipped. Backfill depth via Airflow Variable CVM_CDA_BACKFILL_START
(YYYYMM, default 202401 = ~30 months, matching the inf_diario backfill so the
consolidated PL has the same history). CDA CSVs use a DOT decimal separator.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta

import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Variable

from brazil_economy import transforms
from brazil_economy.alerts import notify_failure
from brazil_economy_assets import RAW_CVM_CDA

# CDA holding rows can carry very long free-text fields
csv.field_size_limit(10**7)

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
DEFAULT_FIRST_MONTH = 202401
URL = "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_{anomes}.zip"
SQL_DIR = "/opt/airflow/include/sql"


@dag(
    dag_id="ingest_cvm_cda",
    description="CVM CDA fund portfolios (cotas block) -> raw (consolidated PL by dbt)",
    schedule="0 7 * * 1-5",  # cheap weekday check; only missing months actually load (no CVM publish on weekends)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=3),
        "on_failure_callback": notify_failure,
    },
    tags=["cvm", "fundos", "cda", "ingestion"],
)
def ingest_cvm_cda():
    @task
    def create_tables() -> None:
        hook = PostgresHook(CONN_ID)
        with open(f"{SQL_DIR}/ddl/008_cvm_cda.sql") as f:
            hook.run(f.read())

    @task
    def months_to_load() -> list[int]:
        first = int(Variable.get("CVM_CDA_BACKFILL_START", DEFAULT_FIRST_MONTH))
        hook = PostgresHook(CONN_ID)
        today = date.today()
        last_month = today.year * 100 + today.month
        loaded = [
            row[0]
            for row in hook.get_records("SELECT DISTINCT anomes FROM raw.cvm_cda_pl")
        ]
        result = transforms.months_to_load(first, last_month, loaded)
        log.info("loading %d months: %s", len(result), result)
        return result

    @task(max_active_tis_per_dag=3)
    def ingest_month(anomes: int) -> int:
        resp = requests.get(URL.format(anomes=anomes), timeout=300)
        if resp.status_code == 404:
            log.info("CDA month %s not published yet", anomes)
            return 0
        resp.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        # L1: zip-bomb guard — reject an absurd declared uncompressed size before
        # reading members into memory (real CVM archives are well under 2 GiB).
        if sum(zi.file_size for zi in archive.infolist()) > 2 * 1024**3:
            raise ValueError(f"CDA archive {anomes} exceeds the 2 GiB uncompressed cap")

        # month-end PL per fund/class (gross + the netting universe)
        pl_rows: list[tuple] = []
        with archive.open(f"cda_fi_PL_{anomes}.csv") as fh:
            # CVM open-data CSVs are ';'-delimited with NO quoting convention;
            # free-text fields (e.g. fund names) can contain a stray '"'. Without
            # QUOTE_NONE the reader treats it as a quoted field and swallows the
            # rest of the file into one field -> "field larger than field limit".
            reader = csv.DictReader(
                io.TextIOWrapper(fh, encoding="latin-1"),
                delimiter=";",
                quoting=csv.QUOTE_NONE,
            )
            for row in reader:
                pl_rows.append(
                    (
                        anomes,
                        row["CNPJ_FUNDO_CLASSE"],
                        transforms.cvm_cda_value(row["VL_PATRIM_LIQ"]),
                    )
                )

        # holdings in cotas of other funds (BLC_2), staged for COPY
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        cota_count = 0
        with archive.open(f"cda_fi_BLC_2_{anomes}.csv") as fh:
            # CVM open-data CSVs are ';'-delimited with NO quoting convention;
            # free-text fields (e.g. fund names) can contain a stray '"'. Without
            # QUOTE_NONE the reader treats it as a quoted field and swallows the
            # rest of the file into one field -> "field larger than field limit".
            reader = csv.DictReader(
                io.TextIOWrapper(fh, encoding="latin-1"),
                delimiter=";",
                quoting=csv.QUOTE_NONE,
            )
            for row in reader:
                writer.writerow(
                    (
                        anomes,
                        row["CNPJ_FUNDO_CLASSE"],
                        row.get("CNPJ_FUNDO_CLASSE_COTA") or "",
                        transforms.cvm_cda_value(row["VL_MERC_POS_FINAL"]) or "",
                    )
                )
                cota_count += 1
        buffer.seek(0)

        hook = PostgresHook(CONN_ID)
        conn = hook.get_conn()
        with conn, conn.cursor() as cur:
            # full month refresh — idempotent re-runs replace the month cleanly
            cur.execute("DELETE FROM raw.cvm_cda_pl WHERE anomes = %s", (anomes,))
            cur.execute("DELETE FROM raw.cvm_cda_cotas WHERE anomes = %s", (anomes,))
            cur.executemany(
                "INSERT INTO raw.cvm_cda_pl (anomes, cnpj, vl_patrim_liq) "
                "VALUES (%s, %s, %s) ON CONFLICT (anomes, cnpj) DO UPDATE SET "
                "vl_patrim_liq = EXCLUDED.vl_patrim_liq, loaded_at = now()",
                pl_rows,
            )
            cur.copy_expert(
                "COPY raw.cvm_cda_cotas "
                "(anomes, cnpj_investidor, cnpj_investido, vl_mercado) "
                "FROM STDIN WITH (FORMAT csv)",
                buffer,
            )
        log.info(
            "CDA month %s: %d funds (PL), %d cota holdings",
            anomes,
            len(pl_rows),
            cota_count,
        )
        return cota_count

    @task(outlets=[RAW_CVM_CDA])
    def publish() -> None:
        """Mark this run's raw CVM CDA data ready — data-aware handoff to dbt."""
        log.info("raw CVM CDA landed; dbt_transform schedules on it")

    tables = create_tables()
    months = months_to_load()
    ingested = ingest_month.expand(anomes=months)
    tables >> months >> ingested >> publish()


ingest_cvm_cda()
