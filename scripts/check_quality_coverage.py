#!/usr/bin/env python3
"""Gate de cobertura de DQ (Sub-projeto C). Lê o OM via API (somente GET).

Verifica se os 11 test cases nativos existem com o testDefinition correto.
Deve retornar exit 1 (RED) até que om_quality.py tenha sido executado.

Run:
  OM_URL=http://localhost:28598 python3 scripts/check_quality_coverage.py
"""

import sys

sys.path.insert(0, "scripts")
import urllib.parse

import om_quality as q


def check_cases(tok):
    errs = []
    for tc in q.TEST_CASES:
        tc_fqn = q.case_fqn(tc)
        encoded = urllib.parse.quote(tc_fqn, safe="")
        path = f"/api/v1/dataQuality/testCases/name/{encoded}?fields=testDefinition"
        code, got = q.api(path, tok=tok)
        if code >= 300 or not isinstance(got, dict) or got.get("name") != tc["name"]:
            errs.append(f"ausente: {tc['name']}")
            continue
        definition_name = (got.get("testDefinition") or {}).get("name")
        if definition_name != tc["definition"]:
            errs.append(
                f"definição errada: {tc['name']}"
                f" (esperado={tc['definition']}, obtido={definition_name})"
            )
    return errs


def main():
    tok = q.login()
    errs = check_cases(tok)
    status = "FAIL" if errs else "OK"
    print(f"[{status}] DQ test cases ({len(q.TEST_CASES)} esperados)")
    for e in errs:
        print(f"    - {e}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
