#!/usr/bin/env python3
"""Falha se algum modelo/fonte/coluna do dbt estiver sem description.
Uso: dbt parse && python3 scripts/check_dbt_doc_coverage.py [caminho_manifest]"""
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else "dbt/target/manifest.json"
m = json.load(open(path))
gaps = []
def walk(items, kind):
    for k, n in items.items():
        if n.get("resource_type") not in ("model", "source"):
            continue
        if not (n.get("description") or "").strip():
            gaps.append(f"{kind} sem descrição: {n['name']}")
        for col, c in (n.get("columns") or {}).items():
            if not (c.get("description") or "").strip():
                gaps.append(f"coluna sem descrição: {n['name']}.{col}")
walk(m.get("nodes", {}), "modelo")
walk(m.get("sources", {}), "fonte")
for g in gaps:
    print(g)
print(f"\n{len(gaps)} lacuna(s).")
sys.exit(1 if gaps else 0)
