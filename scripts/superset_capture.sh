#!/usr/bin/env bash
# One-shot: capture DEV UI edits into code, rebuild DEV, show the diff to commit.
# SAFETY: it first runs the comprehensive diff. If there is any change it CANNOT
# auto-capture (params/viz/dataset/layout/metadata/new/removed chart), it STOPS
# before rebuilding — otherwise the rebuild from code would wipe that UI edit.
#
#   bash scripts/superset_capture.sh [qa|prod]
set -euo pipefail
ENV="${1:-qa}"
HERE="$(dirname "$0")"

echo "── 1/4 verificando TODAS as mudanças (DEV vs $ENV) ──"
set +e
python3 "$HERE/superset_diff.py" "$ENV"
rc=$?
set -e

if [ "$rc" = "1" ]; then
  echo "  (falha ao consultar — abortando)"; exit 1
fi
if [ "$rc" = "20" ]; then
  echo
  echo "⚠  Há mudança(s) [manual] acima que NÃO dá pra capturar automaticamente."
  echo "   NÃO vou reconstruir o DEV — isso apagaria sua edição feita no UI."
  echo "   Edite superset/bootstrap_dashboard.py conforme indicado e rode 'make superset-bootstrap'."
  exit 20
fi
if [ "$rc" = "0" ]; then
  echo "  nada a capturar — DEV já bate com o $ENV."
  exit 0
fi

echo "── 2/4 capturando (título/rename) no código ──"
bash "$HERE/superset_apply.sh" "$ENV" || true

echo "── 3/4 reconstruindo o DEV a partir do código ──"
make --no-print-directory superset-bootstrap >/tmp/sup_capture.log 2>&1 \
  && echo "  ✓ DEV reconstruído (confira em localhost:8088)" \
  || { echo "  ✗ bootstrap falhou:"; tail -5 /tmp/sup_capture.log; exit 1; }

echo "── 4/4 mudança pronta pra commit ──"
git --no-pager diff --stat superset/bootstrap_dashboard.py
if git diff --quiet superset/bootstrap_dashboard.py; then
  echo "  (nenhuma mudança no código — nada a commitar)"
else
  echo
  echo "  Próximo passo:"
  echo "    git add -A && git commit -m \"feat: ...\""
  echo "    git push origin develop:develop   # QA"
  echo "    git push origin develop:main      # PROD"
fi
