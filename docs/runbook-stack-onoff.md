# Runbook — Desligar / Reativar a stack local

Para liberar memória quando o projeto está pausado, e religar tudo depois sem perda de dados.
Todos os passos preservam volumes (Postgres/warehouse, metadados do Airflow e do Superset).

> **Airbyte:** removido em 2026-06-23 (`abctl local uninstall`). O projeto **não usa Airbyte** — a
> ingestão é feita por DAGs Python no Airflow batendo direto nas APIs (BACEN/SGS, Focus, Pix, CVM,
> IPCA/IBGE). Não é necessário religá-lo.

## Componentes e como são gerenciados

| Componente | Containers | Como sobe | Memória aprox. |
|---|---|---|---|
| **Stack principal** (warehouse + orquestração + BI) | `postgres`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`, `airflow-triggerer`, `superset` | `docker compose` (raiz do repo) | ~2,1 GiB |
| OpenMetadata *(opcional)* | `openmetadata_*` | `make om-up` | — (não estava ativo) |
| Cloudflare Tunnel *(opcional)* | `cloudflared` | `make tunnel-up` | — (não estava ativo) |

## Desligar (liberar memória)

```bash
cd /home/geraldo-junior/geraldo/brazil-economy-observatory

# 1) Stack principal — para e remove os containers (volumes preservados)
make down                # = docker compose down

# 2) (Se estiverem ativos) extras opcionais
make om-down             # OpenMetadata
make tunnel-down         # Cloudflare Tunnel

# Conferir que nada do projeto ficou de pé
docker ps
```

## Reativar (uso futuro)

```bash
cd /home/geraldo-junior/geraldo/brazil-economy-observatory

# 1) Stack principal (Postgres + Airflow + Superset)
make up                                   # = docker compose up -d
docker compose ps                         # aguarde todos 'healthy'

# 2) (Opcional) extras
make om-up                                # OpenMetadata
make tunnel-up                            # Cloudflare Tunnel (precisa de creds/tunnel.json)
```

### Endpoints locais após reativar
- Airflow:  http://localhost:8080
- Superset: http://localhost:8088
- Postgres (warehouse): `localhost:5440` (db/user `brazil_economy`)

### Verificação rápida
```bash
docker compose ps                                  # 6 serviços healthy
curl -so /dev/null -w '%{http_code}\n' localhost:8080  # 200/302 = Airflow no ar
curl -so /dev/null -w '%{http_code}\n' localhost:8088  # 200/302 = Superset no ar
```
