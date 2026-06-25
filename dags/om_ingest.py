"""Refresh OpenMetadata after the daily transform.

Once the warehouse has been rebuilt (``dbt_transform``), this DAG nudges
OpenMetadata to re-read it so the public catalog stays current: it triggers the
*native* OM ingestion pipelines — `warehouse_metadata` (Postgres schemas, row
counts) and `superset_dashboards` (new/changed charts) — which OM's own runner
executes. Structural/lineage changes (dbt models) are refreshed on deploy by
``scripts/om_automation_setup.py``; this DAG keeps the *data* view fresh daily.

It is deliberately best-effort and fully decoupled: OpenMetadata is an
observability layer, never on the critical path. If OM is offline, the
automation token is missing, or a pipeline hiccups, the task logs a warning and
succeeds — a metadata refresh must never page anyone or block the data platform.

Auth uses the short-lived `automation-bot` JWT (least-privilege IngestionBotRole)
that the setup script stores in the `om_automation_token` Airflow Variable; the
token never touches the repo. OM is reached over the shared warehouse network at
`openmetadata-server:8585`, so nothing is exposed publicly.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime

from airflow.decorators import dag, task
from airflow.models import Variable

from brazil_economy.alerts import notify_failure
from brazil_economy_assets import MARTS

log = logging.getLogger(__name__)

# OM server on the shared warehouse docker network (internal; never the proxy).
OM_API = "http://openmetadata-server:8585/api"
# Native ingestion pipelines to refresh, by fullyQualifiedName (service.pipeline).
# Overridable via the `om_ingest_pipelines` Airflow Variable (JSON list).
DEFAULT_PIPELINES = [
    "brazil-economy-warehouse.warehouse_metadata",
    "brazil-economy-superset.superset_dashboards",
    "brazil-economy-warehouse.warehouse_dbt",
    "Qualidade_Observatorio.om_dq_observatorio",
]


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{OM_API}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _post(path: str, token: str) -> int:
    req = urllib.request.Request(
        f"{OM_API}{path}",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


@dag(
    dag_id="om_ingest",
    description="Trigger OpenMetadata native ingestion pipelines to refresh the catalog",
    # data-aware: refresh the catalog as soon as dbt_transform emits the marts.
    schedule=[MARTS],
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 0,  # best-effort; retries add no value for a metadata nudge
        "on_failure_callback": notify_failure,
    },
    tags=["openmetadata", "catalog", "observability"],
)
def om_ingest():
    @task
    def refresh_openmetadata() -> None:
        token = Variable.get("om_automation_token", default_var=None)
        if not token:
            log.warning(
                "om_automation_token not set — run scripts/om_automation_setup.py; "
                "skipping OpenMetadata refresh (non-fatal)"
            )
            return

        try:
            pipelines = (
                json.loads(Variable.get("om_ingest_pipelines", default_var="null"))
                or DEFAULT_PIPELINES
            )
        except (ValueError, TypeError):
            pipelines = DEFAULT_PIPELINES

        triggered = 0
        for fqn in pipelines:
            # L2: the pipeline list comes from an Airflow Variable; validate each
            # FQN before interpolating it into the OM API path (defense against a
            # path-altering/SSRF-ish value if the Variable is ever tampered with).
            if not re.fullmatch(r"[A-Za-z0-9._-]+", str(fqn)):
                log.warning("skipping pipeline with unexpected FQN %r (non-fatal)", fqn)
                continue
            try:
                pid = _get(f"/v1/services/ingestionPipelines/name/{fqn}", token)["id"]
                _post(f"/v1/services/ingestionPipelines/trigger/{pid}", token)
                log.info("triggered OpenMetadata pipeline %s", fqn)
                triggered += 1
            except urllib.error.URLError as exc:
                # connection refused / DNS / timeout => OM is offline. Degrade
                # gracefully: stop here, the next run will catch up.
                log.warning(
                    "OpenMetadata unreachable (%s) — skipping refresh of %s "
                    "and remaining pipelines (non-fatal)",
                    getattr(exc, "reason", exc),
                    fqn,
                )
                return
            except Exception:  # noqa: BLE001 — never fail the data platform
                log.warning("could not trigger %s (non-fatal)", fqn, exc_info=True)

        log.info(
            "OpenMetadata refresh requested for %d/%d pipelines",
            triggered,
            len(pipelines),
        )

    refresh_openmetadata()


om_ingest()
