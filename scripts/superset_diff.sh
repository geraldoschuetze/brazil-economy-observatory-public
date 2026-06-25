#!/usr/bin/env bash
# Thin wrapper around the comprehensive Python diff engine (superset_diff.py), which
# compares DEV vs a pristine env (qa|prod) across every dimension the bootstrap owns:
# title, chart set, per-chart viz/params/dataset, layout and metadata.
#
#   bash scripts/superset_diff.sh          # vs QA (default)
#   bash scripts/superset_diff.sh prod
exec python3 "$(dirname "$0")/superset_diff.py" "${1:-qa}"
