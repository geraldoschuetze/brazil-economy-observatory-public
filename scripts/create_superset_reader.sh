#!/usr/bin/env bash
# Create/refresh `superset_reader` — the LEAST-PRIVILEGE, read-only Postgres role
# that Superset uses to query the warehouse for dashboards. SELECT only on
# raw/staging/marts; never the warehouse owner. This keeps the warehouse
# read-only at the DB layer regardless of Superset's app-level RBAC (defense in
# depth behind the anonymous Public role). Mirrors scripts/create_om_reader.sh.
# Password comes from $SUPERSET_READER_PASSWORD (kept in the gitignored .env).
set -euo pipefail
: "${SUPERSET_READER_PASSWORD:?set SUPERSET_READER_PASSWORD (see .env)}"

docker compose exec -T postgres psql -U postgres -d brazil_economy -v ON_ERROR_STOP=1 \
  -v pw="$SUPERSET_READER_PASSWORD" <<'SQL'
-- create the role (no password) only if missing, then set the password
SELECT 'CREATE ROLE superset_reader LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_reader')\gexec
ALTER ROLE superset_reader LOGIN PASSWORD :'pw';

-- read-only on the three data layers; nothing else
GRANT CONNECT ON DATABASE brazil_economy TO superset_reader;
GRANT USAGE ON SCHEMA raw, staging, marts TO superset_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA raw, staging, marts TO superset_reader;
-- FOR ROLE brazil_economy: new tables dbt creates (as that role) stay readable
ALTER DEFAULT PRIVILEGES FOR ROLE brazil_economy IN SCHEMA raw, staging, marts GRANT SELECT ON TABLES TO superset_reader;
SQL
echo "superset_reader ready (read-only on raw/staging/marts)"
