#!/usr/bin/env python3
"""Alertas de observabilidade via event subscriptions do OpenMetadata — Sub-projeto D.

Cria 2 event subscriptions de observabilidade:
  - dq-test-failures: alertas de resultados de teste (testCase)
  - ingestion-failures: alertas de status de pipeline (ingestionPipeline)

**Idempotente e seguro:** toda criação é guardada por "já existe?"; re-rodar
é inócuo. A senha admin nunca é impressa/logada.

Run:
  OM_URL=http://localhost:8595 python3 scripts/om_alerts.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8595").rstrip("/")
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")

# ---------------------------------------------------------------------------
# NOTA: este build do OM (1.12.11) tem o registry de funções de filtro vazio
# (GET /events/subscriptions/functions => []), então não dá para narrar por
# status (Failed/Aborted) via subscription — alertamos a nível de recurso,
# roteado ao owner via ActivityFeed. Filtro por status = follow-up.
DEST = [{"category": "Owners", "type": "ActivityFeed"}]  # Task 1: Owners aceito; Admins é fallback

SUBSCRIPTIONS = [
    {"name": "dq-test-failures", "displayName": "DQ — Resultados de teste (observabilidade)",
     "alertType": "Observability", "enabled": True,
     "resources": ["testCase"], "destinations": DEST},
    {"name": "ingestion-failures", "displayName": "Ingestão — Status de pipeline (observabilidade)",
     "alertType": "Observability", "enabled": True,
     "resources": ["ingestionPipeline"], "destinations": DEST},
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
# ensure_subscriptions — idempotente
# ---------------------------------------------------------------------------


def ensure_subscriptions(tok):
    created = skipped = 0
    for sub in SUBSCRIPTIONS:
        code, got = api(f"/api/v1/events/subscriptions/name/{sub['name']}", tok=tok)
        if code < 300 and isinstance(got, dict) and got.get("id"):
            print(f"  = {sub['name']} já existe"); skipped += 1; continue
        c, r = api("/api/v1/events/subscriptions", "POST", tok=tok, body=sub)
        if c < 300:
            print(f"  + {sub['name']} criado"); created += 1
        else:
            print(f"  ! {sub['name']} -> {c} {r}")
    print(f"subscriptions: {created} criadas, {skipped} já existentes")

def main():
    tok = login()
    print(f"Conectado ao OpenMetadata em {OM_URL}")
    ensure_subscriptions(tok)
    print("done.")

if __name__ == "__main__":
    main()
