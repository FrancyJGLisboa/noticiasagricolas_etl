"""Tests for cleaning module."""

import pytest
from datetime import date

from noticiasagricolas_etl.cleaning import (
    parse_brazilian_number,
    parse_variation,
    parse_br_date,
    parse_fechamento_date,
    slugify_column,
    extract_unit_from_header,
)


class TestParseBrazilianNumber:
    def test_simple_decimal(self):
        assert parse_brazilian_number("126,43") == 126.43

    def test_thousands_separator(self):
        assert parse_brazilian_number("1.234,56") == 1234.56

    def test_positive_sign(self):
        assert parse_brazilian_number("+0,65") == 0.65

    def test_negative_sign(self):
        assert parse_brazilian_number("-0,65") == -0.65

    def test_large_number(self):
        assert parse_brazilian_number("11.152,50") == 11152.50

    def test_four_decimal_places(self):
        assert parse_brazilian_number("11,1525") == 11.1525

    def test_integer(self):
        assert parse_brazilian_number("326") == 326.0

    def test_dash(self):
        assert parse_brazilian_number("-") is None

    def test_double_dash(self):
        assert parse_brazilian_number("--") is None

    def test_empty(self):
        assert parse_brazilian_number("") is None

    def test_sc(self):
        assert parse_brazilian_number("s/c") is None

    def test_whitespace(self):
        assert parse_brazilian_number("  126,43  ") == 126.43

    def test_zero(self):
        assert parse_brazilian_number("0,00") == 0.0


class TestParseVariation:
    def test_positive(self):
        assert parse_variation("+0,65") == 0.65

    def test_negative(self):
        assert parse_variation("-1,02") == -1.02

    def test_with_percent(self):
        assert parse_variation("+0,65%") == 0.65

    def test_zero(self):
        assert parse_variation("0,00") == 0.0

    def test_dash(self):
        assert parse_variation("-") is None


class TestParseBrDate:
    def test_valid(self):
        assert parse_br_date("06/02/2026") == date(2026, 2, 6)

    def test_invalid(self):
        assert parse_br_date("invalid") is None


class TestParseFechamentoDate:
    def test_standard(self):
        assert parse_fechamento_date("Fechamento: 06/02/2026") == date(2026, 2, 6)

    def test_no_date(self):
        assert parse_fechamento_date("No date here") is None


class TestSlugifyColumn:
    def test_valor(self):
        assert slugify_column("Valor R$") == "valor"

    def test_variacao_pct(self):
        assert slugify_column("Variação (%)") == "variacao_pct"

    def test_preco(self):
        assert slugify_column("Preço (R$/Sc de 60 kg)") == "preco"

    def test_fechamento(self):
        assert slugify_column("Fechamento (US$/sc 60 kg)") == "fechamento"

    def test_variacao_cents(self):
        assert slugify_column("Variação (cents/bu)") == "variacao_cents"

    def test_boi_gordo_vista(self):
        result = slugify_column("Boi Gordo - (R$/@ - à vista)")
        assert "boi_gordo" in result
        assert "vista" in result

    def test_boi_gordo_prazo(self):
        result = slugify_column("Boi Gordo - (R$/@ - prazo 30 dias)")
        assert "boi_gordo" in result
        assert "prazo" in result

    def test_vaca_gorda_vista(self):
        result = slugify_column("Vaca Gorda (R$/@ - à vista)")
        assert "vaca" in result
        assert "vista" in result


    # Edge case: arroba symbol
    def test_arroba_rs(self):
        assert slugify_column("R$/@") == "arroba"

    def test_arroba_us(self):
        assert slugify_column("U$/@") == "arroba"

    # Edge case: Var./Dia abbreviation
    def test_var_dia(self):
        assert slugify_column("Var./Dia (%)") == "variacao_pct"

    # Edge case: Variação (Pontos)
    def test_variacao_pontos(self):
        assert slugify_column("Variação (Pontos)") == "variacao_pontos"

    # Edge case: Variação/Semana
    def test_variacao_semana(self):
        assert slugify_column("Variação/Semana (%)") == "variacao_pct"

    # Edge case: Variação Diária
    def test_variacao_diaria(self):
        assert slugify_column("Variação Diária (%)") == "variacao_pct"


class TestParseBrazilianNumberEdgeCases:
    def test_sem_cotacao(self):
        assert parse_brazilian_number("s/ cotação") is None

    def test_sem_cot(self):
        assert parse_brazilian_number("s/ cot") is None

    def test_triple_star(self):
        assert parse_brazilian_number("***") is None

    def test_nd(self):
        assert parse_brazilian_number("n/d") is None

    def test_large_with_thousands(self):
        """182.950,00 should parse as 182950.0 (Ibovespa value)."""
        assert parse_brazilian_number("182.950,00") == 182950.0

    def test_percent_suffix(self):
        """Values like '0,45%' should strip the % and parse."""
        assert parse_brazilian_number("+0,45%") == 0.45

    def test_four_decimals(self):
        """Milk prices like 2,0098."""
        assert parse_brazilian_number("2,0098") == 2.0098


class TestExtractUnit:
    def test_preco_header(self):
        assert extract_unit_from_header("Preço (R$/Sc de 60 kg)") == "R$/Sc de 60 kg"

    def test_fechamento_header(self):
        assert extract_unit_from_header("Fechamento (US$ / Bushel)") == "US$ / Bushel"

    def test_valor_rs(self):
        assert extract_unit_from_header("Valor R$") == "R$"

    def test_no_unit(self):
        assert extract_unit_from_header("Data") == ""
