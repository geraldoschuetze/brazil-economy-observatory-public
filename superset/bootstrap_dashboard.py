"""Bootstrap the 'Brazil Economy - Visao Geral' dashboard on any Superset instance.

Dashboard-as-code, executed INSIDE the superset container with the app's own
ORM (the REST API path breaks when AUTH_ROLE_PUBLIC is set: JWT-authenticated
POSTs resolve the current user as anonymous and fail to assign ownership).
Target: Superset 6.1.0 (see docker-compose.yml). When upgrading Superset,
re-verify the anonymous Public permission set below (security finding M1).

Usage:
    docker compose exec -T \
      -e ADMIN_USERNAME=admin -e BRAZIL_ECONOMY_DB_PASSWORD=... \
      superset python - < superset/bootstrap_dashboard.py
"""

from __future__ import annotations

import json
import os

DB_NAME = "brazil_economy warehouse"
DATASETS = [
    "fct_indicadores_macro",
    "fct_pix_uf_mensal",
    "fct_pix_pessoa_mensal",
    "fct_fundos_diario",
    "fct_pix_projecao",
    "fct_fundos_selic_mensal",
    "fct_inflacao_drivers_mensal",
    "fct_ipca_aberturas",
    "fct_focus_ipca_mensal",
    "fct_fundos_classe_mensal",
    "fct_fundos_vs_cdi",
    "fct_fundos_cdi_classe_mensal",
    "fct_fundos_top_cdi",
    "fct_pix_per_capita_rank",
    "fct_fiscal_mensal",
    "fct_taylor_mensal",
    "fct_fundos_pl_consolidado_mensal",
]
DASH_TITLE = "Economia Brasileira"
DASH_SLUG = "visao-geral"  # stable URL — title is the friendly name

# Dashboard CSS (UX): two concerns, both about visual hierarchy on the dark theme.
# 1) Tab bar reads as a real navigation surface (dark-gray bar, bold light labels,
#    clear active state) instead of a faint line of teal text lost mid-page.
# 2) Each chart reads as an elevated card. The default holder is #141414 on a pure
#    black page with no border/shadow, so charts blend together — separation comes
#    from LIGHTENING the surface (#1b1f27) + a subtle border + shadow, not darkening.
DASHBOARD_CSS = """
/* === Barra de abas (secoes) — destaque de navegacao === */
.dashboard-component-tabs .ant-tabs-nav {
  background-color: #262b35;
  border: 1px solid #363c49;
  border-radius: 10px;
  padding: 4px 10px;
  margin: 6px 0 18px 0;
}
.dashboard-component-tabs .ant-tabs-nav::before { border-bottom: none !important; }
.dashboard-component-tabs .ant-tabs-tab {
  padding: 8px 16px !important;
  margin: 0 2px !important;
  border-radius: 8px;
  transition: background-color .15s ease;
}
.dashboard-component-tabs .ant-tabs-tab .ant-tabs-tab-btn {
  color: #c2c9d6 !important;
  font-weight: 600 !important;
  font-size: 15px !important;
  letter-spacing: .2px;
}
.dashboard-component-tabs .ant-tabs-tab:hover { background-color: rgba(255,255,255,0.06); }
.dashboard-component-tabs .ant-tabs-tab:hover .ant-tabs-tab-btn { color: #ffffff !important; }
.dashboard-component-tabs .ant-tabs-tab.ant-tabs-tab-active { background-color: rgba(45,185,204,0.16); }
.dashboard-component-tabs .ant-tabs-tab.ant-tabs-tab-active .ant-tabs-tab-btn { color: #ffffff !important; }
.dashboard-component-tabs .ant-tabs-ink-bar { background-color: #2DB9CC !important; height: 3px !important; }

/* === Separacao dos charts: cada chart como card elevado === */
.dashboard-component-chart-holder {
  background-color: #1b1f27 !important;
  border: 1px solid rgba(255,255,255,0.07) !important;
  border-radius: 10px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.45) !important;
}
""".strip()

# live data-freshness banner: the max date per source, re-queried on every load
# (a virtual dataset, so it never goes stale between deploys).
FRESHNESS_SQL = """
SELECT 'Macro · Dólar · BACEN' AS "Fonte", MAX(obs_date) AS "Atualizado até",
       '<a href="https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios" target="_blank" rel="noopener">abrir ↗</a>' AS "Link"
  FROM marts.fct_indicadores_macro
UNION ALL
SELECT 'PIX · BACEN', MAX(mes),
       '<a href="https://dadosabertos.bcb.gov.br/dataset/pix" target="_blank" rel="noopener">abrir ↗</a>'
  FROM marts.fct_pix_uf_mensal
UNION ALL
SELECT 'Fundos · CVM', MAX(mes),
       '<a href="https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/" target="_blank" rel="noopener">abrir ↗</a>'
  FROM marts.fct_fundos_pl_consolidado_mensal
UNION ALL
SELECT 'Inflação por grupo · IBGE', MAX(mes),
       '<a href="https://sidra.ibge.gov.br/tabela/7060" target="_blank" rel="noopener">abrir ↗</a>'
  FROM marts.fct_ipca_aberturas
""".strip()

# consistent series colors across every chart (UX: same concept, same color)
LABEL_COLORS = {
    "Selic meta (% a.a.)": "#2965CC",
    "IPCA 12m (%)": "#D13913",
    "Juro real (% a.a.)": "#29A634",
    "USD/BRL": "#137CBD",
    "EUR/BRL": "#7157D9",
    "Média móvel 30d": "#FF9F1C",
    "Volatilidade 30d (% a.a.)": "#DB2C6F",
    "Volume pago (R$)": "#137CBD",
    "Realizado (R$)": "#137CBD",
    "Projeção linear (R$)": "#FF9F1C",
    "Patrimônio líquido (R$)": "#29A634",
    "PL consolidado (líq. de cotas)": "#29A634",
    "PL bruto (soma CVM)": "#A2B1BF",
    "Ticket médio (R$)": "#7157D9",
    "Captação líquida (R$)": "#0F9960",
    "Selic média (% a.a.)": "#2965CC",
    "Selic efetiva (% a.a.)": "#15B0C9",
    "Meta de inflação (%)": "#666666",
    "Teto da meta (%)": "#BBBBBB",
    "Piso da meta (%)": "#BBBBBB",
    "IGP-M 12m (%)": "#A66321",
    "Dólar var. 12m (%)": "#137CBD",
    "IBC-Br var. 12m (%)": "#8F398F",
    "Exp. ano corrente (%)": "#FF9F1C",
    "Exp. ano seguinte (%)": "#7157D9",
    "Juro real ex-ante (% a.a.)": "#29A634",
    "Juro real ex-post (% a.a.)": "#137CBD",
    "Juro neutro estimado (% a.a.)": "#BBBBBB",
    "Distância da meta (pontos percentuais)": "#D13913",
    "Núcleo 12m (%)": "#15B0C9",
    "Difusão (% itens em alta)": "#7157D9",
    "Dívida bruta (% PIB)": "#29A634",
    "Resultado primário (% PIB)": "#D13913",
    "Selic praticada (% a.a.)": "#2965CC",
    "Selic Regra de Taylor (% a.a.)": "#FF9F1C",
    "Juro real ex-ante (r, %)": "#29A634",
    "Crescimento real 12m (g, %)": "#137CBD",
    "Desemprego (%)": "#7157D9",
    "Acima do CDI (%)": "#0F9960",
    "CDI 12m (%)": "#2965CC",
    # series produced by GROUP BY columns carry the data value as label
    "Índice geral": "#D13913",
    "Renda Fixa": "#2965CC",
    "Ações": "#D13913",
    "Multimercado": "#29A634",
    "Cambial": "#FF9F1C",
    "FMP-FGTS": "#7157D9",
    "Outros": "#BBBBBB",
    "Sem cadastro": "#999999",
    "Pago por PF (R$)": "#137CBD",
    "Pago por PJ (R$)": "#FF9F1C",
    "CPF (pessoa física)": "#137CBD",
    "CNPJ (pessoa jurídica)": "#FF9F1C",
    "Cotistas (posições)": "#29A634",
    "Nº de fundos/classes": "#A2B1BF",
}


def metric(column: str, agg: str = "AVG", label: str | None = None) -> dict:
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": agg,
        "label": label or column,
    }


def time_filter(subject: str, comparator: str = "No filter") -> dict:
    return {
        "clause": "WHERE",
        "expressionType": "SIMPLE",
        "operator": "TEMPORAL_RANGE",
        "subject": subject,
        "comparator": comparator,
    }


def big_number(
    col: str, sub: str, complete_months: bool = False, daily: bool = False
) -> dict:
    # Big Number WITH a monthly trendline (sparkline) + month-over-month delta.
    # The displayed value is the latest monthly bucket; compare_lag=1 shows the
    # change vs the previous month. font sizes are proportional to card height —
    # pair with a tall enough row in LAYOUT.
    # complete_months: drop the still-running current month so the MoM compares
    # the last FULLY-published month vs the prior one. Monthly indicators (IPCA
    # 12m, juro real, Selic) carry the last print forward into the running month,
    # so a naive current-vs-previous read would always show zero.
    # daily: bucket by DAY instead of month, so the headline is the value in
    # effect TODAY (e.g. the Selic after a mid-month Copom cut, which a monthly
    # MAX would miss). The delta then compares vs ~30 days earlier (≈ a month;
    # the SGS rate series carries a value on every calendar day).
    filters = [time_filter("obs_date")]
    if complete_months:
        filters.append(
            {
                "clause": "WHERE",
                "expressionType": "SQL",
                "sqlExpression": "obs_date < date_trunc('month', CURRENT_DATE)",
            }
        )
    return {
        "viz_type": "big_number",
        "metric": metric(col, "MAX", sub),
        "x_axis": "obs_date",
        "time_grain_sqla": "P1D" if daily else "P1M",
        "adhoc_filters": filters,
        "compare_lag": 30 if daily else 1,
        "compare_suffix": "vs mês ant.",
        "show_trend_line": True,
        "start_y_axis_at_zero": False,
        "header_font_size": 0.4,
        "subheader_font_size": 0.125,
        "subheader": sub,
        "y_axis_format": ",.2f",
        "time_format": "smart_date",
    }


def line(x: str, metrics: list, grain: str = "P1D") -> dict:
    return {
        "viz_type": "echarts_timeseries_line",
        "x_axis": x,
        "time_grain_sqla": grain,
        "metrics": metrics,
        "adhoc_filters": [time_filter(x)],
        "row_limit": 50000,
        "y_axis_format": "SMART_NUMBER",
        "rich_tooltip": True,
        "show_legend": True,
        "legendOrientation": "top",
    }


CHARTS = [
    (
        "Selic meta (% a.a.)",
        "fct_indicadores_macro",
        big_number("selic_meta", "Selic meta % a.a.", daily=True),
    ),
    (
        "IPCA 12 meses (%)",
        "fct_indicadores_macro",
        big_number("ipca_12m_ff", "IPCA acum. 12m %", complete_months=True),
    ),
    (
        "Juro real 12m (%)",
        "fct_indicadores_macro",
        big_number("juro_real_12m", "Juro real % a.a.", complete_months=True),
    ),
    (
        "Dólar (R$)",
        "fct_indicadores_macro",
        big_number("usd_brl", "USD/BRL"),
    ),
    (
        "Selic × IPCA × Juro real",
        "fct_indicadores_macro",
        line(
            "obs_date",
            [
                metric("selic_meta", "AVG", "Selic meta (% a.a.)"),
                metric("ipca_12m_ff", "AVG", "IPCA 12m (%)"),
                metric("juro_real_12m", "AVG", "Juro real (% a.a.)"),
            ],
        ),
    ),
    (
        "Câmbio — dólar e euro (R$)",
        "fct_indicadores_macro",
        line(
            "obs_date",
            [
                metric("usd_brl", "AVG", "USD/BRL"),
                metric("eur_brl", "AVG", "EUR/BRL"),
            ],
        ),
    ),
    (
        "PIX — volume pago por mês (R$)",
        "fct_pix_pessoa_mensal",
        {
            "viz_type": "echarts_timeseries_bar",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("vl_pago", "SUM", "Volume pago (R$)")],
            "adhoc_filters": [time_filter("mes")],
            "row_limit": 1000,
            "y_axis_format": "SMART_NUMBER",
            "show_legend": False,
        },
    ),
    (
        "Fundos — patrimônio líquido da indústria (consolidado)",
        "fct_fundos_pl_consolidado_mensal",
        line(
            "mes",
            [
                metric("pl_consolidado", "MAX", "PL consolidado (líq. de cotas)"),
                metric("pl_bruto", "MAX", "PL bruto (soma CVM)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "Dólar — à vista × média móvel 30d",
        "fct_indicadores_macro",
        line(
            "obs_date",
            [
                metric("usd_brl", "AVG", "USD/BRL"),
                metric("usd_mm30", "AVG", "Média móvel 30d"),
            ],
        ),
    ),
    (
        "Dólar — volatilidade 30d anualizada",
        "fct_indicadores_macro",
        line(
            "obs_date", [metric("usd_vol_30d_aa", "AVG", "Volatilidade 30d (% a.a.)")]
        ),
    ),
    (
        "PIX — realizado × projeção linear (6 meses)",
        "fct_pix_projecao",
        line(
            "mes",
            [
                metric("vl_realizado", "SUM", "Realizado (R$)"),
                metric("vl_projetado", "SUM", "Projeção linear (R$)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "PIX — ticket médio nacional (R$)",
        "fct_pix_pessoa_mensal",
        line(
            "mes",
            [
                {
                    "expressionType": "SQL",
                    "sqlExpression": "SUM(vl_pago) / NULLIF(SUM(qt_pago), 0)",
                    "label": "Ticket médio (R$)",
                }
            ],
            grain="P1M",
        ),
    ),
    (
        "PIX — volume por região",
        "fct_pix_pessoa_mensal",
        {
            "viz_type": "echarts_timeseries_bar",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("vl_pago", "SUM", "Volume (R$)")],
            "groupby": ["regiao"],
            "stack": True,
            "adhoc_filters": [time_filter("mes")],
            "row_limit": 10000,
            "y_axis_format": "SMART_NUMBER",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "Fundos — captação líquida × Selic",
        "fct_fundos_selic_mensal",
        {
            # cross-source: CVM flows (bars, left axis) vs Selic (line, right)
            "viz_type": "mixed_timeseries",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("captacao_liquida", "SUM", "Captação líquida (R$)")],
            "seriesType": "bar",
            "metrics_b": [metric("selic_media", "AVG", "Selic média (% a.a.)")],
            "seriesTypeB": "line",
            "yAxisIndex": 0,
            "yAxisIndexB": 1,
            "adhoc_filters": [time_filter("mes")],
            "adhoc_filters_b": [time_filter("mes")],
            "row_limit": 1000,
            "row_limit_b": 1000,
            "y_axis_format": "SMART_NUMBER",
            "y_axis_format_secondary": ",.2f",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "IPCA 12m × meta de inflação",
        "fct_inflacao_drivers_mensal",
        line(
            "mes",
            [
                metric("ipca_12m", "MAX", "IPCA 12m (%)"),
                metric("meta_inflacao", "MAX", "Meta de inflação (%)"),
                metric("meta_teto", "MAX", "Teto da meta (%)"),
                metric("meta_piso", "MAX", "Piso da meta (%)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "O que move a inflação? (variação 12 meses)",
        "fct_inflacao_drivers_mensal",
        line(
            "mes",
            [
                metric("ipca_12m", "MAX", "IPCA 12m (%)"),
                metric("igpm_12m", "MAX", "IGP-M 12m (%)"),
                metric("usd_var_12m", "MAX", "Dólar var. 12m (%)"),
                metric("ibcbr_var_12m", "MAX", "IBC-Br var. 12m (%)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "IPCA — decomposição por grupo (12m)",
        "fct_ipca_aberturas",
        {
            **line("mes", [metric("var_12m", "MAX", "Variação 12m (%)")], grain="P1M"),
            "groupby": ["grupo"],
            # headline + the 5 heavyweight groups; 10 lines would be noise
            "adhoc_filters": [
                time_filter("mes"),
                {
                    "clause": "WHERE",
                    "expressionType": "SQL",
                    "sqlExpression": "destaque",
                },
            ],
        },
    ),
    (
        "Focus — IPCA esperado × realizado × meta",
        "fct_focus_ipca_mensal",
        line(
            "mes",
            [
                metric("exp_ano_corrente", "MAX", "Exp. ano corrente (%)"),
                metric("exp_ano_seguinte", "MAX", "Exp. ano seguinte (%)"),
                metric("ipca_12m", "MAX", "IPCA 12m (%)"),
                metric("meta", "MAX", "Meta de inflação (%)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "Fundos — captação líquida por classe",
        "fct_fundos_classe_mensal",
        {
            "viz_type": "echarts_timeseries_bar",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("captacao_liquida", "SUM", "Captação líquida (R$)")],
            "groupby": ["classe"],
            "stack": True,
            "adhoc_filters": [time_filter("mes")],
            "row_limit": 10000,
            "y_axis_format": "SMART_NUMBER",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "Fundos — % que supera o CDI (12 meses)",
        "fct_fundos_vs_cdi",
        line(
            "mes",
            [
                metric("pct_acima_cdi", "MAX", "Acima do CDI (%)"),
                metric("cdi_12m_pct", "MAX", "CDI 12m (%)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "PIX — per capita por UF (último mês)",
        "fct_pix_per_capita_rank",
        {
            "viz_type": "table",
            "query_mode": "aggregate",
            "groupby": ["Estado", "Região"],
            "metrics": [
                # SUM over the CPF/CNPJ rows = total per capita (both divide by
                # the same population); the filter narrows it to one type. Ticket
                # must be recomputed (a ratio can't be summed); population is the
                # same on both rows, so MAX is correct.
                metric("vl_pago_per_capita", "SUM", "PIX pago per capita (R$)"),
                {
                    "expressionType": "SQL",
                    "sqlExpression": "SUM(vl_pago) / NULLIF(SUM(qt_pago), 0)",
                    "label": "Ticket médio (R$)",
                },
                metric("populacao", "MAX", "População (IBGE)"),
            ],
            "timeseries_limit_metric": metric(
                "vl_pago_per_capita", "SUM", "PIX pago per capita (R$)"
            ),
            "order_desc": True,
            "row_limit": 30,
            "page_length": 30,
            "adhoc_filters": [],
        },
    ),
    (
        "Juro real — ex-ante × ex-post",
        "fct_focus_ipca_mensal",
        line(
            "mes",
            [
                metric("juro_real_ex_ante", "MAX", "Juro real ex-ante (% a.a.)"),
                metric("juro_real_ex_post", "MAX", "Juro real ex-post (% a.a.)"),
                metric("juro_neutro", "MAX", "Juro neutro estimado (% a.a.)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "Expectativas — desancoragem (Focus ano seguinte − meta)",
        "fct_focus_ipca_mensal",
        {
            "viz_type": "echarts_timeseries_bar",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [
                metric("desancoragem", "MAX", "Distância da meta (pontos percentuais)")
            ],
            "adhoc_filters": [time_filter("mes")],
            "row_limit": 1000,
            "y_axis_format": ",.2f",
            "show_legend": False,
        },
    ),
    (
        "IPCA cheio × núcleo × difusão",
        "fct_inflacao_drivers_mensal",
        {
            # core vs headline (lines, left axis) and the diffusion index
            # (% of items rising, right axis) — spread vs shock
            "viz_type": "mixed_timeseries",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [
                metric("ipca_12m", "MAX", "IPCA 12m (%)"),
                metric("nucleo_12m", "MAX", "Núcleo 12m (%)"),
            ],
            "seriesType": "line",
            "metrics_b": [metric("difusao", "MAX", "Difusão (% itens em alta)")],
            "seriesTypeB": "line",
            "yAxisIndex": 0,
            "yAxisIndexB": 1,
            "adhoc_filters": [time_filter("mes")],
            "adhoc_filters_b": [time_filter("mes")],
            "row_limit": 1000,
            "row_limit_b": 1000,
            "y_axis_format": ",.2f",
            "y_axis_format_secondary": ",.0f",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "Fiscal — dívida bruta × resultado primário (% PIB)",
        "fct_fiscal_mensal",
        {
            "viz_type": "mixed_timeseries",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("divida_bruta_pib", "MAX", "Dívida bruta (% PIB)")],
            "seriesType": "line",
            "metrics_b": [
                metric("resultado_primario_pib", "MAX", "Resultado primário (% PIB)")
            ],
            "seriesTypeB": "bar",
            "yAxisIndex": 0,
            "yAxisIndexB": 1,
            "adhoc_filters": [time_filter("mes")],
            "adhoc_filters_b": [time_filter("mes")],
            "row_limit": 1000,
            "row_limit_b": 1000,
            "y_axis_format": ",.1f",
            "y_axis_format_secondary": ",.2f",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "PIX per capita — mapa do Brasil (último mês)",
        "fct_pix_per_capita_rank",
        {
            # choropleth keyed on ISO 3166-2 ("BR-SP"), derived in the mart
            "viz_type": "country_map",
            "select_country": "brazil",
            "entity": "uf_iso",
            # SUM over the CPF/CNPJ rows = total per capita; filter narrows it
            "metric": metric("vl_pago_per_capita", "SUM", "PIX pago per capita (R$)"),
            "adhoc_filters": [],
            "linear_color_scheme": "blue_white_yellow",
            "number_format": ",.0f",
        },
    ),
    (
        "Regra de Taylor — Selic sugerida × praticada",
        "fct_taylor_mensal",
        line(
            "mes",
            [
                metric("selic", "MAX", "Selic praticada (% a.a.)"),
                metric("selic_taylor", "MAX", "Selic Regra de Taylor (% a.a.)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "Dinâmica da dívida — r × g",
        "fct_taylor_mensal",
        line(
            "mes",
            [
                metric("juro_real_ex_ante", "MAX", "Juro real ex-ante (r, %)"),
                metric("crescimento_12m", "MAX", "Crescimento real 12m (g, %)"),
            ],
            grain="P1M",
        ),
    ),
    (
        "Curva de Phillips — desemprego × inflação",
        "fct_inflacao_drivers_mensal",
        {
            "viz_type": "mixed_timeseries",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("ipca_12m", "MAX", "IPCA 12m (%)")],
            "seriesType": "line",
            "metrics_b": [metric("desemprego", "MAX", "Desemprego (%)")],
            "seriesTypeB": "line",
            "yAxisIndex": 0,
            "yAxisIndexB": 1,
            "adhoc_filters": [time_filter("mes")],
            "adhoc_filters_b": [time_filter("mes")],
            "row_limit": 1000,
            "row_limit_b": 1000,
            "y_axis_format": ",.2f",
            "y_axis_format_secondary": ",.1f",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "PIX — pessoas físicas × jurídicas (volume pago)",
        "fct_pix_pessoa_mensal",
        {
            "viz_type": "echarts_timeseries_bar",
            "x_axis": "mes",
            "time_grain_sqla": "P1M",
            "metrics": [metric("vl_pago", "SUM", "Volume pago (R$)")],
            "groupby": ["tipo_pessoa"],
            "stack": True,
            "adhoc_filters": [time_filter("mes")],
            "row_limit": 1000,
            "y_axis_format": "SMART_NUMBER",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "Fundos — cotistas × nº de fundos (indústria)",
        "fct_fundos_diario",
        {
            # participation of the industry: total investor positions (line, left)
            # and the number of funds/classes (line, right) — both from the daily
            # CVM report, aggregated to month-end
            "viz_type": "mixed_timeseries",
            "x_axis": "dt_comptc",
            "time_grain_sqla": "P1M",
            "metrics": [metric("cotistas", "MAX", "Cotistas (posições)")],
            "seriesType": "line",
            "metrics_b": [metric("n_fundos", "MAX", "Nº de fundos/classes")],
            "seriesTypeB": "line",
            "yAxisIndex": 0,
            "yAxisIndexB": 1,
            "adhoc_filters": [time_filter("dt_comptc")],
            "adhoc_filters_b": [time_filter("dt_comptc")],
            "row_limit": 5000,
            "row_limit_b": 5000,
            # full integer (e.g. 21,345,678) instead of SMART_NUMBER's "21M",
            # which rounded away the month-to-month variation the user wants to see
            "y_axis_format": ",d",
            "y_axis_format_secondary": ",.0f",
            "rich_tooltip": True,
            "show_legend": True,
            "legendOrientation": "top",
        },
    ),
    (
        "🔗 Origem dos dados",
        "vw_freshness",
        {
            "viz_type": "table",
            "query_mode": "raw",
            "all_columns": ["Fonte", "Atualizado até", "Link"],
            "column_config": {
                "Atualizado até": {"d3TimeFormat": "%d/%m/%Y"},
            },
            "allow_render_html": True,
            "adhoc_filters": [],
            "row_limit": 20,
            "page_length": 0,
            "include_search": False,
            "show_cell_bars": False,
        },
    ),
    (
        # robust companion to "% supera o CDI": the share broken down BY CLASS,
        # so you see WHICH KINDS of funds outperform (immune to single-fund noise)
        "Fundos — % que supera o CDI por classe (12 meses)",
        "fct_fundos_cdi_classe_mensal",
        {
            **line(
                "mes", [metric("pct_acima_cdi", "MAX", "Acima do CDI (%)")], grain="P1M"
            ),
            "groupby": ["classe"],
            "y_axis_format": ",.0f",
        },
    ),
    (
        # every accessible fund beating the CDI, ranked by the margin (paginated)
        "Fundos — quais superam o CDI (12 meses)",
        "fct_fundos_top_cdi",
        {
            "viz_type": "table",
            "query_mode": "raw",
            "all_columns": [
                "Fundo",
                "CNPJ",
                "Classe",
                "Cotistas",
                "Rendimento 12 meses (%)",
                "CDI 12 meses (%)",
                "Acima do CDI (p.p.)",
            ],
            "order_by_cols": ['["Acima do CDI (p.p.)", false]'],
            "column_config": {
                "Cotistas": {"d3NumberFormat": ",d"},
                "Rendimento 12 meses (%)": {"d3NumberFormat": ",.1f"},
                "CDI 12 meses (%)": {"d3NumberFormat": ",.1f"},
                "Acima do CDI (p.p.)": {"d3NumberFormat": ",.1f"},
            },
            "adhoc_filters": [],
            # show ALL accessible funds (paginated 20/page) — high limit so the
            # query never hits it (no "row limit reached" warning)
            "row_limit": 2000,
            "page_length": 20,
            "include_search": True,
            "show_cell_bars": True,
        },
    ),
]

# declarative removals: charts dropped from CHARTS are deleted on next run
REMOVED_CHARTS = [
    "Selic — meta × efetiva (mês a mês)",  # redundant: both lines overlap
    # replaced by the CDA-deduplicated consolidated PL (gross daily sum
    # double-counted fund-of-funds, overstating the industry by ~R$2 tri)
    "Fundos — patrimônio líquido total (R$)",
]

# dashboard narrative: markdown section headers + chart rows
# ("md", text) renders a header; ("row", [(chart idx, width, height), ...])
LAYOUT = [
    ("row", [(0, 3, 30), (1, 3, 30), (2, 3, 30), (3, 3, 30)]),
    ("row", [(31, 12, 30)]),
    (
        "md",
        "## 📈 Juros & Inflação\n"
        "O coração da economia: o Banco Central sobe a **Selic** (o juro "
        "básico) quando a inflação (**IPCA**) ameaça furar a **meta** do "
        "governo. O **juro real** é o que sobra desse juro depois de "
        "descontar a inflação — a verdadeira medida de quanto o crédito "
        "está apertado. Aqui também o que move cada ciclo: preços no atacado "
        "(IGP-M), câmbio e atividade; o que o mercado **espera** de inflação "
        "(pesquisa Focus); o **núcleo** (inflação sem os itens que mais "
        "oscilam, para ver a tendência); e a **desancoragem** — quando o "
        "mercado deixa de acreditar na meta.",
    ),
    ("row", [(4, 12, 42)]),
    ("row", [(21, 6, 40), (22, 6, 40)]),
    ("row", [(14, 6, 40), (17, 6, 40)]),
    ("row", [(15, 12, 40)]),
    ("row", [(16, 6, 40), (23, 6, 40)]),
    (
        "md",
        "## 🏛️ Fiscal\n"
        "A saúde das contas do governo — o pano de fundo de todo juro no "
        "Brasil. A **dívida bruta** (quanto o governo deve, em % do PIB) e o "
        "**resultado primário** dos últimos 12 meses (se o governo gasta "
        "menos do que arrecada; abaixo de zero = déficit, gastou mais). "
        "Dívida alta somada a déficit faz o país pagar mais caro para se "
        "financiar — e isso mantém os juros lá em cima.",
    ),
    ("row", [(24, 12, 40)]),
    (
        "md",
        "## 🎓 Economia aplicada\n"
        "Três modelos clássicos da teoria econômica aplicados ao Brasil de "
        "hoje. A **Regra de Taylor** estima qual Selic 'faria sentido' dada "
        "a inflação esperada e o ritmo da economia — uma régua para julgar "
        "se o juro está alto ou baixo. O **r × g** compara o juro real (r) "
        "com o crescimento da economia (g): com a dívida perto de 80% do "
        "PIB, juro acima do crescimento faz a dívida crescer sozinha, e só "
        "um governo que gasta menos do que arrecada a estanca. A **Curva de "
        "Phillips** mostra a velha gangorra entre desemprego e inflação — "
        "hoje desemprego na mínima e inflação acima da meta, sinal de uma "
        "economia girando a todo vapor.",
    ),
    ("row", [(26, 12, 40)]),
    ("row", [(27, 6, 40), (28, 6, 40)]),
    (
        "md",
        "## 💱 Câmbio\n"
        "O dólar sob três ângulos: o **nível** (quanto custa hoje), a "
        "**tendência** (a média dos últimos 30 dias, que filtra o ruído do "
        "dia a dia) e o **risco** (o quanto a cotação balança — quanto mais "
        "balança, mais imprevisível).",
    ),
    ("row", [(5, 12, 50)]),
    ("row", [(8, 12, 50)]),
    ("row", [(9, 12, 36)]),
    (
        "md",
        "## ⚡ PIX\n"
        "O pagamento instantâneo que virou rotina no Brasil. Quanto circula "
        "por mês no país, uma **projeção** simples dos próximos 6 meses, o "
        "**valor médio** de cada transação, como se divide entre as regiões "
        "e quanto cada habitante movimenta **por estado** (usando a "
        "população do IBGE).",
    ),
    ("row", [(6, 6, 38), (10, 6, 38)]),
    ("row", [(11, 6, 38), (12, 6, 38)]),
    ("row", [(25, 6, 50), (20, 6, 50)]),
    ("row", [(29, 12, 40)]),
    (
        "md",
        "## 🏦 Fundos de investimento\n"
        "Onde o brasileiro investe. O **tamanho** da indústria de fundos é "
        "medido 'limpo': como um fundo pode investir em outro, o mesmo "
        "dinheiro apareceria duas vezes — descontamos isso (carteira CDA da "
        "CVM) e chegamos a ~R$10–11 tri, o número comparável ao da ANBIMA. "
        "As barras mostram o **fluxo** do mês: dinheiro que entrou menos o "
        "que saiu — **acima de zero entrou**, **abaixo de zero saiu** "
        "(comum quando o juro cai e na época do Imposto de Renda). Os fluxos "
        "abrem **por tipo de fundo**, e a régua final: quantos fundos "
        "**superaram o CDI** (a referência da renda fixa) em 12 meses.",
    ),
    ("row", [(7, 6, 38), (13, 6, 38)]),
    ("row", [(18, 6, 38), (19, 6, 38)]),
    # the two CDI views: which CLASSES beat it, then which named FUNDS beat it
    ("row", [(32, 12, 40)]),
    ("row", [(33, 12, 58)]),
    ("row", [(30, 12, 40)]),
]


def build_native_filters(datasets: dict) -> list[dict]:
    """Interactive dashboard filters: a global time range plus a PIX region
    selector. The time filter applies to every time-series chart; the region
    filter auto-applies only to charts whose dataset carries `regiao`.
    """
    filters = [
        {
            "id": "NATIVE_FILTER-periodo",
            "name": "Período",
            "filterType": "filter_time",
            "type": "NATIVE_FILTER",
            "targets": [{}],
            "controlValues": {},
            "defaultDataMask": {"filterState": {}},
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        }
    ]
    pix = datasets.get("fct_pix_uf_mensal")
    if pix is not None:
        filters.append(
            {
                "id": "NATIVE_FILTER-regiao",
                "name": "Região (PIX)",
                "filterType": "filter_select",
                "type": "NATIVE_FILTER",
                "targets": [{"datasetId": pix.id, "column": {"name": "regiao"}}],
                "controlValues": {
                    "multiSelect": True,
                    "enableEmptyFilter": False,
                    "inverseSelection": False,
                    "searchAllOptions": False,
                    "defaultToFirstItem": False,
                },
                "defaultDataMask": {"filterState": {}},
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            }
        )
    pessoa = datasets.get("fct_pix_pessoa_mensal")
    if pessoa is not None:
        filters.append(
            {
                "id": "NATIVE_FILTER-tipopessoa",
                "name": "Pessoa · PIX (CPF/CNPJ)",
                "filterType": "filter_select",
                "type": "NATIVE_FILTER",
                "targets": [
                    {"datasetId": pessoa.id, "column": {"name": "tipo_pessoa"}}
                ],
                "controlValues": {
                    "multiSelect": True,
                    "enableEmptyFilter": False,
                    "inverseSelection": False,
                    "searchAllOptions": False,
                    "defaultToFirstItem": False,
                },
                "defaultDataMask": {"filterState": {}},
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            }
        )
    return filters


# one-line caption rendered under each chart (key = index in CHARTS) explaining
# the series and the data in plain language
CAPTIONS = {
    0: "Taxa básica de juros em vigor hoje (Selic), definida pelo Banco Central; é a referência de todo o crédito. O selo varia vs um mês atrás. Fonte: BACEN.",
    1: "Inflação oficial: quanto os preços subiram nos últimos 12 meses. O selo varia vs o mês anterior. Fonte: IBGE.",
    2: "O juro que sobra depois de descontar a inflação — o ganho 'de verdade' (Selic menos IPCA de 12 meses). Fonte: BACEN/IBGE.",
    3: "Quanto custa um dólar em reais (cotação oficial PTAX). O selo varia vs o mês anterior. Fonte: BACEN.",
    4: "Três linhas: a Selic, a inflação (IPCA 12m) e o juro real — a diferença entre as duas. Fonte: BACEN/IBGE.",
    5: "Quantos reais valem um dólar (USD/BRL) e um euro (EUR/BRL) ao longo do tempo. Fonte: BACEN (PTAX).",
    6: "Quanto dinheiro circulou por PIX a cada mês, em reais. Fonte: BACEN.",
    7: "Tamanho da indústria de fundos: o valor 'limpo' (sem contar o mesmo dinheiro duas vezes) vs o valor bruto somado. Fonte: CVM.",
    8: "Cotação diária do dólar vs sua média dos últimos 30 dias — a média revela a tendência por trás do sobe-e-desce. Fonte: BACEN.",
    9: "O quanto o dólar 'balança' (volatilidade): quanto maior, mais imprevisível e arriscado está o câmbio. Fonte: BACEN.",
    10: "Volume de PIX já realizado (azul) e uma projeção simples para os próximos 6 meses (laranja). Fonte: BACEN.",
    11: "Valor médio de cada PIX — o total pago dividido pelo número de transações. Fonte: BACEN.",
    12: "Volume pago por PIX a cada mês, empilhado pelas cinco regiões do país. Fonte: BACEN.",
    13: "Barras: dinheiro que entrou menos o que saiu dos fundos no mês; linha: a Selic média. Fonte: CVM e BACEN.",
    14: "A inflação (IPCA 12m, vermelho) comparada à meta do governo e às suas margens de teto e piso. Fonte: IBGE e BACEN.",
    15: "A inflação ao lado do que costuma puxá-la: preços no atacado (IGP-M), dólar e atividade econômica. Fonte: IBGE, FGV e BACEN.",
    16: "A inflação de 12 meses dividida pelos principais tipos de gasto (alimentação, transporte, moradia…). Fonte: IBGE.",
    17: "O que o mercado financeiro espera de inflação (pesquisa Focus do BC) vs a meta e o que de fato ocorreu. Fonte: BACEN (Focus).",
    18: "Dinheiro que entrou menos o que saiu dos fundos a cada mês, separado por tipo de fundo. Fonte: CVM.",
    19: "Que fração dos fundos rendeu mais que o CDI (referência da renda fixa) nos últimos 12 meses. Fonte: CVM.",
    20: "Estados ordenados por quanto cada habitante movimenta em PIX, com o valor médio e a população. Fonte: BACEN e IBGE.",
    21: "Três formas de medir o juro descontada a inflação: contra a esperada, contra a ocorrida e o juro de equilíbrio. Fonte: BACEN.",
    22: "O quanto a inflação esperada pelo mercado se afasta da meta — termômetro da confiança no Banco Central. Fonte: BACEN (Focus).",
    23: "Inflação cheia vs o 'núcleo' (sem os itens que mais oscilam) e o % de produtos com preço em alta. Fonte: IBGE e BACEN.",
    24: "A dívida do governo (% do PIB, linha) e se as contas do ano fecham no azul ou no vermelho (barras). Fonte: BACEN.",
    25: "Mapa do Brasil colorido por quanto cada habitante movimenta em PIX, estado a estado. Fonte: BACEN e IBGE.",
    26: "A Selic praticada vs a que um modelo econômico clássico (a Regra de Taylor) recomendaria. Fonte: BACEN/IBGE.",
    27: "Juro real (r) vs crescimento da economia (g): se o juro supera o crescimento e a dívida é alta, ela cresce sozinha. Fonte: BACEN/IBGE.",
    28: "A relação entre desemprego e inflação: quando o desemprego cai demais, a inflação tende a subir. Fonte: IBGE.",
    29: "Volume pago por PIX a cada mês, separando pessoas (CPF) de empresas (CNPJ). Fonte: BACEN.",
    30: "Número de investidores (linha) vs a quantidade de fundos disponíveis no mercado. Fonte: CVM.",
    31: "Quando cada fonte foi atualizada pela última vez e o link para os dados originais (BACEN, CVM, IBGE).",
    32: "Dos fundos de cada tipo (Ações, Multimercado, Renda Fixa…), que fração rendeu mais que o CDI em 12 meses. Fonte: CVM e BACEN.",
    33: "Todos os fundos acessíveis (ao menos 100 cotistas e R$10 mi de patrimônio — exclui veículos exclusivos de 1 investidor) que superaram o CDI no último ano, ordenados pela vantagem (use a busca e as páginas). 'Rendimento 12 meses' = quanto o fundo rendeu; 'CDI 12 meses' = a renda fixa de referência no mesmo período; 'Acima do CDI' = a diferença, em pontos percentuais (p.p.). Fonte: CVM e BACEN.",
}


def _md_height(text: str) -> int:
    # markdown blocks CLIP/rolam em modo de visualização → dimensionar p/ caber
    # SEM sobrar muito e SEM gerar barra de rolagem. Calibrado medindo o render:
    # 1 unidade da grade ≈ 8px; ~120 chars/linha em largura cheia; +5 cobre o
    # título (## maior) e o padding interno.
    lines = len(text) // 120 + text.count("\n") + 1
    return max(13, lines * 3 + 5)


def _cap_height(text: str, width: int) -> int:
    # a legenda ocupa width/12 da página → coluna mais estreita quebra mais linhas.
    # Calibrado pelo render (1u≈8px): 1 linha≈8u, 2≈11u, 4≈17u → linhas*3 + 5,
    # com ~14 chars por unidade de largura (≈42 numa coluna de 1/4).
    per_line = max(1, width * 14)
    return max(8, (len(text) // per_line + 1) * 3 + 5)


def build_position(chart_ids: dict[int, int], chart_uuids: dict[int, str]) -> dict:
    # Tabbed layout: rows that appear BEFORE the first markdown section (the KPI
    # cards) stay pinned at the top, always visible; each "## ..." markdown opens
    # a new TAB whose label is that header and whose first cell is the section's
    # explanatory text, followed by its chart rows.
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "id": "HEADER_ID",
            "type": "HEADER",
            "meta": {"text": DASH_TITLE},
        },
    }
    tabs_id = "TABS-main"

    def make_row(r: int, content: list, ancestry: list[str]) -> list[str]:
        cells = [cell for cell in content if cell[0] in chart_ids]
        if not cells:
            return []
        row_id = f"ROW-{r}"
        pos[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ancestry,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for idx, width, height in cells:
            cid = f"CHART-{chart_ids[idx]}"
            pos[row_id]["children"].append(cid)
            pos[cid] = {
                "type": "CHART",
                "id": cid,
                "children": [],
                "parents": ancestry + [row_id],
                "meta": {
                    "chartId": chart_ids[idx],
                    "sliceName": CHARTS[idx][0],
                    "width": width,
                    "height": height,
                    # the slice's REAL uuid — Superset reconciles layout<->slices
                    # by uuid; a random one makes it think the slices aren't placed
                    # and append a duplicate flat set (see the doubled-layout bug).
                    "uuid": chart_uuids[idx],
                },
            }
        rows = [row_id]
        # a one-line caption row directly beneath, columns aligned to the charts
        cap_cells = [(idx, w) for idx, w, _ in cells if CAPTIONS.get(idx)]
        if cap_cells:
            cap_row_id = f"ROWCAP-{r}"
            pos[cap_row_id] = {
                "type": "ROW",
                "id": cap_row_id,
                "children": [],
                "parents": ancestry,
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            # one uniform height for the whole caption row (the tallest cell) so
            # side-by-side caption cards line up instead of varying with text len
            cap_h = max(_cap_height(CAPTIONS[idx], w) for idx, w in cap_cells)
            for idx, width in cap_cells:
                mid = f"CAPTION-{chart_ids[idx]}"
                pos[cap_row_id]["children"].append(mid)
                pos[mid] = {
                    "type": "MARKDOWN",
                    "id": mid,
                    "children": [],
                    "parents": ancestry + [cap_row_id],
                    "meta": {
                        "width": width,
                        "height": cap_h,
                        "code": CAPTIONS[idx],
                    },
                }
            rows.append(cap_row_id)
        return rows

    tab_ids: list[str] = []
    current_tab: tuple[str, list[str]] | None = None  # None = pre-tabs (top) region
    for r, (kind, content) in enumerate(LAYOUT):
        if kind == "md":
            if tabs_id not in pos:  # create the TABS container on the first section
                pos["GRID_ID"]["children"].append(tabs_id)
                pos[tabs_id] = {
                    "type": "TABS",
                    "id": tabs_id,
                    "children": tab_ids,
                    "parents": ["ROOT_ID", "GRID_ID"],
                    "meta": {},
                }
            tab_id = f"TAB-{r}"
            tab_ids.append(tab_id)
            label = content.split("\n", 1)[0].replace("## ", "").strip()
            tab_anc = ["ROOT_ID", "GRID_ID", tabs_id, tab_id]
            md_id = f"MARKDOWN-{r}"
            pos[tab_id] = {
                "type": "TAB",
                "id": tab_id,
                "children": [md_id],
                "parents": ["ROOT_ID", "GRID_ID", tabs_id],
                "meta": {"text": label},
            }
            pos[md_id] = {
                "type": "MARKDOWN",
                "id": md_id,
                "children": [],
                "parents": tab_anc,
                "meta": {"width": 12, "height": _md_height(content), "code": content},
            }
            current_tab = (tab_id, tab_anc)
            continue
        if current_tab is None:  # KPI rows etc. — pinned above the tabs
            for rid in make_row(r, content, ["ROOT_ID", "GRID_ID"]):
                pos["GRID_ID"]["children"].append(rid)
        else:
            tab_id, tab_anc = current_tab
            for rid in make_row(r, content, tab_anc):
                pos[tab_id]["children"].append(rid)
    return pos


def main() -> None:
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from superset import db, security_manager as sm
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        admin = sm.find_user(os.environ.get("ADMIN_USERNAME", "admin"))

        # Lock the anonymous Public role down to VIEW-ONLY-DASHBOARD. The config
        # no longer sets PUBLIC_ROLE_LIKE = "Gamma" (which copied a content
        # creator's whole permission set to anonymous visitors — including
        # can_write on charts/dashboards, the Charts/Datasets/Databases menus,
        # CSV export and SQL view). Instead we derive Public deterministically
        # from Gamma MINUS a denylist of write/menu/export/introspection perms,
        # plus all_datasource_access (the warehouse holds only public government
        # data). Rebuilt on every deploy, so it survives restarts.
        public = sm.find_role("Public")
        gamma = sm.find_role("Gamma")
        all_ds = sm.find_permission_view_menu(
            "all_datasource_access", "all_datasource_access"
        )
        if public is not None and gamma is not None:
            # permission names stripped from Public (no writing, no browsing the
            # internals, no export, no SQL/query introspection)
            deny = {
                "can_write",
                "can_add",
                "can_edit",
                "can_delete",
                "can_list",
                "can_show",
                "menu_access",
                "can_export",
                "can_csv",
                "can_export_streaming_csv",
                "can_export_as_example",
                "can_tag",
                "can_tags",
                "can_bulk_create",
                "can_view_query",
                "can_put_chart_customizations",
                "can_delete_embedded",
                "can_explore",
                "can_slice",
                "can_recent_activity",
                "can_userinfo",
                "resetmypassword",
                "can_this_form_get",
                "can_this_form_post",
            }
            # ...except these, which transient dashboard state needs to work:
            keep_write_views = {
                "DashboardFilterStateRestApi",
                "DashboardPermalinkRestApi",
                "ExploreFormDataRestApi",
                "ExplorePermalinkRestApi",
            }
            keep_menu_views = {"Dashboards", "Home"}

            # M1: belt-and-suspenders against version drift — besides the explicit
            # deny set above, drop ANY permission whose name looks write-like or
            # SQL-related, so a new/renamed mutating permission introduced by a
            # future Superset upgrade is NOT auto-granted to anonymous visitors.
            # (read perms are preserved; transient-state writes survive via the
            # keep sets.) The read-only DB role from H3 is the real backstop.
            danger_prefixes = (
                "can_write",
                "can_add",
                "can_edit",
                "can_delete",
                "can_save",
                "can_import",
                "can_export",
                "can_mulexport",
                "can_bulk",
                "can_csv",
            )

            def write_like(pname: str) -> bool:
                return pname.startswith(danger_prefixes) or "sql" in pname.lower()

            target = []
            for pvm in gamma.permissions:
                pname, vname = pvm.permission.name, pvm.view_menu.name
                if pname == "can_write" and vname in keep_write_views:
                    target.append(pvm)
                    continue
                if pname == "menu_access" and vname in keep_menu_views:
                    target.append(pvm)
                    continue
                if pname in deny or write_like(pname):
                    continue
                target.append(pvm)
            if all_ds is not None and all_ds not in target:
                target.append(all_ds)
            public.permissions = target
            db.session.flush()
            print(f"role Public hardened: {len(target)} perms (view-only)")

        # H3: prefer the least-privilege read-only role when its password is
        # provided (scripts/create_superset_reader.sh provisions it in the deploy);
        # otherwise fall back to the warehouse OWNER with a loud warning so the
        # deploy never breaks while the operator wires SUPERSET_READER_PASSWORD.
        reader_pw = os.environ.get("SUPERSET_READER_PASSWORD")
        if reader_pw:
            uri = (
                "postgresql+psycopg2://superset_reader:"
                f"{reader_pw}@postgres:5432/brazil_economy"
            )
        else:
            print(
                "WARNING: SUPERSET_READER_PASSWORD unset — Superset connects as the "
                "warehouse OWNER (brazil_economy). Set it to enable the read-only "
                "role (security finding H3)."
            )
            uri = (
                "postgresql+psycopg2://brazil_economy:"
                f"{os.environ['BRAZIL_ECONOMY_DB_PASSWORD']}@postgres:5432/brazil_economy"
            )
        database = (
            db.session.query(Database).filter_by(database_name=DB_NAME).one_or_none()
        )
        if database is None:
            database = Database(database_name=DB_NAME, sqlalchemy_uri=uri)
            db.session.add(database)
        else:
            database.sqlalchemy_uri = uri  # keep the connection in sync (idempotent)
        db.session.flush()
        print(f"database id={database.id}")

        from sqlalchemy.exc import NoSuchTableError

        datasets: dict[str, SqlaTable] = {}
        for table in DATASETS:
            ds = (
                db.session.query(SqlaTable)
                .filter_by(table_name=table, schema="marts", database_id=database.id)
                .one_or_none()
            )
            created = ds is None
            if created:
                ds = SqlaTable(table_name=table, schema="marts", database=database)
                db.session.add(ds)
                db.session.flush()
            try:
                # always resync columns: mart schemas evolve (new columns must
                # reach existing datasets, or charts fail with missing columns)
                ds.fetch_metadata()
            except NoSuchTableError:
                # fresh warehouse (DAGs not run yet): skip for now —
                # the next deploy provisions it once the table exists
                print(f"dataset {table}: table not in warehouse yet, skipping")
                if created:
                    db.session.delete(ds)
                    db.session.flush()
                continue
            datasets[table] = ds
            print(f"dataset {table} id={ds.id}")

        # live freshness virtual dataset (max date per source, re-queried on load)
        fresh = (
            db.session.query(SqlaTable)
            .filter_by(table_name="vw_freshness", database_id=database.id)
            .one_or_none()
        )
        if fresh is None:
            fresh = SqlaTable(table_name="vw_freshness", database=database)
            db.session.add(fresh)
        fresh.sql = FRESHNESS_SQL
        db.session.flush()
        try:
            fresh.fetch_metadata()
            datasets["vw_freshness"] = fresh
            print(f"dataset vw_freshness id={fresh.id}")
        except Exception as exc:  # noqa: BLE001 — warehouse may be empty on first deploy
            print(f"dataset vw_freshness skipped: {exc}")

        chart_ids: dict[int, int] = {}
        chart_uuids: dict[int, str] = {}
        slices: list[Slice] = []
        for idx, (name, table, params) in enumerate(CHARTS):
            if table not in datasets:
                print(f"chart '{name}': dataset unavailable, skipping")
                continue
            ds = datasets[table]
            full_params = json.dumps({**params, "datasource": f"{ds.id}__table"})
            slc = db.session.query(Slice).filter_by(slice_name=name).one_or_none()
            if slc is None:
                slc = Slice(
                    slice_name=name,
                    datasource_type="table",
                    datasource_id=ds.id,
                    viz_type=params["viz_type"],
                    params=full_params,
                    owners=[admin] if admin else [],
                )
                db.session.add(slc)
                db.session.flush()
                action = "created"
            else:
                # declarative mode: this file is the source of truth, so
                # promoting a chart change is just running the script again
                slc.viz_type = params["viz_type"]
                slc.params = full_params
                slc.datasource_id = ds.id
                action = "updated"
            chart_ids[idx] = slc.id
            chart_uuids[idx] = str(slc.uuid)
            slices.append(slc)
            print(f"chart '{name}' id={slc.id} ({action})")

        for name in REMOVED_CHARTS:
            stale = db.session.query(Slice).filter_by(slice_name=name).one_or_none()
            if stale is not None:
                db.session.delete(stale)
                print(f"chart '{name}' deleted (declarative removal)")

        if not slices:
            db.session.commit()
            print("warehouse empty — no charts to publish; dashboard deferred")
            return

        dash = db.session.query(Dashboard).filter_by(slug=DASH_SLUG).one_or_none()
        if dash is None:
            dash = Dashboard(dashboard_title=DASH_TITLE, slug=DASH_SLUG)
            db.session.add(dash)
        dash.dashboard_title = DASH_TITLE  # declarative: renames propagate
        dash.published = True
        dash.css = DASHBOARD_CSS  # declarative UX styling (tabs + chart cards)
        dash.owners = [admin] if admin else []
        dash.slices = slices
        dash.position_json = json.dumps(build_position(chart_ids, chart_uuids))
        dash.json_metadata = json.dumps(
            {
                "refresh_frequency": 0,
                "color_scheme": "supersetColors",
                "label_colors": LABEL_COLORS,
                "expanded_slices": {},
                # filters across the TOP instead of the left rail (frees width)
                "filter_bar_orientation": "HORIZONTAL",
                "native_filter_configuration": build_native_filters(datasets),
            }
        )
        # Declarative ownership: this dashboard fully owns its charts. Any slice
        # no longer in the managed set and not attached to another dashboard is an
        # orphan — e.g. left behind by a rename, where the new name is created as a
        # fresh chart and the old one drops out of the layout. Prune it so the chart
        # list tracks the code on every env (no manual REMOVED_CHARTS bookkeeping).
        db.session.flush()
        managed = {s.id for s in slices}
        # L8: scope the prune to charts on THIS project's datasets only, so a
        # shared Superset instance never loses unrelated standalone charts.
        our_table_ids = {ds.id for ds in datasets.values()}
        for orphan in db.session.query(Slice).all():
            if (
                orphan.id not in managed
                and not orphan.dashboards
                and orphan.datasource_id in our_table_ids
            ):
                print(f"chart '{orphan.slice_name}' id={orphan.id} pruned (orphan)")
                db.session.delete(orphan)
        db.session.commit()
        print(f"dashboard id={dash.id} published -> /superset/dashboard/{DASH_SLUG}/")


if __name__ == "__main__":
    main()
