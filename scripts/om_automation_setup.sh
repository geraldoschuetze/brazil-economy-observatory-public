#!/usr/bin/env bash
# Wire the `om_ingest` automation: (re)create + deploy the native OpenMetadata
# ingestion pipelines and the least-privilege automation bot, then hand the bot's
# fresh JWT to Airflow as the `om_automation_token` Variable so the DAG can trigger
# refreshes. OpenMetadata is opt-in, so every failure here is swallowed — this can
# never break a deploy. Run from the project root (same dir as `docker compose`).
set -uo pipefail

ENVF=infra/openmetadata/openmetadata.env
[ -f "$ENVF" ] || { echo "om: no $ENVF — skipping automation setup"; exit 0; }
# read only the keys we need — do NOT source the file: it exports
# COMPOSE_PROJECT_NAME (the OM stack) and has space-bearing JVM opts, either of
# which would derail the `docker compose` calls below.
read_env() { grep -E "^$1=" "$ENVF" | tail -n1 | cut -d= -f2-; }
OM_PORT=$(read_env OM_PORT)
OM_ADMIN_NEW_PASSWORD=$(read_env OM_ADMIN_NEW_PASSWORD)
OM_URL="http://127.0.0.1:${OM_PORT:-8585}"

# wait (briefly, best-effort) for the OM server to answer
for _ in $(seq 1 20); do
  curl -sf "$OM_URL/api/v1/system/version" >/dev/null 2>&1 && break
  sleep 6
done

# admin password is the hardened one once om_harden has run; fall back to default
TOKEN=""
for pw in "${OM_ADMIN_NEW_PASSWORD:-}" admin; do
  [ -z "$pw" ] && continue
  if OM_URL="$OM_URL" OM_ADMIN_PASSWORD="$pw" \
       python3 scripts/om_automation_setup.py >/tmp/om_tok 2>/tmp/om_setup_err; then
    TOKEN=$(tail -n1 /tmp/om_tok)
    [ "$pw" = "admin" ] && echo "om: WARNING automation authenticated with the FACTORY admin password — set OM_ADMIN_NEW_PASSWORD and run hardening (scripts/om_harden.py)" >&2
    break
  fi
done
[ -s /tmp/om_setup_err ] && cat /tmp/om_setup_err >&2

if [ -z "$TOKEN" ]; then
  echo "om: automation setup produced no token (OM down or not yet ingested) — skipping" >&2
  rm -f /tmp/om_tok /tmp/om_setup_err
  exit 0
fi

if docker compose exec -T airflow-scheduler airflow variables set \
     om_automation_token "$TOKEN" >/dev/null 2>&1; then
  echo "om: om_automation_token registered in Airflow"
else
  echo "om: could not set the Airflow Variable (scheduler down?)" >&2
fi

# DAGs are created paused (AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION); activate
# om_ingest so the daily refresh actually runs. Idempotent.
docker compose exec -T airflow-scheduler airflow dags unpause om_ingest >/dev/null 2>&1 \
  && echo "om: om_ingest DAG unpaused" \
  || echo "om: could not unpause om_ingest (not parsed yet?)" >&2

rm -f /tmp/om_tok /tmp/om_setup_err
