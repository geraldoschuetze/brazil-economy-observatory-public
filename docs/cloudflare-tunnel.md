# Public HTTPS via Cloudflare Tunnel

The public dashboard and catalog are served over HTTPS on a custom domain through
a single **Cloudflare Tunnel** — the VM exposes **no inbound web ports**.

```
visitor ──HTTPS──> Cloudflare edge ──tunnel(outbound)──> cloudflared (VM) ──> localhost:<port>
```

`cloudflared` only dials **out** to Cloudflare (443/7844), so the warehouse VM can
keep every inbound port closed except SSH. TLS is terminated at Cloudflare's edge;
inside the VM traffic is plain HTTP over loopback.

## Topology

- **One tunnel, one connector** for the whole VM — it serves both PROD and QA via
  distinct loopback ports. It runs as its **own compose project**
  (`infra/cloudflared/docker-compose.cloudflared.yml`) with `network_mode: host`,
  so `localhost:<port>` reaches each service's loopback-published host port.
- The connector is brought up by `make tunnel-up` and by the deploy (gated on the
  presence of the gitignored credentials file).

| Hostname | → local service |
|---|---|
| `economy.geraldoschuetze.com` | `localhost:8088` — Superset (PROD, public dashboard) |
| `economy-catalog.geraldoschuetze.com` | `localhost:8585` — OpenMetadata read-only proxy (PROD) |
| `economy-qa.geraldoschuetze.com` | `localhost:8089` — Superset (QA) |
| `economy-qa-catalog.geraldoschuetze.com` | `localhost:8586` — OpenMetadata read-only proxy (QA) |

> Single-level subdomains on purpose: Cloudflare's free Universal SSL covers the
> apex and `*.geraldoschuetze.com` (one level). Deeper names like
> `app.economy.geraldoschuetze.com` would need a paid certificate.

## Defense in depth (OpenMetadata)

The tunnel points OM traffic at the **existing read-only nginx proxy** (`om-proxy`),
not the OM server directly. So two independent layers protect it: Cloudflare (TLS +
edge) and nginx (GET/HEAD + viewer login only; every write/signup → 403). The OM
server port stays loopback-only — admin work is still done over an SSH tunnel.

## Bootstrap

See [../infra/cloudflared/README.md](../infra/cloudflared/README.md) for the
one-time `cloudflared login` / `create` / `route dns` steps and the credentials path.

`config.yml` is committed and contains **no secret** (tunnel id + routing only). The
only secret is `infra/cloudflared/creds/tunnel.json` (gitignored, VM-only).

## Loopback bindings

For the tunnel to be the *only* public path, the backends bind loopback on the VM:

- Superset: `127.0.0.1:8088:8088` (`docker-compose.yml`).
- `om-proxy`: `OM_PUBLIC_BIND=127.0.0.1` in `openmetadata.env`.

Local dev is unaffected — both stay reachable at `http://localhost:<port>`.

## Close the old inbound ports

Once the tunnel is verified, retire the raw-IP/HTTP entry points:

1. Remove the **Oracle Cloud Security List** ingress rules for `8088`, `8089`,
   `8585`, `8586` (Oracle console / OCI CLI). Keep SSH (22).
2. Drop any matching `iptables`/`ufw` allow rules on the VM.
3. Verify from **outside** the VM: `http://your.vm.host:8088` must now refuse /
   time out, while `https://economy.geraldoschuetze.com` still works — proving
   traffic flows only through the tunnel.

`cloudflared` needs no inbound rule.

## Rotate / recreate the tunnel

```bash
make tunnel-down
cloudflared tunnel delete brazil-economy        # then re-create (bootstrap steps)
```

DNS routes follow the tunnel id; re-run `cloudflared tunnel route dns ...` after a
recreate.
