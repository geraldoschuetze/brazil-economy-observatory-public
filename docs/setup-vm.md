# Production VM setup (Oracle Cloud)

How the production environment was provisioned. The whole pipeline runs on a
single Always Free ARM VM — actual cost: **$0**.

## Instance

| Item | Value |
|---|---|
| Shape | VM.Standard.A1.Flex — 4 OCPU / 24 GB (Always Free) |
| Image | Canonical Ubuntu 24.04 (aarch64) |
| Boot volume | 100 GB |
| Region | sa-saopaulo-1 |

Notes from provisioning:

- **Free-tier capacity**: "Out of capacity" errors for A1 shapes are common on
  pure free-tier accounts. Upgrading the account to Pay As You Go solved it —
  the Always Free allowance stays free, and a **budget alert of US$ 0.01**
  (budget `brazil-economy-zero-spend`) guards against any accidental spend.
- **Public IP**: the simplified "Create instance" flow leaves the public-IP
  toggle disabled when creating a new public subnet. Assign an ephemeral
  public IP afterwards: VNIC → IP administration → Edit primary IP →
  *Ephemeral public IP*.
- **Internet access**: use Networking → Quick actions → *Connect public
  subnet to internet* (creates/wires internet gateway, NSG and route table).

## Bootstrap (run once, as ubuntu@vm)

```bash
# Docker Engine + compose plugin
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu noble stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli \
  containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu && newgrp docker

# survive reboots
sudo systemctl enable docker

# clone (read-only deploy key) and start
git clone https://github.com/geraldoschuetze/brazil-economy-observatory.git
cd brazil-economy-observatory
make env   # generates production secrets — never leave the VM
make up
```

`restart: always` on every service + Docker enabled on boot means the stack
self-heals after crashes and VM restarts — no operator needed.

## Exposing Superset

Ubuntu's iptables on Oracle images blocks extra ports by default. To expose
Superset (8088) both layers must allow it:

1. OCI: add an ingress rule (TCP 8088) on the subnet security list or NSG.
2. VM: `sudo iptables -I INPUT -p tcp --dport 8088 -j ACCEPT` (persist with
   `iptables-persistent`).

Planned evolution: Cloudflare Tunnel (no inbound ports at all) once a custom
domain is set up.
