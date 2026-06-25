#!/usr/bin/env python3
"""Falha se o manifest não tiver os meta de governança esperados."""
import sys
sys.path.insert(0, "scripts")
from om_governance import manifest_columns_meta

EXPECT_SENS = {("staging.stg_cvm_inf_diario", "cnpj"),
               ("staging.stg_cvm_inf_diario", "cnpj_digits"),
               ("staging.stg_cvm_cda_pl", "cnpj_digits"),
               ("staging.stg_cvm_cda_cotas", "cnpj_investidor_digits"),
               ("staging.stg_cvm_cda_cotas", "cnpj_investido_digits"),
               ("staging.stg_cvm_cad_fi", "cnpj")}
EXPECT_GLOSS = {("marts.fct_indicadores_macro", "selic_meta", "Selic"),
                ("marts.fct_focus_ipca_mensal", "desancoragem", "Desancoragem"),
                ("marts.fct_pix_per_capita_rank", "vl_pago_per_capita", "PIX per capita")}

meta = manifest_columns_meta()
errs = []
for tbl, col in EXPECT_SENS:
    if meta.get(tbl, {}).get(col, {}).get("om_sensibilidade") != "Identificador de Negócio":
        errs.append(f"sensibilidade ausente: {tbl}.{col}")
for tbl, col, term in EXPECT_GLOSS:
    if meta.get(tbl, {}).get(col, {}).get("om_glossario") != term:
        errs.append(f"glossario ausente: {tbl}.{col} -> {term}")
if errs:
    print("\n".join(errs)); sys.exit(1)
print(f"OK: {sum(len(v) for v in meta.values())} colunas com meta de governança.")
