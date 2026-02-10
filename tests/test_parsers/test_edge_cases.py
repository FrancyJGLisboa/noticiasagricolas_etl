"""Tests for edge-case fixtures that cover unusual table structures.

Covers:
- Bolsas: was misclassified as indicator, uses Bolsa as first column
- Moedas: Moeda as first column, standard physical_market
- Mandioca: 4-column table with Data + Região columns
- Ovos: was misclassified, uses Região/Tipo as first column
- Leite: was misclassified, uses Estados as first column
- Banana: subheader rows with *** that must be skipped
- Feijão: all values are "s/ cotação" -> all null (graceful handling)
- Algodão: standard physical_market with Praça
- Reposição: 5-column table (Estado, Desmama, Bezerro, Garrote, Boi Magro)
- Etanol semanal: indicator with weekly data
"""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.physical_market import PhysicalMarketParser
from noticiasagricolas_etl.parsers.indicator import IndicatorParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


# ---- Helpers ----

def _load_fixture(name: str) -> str:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not found")
    return path.read_text(encoding="utf-8")


def _make_entry(commodity, slug, name, page_type, unit=""):
    return CatalogEntry(
        commodity=commodity, slug=slug, name=name,
        page_type=page_type, unit=unit,
    )


# ---- Bolsas (was indicator, now physical_market) ----

class TestBolsas:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_mercado-financeiro_bolsas.html")
        entry = _make_entry("mercado-financeiro", "bolsas", "Bolsas", PageType.PHYSICAL_MARKET, "pontos")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 60

    def test_has_locations(self, records):
        locs = {r.location for r in records}
        assert "Ibovespa" in locs

    def test_ibovespa_value_large(self, records):
        """Ibovespa should be a large number like 182,950 (thousands separator)."""
        ibov = [r for r in records if r.location == "Ibovespa" and r.column_name == "valor"]
        assert ibov
        assert ibov[0].value > 100000

    def test_has_valor_and_variacao(self, records):
        cols = {r.column_name for r in records}
        assert "valor" in cols
        assert "variacao_pct" in cols

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Moedas ----

class TestMoedas:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_mercado-financeiro_moedas.html")
        entry = _make_entry("mercado-financeiro", "moedas", "Moedas", PageType.PHYSICAL_MARKET, "R$")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 40

    def test_has_multiple_currencies(self, records):
        locs = {r.location for r in records}
        assert len(locs) >= 3

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Mandioca (4-column: Data | Região | Valor | Variação) ----

class TestMandioca:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_mandioca_precos-da-raiz-de-mandioca.html")
        entry = _make_entry("mandioca", "precos-da-raiz-de-mandioca", "Mandioca", PageType.PHYSICAL_MARKET, "R$/T")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 60

    def test_has_regions(self, records):
        locs = {r.location for r in records}
        assert len(locs) >= 4

    def test_few_nulls(self, records):
        nulls = sum(1 for r in records if r.value is None)
        # Some entries may be null but most should parse
        assert nulls / len(records) < 0.1


# ---- Ovos (was indicator, now physical_market) ----

class TestOvos:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_ovos_precos-de-ovos-cepea-produto-a-retirar-bastos.html")
        entry = _make_entry("ovos", "precos-de-ovos-cepea-produto-a-retirar-bastos", "Ovos", PageType.PHYSICAL_MARKET, "R$")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 20

    def test_has_egg_types(self, records):
        locs = {r.location for r in records}
        assert len(locs) >= 2

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Leite (was indicator, now physical_market) ----

class TestLeite:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_leite_leite-precos-ao-produtor-cepea-rs-litro.html")
        entry = _make_entry("leite", "leite-precos-ao-produtor-cepea-rs-litro", "Leite", PageType.PHYSICAL_MARKET, "R$/Litro")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 50

    def test_has_states(self, records):
        locs = {r.location for r in records}
        # Should have Brazilian states like RS, MG, PR, etc.
        assert len(locs) >= 5

    def test_few_nulls(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls / len(records) < 0.1

    def test_values_reasonable(self, records):
        """Milk prices should be in range 0.5 - 10.0 R$/Litro."""
        preco = [r for r in records if "variacao" not in r.column_name and r.value is not None]
        for r in preco:
            assert 0.5 <= r.value <= 10.0, f"Unreasonable price: {r.value} for {r.location}"


# ---- Banana (subheader rows with ***) ----

class TestBanana:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_frutas_banana-nanica-prata-ceasas.html")
        entry = _make_entry("frutas", "banana-nanica-prata-ceasas", "Banana", PageType.PHYSICAL_MARKET, "R$")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 50

    def test_no_subheader_locations(self, records):
        """Subheader rows (with *** values) should NOT appear as locations."""
        for r in records:
            assert r.value_raw.strip() not in ("***", "**", "*"), \
                f"Subheader value leaked through: {r.location} = {r.value_raw}"

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Feijão (all "s/ cotação" -> graceful null) ----

class TestFeijao:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_feijao_feijao-carioca-nota-7.html")
        entry = _make_entry("feijao", "feijao-carioca-nota-7", "Feijão", PageType.PHYSICAL_MARKET, "R$/Sc")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        """Even with all s/c values, rows should still be parsed."""
        assert len(records) >= 50

    def test_all_values_null(self, records):
        """All values should be None since all are 's/ cotação'."""
        for r in records:
            assert r.value is None, f"Expected None but got {r.value} for raw={r.value_raw!r}"

    def test_has_locations(self, records):
        locs = {r.location for r in records}
        assert len(locs) >= 4


# ---- Algodão (standard physical_market) ----

class TestAlgodao:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_algodao_algodo-em-pluma-ao-produtor.html")
        entry = _make_entry("algodao", "algodo-em-pluma-ao-produtor", "Algodão", PageType.PHYSICAL_MARKET, "R$/@")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 20

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Reposição Nelore (5-column: Estado, Desmama, Bezerro, Garrote, Boi Magro) ----

class TestReposicao:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_boi-gordo_reposicao-nelore-macho.html")
        entry = _make_entry("boi-gordo", "reposicao-nelore-macho", "Reposição", PageType.PHYSICAL_MARKET, "R$/@")
        return PhysicalMarketParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 100

    def test_has_four_data_columns(self, records):
        cols = {r.column_name for r in records}
        assert len(cols) == 4  # desmama, bezerro, garrote, boi_magro

    def test_has_states(self, records):
        locs = {r.location for r in records}
        assert len(locs) >= 5

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0


# ---- Etanol Semanal (true indicator with weekly dates) ----

class TestEtanolSemanal:
    @pytest.fixture
    def records(self):
        html = _load_fixture("edge_sucroenergetico_indicador-semanal-etanol-hidratado-cepea-esalq.html")
        entry = _make_entry("sucroenergetico", "indicador-semanal-etanol-hidratado-cepea-esalq", "Etanol", PageType.INDICATOR, "R$/Litro")
        return IndicatorParser().parse_html(html, entry)

    def test_returns_records(self, records):
        assert len(records) >= 10

    def test_no_location(self, records):
        """Indicator type should have no location."""
        for r in records:
            assert r.location is None

    def test_no_null_values(self, records):
        nulls = sum(1 for r in records if r.value is None)
        assert nulls == 0
