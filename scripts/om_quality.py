#!/usr/bin/env python3
"""Qualidade de dados nativa do OpenMetadata — Sub-projeto C.

Cria/mantém 11 test cases nativos (frescor, volume, regras de negócio),
a suite lógica ``Qualidade_Observatorio`` e o TestSuite ingestion pipeline
``om_dq_observatorio`` que os executa.

**Idempotente e seguro:** toda criação é guardada por "já existe?"; re-rodar
é inócuo. A senha admin nunca é impressa/logada.

Run:
  OM_URL=http://localhost:28598 python3 scripts/om_quality.py
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

# ---------------------------------------------------------------------------
# 11 test cases nativos curados — valores ancorados em contagens reais (QA)
# Frescor: 4 casos; Volume: 3 casos; Regras de negócio: 4 casos
# ---------------------------------------------------------------------------
TEST_CASES = [
    # --- Frescor (tableCustomSQLQuery) ------------------------------------
    {
        "name": "om_fresh_stg_sgs_observations",
        "schema": "staging",
        "table": "stg_sgs_observations",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM staging.stg_sgs_observations"
                " WHERE obs_date >= current_date - interval '10 days'"
            ),
            "strategy": "ROWS",
            "operator": ">",
            "threshold": "0",
        },
    },
    {
        "name": "om_fresh_stg_focus_expectativas",
        "schema": "staging",
        "table": "stg_focus_expectativas",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM staging.stg_focus_expectativas"
                " WHERE data >= current_date - interval '21 days'"
            ),
            "strategy": "ROWS",
            "operator": ">",
            "threshold": "0",
        },
    },
    {
        "name": "om_fresh_stg_cvm_inf_diario",
        "schema": "staging",
        "table": "stg_cvm_inf_diario",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM staging.stg_cvm_inf_diario"
                " WHERE dt_comptc >= current_date - interval '75 days'"
            ),
            "strategy": "ROWS",
            "operator": ">",
            "threshold": "0",
        },
    },
    {
        "name": "om_fresh_stg_pix_transacoes_municipio",
        "schema": "staging",
        "table": "stg_pix_transacoes_municipio",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM staging.stg_pix_transacoes_municipio"
                " WHERE to_date(anomes::text,'YYYYMM') >= current_date - interval '120 days'"
            ),
            "strategy": "ROWS",
            "operator": ">",
            "threshold": "0",
        },
    },
    # --- Volume (tableRowCountToBeBetween) --------------------------------
    {
        "name": "om_rowcount_fct_indicadores_macro",
        "schema": "marts",
        "table": "fct_indicadores_macro",
        "column": None,
        "definition": "tableRowCountToBeBetween",
        "params": {"minValue": "1000", "maxValue": "100000000"},
    },
    {
        "name": "om_rowcount_stg_sgs_observations",
        "schema": "staging",
        "table": "stg_sgs_observations",
        "column": None,
        "definition": "tableRowCountToBeBetween",
        "params": {"minValue": "5000", "maxValue": "100000000"},
    },
    {
        "name": "om_rowcount_fct_pix_uf_mensal",
        "schema": "marts",
        "table": "fct_pix_uf_mensal",
        "column": None,
        "definition": "tableRowCountToBeBetween",
        "params": {"minValue": "800", "maxValue": "100000000"},
    },
    # --- Regras de negócio ------------------------------------------------
    {
        "name": "om_range_pct_acima_cdi",
        "schema": "marts",
        "table": "fct_fundos_cdi_classe_mensal",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM marts.fct_fundos_cdi_classe_mensal"
                " WHERE pct_acima_cdi < 0 OR pct_acima_cdi > 100"
            ),
            "strategy": "ROWS",
            "operator": "==",
            "threshold": "0",
        },
    },
    {
        "name": "om_range_vl_pago_per_capita",
        "schema": "marts",
        "table": "fct_pix_per_capita_rank",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM marts.fct_pix_per_capita_rank"
                " WHERE vl_pago_per_capita < 0"
            ),
            "strategy": "ROWS",
            "operator": "==",
            "threshold": "0",
        },
    },
    {
        "name": "om_range_selic_taylor",
        "schema": "marts",
        "table": "fct_taylor_mensal",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM marts.fct_taylor_mensal"
                " WHERE selic_taylor < -5 OR selic_taylor > 50"
            ),
            "strategy": "ROWS",
            "operator": "==",
            "threshold": "0",
        },
    },
    {
        "name": "om_rule_pl_consolidado_le_bruto",
        "schema": "marts",
        "table": "fct_fundos_pl_consolidado_mensal",
        "column": None,
        "definition": "tableCustomSQLQuery",
        "params": {
            "sqlExpression": (
                "SELECT 1 FROM marts.fct_fundos_pl_consolidado_mensal"
                " WHERE pl_consolidado > pl_bruto"
            ),
            "strategy": "ROWS",
            "operator": "==",
            "threshold": "0",
        },
    },
]

# ---------------------------------------------------------------------------
# Helpers: cliente HTTP (stdlib)
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


# ---------------------------------------------------------------------------
# Helpers de FQN
# ---------------------------------------------------------------------------


def table_fqn(schema: str, table: str) -> str:
    return f"{DB_SERVICE}.{DB_NAME}.{schema}.{table}"


def case_fqn(tc) -> str:
    """Retorna o FQN completo do test case.

    - Test de tabela:  <table_fqn>.<name>
    - Test de coluna:  <table_fqn>.<column>.<name>
    """
    base = table_fqn(tc["schema"], tc["table"])
    return f"{base}.{tc['column']}.{tc['name']}" if tc.get("column") else f"{base}.{tc['name']}"


# ---------------------------------------------------------------------------
# ensure_test_cases — idempotente
# ---------------------------------------------------------------------------


def ensure_test_cases(tok: str) -> None:
    """Cria os 11 test cases nativos no OM, pulando os que já existem."""
    created = skipped = 0
    for tc in TEST_CASES:
        fqn = table_fqn(tc["schema"], tc["table"])
        tc_fqn = case_fqn(tc)
        encoded = urllib.parse.quote(tc_fqn, safe="")

        # Idempotência: GET por FQN completo do caso
        code, existing = api(f"/api/v1/dataQuality/testCases/name/{encoded}", tok=tok)
        if code < 300 and isinstance(existing, dict) and existing.get("id"):
            skipped += 1
            continue

        # Monta entityLink
        if tc["column"]:
            link = f"<#E::table::{fqn}::columns::{tc['column']}>"
        else:
            link = f"<#E::table::{fqn}>"

        # Converte params dict → lista [{name, value}]
        param_values = [{"name": k, "value": v} for k, v in tc["params"].items()]

        body = {
            "name": tc["name"],
            "entityLink": link,
            "testDefinition": tc["definition"],
            "parameterValues": param_values,
        }

        post_code, result = api(
            "/api/v1/dataQuality/testCases", method="POST", tok=tok, body=body
        )
        if post_code in (200, 201) and isinstance(result, dict) and result.get("id"):
            created += 1
        else:
            print(f"  ERRO ao criar {tc['name']} ({post_code}): {result}")

    print(f"test cases: {created} criados, {skipped} já existentes")


# ---------------------------------------------------------------------------
# JWT kid helper (usado em ensure_testsuite_bot_token)
# ---------------------------------------------------------------------------


def _kid(jwt: str):
    """Extrai o `kid` do header de um JWT sem validar assinatura."""
    try:
        head = base64.urlsafe_b64decode(jwt.split(".")[0] + "==")
        return json.loads(head).get("kid")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ensure_testsuite_bot_token — pré-requisito JWT (deve rodar antes do deploy)
# ---------------------------------------------------------------------------


def ensure_testsuite_bot_token(tok: str) -> None:
    """Reconcilia o token do testsuite-bot com o kid atual do servidor.

    Se o JWT_KEY_ID foi rotacionado após o último mint, o deploy do pipeline
    embutirá um token stale e as runs falharão com SigningKeyNotFoundException.
    """
    _, jwks = api("/api/v1/system/config/jwks", tok=tok)
    server_kid = None
    if isinstance(jwks, dict) and jwks.get("keys"):
        server_kid = jwks["keys"][0].get("kid")

    code, bot = api("/api/v1/users/name/testsuite-bot", tok=tok)
    if code >= 300 or not isinstance(bot, dict) or not bot.get("id"):
        print("  ! testsuite-bot não encontrado — reconciliação de token ignorada")
        return

    _, tdata = api(f"/api/v1/users/token/{bot['id']}", tok=tok)
    cur_kid = _kid(tdata.get("JWTToken", "")) if isinstance(tdata, dict) else None

    if server_kid and cur_kid != server_kid:
        api(
            f"/api/v1/users/generateToken/{bot['id']}",
            method="PUT",
            tok=tok,
            body={"JWTTokenExpiry": "Unlimited"},
        )
        print(f"  testsuite-bot token re-mintado (kid {cur_kid} -> {server_kid})")
    else:
        print(f"  testsuite-bot token OK (kid={cur_kid})")


# ---------------------------------------------------------------------------
# Suite lógica
# ---------------------------------------------------------------------------

LOGICAL_SUITE = "Qualidade_Observatorio"


def ensure_logical_suite(tok: str) -> str:
    """Cria (ou reutiliza) a suite lógica e vincula os 11 test cases. Retorna o suite id."""
    code, s = api(
        f"/api/v1/dataQuality/testSuites/name/{LOGICAL_SUITE}", tok=tok
    )
    if not (code < 300 and isinstance(s, dict) and s.get("id")):
        post_code, s = api(
            "/api/v1/dataQuality/testSuites",
            method="POST",
            tok=tok,
            body={
                "name": LOGICAL_SUITE,
                "displayName": "Qualidade — Observatório",
                "description": (
                    "Suite lógica de qualidade de dados do observatório"
                    " (frescor, volume, regras de negócio)."
                ),
            },
        )
        if post_code not in (200, 201) or not isinstance(s, dict) or not s.get("id"):
            raise SystemExit(f"Falha ao criar suite lógica ({post_code}): {s}")

    sid = s["id"]

    # Coleta ids dos 11 casos (criados em ensure_test_cases)
    case_ids = []
    for tc in TEST_CASES:
        fqn = case_fqn(tc)
        encoded = urllib.parse.quote(fqn, safe="")
        c_code, got = api(
            f"/api/v1/dataQuality/testCases/name/{encoded}", tok=tok
        )
        if c_code < 300 and isinstance(got, dict) and got.get("id"):
            case_ids.append(got["id"])

    api(
        "/api/v1/dataQuality/testCases/logicalTestCases",
        method="PUT",
        tok=tok,
        body={"testSuiteId": sid, "testCaseIds": case_ids},
    )
    print(f"  suite lógica {LOGICAL_SUITE}: {len(case_ids)}/11 casos vinculados")
    return sid


# ---------------------------------------------------------------------------
# Pipeline TestSuite
# ---------------------------------------------------------------------------


def ensure_testsuite_pipeline(tok: str, suite_id: str) -> str:
    """Cria (ou reutiliza) o ingestion pipeline TestSuite e faz deploy. Retorna o FQN."""
    name = "om_dq_observatorio"
    fqn = f"{LOGICAL_SUITE}.{name}"
    encoded_fqn = urllib.parse.quote(fqn, safe="")

    code, existing = api(
        f"/api/v1/services/ingestionPipelines/name/{encoded_fqn}", tok=tok
    )
    if code < 300 and isinstance(existing, dict) and existing.get("id"):
        pid = existing["id"]
    else:
        body = {
            "name": name,
            "displayName": "DQ Observatório",
            "pipelineType": "TestSuite",
            "service": {"id": suite_id, "type": "testSuite"},
            "sourceConfig": {"config": {"type": "TestSuite"}},
            "airflowConfig": {"scheduleInterval": None},
        }
        post_code, created = api(
            "/api/v1/services/ingestionPipelines", method="POST", tok=tok, body=body
        )
        if post_code not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
            raise SystemExit(f"Falha ao criar pipeline ({post_code}): {created}")
        pid = created["id"]

    deploy_code, _ = api(
        f"/api/v1/services/ingestionPipelines/deploy/{pid}", method="POST", tok=tok
    )
    print(f"  pipeline {name} deployado (fqn={fqn}, deploy_code={deploy_code})")
    return fqn


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    tok = login()
    print(f"Conectado ao OpenMetadata em {OM_URL}")
    ensure_testsuite_bot_token(tok)
    ensure_test_cases(tok)
    sid = ensure_logical_suite(tok)
    ensure_testsuite_pipeline(tok, sid)
    print("done.")


if __name__ == "__main__":
    main()
