#!/usr/bin/env python3
"""Adds charts that the Superset connector skipped (e.g. on QA, where the
connector catalogs only 29/34 — slices created after its last full run).

**Idempotente e seguro em QA/PROD:** só cria um chart se NENHUM com o mesmo
displayName já existir no serviço. Onde o conector já trouxe tudo (ex.: PROD,
34/34) o script pula todos (0 criados) — assim nunca gera duplicatas. Rodar à
toa é inofensivo.

For each missing chart:
  1. Creates the chart entity via PUT /api/v1/charts (name=slice_id).
  2. Patches the PT-BR description.
  3. Adds table→chart lineage where applicable.

Convention matching the existing 29 OM charts:
  - name  = Superset slice_id (as string)
  - displayName = chart title
  - sourceUrl = "http://superset:8088/explore/?slice_id=<id>"
  - service = brazil-economy-superset
  - chartType derived from viz_type:
      big_number / echarts_timeseries_line → "Line"
      table                               → "Table"
      everything else                     → "Other"

Run:
  OM_URL=http://localhost:28595 python3 scripts/om_add_missing_charts.py
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
DB_SERVICE = os.environ.get("OM_DB_SERVICE", "brazil-economy-warehouse")
DB_NAME = os.environ.get("OM_DB_NAME", "brazil_economy")

# ---------------------------------------------------------------------------
# The 5 missing charts: slice_id, title, viz_type, datasource table, schema
# Lineage: mart_table → chart (table as upstream, chart as downstream)
# ---------------------------------------------------------------------------
MISSING_CHARTS = [
    {
        "slice_id": 31,
        "name": "Fundos — cotistas × nº de fundos (indústria)",
        "viz_type": "mixed_timeseries",
        "chart_type": "Other",
        "mart_schema": "marts",
        "mart_table": "fct_fundos_diario",
        "description": (
            "Número de investidores (linha) vs a quantidade de fundos disponíveis "
            "no mercado. Fonte: CVM."
        ),
    },
    {
        "slice_id": 35,
        "name": "🔗 Origem dos dados",
        "viz_type": "table",
        "chart_type": "Table",
        "mart_schema": None,  # vw_freshness is a view — skip lineage
        "mart_table": None,
        "description": (
            "Quando cada fonte foi atualizada pela última vez e o link para os dados "
            "originais (BACEN, CVM, IBGE)."
        ),
    },
    {
        "slice_id": 39,
        "name": "PIX — pessoas físicas × jurídicas (volume pago)",
        "viz_type": "echarts_timeseries_bar",
        "chart_type": "Other",
        "mart_schema": "marts",
        "mart_table": "fct_pix_pessoa_mensal",
        "description": (
            "Volume pago por PIX a cada mês, separando pessoas (CPF) de empresas (CNPJ). "
            "Fonte: BACEN."
        ),
    },
    {
        "slice_id": 40,
        "name": "Fundos — % que supera o CDI por classe (12 meses)",
        "viz_type": "echarts_timeseries_line",
        "chart_type": "Other",
        "mart_schema": "marts",
        "mart_table": "fct_fundos_cdi_classe_mensal",
        "description": (
            "Dos fundos de cada tipo (Ações, Multimercado, Renda Fixa…), que fração "
            "rendeu mais que o CDI em 12 meses. Fonte: CVM e BACEN."
        ),
    },
    {
        "slice_id": 42,
        "name": "Fundos — quais superam o CDI (12 meses)",
        "viz_type": "table",
        "chart_type": "Table",
        "mart_schema": "marts",
        "mart_table": "fct_fundos_top_cdi",
        "description": (
            "Todos os fundos acessíveis (ao menos 100 cotistas e R$10 mi de patrimônio) "
            "que superaram o CDI no último ano, ordenados pela vantagem. "
            "'Acima do CDI' = diferença em pontos percentuais. Fonte: CVM e BACEN."
        ),
    },
]


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
        return e.code, e.read().decode()[:500]


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
    if code >= 300 or not isinstance(r, dict) or "accessToken" not in r:
        raise SystemExit(f"admin login falhou ({code}): {r}")
    return r["accessToken"]


def table_fqn(schema: str, table: str) -> str:
    return f"{DB_SERVICE}.{DB_NAME}.{schema}.{table}"


def get_table_id(tok: str, schema: str, table: str) -> str | None:
    fqn = urllib.parse.quote(table_fqn(schema, table), safe="")
    code, r = api(f"/api/v1/tables/name/{fqn}", tok=tok)
    if code < 300 and isinstance(r, dict):
        return r.get("id")
    return None


def upsert_chart(tok: str, chart: dict) -> str | None:
    """PUT the chart entity; return the OM chart id."""
    body = {
        "name": str(chart["slice_id"]),
        "displayName": chart["name"],
        "chartType": chart["chart_type"],
        "sourceUrl": f"http://superset:8088/explore/?slice_id={chart['slice_id']}",
        "service": SUPERSET_SERVICE,
    }
    code, r = api("/api/v1/charts", "PUT", tok, body)
    if code >= 300 or not isinstance(r, dict):
        print(f"  [!] PUT chart failed ({code}): {r}")
        return None
    chart_id = r.get("id")
    print(f"  [+] chart '{chart['name']}' upserted (id={chart_id}, http={code})")
    return chart_id


def patch_description(
    tok: str, entity_id: str, current_desc: str, new_desc: str
) -> int:
    op = "replace" if current_desc.strip() else "add"
    ops = [{"op": op, "path": "/description", "value": new_desc}]
    code, _ = api(
        f"/api/v1/charts/{entity_id}",
        "PATCH",
        tok,
        ops,
        ct="application/json-patch+json",
    )
    return code


def add_lineage(
    tok: str, from_id: str, from_type: str, to_id: str, to_type: str
) -> int:
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    tok = login()
    print(f"Conectado ao OpenMetadata em {OM_URL}")

    created = 0
    described = 0
    lineaged = 0
    skipped = 0

    # Idempotente + seguro em qualquer ambiente: o conector do Superset já cataloga
    # esses charts onde rodou por completo (ex.: PROD, 34/34). Só criamos um chart
    # se NENHUM com o mesmo displayName já existir — senão geramos duplicatas.
    code, r = api(f"/api/v1/charts?service={SUPERSET_SERVICE}&limit=200", tok=tok)
    existing = {
        (c.get("displayName") or c.get("name"))
        for c in (r.get("data", []) if isinstance(r, dict) else [])
    }

    for chart in MISSING_CHARTS:
        print(f"\n-- slice_id={chart['slice_id']} | '{chart['name']}'")

        if chart["name"] in existing:
            print("  [=] já existe no catálogo (conector já trouxe), pulando")
            skipped += 1
            continue

        # 1. Upsert the chart entity
        chart_id = upsert_chart(tok, chart)
        if not chart_id:
            continue
        created += 1

        # 2. Patch description
        code, current = api(f"/api/v1/charts/{chart_id}", tok=tok)
        current_desc = current.get("description", "") or ""
        if current_desc.strip() == chart["description"]:
            print("  [=] description already set")
            described += 1
        else:
            dc = patch_description(tok, chart_id, current_desc, chart["description"])
            if dc < 300:
                described += 1
                print(f"  [✓] description patched (http={dc})")
            else:
                print(f"  [!] description patch failed (http={dc})")

        # 3. Lineage: mart table → chart
        if not chart.get("mart_schema") or not chart.get("mart_table"):
            print("  [~] lineage skipped (no mart table)")
            continue

        table_id = get_table_id(tok, chart["mart_schema"], chart["mart_table"])
        if not table_id:
            print(f"  [!] mart table '{chart['mart_table']}' not found in OM catalog")
            continue

        lc = add_lineage(tok, table_id, "table", chart_id, "chart")
        if lc < 300:
            lineaged += 1
            print(f"  [✓] lineage: {chart['mart_table']} → chart (http={lc})")
        else:
            print(f"  [!] lineage failed (http={lc})")

    # 4. Final verification
    print("\n" + "=" * 60)
    code, r = api(f"/api/v1/charts?service={SUPERSET_SERVICE}&limit=200", tok=tok)
    total = r.get("paging", {}).get("total", "?") if isinstance(r, dict) else "?"
    print(
        f"RESULTADO: {created} charts criados, {skipped} já existentes (pulados), "
        f"{described} descritos, {lineaged} com lineage."
    )
    print(f"Total charts no OM para {SUPERSET_SERVICE}: {total}")


if __name__ == "__main__":
    main()
