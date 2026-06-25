#!/usr/bin/env python3
"""Gate de cobertura de alertas (Sub-projeto D). Lê o OM via API."""
import sys
sys.path.insert(0, "scripts")
import om_alerts as a


def check(tok):
    errs = []
    for sub in a.SUBSCRIPTIONS:
        code, got = a.api(
            f"/api/v1/events/subscriptions/name/{sub['name']}?fields=filteringRules,destinations",
            tok=tok,
        )
        if code >= 300 or not isinstance(got, dict) or not got.get("id"):
            errs.append(f"ausente: {sub['name']}")
            continue
        if not got.get("enabled"):
            errs.append(f"desabilitada: {sub['name']}")
        # resources aparece em filteringRules.resources (modelo de leitura)
        res = (got.get("filteringRules") or {}).get("resources") or []
        want_res = sub["resources"][0]
        if want_res not in res:
            errs.append(
                f"resource errado: {sub['name']} (esperado {want_res}, veio {res})"
            )
        cats = {d.get("category") for d in (got.get("destinations") or [])}
        want_cat = sub["destinations"][0]["category"]
        if want_cat not in cats:
            errs.append(
                f"destino errado: {sub['name']} (esperado category {want_cat}, veio {cats})"
            )
    return errs


def main():
    tok = a.login()
    errs = check(tok)
    print(f"[{'FAIL' if errs else 'OK'}] alertas ({len(a.SUBSCRIPTIONS)} subscriptions esperadas)")
    for e in errs:
        print("    -", e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
