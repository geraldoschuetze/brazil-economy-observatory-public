#!/usr/bin/env python3
"""Comprehensive diff of the managed dashboard between local DEV and a remote env.

The deploy rebuilds the dashboard from superset/bootstrap_dashboard.py, so ANY UI
edit not reflected in that file is ephemeral. This compares DEV (local) against a
pristine env (qa|prod) across EVERY dimension the bootstrap owns and reports what
diverged, tagging each as [auto] (the apply step can patch it: title, single rename)
or [manual] (you must edit the code: params/viz/dataset/layout/metadata/add/remove).

Env-specific ids (dataset ids, random layout component ids, chart ids) are normalized
out so only real, logical changes surface.

Exit: 0 = identical · 10 = only [auto] diffs · 20 = has [manual] diffs.
"""
from __future__ import annotations
import json, os, subprocess, sys

ENV = sys.argv[1] if len(sys.argv) > 1 else "qa"
HOST = os.environ.get("VM_HOST", "your.vm.host")
USER = os.environ.get("VM_USER", "ubuntu")
REMOTE_DIR = {"qa": "~/brazil-economy-observatory-qa", "prod": "~/brazil-economy-observatory"}.get(ENV)
if REMOTE_DIR is None:
    sys.exit(f"usage: {sys.argv[0]} [qa|prod]")
SLUG = "visao-geral"

QUERY = (
    "SELECT json_build_object("
    f"'title',(SELECT dashboard_title FROM dashboards WHERE slug='{SLUG}'),"
    f"'position',(SELECT position_json FROM dashboards WHERE slug='{SLUG}'),"
    f"'metadata',(SELECT json_metadata FROM dashboards WHERE slug='{SLUG}'),"
    "'charts',(SELECT json_agg(json_build_object("
    "'name',s.slice_name,'viz',s.viz_type,'params',s.params,'dataset',t.table_name) "
    "ORDER BY s.slice_name) FROM slices s "
    "JOIN dashboard_slices ds ON ds.slice_id=s.id "
    "JOIN dashboards d ON d.id=ds.dashboard_id "
    "LEFT JOIN tables t ON t.id=s.datasource_id "
    f"WHERE d.slug='{SLUG}'))::text;"
)
PSQL = "psql -U postgres -d superset -t -A -f -"


def fetch(local: bool) -> dict:
    if local:
        cmd = ["docker", "compose", "exec", "-T", "postgres", *PSQL.split()]
    else:
        cmd = ["ssh", "-o", "ConnectTimeout=15", f"{USER}@{HOST}",
               f"cd {REMOTE_DIR} && docker compose exec -T postgres {PSQL}"]
    out = subprocess.run(cmd, input=QUERY, capture_output=True, text=True, check=True).stdout.strip()
    return json.loads(out)


def clean_params(params: str) -> dict:
    try:
        p = json.loads(params)
    except Exception:
        return {}
    for k in ("datasource", "slice_id"):  # env-specific ids
        p.pop(k, None)
    return p


def body_match(ref: dict, cur: dict) -> bool:
    """True if `cur` (DEV, possibly noisy) matches `ref` (pristine, code-origin).

    Opening a chart in the Explore UI makes Superset materialize ~80 default
    form-control keys into its params (stack, area, groupby, matrixify_*, ...).
    That noise is purely ADDITIVE — it never changes the keys the bootstrap sets.
    So we compare only the keys present on the pristine side: if all match, the
    charts are semantically identical (the extra DEV keys are Superset defaults).
    A real edit shows up as a differing value on a code-set key."""
    if ref["viz"] != cur["viz"] or ref["dataset"] != cur["dataset"]:
        return False
    return all(cur["params"].get(k) == v for k, v in ref["params"].items())


def canon_layout(pos: str):
    if not pos:
        return None
    try:
        d = json.loads(pos)
    except Exception:
        return "<unparseable>"

    def walk(nid):
        n = d.get(nid) or {}
        meta = {k: v for k, v in (n.get("meta") or {}).items() if k not in ("chartId", "uuid")}
        return {"t": n.get("type"), "meta": meta, "ch": [walk(c) for c in (n.get("children") or [])]}

    return walk("ROOT_ID") if "ROOT_ID" in d else "<no-root>"


def canon_meta(meta: str):
    if not meta:
        return None
    try:
        m = json.loads(meta)
    except Exception:
        return "<unparseable>"
    for k in ("default_filters", "filter_scopes", "expanded_slices", "chart_configuration",
              "color_scheme_domain", "map_label_colors", "shared_label_colors"):
        m.pop(k, None)  # volatile / runtime color cache / keyed by chart id (Superset writes these on UI save)
    for f in (m.get("native_filter_configuration") or []):
        f.pop("id", None)
        for tgt in (f.get("targets") or []):
            tgt.pop("datasetId", None)
    return json.dumps(m, sort_keys=True, ensure_ascii=False)


def fingerprint(blob: dict) -> dict:
    charts = {}
    for c in (blob.get("charts") or []):
        charts[c["name"]] = {"viz": c["viz"], "dataset": c["dataset"], "params": clean_params(c["params"])}
    return {"title": blob.get("title"), "charts": charts,
            "layout": canon_layout(blob.get("position")), "metadata": canon_meta(blob.get("metadata"))}


def main() -> int:
    try:
        dev = fingerprint(fetch(local=True))
        rem = fingerprint(fetch(local=False))
    except subprocess.CalledProcessError as e:
        sys.stderr.write((e.stderr or "erro ao consultar o banco") + "\n")
        return 1

    auto, manual = [], []

    if dev["title"] != rem["title"]:
        auto.append(f'TÍTULO: "{rem["title"]}" → "{dev["title"]}"')

    dn, qn = set(dev["charts"]), set(rem["charts"])
    added, removed = dn - qn, qn - dn
    if len(added) == 1 and len(removed) == 1:
        a, r = next(iter(added)), next(iter(removed))
        if body_match(rem["charts"][r], dev["charts"][a]):  # same body, only the name moved
            auto.append(f'RENAME de chart: "{r}" → "{a}"')
            added, removed = set(), set()
    for a in sorted(added):
        manual.append(f'chart NOVO no DEV: "{a}" — adicione a tupla na lista CHARTS')
    for r in sorted(removed):
        manual.append(f'chart REMOVIDO no DEV: "{r}" — tire de CHARTS (ou use REMOVED_CHARTS)')

    for n in sorted(dn & qn):
        if not body_match(rem["charts"][n], dev["charts"][n]):
            parts = []
            if dev["charts"][n]["viz"] != rem["charts"][n]["viz"]:
                parts.append(f'viz {rem["charts"][n]["viz"]}→{dev["charts"][n]["viz"]}')
            if dev["charts"][n]["dataset"] != rem["charts"][n]["dataset"]:
                parts.append("dataset")
            if not parts or any(dev["charts"][n]["params"].get(k) != v
                                for k, v in rem["charts"][n]["params"].items()):
                parts.append("métricas/params/filtros/formatação")
            manual.append(f'chart "{n}" ALTERADO ({", ".join(parts)}) — edite os params em CHARTS')

    if dev["layout"] != rem["layout"]:
        manual.append("LAYOUT mudou (abas/ordem/tamanho) — ajuste build_position/LAYOUT no código")
    if dev["metadata"] != rem["metadata"]:
        manual.append("METADATA mudou (cores/filtros nativos/refresh) — ajuste json_metadata no código")

    if not auto and not manual:
        print(f"✓ DEV idêntico ao {ENV} — nenhuma edição pendente.")
        return 0

    print(f"Edições no DEV ainda NÃO refletidas no código (vs {ENV}):\n")
    for a in auto:
        print(f"  [auto]   {a}")
    for m in manual:
        print(f"  [manual] {m}")
    print()
    if manual:
        print("  [auto] = 'make superset-apply' resolve. [manual] = edite bootstrap_dashboard.py.")
    else:
        print("  Tudo capturável: rode 'make superset-capture' (aplica + reconstrói + diff).")
    return 20 if manual else 10


if __name__ == "__main__":
    sys.exit(main())
