"""Ingest BACEN Olinda PIX statistics (transactions per municipality).

Data is monthly. Each run loads every month not yet present in the warehouse
plus the two most recent ones (BACEN revises recent months), upserting by
(month, municipality) — fully idempotent. First run backfills from PIX launch.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook

from brazil_economy import transforms
from brazil_economy.alerts import notify_failure
from brazil_economy_assets import RAW_PIX

log = logging.getLogger(__name__)

CONN_ID = "brazil_economy_warehouse"
FIRST_MONTH = 202011  # PIX launched in November 2020
PAGE_SIZE = 10_000  # Olinda hard-caps responses; paginate defensively
API_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1/"
    "odata/TransacoesPixPorMunicipio(DataBase=@DataBase)"
)
SQL_DIR = "/opt/airflow/include/sql"
IBGE_POP_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-6"
    "/variaveis/9324?localidades=N3[all]"
)

UPSERT_SQL = """
    INSERT INTO raw.pix_transacoes_municipio (
        anomes, municipio_ibge, municipio, estado_ibge, estado,
        sigla_regiao, regiao,
        vl_pagador_pf, qt_pagador_pf, vl_pagador_pj, qt_pagador_pj,
        vl_recebedor_pf, qt_recebedor_pf, vl_recebedor_pj, qt_recebedor_pj,
        qt_pes_pagador_pf, qt_pes_pagador_pj,
        qt_pes_recebedor_pf, qt_pes_recebedor_pj
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (anomes, municipio_ibge) DO UPDATE SET
        vl_pagador_pf = EXCLUDED.vl_pagador_pf,
        qt_pagador_pf = EXCLUDED.qt_pagador_pf,
        vl_pagador_pj = EXCLUDED.vl_pagador_pj,
        qt_pagador_pj = EXCLUDED.qt_pagador_pj,
        vl_recebedor_pf = EXCLUDED.vl_recebedor_pf,
        qt_recebedor_pf = EXCLUDED.qt_recebedor_pf,
        vl_recebedor_pj = EXCLUDED.vl_recebedor_pj,
        qt_recebedor_pj = EXCLUDED.qt_recebedor_pj,
        qt_pes_pagador_pf = EXCLUDED.qt_pes_pagador_pf,
        qt_pes_pagador_pj = EXCLUDED.qt_pes_pagador_pj,
        qt_pes_recebedor_pf = EXCLUDED.qt_pes_recebedor_pf,
        qt_pes_recebedor_pj = EXCLUDED.qt_pes_recebedor_pj,
        loaded_at = now()
"""


def _get_with_backoff(url: str, attempts: int = 5) -> requests.Response:
    """GET with exponential backoff on 5xx/429 — Olinda rate-limits bursts."""
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
    dag_id="ingest_pix",
    description="BACEN Olinda PIX transactions per municipality -> raw (marts by dbt)",
    schedule="30 8 * * 1-5",  # weekdays only (no BCB publish on weekends)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": notify_failure,
    },
    tags=["bacen", "pix", "ingestion"],
)
def ingest_pix():
    @task
    def create_tables() -> None:
        hook = PostgresHook(CONN_ID)
        for ddl in ("002_pix.sql", "005_populacao.sql"):
            with open(f"{SQL_DIR}/ddl/{ddl}") as f:
                hook.run(f.read())

    @task
    def ingest_populacao() -> int:
        """IBGE population estimates per state (agregado 6579, latest year)."""
        resp = requests.get(IBGE_POP_URL, timeout=120)
        resp.raise_for_status()
        rows = []
        for serie in resp.json()[0]["resultados"][0]["series"]:
            ano, valor = sorted(serie["serie"].items())[-1]
            rows.append(
                (
                    int(serie["localidade"]["id"]),
                    serie["localidade"]["nome"],
                    int(valor),
                    int(ano),
                )
            )
        hook = PostgresHook(CONN_ID)
        conn = hook.get_conn()
        with conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw.dim_populacao_uf (uf_ibge, uf, populacao, ano) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (uf_ibge) DO UPDATE SET populacao = EXCLUDED.populacao, "
                "ano = EXCLUDED.ano, loaded_at = now()",
                rows,
            )
        log.info("population refreshed: %d states (year %s)", len(rows), rows[0][3])
        return len(rows)

    @task
    def months_to_load() -> list[int]:
        """Missing months plus the two most recent (subject to revision)."""
        hook = PostgresHook(CONN_ID)
        today = date.today()
        last_month = today.year * 100 + today.month
        loaded = [
            row[0]
            for row in hook.get_records(
                "SELECT DISTINCT anomes FROM raw.pix_transacoes_municipio"
            )
        ]
        result = transforms.months_to_load(FIRST_MONTH, last_month, loaded)
        log.info("loading %d months: %s", len(result), result)
        return result

    # sequential months: parallel calls trip Olinda's rate limiting into 500s
    @task(max_active_tis_per_dag=1)
    def ingest_month(anomes: int) -> int:
        hook = PostgresHook(CONN_ID)
        # Olinda's OData parser rejects percent-encoded '@', '$' and quotes, so
        # keep them literal. It also answers HTTP 500 to ANY request carrying
        # $skip (even $skip=0), so pagination is impossible — the whole month
        # must fit in one page (5,570 municipalities << PAGE_SIZE).
        query = urlencode(
            {
                "@DataBase": f"'{anomes}'",
                "$filter": f"AnoMes eq {anomes}",
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
                f"month {anomes}: response hit the {PAGE_SIZE}-row page limit "
                "and the endpoint does not support $skip — refusing to "
                "silently truncate"
            )
        # BACEN ships one "NAO INFORMADO" bucket row per month with NULL IBGE
        # codes (transactions not attributable to a municipality); keep it
        # under sentinel code -1 so national totals stay correct
        rows = [
            (
                item["AnoMes"],
                item["Municipio_Ibge"] if item["Municipio_Ibge"] is not None else -1,
                item["Municipio"],
                item["Estado_Ibge"] if item["Estado_Ibge"] is not None else -1,
                item["Estado"],
                item["Sigla_Regiao"],
                item["Regiao"],
                item["VL_PagadorPF"],
                item["QT_PagadorPF"],
                item["VL_PagadorPJ"],
                item["QT_PagadorPJ"],
                item["VL_RecebedorPF"],
                item["QT_RecebedorPF"],
                item["VL_RecebedorPJ"],
                item["QT_RecebedorPJ"],
                item["QT_PES_PagadorPF"],
                item["QT_PES_PagadorPJ"],
                item["QT_PES_RecebedorPF"],
                item["QT_PES_RecebedorPJ"],
            )
            for item in batch
        ]
        time.sleep(1)  # politeness between months

        if rows:
            conn = hook.get_conn()
            with conn, conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
        log.info("month %s: upserted %d municipalities", anomes, len(rows))
        return len(rows)

    @task(outlets=[RAW_PIX])
    def publish() -> None:
        """Mark this run's raw PIX data ready — data-aware handoff to dbt."""
        log.info("raw PIX landed; dbt_transform schedules on it")

    # raw landing only — the PIX marts are built and tested by dbt_transform
    tables = create_tables()
    months = months_to_load()
    populacao = ingest_populacao()
    ingested = ingest_month.expand(anomes=months)
    ready = publish()
    tables >> months >> ingested >> ready
    tables >> populacao >> ready


ingest_pix()
