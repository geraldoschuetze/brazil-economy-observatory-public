#!/usr/bin/env bash
# Dump or restore the Superset metadata DB — the safety net for a version upgrade
# (Superset migrations are one-way; the dump makes rollback instant). The
# dashboard itself is regenerable from bootstrap, but the dump preserves users,
# roles and any UI-side state.
#
#   bash scripts/superset_metadata_backup.sh dump    > superset_meta.dump
#   bash scripts/superset_metadata_backup.sh restore < superset_meta.dump
set -euo pipefail
ACTION="${1:?usage: dump|restore}"
case "$ACTION" in
  dump)
    docker compose exec -T postgres pg_dump -U postgres -Fc superset
    ;;
  restore)
    docker compose stop superset superset-init >/dev/null 2>&1 || true
    docker compose exec -T postgres psql -U postgres -c \
      "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='superset' AND pid<>pg_backend_pid();" >/dev/null 2>&1 || true
    docker compose exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS superset;"
    docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE superset OWNER superset;"
    docker compose exec -T postgres pg_restore -U postgres -d superset
    docker compose up -d superset-init superset >/dev/null 2>&1
    echo "restored superset metadata; superset coming back up"
    ;;
  *)
    echo "unknown action: $ACTION (use dump|restore)" >&2; exit 1 ;;
esac
