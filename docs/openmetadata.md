# Data catalog, lineage & governance — OpenMetadata

OpenMetadata is the **governance layer**: a searchable catalog of every table and
dashboard, with automatic **column-level lineage** from the public APIs all the
way to the Superset charts:

```
BACEN/CVM/IBGE APIs → raw → (dbt) staging → (dbt) marts → Superset dashboard
```

Lineage is reconstructed from the **dbt artifacts** (`manifest.json` +
`catalog.json`) the `dbt_transform` DAG emits, so the `ref()`/`source()` graph
becomes real, navigable lineage. On top of that the project provisions a
**glossary**, **classifications/tags** (source + layer), a **domain with data
products**, and **ownership** — see `scripts/om_governance.py`.

> ⚠️ **Opt-in / resource cost.** OpenMetadata needs its own Postgres + an
> Elasticsearch and adds ~3–5 GB of RAM **per environment** on top of the core
> stack. It is **not** part of the default `make up`. On the Always-Free VM it
> runs on both QA and PROD; keep an eye on `free -h` (the box has no swap).

Version: **1.12.11** (pinned in `infra/openmetadata/openmetadata.env`).

## How it's exposed (HTTPS, read-only)

Unlike a raw OM install, the server port is **never** published, and the public
link is HTTPS on a custom domain via the Cloudflare Tunnel — no inbound port is
open on the VM. Three layers:

- `openmetadata-server` binds **loopback only** (`127.0.0.1:${OM_PORT}`) — admin
  work goes through an SSH tunnel to that port.
- `om-proxy` (nginx, `infra/openmetadata/nginx-readonly.conf`) is the read-only
  gate, bound to **loopback** (`OM_PUBLIC_BIND=127.0.0.1`). It allows `GET`/`HEAD`
  + the viewer login endpoints and denies every mutating method
  (`PUT`/`PATCH`/`DELETE`/other `POST`) and signup with **403** — so even a forged
  or escalated token cannot write through it.
- the **Cloudflare Tunnel** maps `economy-catalog.geraldoschuetze.com` →
  `om-proxy` (TLS at Cloudflare's edge). See
  [cloudflare-tunnel.md](cloudflare-tunnel.md).

| Env  | server (loopback, admin) | proxy (loopback) | public HTTPS link                          |
|------|--------------------------|------------------|--------------------------------------------|
| PROD | `127.0.0.1:8597`         | `127.0.0.1:8585` | `https://economy-catalog.geraldoschuetze.com`    |
| QA   | `127.0.0.1:8595`         | `127.0.0.1:8586` | `https://economy-qa-catalog.geraldoschuetze.com` |

The public catalog is browsed with a **shared, read-only `viewer`** account
(role `DataConsumer`). Its password is provisioned by `scripts/om_harden.py`
from `OM_VIEWER_PASSWORD` in the **gitignored** `openmetadata.env` and shared
out-of-band — no credential is ever committed. Admin
(`admin@open-metadata.org`) is reachable only over the loopback server port.

## 1. Configure

```bash
cp infra/openmetadata/openmetadata.env.example infra/openmetadata/openmetadata.env
# then set, in that gitignored file:
#   OM_PORT=8597            # loopback server port (8595 on QA)
#   OM_PUBLIC_BIND=0.0.0.0  # publish the read-only proxy (firewall must allow it)
#   OM_PUBLIC_PORT=8585     # public proxy port (8586 on QA)
#   OM_READER_PASSWORD=...        # least-privilege warehouse reader (random)
#   OM_VIEWER_PASSWORD=...        # shared read-only UI login
#   OM_ADMIN_NEW_PASSWORD=...     # rotates the default admin/admin
```

The compose file joins the core-stack network so ingestion can resolve the
`postgres` and `superset` hosts, so the core stack must be up first (`make up`).

## 2. Start the stack

```bash
make om-up        # docker compose -f infra/openmetadata/... --env-file ... up -d
```

> 🚫 **Never let the main project's `COMPOSE_PROJECT_NAME` leak into this
> command.** The OM stack must use its *own* project name (from
> `openmetadata.env`). If a parent shell exports the main project's name (e.g.
> after `. ./.env`), docker compose creates a **duplicate** OM stack under the
> main project and doubles the RAM. `make om-up` and the deploy use a clean shell
> / `env -u COMPOSE_PROJECT_NAME` to prevent this.

## 3. Provision: reader, ingestion, governance, hardening

Run once per environment (admin over the loopback port). All scripts are
stdlib-only and idempotent:

```bash
# least-privilege Postgres reader (SELECT only on raw/staging/marts)
OM_READER_PASSWORD=... bash scripts/create_om_reader.sh

# ingest metadata + dbt lineage + Superset (admin/admin on a fresh instance):
#   - postgres-metadata.yaml uses om_reader
#   - dbt-lineage.yaml needs target/manifest.json+catalog.json (dbt docs generate)
#   - superset-dashboards.yaml links charts downstream of the marts
# (see git history / the deploy for the exact `metadata ingest -c` invocations)

# governance: glossary, tags, domain + data products, ownership
OM_URL=http://127.0.0.1:8597 OM_ADMIN_PASSWORD=admin python3 scripts/om_governance.py

# hardening: rotate admin password + (re)create the read-only viewer
OM_URL=http://127.0.0.1:8597 OM_ADMIN_PASSWORD=admin \
  OM_ADMIN_NEW_PASSWORD=... OM_VIEWER_PASSWORD=... python3 scripts/om_harden.py
```

## 4. Keep it fresh — the `om_ingest` DAG

Refreshing the catalog is automated, so it never drifts:

- **Daily (data):** the `om_ingest` Airflow DAG (`dags/om_ingest.py`) is triggered
  **data-aware** — scheduled on the `marts` Asset that `dbt_transform` emits, so it
  runs right after each rebuild (no fixed clock). It triggers OpenMetadata's
  **native** ingestion pipelines
  `warehouse_metadata` (Postgres) and `superset_dashboards`. It is best-effort
  and fully decoupled — if OM is offline or the token is missing it logs a
  warning and succeeds, never blocking the data platform.
- **On deploy (structure/lineage):** `scripts/om_automation_setup.sh` (wired into
  the deploy, also `make om-automate`) creates+deploys those native pipelines and
  (re)creates a least-privilege **`automation-bot`** (role `IngestionBotRole`),
  handing its fresh JWT to Airflow as the `om_automation_token` Variable and
  unpausing the DAG. dbt lineage is refreshed here, where the artifacts are
  freshly built.

The bot JWT lives only in the Airflow Variable (rotated every deploy) — never in
the repo. OM is reached over the internal `openmetadata-server:8585`, not the
public proxy.

## CI/CD (dev → qa → prod)

The deploy workflow brings OM up and runs the automation **only where
`infra/openmetadata/openmetadata.env` exists on the VM** — so OM is opt-in per
environment and the rest of the pipeline is unaffected where it isn't. The whole
step is best-effort and can never fail a deploy.

## Make targets

| target        | what it does                                             |
|---------------|----------------------------------------------------------|
| `om-up`       | start the OpenMetadata stack                              |
| `om-down`     | stop it (volumes kept)                                    |
| `om-logs`     | tail its logs                                             |
| `om-automate` | deploy native pipelines + bot, register the Airflow token |

## Security notes

- **Read-only public surface:** the nginx proxy blocks all writes + signup
  (403); the OM server port is loopback-only (admin via SSH tunnel).
- **Least privilege everywhere:** `om_reader` is `SELECT`-only on
  raw/staging/marts (never the warehouse owner); the `automation-bot` only holds
  `IngestionBotRole`; the public `viewer` only holds `DataConsumer`.
- **No secrets in git:** `openmetadata.env` (passwords), the JWT signing keys
  (`infra/openmetadata/certs/*.der`) and the tunnel credentials are all gitignored
  — only the `.example`/`config.yml` (no secrets) ship; the bot token lives only
  in Airflow.
- **JWT signing keys are generated per-environment on the VM**
  (`scripts/om_gen_jwt_keys.sh` → `infra/openmetadata/certs/`, mounted over the
  image's demo keys) with a fresh per-env `JWT_KEY_ID`. The bundled public demo
  keys are no longer used — so a forged token can't be signed even if the surface
  is reached.
