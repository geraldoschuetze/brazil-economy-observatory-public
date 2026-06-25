#!/usr/bin/env python3
"""Provision OpenMetadata automation: native ingestion pipelines + a bot token.

Run on the VM host against the loopback OM API (admin). Idempotent. It:

  1. creates/updates and *deploys* the native ingestion pipelines that OM's own
     runner executes — `warehouse_metadata` (Postgres) and `superset_dashboards`
     (dashboards). They reuse the connection already stored on each service, so
     no warehouse/Superset secret is handled here.
  2. (re)creates the least-privilege `automation-bot` (IngestionBotRole) with a
     fresh JWT and prints ONLY that token on stdout — the caller hands it to
     Airflow (`airflow variables set om_automation_token`). The bot is recreated
     each run because OM masks the JWT on read, so rotating is the only way to
     obtain a usable token deterministically. Everything else goes to stderr.

The `om_ingest` DAG then uses that token to trigger the pipelines daily.

Usage:
    OM_URL=http://127.0.0.1:8595 OM_ADMIN_PASSWORD=... python3 scripts/om_automation_setup.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8595").rstrip("/")
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")
ADMIN_PW = os.environ.get("OM_ADMIN_PASSWORD", "admin")

DB_SERVICE = "brazil-economy-warehouse"
DASH_SERVICE = "brazil-economy-superset"
BOT_NAME = "automation-bot"
BOT_EMAIL = "automation-bot@brazil-economy.observatory"
INGESTION_BOT_ROLE = "IngestionBotRole"

# the two native pipelines this project refreshes from the daily DAG
PIPELINES = [
    {
        "name": "warehouse_metadata",
        "type": "metadata",
        "service": DB_SERVICE,
        "service_kind": "databaseServices",
        "service_ref": "databaseService",
        "source_config": {
            "type": "DatabaseMetadata",
            "schemaFilterPattern": {"includes": ["^raw$", "^staging$", "^marts$"]},
            "includeViews": True,
            "includeTags": False,
        },
    },
    {
        "name": "superset_dashboards",
        "type": "metadata",
        "service": DASH_SERVICE,
        "service_kind": "dashboardServices",
        "service_ref": "dashboardService",
        "source_config": {"type": "DashboardMetadata"},
    },
    {
        "name": "warehouse_dbt",
        "type": "dbt",
        "service": DB_SERVICE,
        "service_kind": "databaseServices",
        "service_ref": "databaseService",
        "source_config": {
            "type": "DBT",
            # sem isto o conector cria o nó dbt mas NÃO grava as descrições de
            # coluna no OM (default false). Com true, sincroniza tabela + colunas.
            "dbtUpdateDescriptions": True,
            "includeTags": True,
            "dbtConfigSource": {
                "dbtConfigType": "local",
                "dbtManifestFilePath": "/opt/dbt/target/manifest.json",
                "dbtCatalogFilePath": "/opt/dbt/target/catalog.json",
                "dbtRunResultsFilePath": "/opt/dbt/target/run_results.json",
            },
        },
    },
]


def log(*a: object) -> None:
    print(*a, file=sys.stderr)


def login() -> str:
    pw = base64.b64encode(ADMIN_PW.encode()).decode()
    body = json.dumps({"email": ADMIN_EMAIL, "password": pw}).encode()
    req = urllib.request.Request(
        f"{OM_URL}/api/v1/users/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["accessToken"]


def api(tok: str, method: str, path: str, payload=None, patch=False):
    data = json.dumps(payload).encode() if payload is not None else None
    ct = "application/json-patch+json" if patch else "application/json"
    req = urllib.request.Request(
        f"{OM_URL}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": ct},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def ensure_pipelines(tok: str) -> None:
    log("== ingestion pipelines ==")
    for p in PIPELINES:
        code, svc = api(
            tok, "GET", f"/api/v1/services/{p['service_kind']}/name/{p['service']}"
        )
        if code >= 300 or not isinstance(svc, dict):
            log(
                f"  ! service {p['service']} not found ({code}) — run a full ingestion first; skipping {p['name']}"
            )
            continue
        body = {
            "name": p["name"],
            "displayName": p["name"].replace("_", " ").title(),
            "pipelineType": p["type"],
            "service": {"id": svc["id"], "type": p["service_ref"]},
            "sourceConfig": {"config": p["source_config"]},
            "airflowConfig": {"scheduleInterval": None},
        }
        fqn = f"{p['service']}.{p['name']}"
        code, existing = api(
            tok, "GET", f"/api/v1/services/ingestionPipelines/name/{fqn}"
        )
        if code < 300 and isinstance(existing, dict) and existing.get("id"):
            # already exists — leave config in place, just (re)deploy below
            pid = existing["id"]
            log(f"  = {p['name']} exists")
        else:
            code, created = api(
                tok, "POST", "/api/v1/services/ingestionPipelines", body
            )
            if code >= 300:
                log(f"  ! create {p['name']} -> {code} {created}")
                continue
            pid = created["id"]
            log(f"  + {p['name']} created")
        code, _ = api(tok, "POST", f"/api/v1/services/ingestionPipelines/deploy/{pid}")
        log(f"    deploy {p['name']} -> {code}")


def ensure_ingestion_bot_token(tok: str) -> None:
    # Every ingestion-pipeline DEPLOY embeds the built-in `ingestion-bot` JWT in
    # the workflow config. If JWT_KEY_ID was rotated after that token was minted,
    # its keyID no longer matches the server's signing key and *all* deploys fail
    # with `SigningKeyNotFoundException`. Reconcile: re-mint the bot token when its
    # keyID differs from the server's current JWKS key.
    log("== ingestion-bot token ==")

    def kid(jwt: str):
        try:
            head = base64.urlsafe_b64decode(jwt.split(".")[0] + "==")
            return json.loads(head).get("kid")
        except Exception:
            return None

    _, jwks = api(tok, "GET", "/api/v1/system/config/jwks")
    server_kid = None
    if isinstance(jwks, dict) and jwks.get("keys"):
        server_kid = jwks["keys"][0].get("kid")
    code, bot = api(tok, "GET", "/api/v1/users/name/ingestion-bot")
    if code >= 300 or not isinstance(bot, dict) or not bot.get("id"):
        log("  ! ingestion-bot not found — skipping token reconcile")
        return
    _, tdata = api(tok, "GET", f"/api/v1/users/token/{bot['id']}")
    cur_kid = kid(tdata.get("JWTToken", "")) if isinstance(tdata, dict) else None
    if server_kid and cur_kid != server_kid:
        code, _ = api(
            tok,
            "PUT",
            f"/api/v1/users/generateToken/{bot['id']}",
            {"JWTTokenExpiry": "Unlimited"},
        )
        log(
            f"  re-minted ingestion-bot token (kid {cur_kid} -> {server_kid}) -> {code}"
        )
    else:
        log(f"  ingestion-bot token keyID OK ({cur_kid})")


def rotate_bot(tok: str) -> str:
    log("== automation bot ==")
    # delete any prior bot user so the new JWT is the only valid one
    code, existing = api(tok, "GET", f"/api/v1/users/name/{BOT_NAME}")
    if code < 300 and isinstance(existing, dict) and existing.get("id"):
        api(tok, "DELETE", f"/api/v1/users/{existing['id']}?hardDelete=true")
        log("  old bot user removed")
    code, created = api(
        tok,
        "POST",
        "/api/v1/users",
        {
            "name": BOT_NAME,
            "email": BOT_EMAIL,
            "displayName": "Automation Bot (om_ingest)",
            "isBot": True,
            "authenticationMechanism": {
                "authType": "JWT",
                # Bounded expiry (security finding M2): this token leaves OM and is
                # stored as an Airflow Variable, so it must not live forever. Every
                # deploy re-runs this setup and re-mints + re-registers it, so 90d
                # is always refreshed well before it lapses.
                "config": {"JWTTokenExpiry": "90"},
            },
        },
    )
    if code >= 300:
        log(f"  ! create bot user -> {code} {created}")
        sys.exit(1)
    bot_uid = created["id"]
    token = (
        created.get("authenticationMechanism", {}).get("config", {}).get("JWTToken", "")
    )
    # least-privilege: same role the built-in ingestion-bot uses
    code, role = api(tok, "GET", f"/api/v1/roles/name/{INGESTION_BOT_ROLE}")
    if code < 300:
        api(
            tok,
            "PATCH",
            f"/api/v1/users/{bot_uid}",
            [
                {
                    "op": "add",
                    "path": "/roles/0",
                    "value": {"id": role["id"], "type": "role"},
                }
            ],
            patch=True,
        )
        log(f"  role {INGESTION_BOT_ROLE} granted")
    # bind the Bot entity (idempotent PUT)
    api(
        tok,
        "PUT",
        "/api/v1/bots",
        {
            "name": BOT_NAME,
            "botUser": BOT_NAME,
            "description": "Triggers OM ingestion from the project Airflow (om_ingest DAG).",
        },
    )
    if not token:
        log("  ! no JWT returned for the bot")
        sys.exit(1)
    log("  bot ready")
    return token


def main() -> None:
    tok = login()
    ensure_ingestion_bot_token(tok)
    ensure_pipelines(tok)
    # give a freshly-deployed pipeline a moment to register in OM's runner
    time.sleep(3)
    token = rotate_bot(tok)
    # stdout = the token only, for: airflow variables set om_automation_token "$(...)"
    print(token)


if __name__ == "__main__":
    main()
