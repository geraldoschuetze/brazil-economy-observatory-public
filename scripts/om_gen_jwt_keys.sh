#!/usr/bin/env bash
# Generate OpenMetadata JWT signing keys (RSA-2048, DER) into the gitignored
# infra/openmetadata/certs/ dir. Idempotent: does nothing if both keys exist.
# Run ON THE VM (per environment). The private key never leaves the host and is
# never committed. Pairs with a fresh JWT_KEY_ID in openmetadata.env.
set -euo pipefail
CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/openmetadata/certs"
mkdir -p "$CERT_DIR"
PRIV="$CERT_DIR/private_key.der"
PUB="$CERT_DIR/public_key.der"

if [ -s "$PRIV" ] && [ -s "$PUB" ]; then
  echo "JWT keys already present in $CERT_DIR — leaving them in place."
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
openssl genrsa -out "$tmp/private_key.pem" 2048
# OM expects PKCS#8 DER for the private key and X.509 DER for the public key
openssl pkcs8 -topk8 -inform PEM -outform DER -in "$tmp/private_key.pem" -out "$PRIV" -nocrypt
openssl rsa -in "$tmp/private_key.pem" -pubout -outform DER -out "$PUB"
chmod 644 "$PUB"
# The OpenMetadata server container runs as uid 1000 (openmetadata) and mounts
# the private key read-only — it must be readable by that uid, which usually
# differs from the host deploy user. Prefer handing the file to uid 1000 with
# group-only access (640, not world-readable); fall back to world-readable so
# the container can always read it on a single-tenant host.
OM_UID=1000
if sudo -n chown "$OM_UID:$OM_UID" "$PRIV" 2>/dev/null && sudo -n chmod 640 "$PRIV" 2>/dev/null; then
  echo "private key owned by uid $OM_UID, mode 640"
else
  chmod 644 "$PRIV"
  echo "SECURITY WARNING: could not chown the JWT private key to uid $OM_UID (no sudo)."
  echo "  Left world-readable (644) so the container can read it. Any local user who"
  echo "  reads this key can forge OM admin tokens — on a multi-user host, re-run with"
  echo "  sudo so the key becomes 640 owned by uid $OM_UID."
fi
echo "Generated $PRIV and $PUB"
echo "Reminder: set a fresh JWT_KEY_ID (UUID) in infra/openmetadata/openmetadata.env"
