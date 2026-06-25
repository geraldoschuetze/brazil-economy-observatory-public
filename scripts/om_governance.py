#!/usr/bin/env python3
"""Provision OpenMetadata governance for the Brazil Economy Observatory.

Idempotent (PUT create-or-update) — safe to re-run. Uses only the Python
standard library (runs on the VM host against the loopback OM API).

Pilares implementados:
  Era A — base: classifications (Fonte, Camada) + tags, glossário de termos
           econômicos (TERMS), domain 'Economia Brasileira', Data Products,
           Team, ownership do warehouse service, tag de tabelas por layer/fonte.
  B1 — Classificação honesta de sensibilidade: classification 'Sensibilidade'
       com tags 'Público' / 'Identificador de Negócio' / 'Dado Pessoal' (não
       utilizado). Aplicada via dbt manifest.json (meta.om_sensibilidade),
       atualmente em colunas CNPJ da CVM.
  B2 — Glossário ampliado: 8 termos de vocabulário operacional (VOCAB_TERMS)
       adicionados ao glossário 'Economia Brasileira', com vínculos de
       coluna→term lidos do dbt/target/manifest.json (meta.om_glossario).
  B3 — 10 entidades Metric com fórmula SQL/SGS e lineage tabela→metric
       (upstream = mart, downstream = Metric entity no OM).
  B4 — Marts atribuídos a seus Data Products após setar o domain
       'Economia Brasileira' em cada tabela (exigido pela regra de validação
       do OM 'Data Product Domain Validation').

Usage:
    OM_URL=http://127.0.0.1:8595 OM_ADMIN_PASSWORD=... python3 scripts/om_governance.py
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8595").rstrip("/")
MANIFEST_PATH = os.environ.get("MANIFEST_PATH", "dbt/target/manifest.json")


def manifest_columns_meta(path: str = MANIFEST_PATH) -> dict:
    """{ 'schema.table': { 'col': {'om_sensibilidade':..,'om_glossario':..} } } a partir do manifest dbt."""
    with open(path) as fh:
        man = json.load(fh)
    out: dict = {}
    for node in man.get("nodes", {}).values():
        if node.get("resource_type") != "model":
            continue
        schema, name = node["schema"], node["name"]
        cols = {}
        for col, meta in node.get("columns", {}).items():
            m = (meta or {}).get("meta") or {}
            if "om_sensibilidade" in m or "om_glossario" in m:
                cols[col] = {
                    "om_sensibilidade": m.get("om_sensibilidade"),
                    "om_glossario": m.get("om_glossario"),
                }
        if cols:
            out[f"{schema}.{name}"] = cols
    return out
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")
ADMIN_PASSWORD = os.environ.get("OM_ADMIN_PASSWORD", "admin")
DB_SERVICE = "brazil-economy-warehouse"

# --- classifications -> tags ----------------------------------------------
CLASSIFICATIONS = {
    "Fonte": ("Fonte de dados pública de origem", ["BACEN", "CVM", "IBGE"]),
    "Camada": ("Camada do warehouse dimensional", ["Raw", "Staging", "Marts"]),
}

# raw table -> source tag (derived layers inherit via lineage, not tagged here)
RAW_SOURCE = {
    "sgs_observations": "BACEN",
    "focus_expectativas": "BACEN",
    "pix_transacoes_municipio": "BACEN",
    "cvm_inf_diario": "CVM",
    "cvm_cad_fi": "CVM",
    "cvm_cda_pl": "CVM",
    "cvm_cda_cotas": "CVM",
    "dim_populacao_uf": "IBGE",
    "ipca_aberturas": "IBGE",
}

GLOSSARY = "Economia Brasileira"
TERMS = {
    "Selic": "Taxa básica de juros da economia, definida pelo Copom (BACEN).",
    "CDI": "Certificado de Depósito Interbancário; referência de renda fixa, ~Selic.",
    "IPCA": "Índice de Preços ao Consumidor Amplo; inflação oficial (IBGE).",
    "Juro real ex-ante": "(1+Selic)/(1+inflação esperada) − 1; aperto monetário vs expectativa.",
    "Juro real ex-post": "Selic menos a inflação (IPCA 12m) já realizada.",
    "Focus": "Pesquisa do BACEN com as expectativas de mercado (IPCA, Selic).",
    "Desancoragem": "Expectativa de inflação do ano seguinte menos a meta; credibilidade do BC.",
    "IGP-M": "Índice Geral de Preços do Mercado (FGV); preços no atacado, antecede o IPCA.",
    "Dívida bruta": "Dívida Bruta do Governo Geral em % do PIB.",
    "Resultado primário": "Receitas menos despesas (exceto juros) em % do PIB; + = superávit.",
    "Regra de Taylor": "Selic que o modelo (1993) recomendaria dado hiato e desvio da meta.",
    "Curva de Phillips": "Relação inversa de curto prazo entre desemprego e inflação.",
    "PL consolidado": "Patrimônio dos fundos líquido de cotas-de-fundos (sem dupla contagem; ~ANBIMA).",
    "PIX per capita": "Valor pago via PIX por habitante (UF), normalizado pela população IBGE.",
}

SENSIBILIDADE = {
    "Público": "Dado público de origem regulatória/estatística (BACEN, CVM, IBGE); sem restrição de divulgação.",
    "Identificador de Negócio": "Identificador de pessoa jurídica de registro público (ex.: CNPJ de fundo na CVM). Não é dado pessoal.",
    "Dado Pessoal": "Reservado a dados pessoais (LGPD). NÃO UTILIZADO: o warehouse não contém dados de pessoa física — PIX é agregado por UF e os CNPJs são de fundos (PJ).",
}

DOMAIN = "Economia Brasileira"
DATA_PRODUCTS = {
    "Indicadores Macro": "Selic, IPCA, câmbio, juro real e atividade (BACEN SGS).",
    "Inflação": "IPCA, núcleo, difusão, IGP-M, decomposição por grupo e Focus.",
    "Fiscal": "Dívida bruta e resultado primário (% PIB).",
    "Câmbio": "USD/BRL, EUR/BRL, média móvel e volatilidade.",
    "PIX": "Adoção do PIX por município/UF, ticket, projeção e per capita.",
    "Fundos": "Universo CVM: PL consolidado, captação por classe, % acima do CDI.",
}

TEAM = "Data Platform"


def token() -> str:
    pw = base64.b64encode(ADMIN_PASSWORD.encode()).decode()
    body = json.dumps({"email": ADMIN_EMAIL, "password": pw}).encode()
    req = urllib.request.Request(
        f"{OM_URL}/api/v1/users/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["accessToken"]


_TOK: str | None = None


def _get_tok() -> str:
    global _TOK
    if _TOK is None:
        _TOK = token()
    return _TOK


def call(method: str, path: str, payload=None, patch=False):
    data = json.dumps(payload).encode() if payload is not None else None
    ct = "application/json-patch+json" if patch else "application/json"
    req = urllib.request.Request(
        f"{OM_URL}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {_get_tok()}", "Content-Type": ct},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"  ! {method} {path} -> {e.code} {body}")
        return None


def put(path, payload):
    return call("PUT", path, payload)


def get_table_by_fqn(fqn: str):
    return call("GET", f"/api/v1/tables/name/{urllib.parse.quote(fqn, safe='')}?fields=columns,tags")


def patch_column_tag(table: dict, col_name: str, tagfqn: str, source: str) -> bool:
    """Adiciona tag a UMA coluna por índice; idempotente (não duplica)."""
    cols = table.get("columns", [])
    idx = next((i for i, c in enumerate(cols) if c["name"] == col_name), None)
    if idx is None:
        print(f"  ! coluna {col_name} ausente em {table['fullyQualifiedName']}")
        return False
    have = {t.get("tagFQN") for t in (cols[idx].get("tags") or [])}
    if tagfqn in have:
        return True
    call("PATCH", f"/api/v1/tables/{table['id']}",
         [{"op": "add", "path": f"/columns/{idx}/tags/-",
           "value": {"tagFQN": tagfqn, "source": source}}], patch=True)
    return True


def create_metric(spec: dict):
    """PUT idempotente de uma Metric. spec: name, description, code, granularity, unit."""
    return put("/api/v1/metrics", {
        "name": spec["name"],
        "displayName": spec["name"],
        "description": spec["description"],
        "metricExpression": {"language": "SQL", "code": spec["code"]},
        "granularity": spec["granularity"],
        "unitOfMeasurement": spec["unit"],
    })


def link_table_metric(table_id: str, metric_id: str):
    """lineage tabela(upstream) -> metric(downstream)."""
    return put("/api/v1/lineage", {"edge": {
        "fromEntity": {"id": table_id, "type": "table"},
        "toEntity": {"id": metric_id, "type": "metric"}}})


def add_dp_asset(dp_name: str, table_id: str):
    """PUT /api/v1/dataProducts/{name}/assets/add — confirmado em probe (OPTIONS → PUT).
    Usa o *name* do DP (não o id), conforme OMetaDomainMixin do SDK oficial (domain_mixin.py).
    REQUER que a tabela já tenha o domain do DP (regra 'Data Product Domain Validation').
    Retorna o dict de resposta ou None em falha.
    """
    return call("PUT", f"/api/v1/dataProducts/{urllib.parse.quote(dp_name, safe='')}/assets/add",
                {"assets": [{"id": table_id, "type": "table"}]})


def set_table_domain(table: dict, domain_ref: dict) -> bool:
    """Garante que a tabela pertence ao domain indicado (idempotente).

    Args:
        table: dict da tabela (precisa de 'id' e 'fullyQualifiedName').
        domain_ref: {"id": DOMAIN_ID, "type": "domain"}.

    Returns:
        True se o domain já estava presente ou foi adicionado com sucesso; False em erro.
    """
    tid = table["id"]
    # Re-GET com fields=domains para verificar o estado atual
    t = call("GET", f"/api/v1/tables/{tid}?fields=domains")
    if t is None:
        return False
    existing = {d.get("id") for d in (t.get("domains") or [])}
    if domain_ref["id"] in existing:
        return True  # já tem o domain; nada a fazer
    result = call(
        "PATCH",
        f"/api/v1/tables/{tid}",
        [{"op": "add", "path": "/domains/-", "value": domain_ref}],
        patch=True,
    )
    return result is not None


METRICS = [
    {"name": "Juro Real Ex-Ante", "table": "marts.fct_focus_ipca_mensal",
     "code": "(1 + selic/100) / (1 + exp_12m/100) - 1", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Juro real prospectivo (Fisher) usando a Selic e a expectativa de IPCA 12m do Focus."},
    {"name": "Juro Real Ex-Post", "table": "marts.fct_indicadores_macro",
     "code": "selic_meta - ipca_12m_ff", "granularity": "DAY", "unit": "PERCENTAGE",
     "description": "Juro real realizado: Selic meta menos IPCA acumulado 12m."},
    {"name": "Desancoragem", "table": "marts.fct_focus_ipca_mensal",
     "code": "exp_ano_seguinte - meta", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Expectativa de IPCA do ano seguinte menos a meta; medida de credibilidade do BC."},
    {"name": "% Fundos Acima do CDI", "table": "marts.fct_fundos_cdi_classe_mensal",
     "code": "100.0 * avg((ret_12m > cdi_ret_12m)::int)", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Fração dos fundos cujo retorno 12m supera o CDI 12m, por classe."},
    {"name": "PIX Per Capita", "table": "marts.fct_pix_per_capita_rank",
     "code": "vl_pago / populacao", "granularity": "MONTH", "unit": "DOLLARS",
     "description": "Valor pago via PIX por habitante (UF), normalizado pela população IBGE."},
    {"name": "Dívida Bruta (% PIB)", "table": "marts.fct_fiscal_mensal",
     "code": "SGS 13762", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Dívida Bruta do Governo Geral em % do PIB (BACEN SGS 13762)."},
    {"name": "Resultado Primário (% PIB)", "table": "marts.fct_fiscal_mensal",
     "code": "-1 * SGS 5793", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Resultado primário do governo central em % do PIB; positivo = superávit."},
    {"name": "Selic Prescrita (Taylor)", "table": "marts.fct_taylor_mensal",
     "code": "juro_neutro + exp_12m + 0.5*(exp_12m - meta) + 0.5*hiato", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "Selic que a regra de Taylor (1993) recomendaria dado hiato e desvio da meta."},
    {"name": "IPCA 12m", "table": "marts.fct_inflacao_drivers_mensal",
     "code": "SGS 13522", "granularity": "MONTH", "unit": "PERCENTAGE",
     "description": "IPCA acumulado em 12 meses (inflação cheia, BACEN SGS 13522)."},
    {"name": "Selic Meta", "table": "marts.fct_indicadores_macro",
     "code": "SGS 432", "granularity": "DAY", "unit": "PERCENTAGE",
     "description": "Taxa Selic meta definida pelo Copom (BACEN SGS 432)."},
]

def apply_metrics(tok=None):
    for spec in METRICS:
        existing = call("GET", "/api/v1/metrics/name/" + urllib.parse.quote(spec["name"], safe=""))
        m = create_metric(spec)
        if not m:
            continue
        tbl = get_table_by_fqn(f"{DB_SERVICE}.brazil_economy.{spec['table']}")
        if tbl and m.get("id"):
            link_table_metric(tbl["id"], m["id"])
        if not existing:
            print(f"  + métrica '{spec['name']}' <- {spec['table']}")

DP_ASSETS = {
    "Indicadores Macro": ["fct_indicadores_macro"],
    "Inflação": ["fct_focus_ipca_mensal", "fct_inflacao_drivers_mensal",
                 "fct_ipca_aberturas", "fct_taylor_mensal"],
    "Fiscal": ["fct_fiscal_mensal"],
    "PIX": ["fct_pix_pessoa_mensal", "fct_pix_uf_mensal",
            "fct_pix_per_capita_rank", "fct_pix_projecao"],
    "Fundos": ["fct_fundos_diario", "fct_fundos_classe_mensal",
               "fct_fundos_cdi_classe_mensal", "fct_fundos_vs_cdi",
               "fct_fundos_top_cdi", "fct_fundos_pl_consolidado_mensal",
               "fct_fundos_selic_mensal"],
}


def _dp_existing_assets(dp_id: str) -> set:
    """GET /api/v1/dataProducts/{id}/assets — retorna nomes dos assets já atribuídos."""
    d = call("GET", f"/api/v1/dataProducts/{dp_id}/assets?limit=200")
    return {a["name"] for a in (d or {}).get("data", [])}


def apply_dp_assets(tok=None):
    """Atribui marts aos Data Products via PUT /dataProducts/{name}/assets/add (idempotente).

    Fluxo por tabela:
      1. Verifica se o mart já é asset do DP (skip se sim).
      2. Garante que a tabela tem o domain 'Economia Brasileira' (obrigatório pela
         regra 'Data Product Domain Validation' do OM antes do assets/add).
      3. Chama assets/add e imprime sucesso apenas se a resposta indicar "success".
    """
    # Resolve o domain uma única vez
    dom = call("GET", f"/api/v1/domains/name/{urllib.parse.quote(DOMAIN, safe='')}")
    if not dom:
        print(f"  ! domain '{DOMAIN}' não encontrado — abortando apply_dp_assets")
        return
    domain_ref = {"id": dom["id"], "type": "domain"}

    for dp, marts in DP_ASSETS.items():
        d = call("GET", f"/api/v1/dataProducts/name/{urllib.parse.quote(dp, safe='')}")
        if not d:
            print(f"  ! data product ausente: {dp}"); continue
        have = _dp_existing_assets(d["id"])
        for mart in marts:
            if mart in have:
                continue  # já é asset; idempotente
            tbl = get_table_by_fqn(f"{DB_SERVICE}.brazil_economy.marts.{mart}")
            if not tbl:
                print(f"  ! tabela não encontrada: marts.{mart}")
                continue
            # Passo 2: garante domain na tabela (exigido pela regra de validação do DP)
            if not set_table_domain(tbl, domain_ref):
                print(f"  ! falha ao setar domain em {mart} — pulando assets/add")
                continue
            # Passo 3: adiciona ao Data Product
            resp = add_dp_asset(dp, tbl["id"])
            if resp and resp.get("status") == "success":
                print(f"  + asset {mart} -> {dp}")



VOCAB_TERMS = {
    "CNPJ (fundo)": "CNPJ do fundo de investimento; identificador público de PJ (registro CVM).",
    "anomes": "Competência no formato AAAAMM (ano e mês concatenados).",
    "vl_quota": "Valor da cota do fundo na data de competência (CVM Informe Diário).",
    "vl_patrim_liq": "Patrimônio líquido do fundo/classe ao fim do mês (CVM CDA).",
    "tipo_pessoa": "Categoria do pagador no PIX: pessoa física (CPF) ou jurídica (CNPJ). Rótulo agregado, sem documento individual.",
    "series_code (SGS)": "Código numérico da série temporal no Sistema Gerenciador de Séries (SGS) do BACEN.",
    "dt_comptc": "Data de competência do informe CVM.",
    "cnpj_digits": "CNPJ do fundo somente com dígitos (sem pontuação), usado em joins.",
}


def apply_glossary_links(tok=None):
    for term, definition in VOCAB_TERMS.items():
        put("/api/v1/glossaryTerms", {"glossary": GLOSSARY, "name": term, "description": definition})
    meta = manifest_columns_meta()
    cache = {}
    for tbl_key, cols in meta.items():
        for col, m in cols.items():
            if m.get("om_glossario"):
                fqn = f"{DB_SERVICE}.brazil_economy.{tbl_key}"
                tbl = cache.get(fqn) or get_table_by_fqn(fqn)
                cache[fqn] = tbl
                if tbl:
                    patch_column_tag(tbl, col, f"{GLOSSARY}.{m['om_glossario']}", "Glossary")


def apply_sensibilidade(tok=None):
    put("/api/v1/classifications", {"name": "Sensibilidade",
        "description": "Classificação de sensibilidade do dado (LGPD), aplicada com honestidade ao acervo público."})
    for tag, desc in SENSIBILIDADE.items():
        put("/api/v1/tags", {"classification": "Sensibilidade", "name": tag, "description": desc})
    meta = manifest_columns_meta()
    cache = {}
    for tbl_key, cols in meta.items():
        for col, m in cols.items():
            if m.get("om_sensibilidade"):
                fqn = f"{DB_SERVICE}.brazil_economy.{tbl_key}"
                tbl = cache.get(fqn) or get_table_by_fqn(fqn)
                cache[fqn] = tbl
                if tbl:
                    patch_column_tag(tbl, col, f"Sensibilidade.{m['om_sensibilidade']}", "Classification")


def main() -> None:
    print("== classifications & tags ==")
    for cls, (desc, tags) in CLASSIFICATIONS.items():
        put("/api/v1/classifications", {"name": cls, "description": desc})
        for t in tags:
            put("/api/v1/tags", {"classification": cls, "name": t, "description": t})
    print("== B1 sensibilidade ==")
    apply_sensibilidade()
    print("== glossary ==")
    put("/api/v1/glossaries", {"name": GLOSSARY, "description": "Termos econômicos do observatório."})
    for term, definition in TERMS.items():
        put("/api/v1/glossaryTerms", {"glossary": GLOSSARY, "name": term, "description": definition})
    print("== B2 glossário + vínculos ==")
    apply_glossary_links()
    print("== B3 métricas ==")
    apply_metrics()
    print("== domain & data products ==")
    put("/api/v1/domains", {"name": DOMAIN, "domainType": "Aggregate",
                            "description": "Dados públicos da economia brasileira."})
    for dp, desc in DATA_PRODUCTS.items():
        put("/api/v1/dataProducts", {"name": dp, "domains": [DOMAIN], "description": desc})
    print("== team ==")
    put("/api/v1/teams", {"name": TEAM, "teamType": "Group",
                          "description": "Time responsável pela plataforma de dados."})
    print("== tag tables by layer & source ==")
    res = call("GET", "/api/v1/tables?limit=1000&fields=tags")
    for tbl in (res or {}).get("data", []):
        fqn = tbl["fullyQualifiedName"]
        parts = fqn.split(".")
        schema, name = parts[-2], parts[-1]
        layer = {"raw": "Raw", "staging": "Staging", "marts": "Marts"}.get(schema)
        tags = []
        if layer:
            tags.append({"tagFQN": f"Camada.{layer}", "source": "Classification"})
        if schema == "raw" and name in RAW_SOURCE:
            tags.append({"tagFQN": f"Fonte.{RAW_SOURCE[name]}", "source": "Classification"})
        for tag in tags:
            call("PATCH", f"/api/v1/tables/{tbl['id']}",
                 [{"op": "add", "path": "/tags/-", "value": tag}], patch=True)
    print("== set warehouse service owner = team ==")
    svc = call("GET", f"/api/v1/services/databaseServices/name/{DB_SERVICE}")
    team = call("GET", f"/api/v1/teams/name/{urllib.parse.quote(TEAM)}")
    if svc and team:
        call("PATCH", f"/api/v1/services/databaseServices/{svc['id']}",
             [{"op": "add", "path": "/owners/-",
               "value": {"id": team["id"], "type": "team"}}], patch=True)
    print("== B4 domains & ownership ==")
    apply_dp_assets()
    print("done.")


if __name__ == "__main__":
    main()
