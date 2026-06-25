#!/usr/bin/env python3
"""Gate de cobertura de governança (Sub-projeto B). Lê o OM via API."""
import os, sys, urllib.parse
sys.path.insert(0, "scripts")
import om_governance as g

DB = "brazil-economy-warehouse"
DBN = "brazil_economy"

CNPJ_COLS = [("staging", "stg_cvm_inf_diario", "cnpj"),
             ("staging", "stg_cvm_inf_diario", "cnpj_digits"),
             ("staging", "stg_cvm_cda_pl", "cnpj_digits"),
             ("staging", "stg_cvm_cda_cotas", "cnpj_investidor_digits"),
             ("staging", "stg_cvm_cda_cotas", "cnpj_investido_digits"),
             ("staging", "stg_cvm_cad_fi", "cnpj")]

def _col_tags(tbl, col):
    t = g.get_table_by_fqn(f"{DB}.{DBN}.{tbl}")
    if not t:
        return None
    c = next((c for c in t.get("columns", []) if c["name"] == col), None)
    return {x.get("tagFQN") for x in (c.get("tags") or [])} if c else None

def check_sensibilidade():
    errs = []
    cls = g.call("GET", "/api/v1/classifications/name/Sensibilidade")
    if not cls:
        errs.append("classification Sensibilidade ausente")
    for schema, tbl, col in CNPJ_COLS:
        tags = _col_tags(f"{schema}.{tbl}", col)
        if tags is None:
            errs.append(f"coluna ausente: {tbl}.{col}"); continue
        if "Sensibilidade.Identificador de Negócio" not in tags:
            errs.append(f"sem 'Identificador de Negócio': {tbl}.{col}")
        if "Sensibilidade.Dado Pessoal" in tags:
            errs.append(f"PII indevida: {tbl}.{col}")
    return errs

def check_glossario():
    errs = []
    gl = g.call("GET", "/api/v1/glossaries/name/" + urllib.parse.quote("Economia Brasileira"))
    if not gl:
        errs.append("glossário Economia Brasileira ausente")
        return errs
    res = g.call("GET", f"/api/v1/glossaryTerms?glossary={gl['id']}&limit=200")
    terms = {t["name"] for t in (res or {}).get("data", [])}
    for vt in ["CNPJ (fundo)", "anomes", "vl_quota", "vl_patrim_liq",
               "tipo_pessoa", "series_code (SGS)", "dt_comptc", "cnpj_digits"]:
        if vt not in terms:
            errs.append(f"termo de vocabulário ausente: {vt}")
    # cada termo deve estar ligado a >=1 coluna: amostragem em colunas-chave
    spot = [("staging.stg_cvm_inf_diario", "cnpj", "Economia Brasileira.CNPJ (fundo)"),
            ("marts.fct_indicadores_macro", "selic_meta", "Economia Brasileira.Selic"),
            ("marts.fct_pix_per_capita_rank", "vl_pago_per_capita", "Economia Brasileira.PIX per capita")]
    for tbl, col, gfqn in spot:
        tags = _col_tags(tbl, col)
        if tags is None or gfqn not in tags:
            errs.append(f"vínculo glossário ausente: {tbl}.{col} -> {gfqn}")
    return errs

METRIC_NAMES = ["Juro Real Ex-Ante", "Juro Real Ex-Post", "Desancoragem",
                "% Fundos Acima do CDI", "PIX Per Capita", "Dívida Bruta (% PIB)",
                "Resultado Primário (% PIB)", "Selic Prescrita (Taylor)",
                "IPCA 12m", "Selic Meta"]

def check_metricas():
    errs = []
    for name in METRIC_NAMES:
        m = g.call("GET", f"/api/v1/metrics/name/{urllib.parse.quote(name, safe='')}?fields=owners")
        if not m:
            errs.append(f"métrica ausente: {name}"); continue
        if not (m.get("metricExpression") or {}).get("code"):
            errs.append(f"métrica sem fórmula: {name}")
        lin = g.call("GET", f"/api/v1/lineage/getLineage?fqn={urllib.parse.quote(m['fullyQualifiedName'], safe='')}&type=metric&upstreamDepth=1&downstreamDepth=0")
        if not (lin or {}).get("upstreamEdges"):
            errs.append(f"métrica sem lineage upstream: {name}")
    return errs

MART_TO_DP = {
    "fct_indicadores_macro": "Indicadores Macro",
    "fct_focus_ipca_mensal": "Inflação", "fct_inflacao_drivers_mensal": "Inflação",
    "fct_ipca_aberturas": "Inflação", "fct_taylor_mensal": "Inflação",
    "fct_fiscal_mensal": "Fiscal",
    "fct_pix_pessoa_mensal": "PIX", "fct_pix_uf_mensal": "PIX",
    "fct_pix_per_capita_rank": "PIX", "fct_pix_projecao": "PIX",
    "fct_fundos_diario": "Fundos", "fct_fundos_classe_mensal": "Fundos",
    "fct_fundos_cdi_classe_mensal": "Fundos", "fct_fundos_vs_cdi": "Fundos",
    "fct_fundos_top_cdi": "Fundos", "fct_fundos_pl_consolidado_mensal": "Fundos",
    "fct_fundos_selic_mensal": "Fundos",
}


def check_domains():
    errs = []
    DOMAIN_NAME = "Economia Brasileira"

    # Resolve o domain id uma vez
    dom = g.call("GET", f"/api/v1/domains/name/{urllib.parse.quote(DOMAIN_NAME)}")
    domain_id = dom["id"] if dom else None
    if not domain_id:
        errs.append(f"domain '{DOMAIN_NAME}' ausente")

    # Verificação por DP: GET /api/v1/dataProducts/{id}/assets (endpoint paginado confirmado em probe)
    dp_cache: dict = {}
    for dp in set(MART_TO_DP.values()):
        d = g.call("GET", f"/api/v1/dataProducts/name/{urllib.parse.quote(dp)}")
        if not d:
            errs.append(f"data product ausente: {dp}"); continue
        assets_resp = g.call("GET", f"/api/v1/dataProducts/{d['id']}/assets?limit=200")
        dp_cache[dp] = {a["name"] for a in (assets_resp or {}).get("data", [])}

    for mart, dp in MART_TO_DP.items():
        if dp not in dp_cache:
            continue  # já reportado como ausente acima
        if mart not in dp_cache[dp]:
            errs.append(f"asset não atribuído: {mart} -> {dp}")

        # Verifica que a tabela mart carrega o domain 'Economia Brasileira'
        if domain_id:
            fqn = f"{DB}.{DBN}.marts.{mart}"
            t = g.call("GET", f"/api/v1/tables/name/{urllib.parse.quote(fqn, safe='')}?fields=domains")
            if t:
                existing_ids = {d2.get("id") for d2 in (t.get("domains") or [])}
                if domain_id not in existing_ids:
                    errs.append(f"tabela sem domain '{DOMAIN_NAME}': {mart}")

    # OM 1.10: 'domain' não é campo válido em databaseServices — verificar apenas owners
    svc = g.call("GET", "/api/v1/services/databaseServices/name/brazil-economy-warehouse?fields=owners")
    if not (svc or {}).get("owners"):
        errs.append("serviço sem owner")
    return errs


CHECKS = [("B1 Sensibilidade", check_sensibilidade), ("B2 Glossário", check_glossario), ("B3 Métricas", check_metricas), ("B4 Domains/Ownership", check_domains)]

def main():
    total = []
    for name, fn in CHECKS:
        errs = fn()
        print(f"[{'FAIL' if errs else 'OK'}] {name}")
        for e in errs:
            print(f"    - {e}")
        total += errs
    sys.exit(1 if total else 0)

if __name__ == "__main__":
    main()
