#!/usr/bin/env python3
"""Aplica no OpenMetadata as descrições de TABELA e COLUNA do dbt (manifest).

O conector dbt do OM 1.12 sincroniza lineage de coluna, dbt tests e a descrição da
tabela, mas NÃO grava as descrições de coluna (lê do catalog, que não as tem). Este
script preenche essa lacuna lendo o `manifest.json` (fonte de verdade dos
`schema.yml`) e dando PATCH em tabela + colunas. Idempotente.

  OM_URL=http://localhost:28595 MANIFEST_PATH=/tmp/manifest.json python3 scripts/om_dbt_descriptions.py
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
MANIFEST_PATH = os.environ.get("MANIFEST_PATH", "dbt/target/manifest.json")


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
    req = urllib.request.Request(OM_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def login() -> str:
    pw = admin_password()
    code, r = api(
        "/api/v1/users/login",
        "POST",
        body={"email": ADMIN_EMAIL, "password": base64.b64encode(pw.encode()).decode()},
    )
    if code >= 300 or "accessToken" not in r:
        raise SystemExit(f"admin login falhou ({code}): {r}")
    return r["accessToken"]


def manifest_descriptions():
    """Mapa  FQN-da-tabela-no-OM -> {"desc": str|None, "cols": {nome: desc}}."""
    m = json.load(open(MANIFEST_PATH))
    out = {}

    def add(node, schema, name):
        fqn = f"{DB_SERVICE}.{DB_NAME}.{schema}.{name}"
        cols = {
            c: (v.get("description") or "").strip()
            for c, v in (node.get("columns") or {}).items()
            if (v.get("description") or "").strip()
        }
        out[fqn] = {"desc": (node.get("description") or "").strip() or None, "cols": cols}

    for n in m.get("nodes", {}).values():
        if n.get("resource_type") == "model":
            add(n, n["schema"], n.get("alias") or n["name"])
    for s in m.get("sources", {}).values():
        if s.get("resource_type") == "source":
            add(s, s["schema"], s.get("identifier") or s["name"])
    return out


def main() -> None:
    tok = login()
    desc = manifest_descriptions()
    tables = 0
    columns = 0
    for fqn, info in desc.items():
        code, t = api(f"/api/v1/tables/name/{urllib.parse.quote(fqn, safe='')}?fields=columns", tok=tok)
        if code >= 300 or not isinstance(t, dict) or "id" not in t:
            print(f"  ! tabela não encontrada no OM: {fqn}")
            continue
        ops = []
        if info["desc"] and (t.get("description") or "").strip() != info["desc"]:
            op = "replace" if (t.get("description") or "").strip() else "add"
            ops.append({"op": op, "path": "/description", "value": info["desc"]})
        for i, col in enumerate(t.get("columns", [])):
            d = info["cols"].get(col.get("name"))
            if d and (col.get("description") or "").strip() != d:
                op = "replace" if (col.get("description") or "").strip() else "add"
                ops.append({"op": op, "path": f"/columns/{i}/description", "value": d})
                columns += 1
        if ops:
            code, _ = api(
                f"/api/v1/tables/{t['id']}",
                "PATCH",
                tok,
                ops,
                ct="application/json-patch+json",
            )
            if code < 300:
                tables += 1
            else:
                print(f"  ! patch {fqn} -> {code}")
    print(f"done. {tables} tabelas atualizadas, {columns} colunas descritas.")


if __name__ == "__main__":
    main()
