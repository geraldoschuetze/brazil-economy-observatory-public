"""Ingest CVM daily investment-fund reports (informe diário).

High-volume source: ~500k rows per monthly CSV (zipped), updated daily for the
current month. Each run loads every month not yet present plus the two most
recent ones, staging rows via COPY and upserting by (cnpj, subclass, date).

Backfill depth is controlled by the Airflow Variable CVM_BACKFILL_START
(YYYYMM, default 202401 = ~30 months) — deep enough for the trailing-12-month
fund metrics (e.g. % beating the CDI) to populate. Override via the Variable.
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
from brazil_economy_assets import RAW_CVM_FUNDS

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
DEFAULT_FIRST_MONTH = 202401
URL = (
    "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{anomes}.zip"
)
CAD_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"
REGISTRO_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
SQL_DIR = "/opt/airflow/include/sql"
COPY_COLUMNS = (
    "cnpj",
    "id_subclasse",
    "dt_comptc",
    "tp_fundo",
    "vl_total",
    "vl_quota",
    "vl_patrim_liq",
    "captc_dia",
    "resg_dia",
    "nr_cotst",
)

MERGE_SQL = f"""
    INSERT INTO raw.cvm_inf_diario ({", ".join(COPY_COLUMNS)})
    SELECT {", ".join(COPY_COLUMNS)} FROM _cvm_stage
    ON CONFLICT (cnpj, id_subclasse, dt_comptc) DO UPDATE SET
        tp_fundo      = EXCLUDED.tp_fundo,
        vl_total      = EXCLUDED.vl_total,
        vl_quota      = EXCLUDED.vl_quota,
        vl_patrim_liq = EXCLUDED.vl_patrim_liq,
        captc_dia     = EXCLUDED.captc_dia,
        resg_dia      = EXCLUDED.resg_dia,
        nr_cotst      = EXCLUDED.nr_cotst,
        loaded_at     = now()
"""


@dag(
    dag_id="ingest_cvm_funds",
    description="CVM daily fund reports (high volume) -> raw (marts built by dbt)",
    schedule="0 9 * * 1-5",  # CVM refreshes files around 04:00 BRT; weekdays only (no CVM publish on weekends)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=3),
        "on_failure_callback": notify_failure,
    },
    tags=["cvm", "fundos", "ingestion"],
)
def ingest_cvm_funds():
    @task
    def create_tables() -> None:
        hook = PostgresHook(CONN_ID)
        for ddl in ("003_cvm.sql", "004_cvm_cadastro.sql"):
            with open(f"{SQL_DIR}/ddl/{ddl}") as f:
                hook.run(f.read())

    @task
    def ingest_cadastro() -> int:
        """Fund/class registry dimension, full refresh from BOTH regimes.

        Old regime: cad_fi.csv keyed by fund CNPJ. New regime (CVM 175): the
        daily report identifies SHARE CLASSES, registered in
        registro_classe.csv keyed by class CNPJ — without it ~99% of current
        flows would not match any registry row. CNPJs are normalized to
        digits-only; class labels are unified across regimes ('Fundo de
        Renda Fixa' -> 'Renda Fixa'). New regime wins on collisions.

        Resilience: if CVM drops registro_fundo_classe.zip (HTTP 404, a
        recurring publication gap on their open-data bucket — not our bug),
        we keep the cad_fi.csv registry and skip class enrichment this run
        with a loud warning instead of failing the DAG; the next run recovers
        automatically once CVM republishes. Any other error still raises.
        """
        best: dict[str, tuple] = {}

        resp = requests.get(CAD_URL, timeout=300)
        resp.raise_for_status()
        reader = csv.DictReader(
            io.StringIO(resp.content.decode("latin-1")), delimiter=";"
        )
        for row in reader:
            cnpj = transforms.only_digits(row["CNPJ_FUNDO"])
            active = row.get("SIT", "").startswith("EM FUNCIONAMENTO")
            if cnpj not in best or active:
                classe = transforms.clean_fund_class(row.get("CLASSE"))
                best[cnpj] = (
                    cnpj,
                    row.get("DENOM_SOCIAL"),
                    row.get("SIT"),
                    classe,
                    row.get("GESTOR"),
                    row.get("ADMIN"),
                )

        resp = requests.get(REGISTRO_URL, timeout=300)
        if resp.status_code == 404:
            # CVM publication gap: the class registry is temporarily missing.
            # Degrade gracefully (cad_fi.csv only) instead of failing the DAG.
            log.warning(
                "CVM registro_fundo_classe.zip indisponivel (HTTP 404) em %s; "
                "seguindo so com cad_fi.csv — enriquecimento de classe incompleto "
                "nesta carga. Sera recuperado quando a CVM republicar.",
                REGISTRO_URL,
            )
        else:
            resp.raise_for_status()
            archive = zipfile.ZipFile(io.BytesIO(resp.content))
            # L1: zip-bomb guard before reading the member into memory.
            if sum(zi.file_size for zi in archive.infolist()) > 2 * 1024**3:
                raise ValueError(
                    "CVM registro archive exceeds the 2 GiB uncompressed cap"
                )
            text = io.TextIOWrapper(
                archive.open("registro_classe.csv"), encoding="latin-1"
            )
            for row in csv.DictReader(text, delimiter=";"):
                cnpj = transforms.only_digits(row["CNPJ_Classe"])
                active = row.get("Situacao", "").startswith("Em Funcionamento")
                if cnpj not in best or active:
                    best[cnpj] = (
                        cnpj,
                        row.get("Denominacao_Social"),
                        row.get("Situacao"),
                        row.get("Classificacao"),
                        None,
                        None,
                    )

        hook = PostgresHook(CONN_ID)
        conn = hook.get_conn()
        with conn, conn.cursor() as cur:
            cur.execute("TRUNCATE raw.cvm_cad_fi")
            cur.executemany(
                "INSERT INTO raw.cvm_cad_fi "
                "(cnpj, denom_social, sit, classe, gestor, administrador) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                list(best.values()),
            )
        log.info("registry refreshed: %d funds/classes", len(best))
        return len(best)

    @task
    def months_to_load() -> list[int]:
        first = int(Variable.get("CVM_BACKFILL_START", DEFAULT_FIRST_MONTH))
        hook = PostgresHook(CONN_ID)
        today = date.today()
        last_month = today.year * 100 + today.month
        loaded = [
            row[0]
            for row in hook.get_records(
                "SELECT DISTINCT to_char(dt_comptc, 'YYYYMM')::int FROM raw.cvm_inf_diario"
            )
        ]
        result = transforms.months_to_load(first, last_month, loaded)
        log.info("loading %d months: %s", len(result), result)
        return result

    @task(max_active_tis_per_dag=2)  # each month is a ~50 MB CSV; limit parallelism
    def ingest_month(anomes: int) -> int:
        resp = requests.get(URL.format(anomes=anomes), timeout=300)
        if resp.status_code == 404:
            log.info("month %s not published yet", anomes)
            return 0
        resp.raise_for_status()

        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        # L1: zip-bomb guard before reading the member into memory.
        if sum(zi.file_size for zi in archive.infolist()) > 2 * 1024**3:
            raise ValueError(f"CVM inf_diario archive {anomes} exceeds the 2 GiB cap")
        csv_name = archive.namelist()[0]
        text = io.TextIOWrapper(archive.open(csv_name), encoding="latin-1")
        reader = csv.DictReader(text, delimiter=";")

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        count = 0
        for row in reader:
            writer.writerow(transforms.normalize_cvm_row(row))
            count += 1
        buffer.seek(0)

        hook = PostgresHook(CONN_ID)
        conn = hook.get_conn()
        with conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE _cvm_stage (LIKE raw.cvm_inf_diario "
                "INCLUDING DEFAULTS EXCLUDING CONSTRAINTS) ON COMMIT DROP"
            )
            cur.copy_expert(
                f"COPY _cvm_stage ({', '.join(COPY_COLUMNS)}) "
                # empty CSV fields become NULL by default; id_subclasse is part
                # of the primary key and must stay '' instead
                "FROM STDIN WITH (FORMAT csv, FORCE_NOT_NULL (id_subclasse))",
                buffer,
            )
            # the current-month file may repeat (cnpj, date) across partial
            # updates; deduplicate inside the stage before merging
            cur.execute(
                "DELETE FROM _cvm_stage a USING _cvm_stage b WHERE "
                "a.ctid < b.ctid AND a.cnpj = b.cnpj AND "
                "a.id_subclasse = b.id_subclasse AND a.dt_comptc = b.dt_comptc"
            )
            cur.execute(MERGE_SQL)
        log.info("month %s: staged %d rows and merged", anomes, count)
        return count

    @task(outlets=[RAW_CVM_FUNDS])
    def publish() -> None:
        """Mark this run's raw CVM fund data ready — data-aware handoff to dbt."""
        log.info("raw CVM funds landed; dbt_transform schedules on it")

    # raw landing only — the fund marts are built and tested by dbt_transform
    tables = create_tables()
    months = months_to_load()
    cadastro = ingest_cadastro()
    ingested = ingest_month.expand(anomes=months)
    ready = publish()
    tables >> months >> ingested >> ready
    tables >> cadastro >> ready


ingest_cvm_funds()
