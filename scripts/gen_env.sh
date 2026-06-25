#!/usr/bin/env bash
# Generates .env from .env.example, replacing placeholders with random secrets.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  echo ".env already exists — nothing to do (delete it manually to regenerate)."
  exit 0
fi

while IFS= read -r line; do
  while [[ "$line" == *"__GENERATE__"* ]]; do
    line="${line/__GENERATE__/$(openssl rand -hex 24)}"
  done
  # Fernet keys must be 32 url-safe base64-encoded bytes
  while [[ "$line" == *"__FERNET__"* ]]; do
    line="${line/__FERNET__/$(openssl rand -base64 32 | tr '+/' '-_')}"
  done
  printf '%s\n' "$line"
done < .env.example > .env

sed -i "s/^AIRFLOW_UID=.*/AIRFLOW_UID=$(id -u)/" .env
chmod 600 .env

echo ".env generated with random secrets (mode 600, gitignored)."
echo "Check credentials with: grep -E 'USERNAME|PASSWORD' .env"
