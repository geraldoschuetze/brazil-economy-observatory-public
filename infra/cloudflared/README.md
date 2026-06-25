# Cloudflare Tunnel (cloudflared)

One **locally-managed** tunnel exposes the VM's public surface over HTTPS, with
**no inbound ports open** — `cloudflared` only makes outbound connections to
Cloudflare's edge. It is VM-level infra: a single tunnel serves both PROD and QA.

## What's in here

| File | Secret? | Purpose |
|---|---|---|
| `config.yml` | **No** (committed) | Tunnel id + hostname→loopback routing |
| `docker-compose.cloudflared.yml` | No | Runs the connector host-networked |
| `creds/tunnel.json` | **Yes** (gitignored) | Tunnel credentials — VM only |

`config.yml` carries no secret: the tunnel id is a public identifier and the
routing maps hostnames to `localhost` ports. The only secret is `creds/tunnel.json`.

## Hostnames

| Hostname | → local service |
|---|---|
| `economy.geraldoschuetze.com` | `localhost:8088` — Superset (PROD) |
| `economy-catalog.geraldoschuetze.com` | `localhost:8585` — OpenMetadata proxy (PROD) |
| `economy-qa.geraldoschuetze.com` | `localhost:8089` — Superset (QA) |
| `economy-qa-catalog.geraldoschuetze.com` | `localhost:8586` — OpenMetadata proxy (QA) |

## One-time bootstrap (on the VM)

```bash
# 1. install cloudflared (ARM64)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 \
  -o /tmp/cloudflared && sudo install /tmp/cloudflared /usr/local/bin/cloudflared

# 2. authorize the geraldoschuetze.com zone (opens a browser URL)
cloudflared tunnel login

# 3. create the tunnel — prints a UUID and writes ~/.cloudflared/<UUID>.json
cloudflared tunnel create brazil-economy

# 4. put the UUID into config.yml (replace __TUNNEL_UUID__) and place the creds
mkdir -p infra/cloudflared/creds
cp ~/.cloudflared/<UUID>.json infra/cloudflared/creds/tunnel.json
chmod 600 infra/cloudflared/creds/tunnel.json

# 5. DNS routes (CNAME -> tunnel)
cloudflared tunnel route dns brazil-economy economy.geraldoschuetze.com
cloudflared tunnel route dns brazil-economy economy-catalog.geraldoschuetze.com
cloudflared tunnel route dns brazil-economy economy-qa.geraldoschuetze.com
cloudflared tunnel route dns brazil-economy economy-qa-catalog.geraldoschuetze.com

# 6. start it
make tunnel-up   # or: docker compose -f infra/cloudflared/docker-compose.cloudflared.yml up -d
```

The deploy brings the tunnel up automatically wherever `creds/tunnel.json` exists.

See [../../docs/cloudflare-tunnel.md](../../docs/cloudflare-tunnel.md) for the full runbook.
