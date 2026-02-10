"""Tests for normalize.py — 7 normalization functions."""

import pytest
import pandas as pd
from datetime import date

from noticiasagricolas_etl.normalize import (
    normalize_measure,
    extract_currency,
    normalize_unit_std,
    extract_price_basis,
    normalize_contract_month,
    extract_state,
    classify_market_type,
    normalize_df,
)


# ── normalize_measure ────────────────────────────────────────────────────────


class TestNormalizeMeasure:
    def test_price_columns(self):
        for col in ("preco", "valor", "fechamento", "ultimo", "preco_medio",
                     "boi_gordo_vista", "boi_gordo_prazo", "abertura"):
            assert normalize_measure(col) == "price", f"Failed for {col}"

    def test_change_pct(self):
        for col in ("variacao_pct", "variacao", "variacao_diaria", "variacao_semana"):
            assert normalize_measure(col) == "change_pct", f"Failed for {col}"

    def test_change_abs(self):
        for col in ("variacao_cents", "variacao_pontos"):
            assert normalize_measure(col) == "change_abs", f"Failed for {col}"

    def test_rate(self):
        for col in ("taxa_efetiva", "taxa_ao_ano"):
            assert normalize_measure(col) == "rate", f"Failed for {col}"

    def test_index(self):
        for col in ("pontos", "investing", "fech_investing"):
            assert normalize_measure(col) == "index", f"Failed for {col}"

    def test_strips_whitespace(self):
        assert normalize_measure("  variacao  ") == "change_pct"


# ── extract_currency ─────────────────────────────────────────────────────────


class TestExtractCurrency:
    def test_brl(self):
        assert extract_currency("R$/Sc de 60 kg") == "BRL"
        assert extract_currency("R$/@") == "BRL"
        assert extract_currency("R$/Kg") == "BRL"
        assert extract_currency("R$/litro") == "BRL"

    def test_usd(self):
        assert extract_currency("US$/bu") == "USD"
        assert extract_currency("US$/ton") == "USD"
        assert extract_currency("¢/lb") == "USD"
        assert extract_currency("cents/lb") == "USD"
        assert extract_currency("c/lb") == "USD"

    def test_none_for_pct(self):
        assert extract_currency("%") is None

    def test_none_for_points(self):
        assert extract_currency("Pontos") is None
        assert extract_currency("pontos") is None

    def test_none_for_empty(self):
        assert extract_currency("") is None
        assert extract_currency(None) is None

    def test_none_for_8_dias(self):
        assert extract_currency("8 dias") is None


# ── normalize_unit_std ───────────────────────────────────────────────────────


class TestNormalizeUnitStd:
    def test_saca_60(self):
        assert normalize_unit_std("R$/Sc de 60 kg") == "sc60kg"
        assert normalize_unit_std("R$/saca 60 Kg") == "sc60kg"
        assert normalize_unit_std("R$/sc 60kg") == "sc60kg"

    def test_saca_50(self):
        assert normalize_unit_std("R$/Sc de 50 kg") == "sc50kg"

    def test_saca_40(self):
        assert normalize_unit_std("R$/Sc de 40 kg") == "sc40kg"

    def test_arroba(self):
        assert normalize_unit_std("R$/@") == "arroba"

    def test_ton(self):
        assert normalize_unit_std("R$/tonelada") == "ton"
        assert normalize_unit_std("US$/ton") == "ton"
        assert normalize_unit_std("US$/short ton") == "ton"

    def test_kg(self):
        assert normalize_unit_std("R$/Kg") == "kg"
        assert normalize_unit_std("R$/kg") == "kg"

    def test_litro(self):
        assert normalize_unit_std("R$/litro") == "litro"
        assert normalize_unit_std("R$/Litro") == "litro"

    def test_bushel(self):
        assert normalize_unit_std("¢/bu") == "bu"
        assert normalize_unit_std("US$/Bushel") == "bu"

    def test_lb(self):
        assert normalize_unit_std("¢/lb") == "lb"
        assert normalize_unit_std("US$/libra peso") == "lb"

    def test_points(self):
        assert normalize_unit_std("Pontos") == "points"
        assert normalize_unit_std("pontos") == "points"

    def test_pct(self):
        assert normalize_unit_std("%") == "pct"

    def test_cab(self):
        assert normalize_unit_std("R$/cab") == "cab"

    def test_gallon(self):
        assert normalize_unit_std("US$/gal") == "gal"

    def test_fx(self):
        assert normalize_unit_std("R$/US$") == "usd"
        assert normalize_unit_std("R$/€") == "eur"

    def test_empty(self):
        assert normalize_unit_std("") == ""
        assert normalize_unit_std(None) == ""

    def test_sc_without_qualifier(self):
        assert normalize_unit_std("R$/sc") == "sc60kg"

    def test_30dz(self):
        assert normalize_unit_std("R$/30 dúz") == "30dz"
        assert normalize_unit_std("R$/30 duz") == "30dz"

    def test_cx23kg(self):
        assert normalize_unit_std("R$/Cx 23 kg") == "cx23kg"
        assert normalize_unit_std("R$/cx 23 kg") == "cx23kg"

    def test_m3(self):
        assert normalize_unit_std("R$/m³") == "m3"


# ── extract_price_basis ──────────────────────────────────────────────────────


class TestExtractPriceBasis:
    def test_spot_default(self):
        assert extract_price_basis("R$/sc 60kg") == "spot"

    def test_spot_explicit(self):
        assert extract_price_basis("R$/@ à vista") == "spot"

    def test_forward(self):
        assert extract_price_basis("R$/@ a prazo") == "forward"

    def test_futures_with_contract(self):
        assert extract_price_basis("R$/@", "Julho/2025") == "futures"

    def test_futures_ignores_dirty_contract(self):
        assert extract_price_basis("R$/@", "Dólar: 5,28") == "spot"
        assert extract_price_basis("R$/@", "R$ 136,43") == "spot"

    def test_no_unit(self):
        assert extract_price_basis(None) == "spot"
        assert extract_price_basis("") == "spot"


# ── normalize_contract_month ─────────────────────────────────────────────────


class TestNormalizeContractMonth:
    def test_full_month_4digit_year(self):
        assert normalize_contract_month("Janeiro/2025") == "2025-01"
        assert normalize_contract_month("Dezembro/2024") == "2024-12"

    def test_abbrev_month_2digit_year(self):
        assert normalize_contract_month("Jan/25") == "2025-01"
        assert normalize_contract_month("Dez/24") == "2024-12"

    def test_march_with_accent(self):
        assert normalize_contract_month("Março/2025") == "2025-03"
        assert normalize_contract_month("Marco/2025") == "2025-03"

    def test_none_for_empty(self):
        assert normalize_contract_month(None) is None
        assert normalize_contract_month("") is None
        assert normalize_contract_month("  ") is None

    def test_none_for_dirty(self):
        assert normalize_contract_month("Dólar: 5,28") is None
        assert normalize_contract_month("R$ 136,43") is None
        assert normalize_contract_month("US$ 50.00") is None

    def test_none_for_unrecognized(self):
        assert normalize_contract_month("SomeGarbage") is None


# ── extract_state ────────────────────────────────────────────────────────────


class TestExtractState:
    def test_city_slash_state(self):
        assert extract_state("Alto Garças/MT (Samir Rosa)") == "MT"
        assert extract_state("Paranaguá/PR") == "PR"
        assert extract_state("Campinas/SP") == "SP"

    def test_full_state_name(self):
        assert extract_state("Bahia") == "BA"
        assert extract_state("Mato Grosso do Sul") == "MS"
        assert extract_state("Mato Grosso") == "MT"
        assert extract_state("São Paulo") == "SP"
        assert extract_state("Goiás") == "GO"

    def test_none_for_no_state(self):
        assert extract_state("Porto Paranaguá") is None
        assert extract_state("CBOT") is None

    def test_none_for_empty(self):
        assert extract_state(None) is None
        assert extract_state("") is None

    def test_rio_grande_do_sul(self):
        assert extract_state("Rio Grande do Sul") == "RS"

    def test_rio_grande_do_norte(self):
        assert extract_state("Rio Grande do Norte") == "RN"


# ── classify_market_type ─────────────────────────────────────────────────────


class TestClassifyMarketType:
    def test_b3(self):
        assert classify_market_type("milho-b3-prego-regular") == "b3"
        assert classify_market_type("soja-b3-prego-regular") == "b3"

    def test_cme(self):
        assert classify_market_type("milho-chicago-cme") == "cme"
        assert classify_market_type("soja-chicago-cbot") == "cme"

    def test_nybot(self):
        assert classify_market_type("acucar-nova-iorque") == "nybot"

    def test_liffe(self):
        assert classify_market_type("cafe-londres-liffe") == "liffe"

    def test_physical(self):
        assert classify_market_type("soja-mercado-fisico-sindicatos-e-cooperativas") == "physical"
        assert classify_market_type("milho-mercado-fisico-ceasas") == "physical"
        assert classify_market_type("frango-sp") == "physical"

    def test_indicator(self):
        assert classify_market_type("soja-indicador-cepea-esalq-porto-paranagua") == "indicator"
        assert classify_market_type("milho-indicador-cepea-esalq-campinas") == "indicator"
        assert classify_market_type("cambio-dolar-ptax") == "indicator"

    def test_other(self):
        assert classify_market_type("some-unknown-page") == "other"


# ── normalize_df (integration) ───────────────────────────────────────────────


class TestNormalizeDf:
    def _make_df(self):
        return pd.DataFrame([
            {
                "date": date(2024, 1, 2),
                "commodity": "soja",
                "indicator": "soja-indicador-cepea-esalq-porto-paranagua",
                "indicator_name": "Soja Indicador CEPEA",
                "location": "Paranaguá/PR",
                "contract_month": None,
                "column_name": "preco",
                "value": 136.43,
                "value_raw": "136,43",
                "unit": "R$/Sc de 60 kg",
            },
            {
                "date": date(2024, 1, 2),
                "commodity": "soja",
                "indicator": "soja-indicador-cepea-esalq-porto-paranagua",
                "indicator_name": "Soja Indicador CEPEA",
                "location": "Paranaguá/PR",
                "contract_month": None,
                "column_name": "variacao_pct",
                "value": 0.5,
                "value_raw": "0,50",
                "unit": "%",
            },
            {
                "date": date(2024, 1, 2),
                "commodity": "milho",
                "indicator": "milho-b3-prego-regular",
                "indicator_name": "Milho B3",
                "location": None,
                "contract_month": "Julho/2025",
                "column_name": "fechamento",
                "value": 72.50,
                "value_raw": "72,50",
                "unit": "R$/Sc de 60 kg",
            },
        ])

    def test_adds_all_7_columns(self):
        df = self._make_df()
        result = normalize_df(df)
        for col in ("measure", "currency", "unit_std", "price_basis",
                     "contract", "state", "market_type"):
            assert col in result.columns, f"Missing column: {col}"

    def test_does_not_modify_original(self):
        df = self._make_df()
        cols_before = list(df.columns)
        normalize_df(df)
        assert list(df.columns) == cols_before

    def test_measure_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["measure"] == "price"
        assert result.iloc[1]["measure"] == "change_pct"
        assert result.iloc[2]["measure"] == "price"

    def test_currency_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["currency"] == "BRL"
        assert pd.isna(result.iloc[1]["currency"])
        assert result.iloc[2]["currency"] == "BRL"

    def test_unit_std_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["unit_std"] == "sc60kg"
        assert result.iloc[1]["unit_std"] == "pct"
        assert result.iloc[2]["unit_std"] == "sc60kg"

    def test_price_basis_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["price_basis"] == "spot"
        assert result.iloc[2]["price_basis"] == "futures"

    def test_contract_values(self):
        result = normalize_df(self._make_df())
        assert pd.isna(result.iloc[0]["contract"])
        assert result.iloc[2]["contract"] == "2025-07"

    def test_state_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["state"] == "PR"
        assert pd.isna(result.iloc[2]["state"])

    def test_market_type_values(self):
        result = normalize_df(self._make_df())
        assert result.iloc[0]["market_type"] == "indicator"
        assert result.iloc[2]["market_type"] == "b3"

    def test_empty_df(self):
        df = pd.DataFrame(columns=[
            "date", "commodity", "indicator", "indicator_name", "location",
            "contract_month", "column_name", "value", "value_raw", "unit",
        ])
        result = normalize_df(df)
        assert "measure" in result.columns
        assert len(result) == 0
