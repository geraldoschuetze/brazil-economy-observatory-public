#!/usr/bin/env bash
# Capture manual edits done in the DEV UI straight into code, so you can promote
# them without hand-editing Python. Diffs DEV vs a pristine env (qa|prod) and patches
# superset/bootstrap_dashboard.py for what it can resolve automatically:
#   - the dashboard TITLE (DASH_TITLE)
#   - a single chart RENAME (one quoted name -> another)
# Anything more complex (new/removed chart, metric/SQL/layout change) it leaves for a
# manual edit and tells you where to look.
#
#   bash scripts/superset_apply.sh          # vs QA (default)
#   bash scripts/superset_apply.sh prod
set -euo pipefail
ENV="${1:-qa}"
VM_HOST="${VM_HOST:-your.vm.host}"
VM_USER="${VM_USER:-ubuntu}"
FILE="superset/bootstrap_dashboard.py"
case "$ENV" in
  qa)   REMOTE_DIR='~/brazil-economy-observatory-qa' ;;
  prod) REMOTE_DIR='~/brazil-economy-observatory' ;;
  *) echo "usage: $0 [qa|prod]" >&2; exit 1 ;;
esac

SLUG="visao-geral"
NAMES_SQL="SELECT slice_name FROM slices ORDER BY slice_name;"
TITLE_SQL="SELECT dashboard_title FROM dashboards WHERE slug='$SLUG';"
loc() { docker compose exec -T postgres psql -U postgres -d superset -t -A -c "$1"; }
rem() { ssh -o ConnectTimeout=15 "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && docker compose exec -T postgres psql -U postgres -d superset -t -A -c \"$1\""; }

DEV_NAMES=$(loc "$NAMES_SQL" | sed '/^$/d')
REM_NAMES=$(rem "$NAMES_SQL" | sed '/^$/d')
DEV_TITLE=$(loc "$TITLE_SQL" | sed '/^$/d')
REM_TITLE=$(rem "$TITLE_SQL" | sed '/^$/d')

set +e
DEV_NAMES="$DEV_NAMES" REM_NAMES="$REM_NAMES" DEV_TITLE="$DEV_TITLE" REM_TITLE="$REM_TITLE" ENVLBL="$ENV" \
python3 - "$FILE" <<'PY'
import os, re, sys, json, pathlib
f = pathlib.Path(sys.argv[1])
src = f.read_text()
dev_title, rem_title = os.environ["DEV_TITLE"], os.environ["REM_TITLE"]
dev_names = set(filter(None, os.environ["DEV_NAMES"].splitlines()))
rem_names = set(filter(None, os.environ["REM_NAMES"].splitlines()))

changes, problems = [], []

# 1) dashboard title
if dev_title != rem_title:
    lit = json.dumps(dev_title, ensure_ascii=False)
    src, n = re.subn(r'(?m)^DASH_TITLE\s*=.*$', f'DASH_TITLE = {lit}', src)
    if n != 1:
        problems.append(f"DASH_TITLE: {n} ocorrências (esperado 1) — edite à mão")
    else:
        changes.append(f'título: "{rem_title}" -> "{dev_title}"')

# 2) single chart rename
old = sorted(rem_names - dev_names)
new = sorted(dev_names - rem_names)
if len(old) == 1 and len(new) == 1:
    needle = f'"{old[0]}"'
    if src.count(needle) != 1:
        problems.append(f'chart {needle}: {src.count(needle)} ocorrências (esperado 1) — edite à mão')
    else:
        src = src.replace(needle, f'"{new[0]}"')
        changes.append(f'chart: "{old[0]}" -> "{new[0]}"')
elif old or new:
    problems.append(f"charts não é rename simples — só no {os.environ.get('ENVLBL','remoto')}: {old} | só no DEV: {new}")

if not changes and not problems:
    print("Nada a aplicar — DEV idêntico ao ambiente comparado.")
    sys.exit(0)
if changes:
    f.write_text(src)
    for c in changes:
        print(f"OK: {c}")
for p in problems:
    print(f"AVISO: {p}")
sys.exit(2 if problems else 0)
PY
rc=$?
set -e
exit $rc
