#!/usr/bin/env python3
"""Aplica descrições de chart e dashboard no OpenMetadata, reutilizando as
legendas curadas em superset/bootstrap_dashboard.py.

Idempotente: dá PATCH apenas quando a descrição atual difere da desejada.

  OM_URL=http://localhost:28595 python3 scripts/om_descriptions.py   # QA via túnel
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
SUPERSET_SERVICE = "brazil-economy-superset"

# ---------------------------------------------------------------------------
# Descrições curadas (copiadas de superset/bootstrap_dashboard.py · CAPTIONS,
# indexadas pelo título exato do chart). Textos originais em PT-BR.
# ---------------------------------------------------------------------------

CHART_DESC: dict[str, str] = {
    "Selic meta (% a.a.)": (
        "Taxa básica de juros em vigor hoje (Selic), definida pelo Banco Central; "
        "é a referência de todo o crédito. O selo varia vs um mês atrás. Fonte: BACEN."
    ),
    "IPCA 12 meses (%)": (
        "Inflação oficial: quanto os preços subiram nos últimos 12 meses. "
        "O selo varia vs o mês anterior. Fonte: IBGE."
    ),
    "Juro real 12m (%)": (
        "O juro que sobra depois de descontar a inflação — o ganho 'de verdade' "
        "(Selic menos IPCA de 12 meses). Fonte: BACEN/IBGE."
    ),
    "Dólar (R$)": (
        "Quanto custa um dólar em reais (cotação oficial PTAX). "
        "O selo varia vs o mês anterior. Fonte: BACEN."
    ),
    "Selic × IPCA × Juro real": (
        "Três linhas: a Selic, a inflação (IPCA 12m) e o juro real — "
        "a diferença entre as duas. Fonte: BACEN/IBGE."
    ),
    "Câmbio — dólar e euro (R$)": (
        "Quantos reais valem um dólar (USD/BRL) e um euro (EUR/BRL) ao longo do tempo. "
        "Fonte: BACEN (PTAX)."
    ),
    "PIX — volume pago por mês (R$)": (
        "Quanto dinheiro circulou por PIX a cada mês, em reais. Fonte: BACEN."
    ),
    "Fundos — patrimônio líquido da indústria (consolidado)": (
        "Tamanho da indústria de fundos: o valor 'limpo' (sem contar o mesmo dinheiro "
        "duas vezes) vs o valor bruto somado. Fonte: CVM."
    ),
    "Dólar — à vista × média móvel 30d": (
        "Cotação diária do dólar vs sua média dos últimos 30 dias — "
        "a média revela a tendência por trás do sobe-e-desce. Fonte: BACEN."
    ),
    "Dólar — volatilidade 30d anualizada": (
        "O quanto o dólar 'balança' (volatilidade): quanto maior, "
        "mais imprevisível e arriscado está o câmbio. Fonte: BACEN."
    ),
    "PIX — realizado × projeção linear (6 meses)": (
        "Volume de PIX já realizado (azul) e uma projeção simples para os próximos "
        "6 meses (laranja). Fonte: BACEN."
    ),
    "PIX — ticket médio nacional (R$)": (
        "Valor médio de cada PIX — o total pago dividido pelo número de transações. "
        "Fonte: BACEN."
    ),
    "PIX — volume por região": (
        "Volume pago por PIX a cada mês, empilhado pelas cinco regiões do país. "
        "Fonte: BACEN."
    ),
    "Fundos — captação líquida × Selic": (
        "Barras: dinheiro que entrou menos o que saiu dos fundos no mês; "
        "linha: a Selic média. Fonte: CVM e BACEN."
    ),
    "IPCA 12m × meta de inflação": (
        "A inflação (IPCA 12m, vermelho) comparada à meta do governo e "
        "às suas margens de teto e piso. Fonte: IBGE e BACEN."
    ),
    "O que move a inflação? (variação 12 meses)": (
        "A inflação ao lado do que costuma puxá-la: preços no atacado (IGP-M), "
        "dólar e atividade econômica. Fonte: IBGE, FGV e BACEN."
    ),
    "IPCA — decomposição por grupo (12m)": (
        "A inflação de 12 meses dividida pelos principais tipos de gasto "
        "(alimentação, transporte, moradia…). Fonte: IBGE."
    ),
    "Focus — IPCA esperado × realizado × meta": (
        "O que o mercado financeiro espera de inflação (pesquisa Focus do BC) "
        "vs a meta e o que de fato ocorreu. Fonte: BACEN (Focus)."
    ),
    "Fundos — captação líquida por classe": (
        "Dinheiro que entrou menos o que saiu dos fundos a cada mês, "
        "separado por tipo de fundo. Fonte: CVM."
    ),
    "Fundos — % que supera o CDI (12 meses)": (
        "Que fração dos fundos rendeu mais que o CDI (referência da renda fixa) "
        "nos últimos 12 meses. Fonte: CVM."
    ),
    "PIX — per capita por UF (último mês)": (
        "Estados ordenados por quanto cada habitante movimenta em PIX, "
        "com o valor médio e a população. Fonte: BACEN e IBGE."
    ),
    "Juro real — ex-ante × ex-post": (
        "Três formas de medir o juro descontada a inflação: contra a esperada, "
        "contra a ocorrida e o juro de equilíbrio. Fonte: BACEN."
    ),
    "Expectativas — desancoragem (Focus ano seguinte − meta)": (
        "O quanto a inflação esperada pelo mercado se afasta da meta — "
        "termômetro da confiança no Banco Central. Fonte: BACEN (Focus)."
    ),
    "IPCA cheio × núcleo × difusão": (
        "Inflação cheia vs o 'núcleo' (sem os itens que mais oscilam) "
        "e o % de produtos com preço em alta. Fonte: IBGE e BACEN."
    ),
    "Fiscal — dívida bruta × resultado primário (% PIB)": (
        "A dívida do governo (% do PIB, linha) e se as contas do ano fecham "
        "no azul ou no vermelho (barras). Fonte: BACEN."
    ),
    "PIX per capita — mapa do Brasil (último mês)": (
        "Mapa do Brasil colorido por quanto cada habitante movimenta em PIX, "
        "estado a estado. Fonte: BACEN e IBGE."
    ),
    "Regra de Taylor — Selic sugerida × praticada": (
        "A Selic praticada vs a que um modelo econômico clássico "
        "(a Regra de Taylor) recomendaria. Fonte: BACEN/IBGE."
    ),
    "Dinâmica da dívida — r × g": (
        "Juro real (r) vs crescimento da economia (g): se o juro supera o crescimento "
        "e a dívida é alta, ela cresce sozinha. Fonte: BACEN/IBGE."
    ),
    "Curva de Phillips — desemprego × inflação": (
        "A relação entre desemprego e inflação: quando o desemprego cai demais, "
        "a inflação tende a subir. Fonte: IBGE."
    ),
    "PIX — pessoas físicas × jurídicas (volume pago)": (
        "Volume pago por PIX a cada mês, separando pessoas (CPF) de empresas (CNPJ). "
        "Fonte: BACEN."
    ),
    "Fundos — cotistas × nº de fundos (indústria)": (
        "Número de investidores (linha) vs a quantidade de fundos disponíveis "
        "no mercado. Fonte: CVM."
    ),
    "🔗 Origem dos dados": (
        "Quando cada fonte foi atualizada pela última vez e o link para os dados "
        "originais (BACEN, CVM, IBGE)."
    ),
    "Fundos — % que supera o CDI por classe (12 meses)": (
        "Dos fundos de cada tipo (Ações, Multimercado, Renda Fixa…), que fração "
        "rendeu mais que o CDI em 12 meses. Fonte: CVM e BACEN."
    ),
    "Fundos — quais superam o CDI (12 meses)": (
        "Todos os fundos acessíveis (ao menos 100 cotistas e R$10 mi de patrimônio) "
        "que superaram o CDI no último ano, ordenados pela vantagem. "
        "'Acima do CDI' = diferença em pontos percentuais. Fonte: CVM e BACEN."
    ),
}

DASHBOARD_DESC = (
    "Painel de indicadores macroeconômicos do Brasil — atualizado automaticamente a "
    "partir de fontes oficiais (BACEN, CVM, IBGE). Reúne juros (Selic, IPCA, juro real), "
    "câmbio, PIX, fundos de investimento e análises econômicas aplicadas "
    "(Regra de Taylor, dinâmica da dívida r×g, Curva de Phillips)."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def admin_password() -> str:
    pw = os.environ.get("OM_ADMIN_NEW_PASSWORD") or os.environ.get("OM_ADMIN_PASSWORD")
    if pw:
        return pw
    try:
        m = re.search(r"^OM_ADMIN_NEW_PASSWORD=(.+)$", open(".env").read(), re.M)
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def api(path, method="GET", tok=None, body=None, ct="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": ct}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(
        OM_URL + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def login() -> str:
    pw = admin_password()
    code, r = api(
        "/api/v1/users/login",
        "POST",
        body={
            "email": ADMIN_EMAIL,
            "password": base64.b64encode(pw.encode()).decode(),
        },
    )
    if code >= 300 or "accessToken" not in r:
        raise SystemExit(f"admin login falhou ({code}): {r}")
    return r["accessToken"]


def patch_description(tok, entity_type: str, entity_id: str, current_desc: str, new_desc: str) -> int:
    """Aplica PATCH de /description no entity. Retorna o status HTTP."""
    op = "replace" if current_desc.strip() else "add"
    ops = [{"op": op, "path": "/description", "value": new_desc}]
    code, _ = api(
        f"/api/v1/{entity_type}/{entity_id}",
        "PATCH",
        tok,
        ops,
        ct="application/json-patch+json",
    )
    return code


def list_all(tok, endpoint: str) -> list[dict]:
    """Lista todas as entidades paginando (limit=100)."""
    results = []
    after = None
    while True:
        qs = f"service={SUPERSET_SERVICE}&limit=100"
        if after:
            qs += f"&after={urllib.parse.quote(after)}"
        code, r = api(f"/api/v1/{endpoint}?{qs}", tok=tok)
        if code >= 300 or not isinstance(r, dict):
            print(f"  ! erro ao listar {endpoint}: {code} {r}")
            break
        results.extend(r.get("data", []))
        paging = r.get("paging", {})
        after = paging.get("after")
        if not after:
            break
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    tok = login()
    print(f"Conectado ao OpenMetadata em {OM_URL}")

    # ---- Charts ----
    print(f"\n== Charts do serviço {SUPERSET_SERVICE} ==")
    charts = list_all(tok, "charts")
    print(f"  {len(charts)} charts encontrados no OM")

    matched = 0
    unmatched: list[str] = []

    for chart in charts:
        # OM pode usar displayName ou name dependendo de como o Superset connector indexou
        title = chart.get("displayName") or chart.get("name") or ""
        desc_new = CHART_DESC.get(title)
        if desc_new is None:
            unmatched.append(title)
            continue
        current = (chart.get("description") or "").strip()
        if current == desc_new:
            matched += 1
            print(f"  [=] {title}")
            continue
        code = patch_description(tok, "charts", chart["id"], current, desc_new)
        if code < 300:
            matched += 1
            print(f"  [✓] {title}")
        else:
            print(f"  [!] ERRO PATCH {title} -> HTTP {code}")

    # ---- Dashboard ----
    print(f"\n== Dashboards do serviço {SUPERSET_SERVICE} ==")
    dashboards = list_all(tok, "dashboards")
    print(f"  {len(dashboards)} dashboards encontrados no OM")

    dash_updated = 0
    for dash in dashboards:
        current = (dash.get("description") or "").strip()
        if current == DASHBOARD_DESC:
            print(f"  [=] {dash.get('displayName') or dash.get('name')}")
            dash_updated += 1
            continue
        code = patch_description(tok, "dashboards", dash["id"], current, DASHBOARD_DESC)
        name = dash.get("displayName") or dash.get("name")
        if code < 300:
            dash_updated += 1
            print(f"  [✓] {name}")
        else:
            print(f"  [!] ERRO PATCH dashboard '{name}' -> HTTP {code}")

    # ---- Relatório ----
    print("\n" + "=" * 60)
    print(f"RESULTADO: {matched}/{len(charts)} charts descritos, "
          f"{dash_updated}/{len(dashboards)} dashboards descritos.")
    if unmatched:
        print(f"\nATENÇÃO — {len(unmatched)} chart(s) no OM sem legenda no CHART_DESC:")
        for t in unmatched:
            print(f"  - {t!r}")
    else:
        print("Todos os charts foram casados com uma legenda.")


if __name__ == "__main__":
    main()
