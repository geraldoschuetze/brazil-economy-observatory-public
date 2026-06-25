"""Run the dbt transformation layer: staging + marts + data-quality tests.

The ingestion DAGs land immutable data in `raw`; this DAG turns it into the
`staging` views and `marts` star schema and *tests* it — `dbt build` runs each
model and its tests in dependency order, so a failing test stops bad data from
propagating downstream. Scheduled after the morning ingestion window.

dbt lives in an isolated venv (see infra/airflow/Dockerfile) and reads its
profile from DBT_PROFILES_DIR; the warehouse password comes from .env.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta

from airflow.decorators import dag, task

from brazil_economy.alerts import notify_failure
from brazil_economy_assets import MARTS, RAW_ALL

log = logging.getLogger(__name__)

DBT_BIN = "/opt/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/dbt"


def _run_dbt(args: list[str], *, check: bool) -> int:
    """Invoke dbt, streaming its output into the task log."""
    cmd = [DBT_BIN, *args, "--project-dir", DBT_DIR, "--no-use-colors"]
    log.info("running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        log.info(proc.stdout)
    if proc.stderr:
        log.warning(proc.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"dbt {args[0]} failed (exit {proc.returncode})")
    return proc.returncode


@dag(
    dag_id="dbt_transform",
    description="dbt build (staging + marts) + data-quality tests + source freshness",
    # data-aware: rebuild once ALL six raw sources have landed for the day,
    # instead of betting on a fixed clock (the ingestion DAGs keep their crons).
    schedule=RAW_ALL,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "on_failure_callback": notify_failure,
    },
    tags=["dbt", "transform", "data-quality"],
)
def dbt_transform():
    @task
    def source_freshness() -> None:
        # report-only: a stale source warns but must not block the rebuild,
        # which still produces the best marts it can from what has landed
        rc = _run_dbt(["source", "freshness"], check=False)
        if rc != 0:
            log.warning(
                "dbt source freshness reported stale/error sources (exit %s)", rc
            )

    @task(outlets=[MARTS])
    def build() -> None:
        # `build` = run models + run their tests, in dependency order, failing
        # (and skipping downstream) the moment a data-quality test breaks. On
        # success it emits the MARTS Asset, which schedules om_ingest.
        _run_dbt(["build"], check=True)

    @task
    def docs_generate() -> None:
        # emits target/manifest.json + catalog.json — the artifacts OpenMetadata
        # ingests for column-level lineage and model descriptions. Best-effort:
        # a hiccup here must not fail the (already-built, already-tested) marts.
        _run_dbt(["docs", "generate"], check=False)

    source_freshness() >> build() >> docs_generate()


dbt_transform()
