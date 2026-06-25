#!/usr/bin/env bash
# Create/refresh `om_reader` — the LEAST-PRIVILEGE, read-only Postgres role that
# OpenMetadata uses to ingest warehouse metadata. SELECT only on raw/staging/marts;
# never the warehouse owner. The password comes from $OM_READER_PASSWORD (kept in
# the gitignored infra/openmetadata/openmetadata.env, never committed).
set -euo pipefail
: "${OM_READER_PASSWORD:?set OM_READER_PASSWORD (see infra/openmetadata/openmetadata.env)}"

docker compose exec -T postgres psql -U postgres -d brazil_economy -v ON_ERROR_STOP=1 \
  -v pw="$OM_READER_PASSWORD" <<'SQL'
-- create the role (no password) only if missing, then set the password
SELECT 'CREATE ROLE om_reader LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'om_reader')\gexec
ALTER ROLE om_reader LOGIN PASSWORD :'pw';

-- read-only on the three public-data layers; nothing else
GRANT CONNECT ON DATABASE brazil_economy TO om_reader;
GRANT USAGE ON SCHEMA raw, staging, marts TO om_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA raw, staging, marts TO om_reader;
-- FOR ROLE brazil_economy ensures new tables created by dbt (as that role) are automatically readable
ALTER DEFAULT PRIVILEGES FOR ROLE brazil_economy IN SCHEMA raw, staging, marts GRANT SELECT ON TABLES TO om_reader;
SQL
echo "om_reader ready (read-only on raw/staging/marts)"
