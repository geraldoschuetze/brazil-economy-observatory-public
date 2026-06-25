"""Pure transformation helpers shared across ingestion DAGs.

No Airflow, no network, no database — just deterministic functions over plain
Python values, so each one is trivially unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterable


def month_range(first: int, last: int) -> list[int]:
    """All YYYYMM integers from `first` to `last`, inclusive.

    >>> month_range(202011, 202102)
    [202011, 202012, 202101, 202102]
    """
    months: list[int] = []
    current = first
    while current <= last:
        months.append(current)
        year, month = divmod(current, 100)
        current = (year + 1) * 100 + 1 if month == 12 else current + 1
    return months


def months_to_load(
    first: int,
    last: int,
    loaded: Iterable[int],
    revise_recent: int = 2,
) -> list[int]:
    """Months still missing between `first` and `last`, plus the most recent
    `revise_recent` (BACEN/CVM revise recent months, so reload them).

    Pure set logic extracted from the PIX and CVM ingestion DAGs.

    >>> months_to_load(202011, 202103, loaded=[202011, 202012, 202101])
    [202102, 202103]
    >>> months_to_load(202101, 202103, loaded=[202101, 202102, 202103])
    [202102, 202103]
    """
    wanted = month_range(first, last)
    wanted_set = set(wanted)
    revisable = set(wanted[-revise_recent:]) if revise_recent else set()
    return sorted((wanted_set - set(loaded)) | revisable)


def clean_fund_class(raw: str | None) -> str:
    """Normalize a CVM fund-class label across the two registry regimes:
    'Fundo de Renda Fixa' -> 'Renda Fixa', 'Fundo Multimercado' -> 'Multimercado'.

    >>> clean_fund_class('Fundo de Renda Fixa')
    'Renda Fixa'
    >>> clean_fund_class('Fundo Multimercado')
    'Multimercado'
    >>> clean_fund_class(None)
    ''
    """
    classe = (raw or "").removeprefix("Fundo de ")
    return classe.removeprefix("Fundo ")


def only_digits(value: str | None) -> str:
    """Keep digits only — used to conform CNPJs across CVM layouts.

    >>> only_digits('12.345.678/0001-90')
    '12345678000190'
    """
    return "".join(c for c in (value or "") if c.isdigit())


# CVM ships empty strings for missing numerics and uses two different column
# layouts (pre/post the 2025 fund-class reform); map both to our schema.
_CVM_NUMERIC_FIELDS = (
    "VL_TOTAL",
    "VL_QUOTA",
    "VL_PATRIM_LIQ",
    "CAPTC_DIA",
    "RESG_DIA",
    "NR_COTST",
)


def normalize_cvm_row(row: dict) -> tuple:
    """Map a CVM informe-diário CSV row (either layout) to the warehouse tuple,
    turning empty strings into None for numeric columns.

    >>> r = {
    ...     'CNPJ_FUNDO': '00.000.000/0001-00', 'DT_COMPTC': '2026-01-02',
    ...     'TP_FUNDO': 'FI', 'VL_TOTAL': '10', 'VL_QUOTA': '1.5',
    ...     'VL_PATRIM_LIQ': '9', 'CAPTC_DIA': '', 'RESG_DIA': '',
    ...     'NR_COTST': '3',
    ... }
    >>> normalize_cvm_row(r)
    ('00.000.000/0001-00', '', '2026-01-02', 'FI', '10', '1.5', '9', None, None, '3')
    """
    return (
        row.get("CNPJ_FUNDO_CLASSE") or row.get("CNPJ_FUNDO"),
        row.get("ID_SUBCLASSE") or "",
        row["DT_COMPTC"],
        row.get("TP_FUNDO_CLASSE") or row.get("TP_FUNDO"),
        *(row[field] or None for field in _CVM_NUMERIC_FIELDS),
    )


# IPCA SIDRA marks not-yet-published / not-applicable cells with these tokens
_IPCA_MISSING = {"...", "-", ""}


def is_ipca_value_published(value: str) -> bool:
    """True when a SIDRA IPCA cell carries a real number (not a missing token).

    >>> is_ipca_value_published('4.62')
    True
    >>> is_ipca_value_published('...')
    False
    """
    return value not in _IPCA_MISSING


def sidra_period_to_date(d3c: str) -> str:
    """Convert a SIDRA D3C period code (YYYYMM) to an ISO first-of-month date.

    >>> sidra_period_to_date('202601')
    '2026-01-01'
    """
    return f"{d3c[:4]}-{d3c[4:6]}-01"


def cvm_cda_value(s: str | None) -> float | None:
    """Parse a CVM CDA monetary value.

    CDA files use a DOT decimal separator and NO thousands separator (unlike the
    daily informe, which uses a comma) — e.g. '28761441362.85'. Empty becomes None.

    >>> cvm_cda_value('28761441362.85')
    28761441362.85
    >>> cvm_cda_value('  1190486.68 ')
    1190486.68
    >>> cvm_cda_value('') is None
    True
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None
