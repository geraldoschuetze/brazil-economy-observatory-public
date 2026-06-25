"""Unit tests for the pure ingestion helpers (no Airflow, no network)."""

from __future__ import annotations

import pytest

from brazil_economy import transforms


class TestMonthRange:
    def test_within_year(self):
        assert transforms.month_range(202101, 202104) == [
            202101,
            202102,
            202103,
            202104,
        ]

    def test_crosses_year_boundary(self):
        assert transforms.month_range(202011, 202102) == [
            202011,
            202012,
            202101,
            202102,
        ]

    def test_single_month(self):
        assert transforms.month_range(202601, 202601) == [202601]

    def test_empty_when_first_after_last(self):
        assert transforms.month_range(202602, 202601) == []


class TestMonthsToLoad:
    def test_missing_plus_recent_revision(self):
        # 202011/202012/202101 already loaded; 202102/202103 missing, and the
        # two most recent (202102, 202103) are always revisited
        result = transforms.months_to_load(
            202011, 202103, loaded=[202011, 202012, 202101]
        )
        assert result == [202102, 202103]

    def test_all_loaded_still_revisits_recent_two(self):
        result = transforms.months_to_load(
            202101, 202103, loaded=[202101, 202102, 202103]
        )
        assert result == [202102, 202103]

    def test_revise_recent_zero(self):
        result = transforms.months_to_load(
            202101, 202103, loaded=[202101, 202102, 202103], revise_recent=0
        )
        assert result == []

    def test_nothing_loaded_returns_full_range(self):
        result = transforms.months_to_load(202101, 202103, loaded=[])
        assert result == [202101, 202102, 202103]

    def test_result_is_sorted_and_deduplicated(self):
        result = transforms.months_to_load(202101, 202103, loaded=[202103])
        assert result == [202101, 202102, 202103]


class TestCleanFundClass:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Fundo de Renda Fixa", "Renda Fixa"),
            ("Fundo Multimercado", "Multimercado"),
            ("Fundo de Ações", "Ações"),
            ("Renda Fixa", "Renda Fixa"),  # already clean
            (None, ""),
            ("", ""),
        ],
    )
    def test_label_normalization(self, raw, expected):
        assert transforms.clean_fund_class(raw) == expected


class TestOnlyDigits:
    def test_strips_cnpj_punctuation(self):
        assert transforms.only_digits("12.345.678/0001-90") == "12345678000190"

    def test_handles_none(self):
        assert transforms.only_digits(None) == ""


class TestNormalizeCvmRow:
    def test_new_regime_layout(self):
        row = {
            "CNPJ_FUNDO_CLASSE": "11.111.111/0001-11",
            "ID_SUBCLASSE": "SUB1",
            "DT_COMPTC": "2026-01-02",
            "TP_FUNDO_CLASSE": "FIC",
            "VL_TOTAL": "100",
            "VL_QUOTA": "1.23",
            "VL_PATRIM_LIQ": "99",
            "CAPTC_DIA": "5",
            "RESG_DIA": "2",
            "NR_COTST": "10",
        }
        assert transforms.normalize_cvm_row(row) == (
            "11.111.111/0001-11",
            "SUB1",
            "2026-01-02",
            "FIC",
            "100",
            "1.23",
            "99",
            "5",
            "2",
            "10",
        )

    def test_old_regime_layout_and_empty_numerics_become_none(self):
        row = {
            "CNPJ_FUNDO": "00.000.000/0001-00",
            "DT_COMPTC": "2026-01-02",
            "TP_FUNDO": "FI",
            "VL_TOTAL": "10",
            "VL_QUOTA": "1.5",
            "VL_PATRIM_LIQ": "9",
            "CAPTC_DIA": "",
            "RESG_DIA": "",
            "NR_COTST": "3",
        }
        assert transforms.normalize_cvm_row(row) == (
            "00.000.000/0001-00",
            "",
            "2026-01-02",
            "FI",
            "10",
            "1.5",
            "9",
            None,
            None,
            "3",
        )


class TestIpcaHelpers:
    @pytest.mark.parametrize(
        "value,published",
        [("4.62", True), ("0", True), ("...", False), ("-", False), ("", False)],
    )
    def test_is_value_published(self, value, published):
        assert transforms.is_ipca_value_published(value) is published

    def test_sidra_period_to_date(self):
        assert transforms.sidra_period_to_date("202601") == "2026-01-01"
        assert transforms.sidra_period_to_date("202012") == "2020-12-01"


class TestCvmCdaValue:
    def test_dot_decimal_parsed(self):
        assert transforms.cvm_cda_value("28761441362.85") == 28761441362.85

    def test_strips_whitespace(self):
        assert transforms.cvm_cda_value("  1190486.68 ") == 1190486.68

    def test_empty_and_invalid_become_none(self):
        assert transforms.cvm_cda_value("") is None
        assert transforms.cvm_cda_value(None) is None
        assert transforms.cvm_cda_value("n/d") is None
