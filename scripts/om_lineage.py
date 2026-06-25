#!/usr/bin/env python3
"""Build the end-to-end data lineage in OpenMetadata.

The automated connectors cover only part of the chain (Postgres metadata, dbt
model lineage, Superset dashboards). This script fills the rest over the OM REST
API — idempotent, so it can run against QA then PROD:

  Phase 1 (this file): Airflow as a Pipeline Service, one pipeline per ingestion
  DAG, and lineage  DAG -> raw table  (the DAG fetches an external source and
  lands it in `raw`). Later phases add the external API sources (BACEN/CVM/IBGE)
  and stitch the full source -> raw -> staging -> mart -> chart -> dashboard path.

Auth: admin login. OM_ADMIN_NEW_PASSWORD from the env (or parsed from ./.env);
OM_URL defaults to the VM loopback (run on the VM) — override for a tunnel.

  OM_URL=http://localhost:28595 python3 scripts/om_lineage.py   # QA via tunnel
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8595").rstrip("/")
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")
DB_SERVICE = os.environ.get("OM_DB_SERVICE", "brazil-economy-warehouse")
DB_NAME = os.environ.get("OM_DB_NAME", "brazil_economy")
AIRFLOW_SERVICE = "brazil-economy-airflow"

# each ingestion DAG and the raw table(s) it lands (the external source it pulls
# from is added as an API service in a later phase and linked upstream of these)
DAGS: dict[str, dict] = {
    "ingest_sgs": {
        "raw": ["sgs_observations"],
        "desc": "BACEN SGS (séries macro) → raw.sgs_observations",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "ingest_series",
                "description": (
                    "Busca observações incrementais da API BACEN SGS para cada série macro"
                    " (Selic, IPCA, câmbio, dívida etc.) e faz upsert em raw.sgs_observations."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_SGS sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
    "ingest_pix": {
        "raw": ["pix_transacoes_municipio", "dim_populacao_uf"],
        "desc": "BACEN PIX por município + população IBGE → raw",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "months_to_load",
                "description": (
                    "Calcula a lista de meses faltantes mais os dois mais recentes"
                    " (sujeitos a revisão pelo BACEN) que precisam ser (re)carregados."
                ),
            },
            {
                "name": "ingest_populacao",
                "description": (
                    "Carrega a estimativa populacional mais recente por UF"
                    " (IBGE agregado 6579) em raw.dim_populacao_uf."
                ),
            },
            {
                "name": "ingest_month",
                "description": (
                    "Baixa e carrega as transações PIX por município/PF/PJ de um mês específico"
                    " (Olinda OData) em raw.pix_transacoes_municipio. Executada em paralelo por mês."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_PIX sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
    "ingest_cvm_funds": {
        "raw": ["cvm_cad_fi", "cvm_inf_diario"],
        "desc": "CVM cadastro + informe diário de fundos → raw",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "months_to_load",
                "description": (
                    "Calcula a lista de meses faltantes mais os mais recentes"
                    " que precisam ser (re)carregados do portal CVM."
                ),
            },
            {
                "name": "ingest_cadastro",
                "description": (
                    "Carrega o cadastro completo de fundos de investimento (cad_fi.csv)"
                    " em raw.cvm_cad_fi — carga full refresh da dimensão."
                ),
            },
            {
                "name": "ingest_month",
                "description": (
                    "Baixa e carrega o informe diário de fundos (inf_diario_fi_{anomes}.zip)"
                    " de um mês específico em raw.cvm_inf_diario. Executada em paralelo por mês."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_CVM_FUNDS sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
    "ingest_cvm_cda": {
        "raw": ["cvm_cda_pl", "cvm_cda_cotas"],
        "desc": "CVM composição das carteiras (CDA) → raw",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "months_to_load",
                "description": (
                    "Calcula a lista de meses CDA faltantes ou recentes"
                    " que precisam ser (re)carregados do portal CVM."
                ),
            },
            {
                "name": "ingest_month",
                "description": (
                    "Baixa e carrega a composição das carteiras (cda_fi_{anomes}.zip)"
                    " de um mês específico — PL e cotas — em raw.cvm_cda_pl e raw.cvm_cda_cotas."
                    " Executada em paralelo por mês."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_CVM_CDA sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
    "ingest_focus": {
        "raw": ["focus_expectativas"],
        "desc": "BACEN Focus (expectativas de mercado) → raw.focus_expectativas",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "chunks_to_load",
                "description": (
                    "Calcula a lista de chunks (indicador × ano de referência) ainda ausentes"
                    " ou do ano corrente que precisam ser (re)carregados via Olinda OData."
                ),
            },
            {
                "name": "ingest_chunk",
                "description": (
                    "Baixa e carrega as expectativas Focus de um chunk específico"
                    " (indicador × ano) em raw.focus_expectativas."
                    " Executada em paralelo por chunk, serializada para não sobrecarregar o Olinda."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_FOCUS sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
    "ingest_ipca_aberturas": {
        "raw": ["ipca_aberturas"],
        "desc": "IBGE SIDRA (IPCA por grupo) → raw.ipca_aberturas",
        "tasks": [
            {
                "name": "create_tables",
                "description": "Cria as tabelas raw no Postgres (DDL idempotente) se não existirem.",
            },
            {
                "name": "ingest",
                "description": (
                    "Carrega o IPCA por grupo de despesa (IBGE SIDRA tabela 7060,"
                    " variação mensal) em raw.ipca_aberturas via upsert incremental."
                ),
            },
            {
                "name": "publish",
                "description": (
                    "Emite o Asset RAW_IPCA sinalizando que os dados brutos estão prontos"
                    " para o dbt downstream."
                ),
            },
        ],
    },
}

# external data sources (the public APIs each DAG pulls from), modeled as OM API
# services -> collections -> endpoints. Each endpoint is linked  endpoint -> DAG
# (the DAG consumes the API), so the full chain reads  API -> DAG -> raw.
# URLs must be valid URIs (no {…} templates — those go in the description).
SOURCES: dict[str, dict] = {
    "bacen": {
        "displayName": "Banco Central do Brasil",
        "description": "APIs públicas do BACEN: SGS (séries), PIX e Focus (Olinda/OData).",
        "collections": {
            "sgs": {
                "url": "https://api.bcb.gov.br/dados/serie",
                "desc": "SGS — séries temporais macroeconômicas.",
                "endpoints": {
                    "sgs_series": {
                        "url": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados",
                        "method": "GET",
                        "desc": "GET bcdata.sgs.{code}/dados — Selic(432), IPCA 12m(13522), USD(1)…",
                        "dag": "ingest_sgs",
                    }
                },
            },
            "pix": {
                "url": "https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1",
                "desc": "PIX — estatísticas transacionais (dados abertos, OData).",
                "endpoints": {
                    "pix_transacoes": {
                        "url": "https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1",
                        "method": "GET",
                        "desc": "Transações PIX por município/PF/PJ.",
                        "dag": "ingest_pix",
                    }
                },
            },
            "focus": {
                "url": "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1",
                "desc": "Focus — expectativas de mercado (OData).",
                "endpoints": {
                    "expectativas": {
                        "url": "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1",
                        "method": "GET",
                        "desc": "Expectativas mensais de inflação/Selic/câmbio.",
                        "dag": "ingest_focus",
                    }
                },
            },
        },
    },
    "cvm": {
        "displayName": "CVM — Dados Abertos",
        "description": "Portal de dados abertos da CVM: fundos de investimento (FI).",
        "collections": {
            "fundos": {
                "url": "https://dados.cvm.gov.br/dados/FI",
                "desc": "Fundos de investimento: cadastro, informe diário e CDA.",
                "endpoints": {
                    "inf_diario": {
                        "url": "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS",
                        "method": "GET",
                        "desc": "inf_diario_fi_{anomes}.zip — cota/PL/cotistas diários.",
                        "dag": "ingest_cvm_funds",
                    },
                    "cadastro": {
                        "url": "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv",
                        "method": "GET",
                        "desc": "cad_fi.csv — cadastro (nome, classe, situação).",
                        "dag": "ingest_cvm_funds",
                    },
                    "cda": {
                        "url": "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS",
                        "method": "GET",
                        "desc": "cda_fi_{anomes}.zip — composição das carteiras.",
                        "dag": "ingest_cvm_cda",
                    },
                },
            },
        },
    },
    "ibge": {
        "displayName": "IBGE",
        "description": "APIs do IBGE: SIDRA (tabelas) e Serviço de Dados (agregados).",
        "collections": {
            "sidra": {
                "url": "https://apisidra.ibge.gov.br",
                "desc": "SIDRA — tabelas agregadas (IPCA por grupo).",
                "endpoints": {
                    "ipca_grupos": {
                        "url": "https://apisidra.ibge.gov.br/values/t/7060/n1/all/v/2265",
                        "method": "GET",
                        "desc": "Tabela 7060 — IPCA variação por grupo de despesa.",
                        "dag": "ingest_ipca_aberturas",
                    }
                },
            },
            "agregados": {
                "url": "https://servicodados.ibge.gov.br/api/v3/agregados",
                "desc": "Serviço de Dados — agregados (população estimada).",
                "endpoints": {
                    "populacao": {
                        "url": "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-6",
                        "method": "GET",
                        "desc": "Agregado 6579 — população estimada por UF.",
                        "dag": "ingest_pix",
                    }
                },
            },
        },
    },
}


def admin_password() -> str:
    pw = os.environ.get("OM_ADMIN_NEW_PASSWORD", "")
    if pw:
        return pw
    try:
        m = re.search(r"^OM_ADMIN_NEW_PASSWORD=(.+)$", open(".env").read(), re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def api(path, method="GET", tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(
        OM_URL + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def login() -> str:
    pw = admin_password()
    code, r = api(
        "/api/v1/users/login",
        "POST",
        body={"email": ADMIN_EMAIL, "password": base64.b64encode(pw.encode()).decode()},
    )
    if code >= 300 or "accessToken" not in r:
        raise SystemExit(f"admin login failed ({code}): {r}")
    return r["accessToken"]


def table_id(tok, schema, name):
    fqn = f"{DB_SERVICE}.{DB_NAME}.{schema}.{name}"
    code, r = api(f"/api/v1/tables/name/{urllib.parse.quote(fqn, safe='')}", tok=tok)
    return r.get("id") if isinstance(r, dict) and code < 300 else None


def pipeline_id(tok, dag):
    code, r = api(f"/api/v1/pipelines/name/{AIRFLOW_SERVICE}.{dag}", tok=tok)
    return r.get("id") if isinstance(r, dict) and code < 300 else None


def add_edge(tok, from_id, from_type, to_id, to_type):
    code, _ = api(
        "/api/v1/lineage",
        "PUT",
        tok,
        {
            "edge": {
                "fromEntity": {"id": from_id, "type": from_type},
                "toEntity": {"id": to_id, "type": to_type},
            }
        },
    )
    return code


def ensure_sources(tok) -> None:
    # Phase 2: external API sources -> collections -> endpoints, linked
    # endpoint -> DAG (so the chain is API -> DAG -> raw, the DAG built in phase 1)
    print("== Phase 2: external API sources ==")
    edges = 0
    for svc, meta in SOURCES.items():
        api(
            "/api/v1/services/apiServices",
            "PUT",
            tok,
            {
                "name": svc,
                "serviceType": "Rest",
                "displayName": meta["displayName"],
                "description": meta["description"],
                "connection": {"config": {"type": "Rest"}},
            },
        )
        for coll, cmeta in meta["collections"].items():
            api(
                "/api/v1/apiCollections",
                "PUT",
                tok,
                {
                    "name": coll,
                    "service": svc,
                    "endpointURL": cmeta["url"],
                    "description": cmeta["desc"],
                },
            )
            for ep, emeta in cmeta["endpoints"].items():
                _, r = api(
                    "/api/v1/apiEndpoints",
                    "PUT",
                    tok,
                    {
                        "name": ep,
                        "apiCollection": f"{svc}.{coll}",
                        "endpointURL": emeta["url"],
                        "requestMethod": emeta["method"],
                        "description": emeta["desc"],
                    },
                )
                eid = r.get("id") if isinstance(r, dict) else None
                pid = pipeline_id(tok, emeta["dag"])
                if eid and pid:
                    ec = add_edge(tok, eid, "apiEndpoint", pid, "pipeline")
                    edges += ec < 300
                    print(f"  {svc}.{coll}.{ep} -> {emeta['dag']} -> {ec}")
                else:
                    print(f"  ! {svc}.{coll}.{ep}: not resolved (ep={eid} pid={pid})")
    print(f"done. {edges} lineage edges (API endpoint -> DAG).")


def ensure_dbt_lineage(tok) -> None:
    # Phase 3: raw -> staging -> marts, reconstructed from the dbt manifest's
    # ref()/source() graph (the source of truth). Each dbt node maps 1:1 to a
    # warehouse table, so depends_on becomes a table -> table lineage edge.
    path = os.environ.get("MANIFEST_PATH", "dbt/target/manifest.json")
    if not os.path.exists(path):
        print(f"== Phase 3: dbt manifest not found at {path}; skipping ==")
        return
    print("== Phase 3: dbt model lineage (raw -> staging -> marts) ==")
    m = json.load(open(path))
    nodes, sources = m["nodes"], m["sources"]

    def fqn_of(node_id):
        if node_id.startswith("model."):
            n = nodes.get(node_id)
            return (
                f"{DB_SERVICE}.{DB_NAME}.{n['schema']}.{n.get('alias') or n['name']}"
                if n
                else None
            )
        if node_id.startswith("source."):
            s = sources.get(node_id)
            return (
                f"{DB_SERVICE}.{DB_NAME}.{s['schema']}.{s.get('identifier') or s['name']}"
                if s
                else None
            )
        return None

    cache: dict[str, str | None] = {}

    def tid(fqn):
        if fqn not in cache:
            code, r = api(
                f"/api/v1/tables/name/{urllib.parse.quote(fqn, safe='')}", tok=tok
            )
            cache[fqn] = r.get("id") if isinstance(r, dict) and code < 300 else None
        return cache[fqn]

    edges = 0
    for nid, n in nodes.items():
        if n.get("resource_type") != "model":
            continue
        dtid = tid(fqn_of(nid))
        if not dtid:
            continue
        for up in n["depends_on"]["nodes"]:
            ufqn = fqn_of(up)
            utid = tid(ufqn) if ufqn else None
            if utid and utid != dtid:
                edges += add_edge(tok, utid, "table", dtid, "table") < 300
    print(f"done. {edges} lineage edges (table -> table, dbt).")


def main() -> None:
    tok = login()

    # 1) Airflow pipeline service. Created once with a Backend placeholder; if it
    # already exists, leave its connection untouched — the real Airflow metadata-DB
    # connection that powers the ingestion agent is set out-of-band on the VM (it
    # carries the Airflow DB password, which never belongs in this script).
    code, existing = api(
        "/api/v1/services/pipelineServices/name/" + AIRFLOW_SERVICE, tok=tok
    )
    if code >= 300 or not (isinstance(existing, dict) and existing.get("id")):
        code, _ = api(
            "/api/v1/services/pipelineServices",
            "PUT",
            tok,
            {
                "name": AIRFLOW_SERVICE,
                "serviceType": "Airflow",
                "description": "Airflow 3.2 — orquestra as ingestões diárias para o warehouse.",
                "connection": {
                    "config": {
                        "type": "Airflow",
                        "hostPort": "http://airflow-apiserver:8080",
                        "connection": {"type": "Backend"},
                    }
                },
            },
        )
        print(f"pipeline service {AIRFLOW_SERVICE} created -> {code}")
    else:
        print(f"pipeline service {AIRFLOW_SERVICE} exists -> connection preserved")

    # 2) one pipeline per DAG + 3) lineage DAG -> raw table
    edges = 0
    for dag, meta in DAGS.items():
        code, r = api(
            "/api/v1/pipelines",
            "PUT",
            tok,
            {
                "name": dag,
                "service": AIRFLOW_SERVICE,
                "displayName": f"{dag} (Airflow DAG)",
                "description": meta["desc"],
                # tasks must be non-null: the Airflow agent's status ingestion
                # calls Pipeline.getTasks().stream() server-side and NPEs on null.
                # Each task is a dict with "name" and "description" (PT).
                "tasks": [
                    {"name": t["name"], "description": t["description"]}
                    for t in meta["tasks"]
                ],
            },
        )
        pid = r.get("id") if isinstance(r, dict) else None
        print(f"  pipeline {dag} -> {code}")
        if not pid:
            continue
        for raw in meta["raw"]:
            tid = table_id(tok, "raw", raw)
            if tid:
                ec = add_edge(tok, pid, "pipeline", tid, "table")
                edges += ec < 300
                print(f"    lineage {dag} -> raw.{raw} -> {ec}")
            else:
                print(f"    ! raw.{raw} not found in catalog")
    print(f"phase 1 done. {edges} lineage edges (DAG -> raw).")

    ensure_sources(tok)
    ensure_dbt_lineage(tok)


if __name__ == "__main__":
    main()
