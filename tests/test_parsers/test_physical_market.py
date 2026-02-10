"""Tests for physical market parser using real HTML fixture."""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.physical_market import PhysicalMarketParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def entry():
    return CatalogEntry(
        commodity="soja",
        slug="soja-mercado-fisico-sindicatos-e-cooperativas",
        name="Soja - Mercado Físico",
        page_type=PageType.PHYSICAL_MARKET,
        unit="R$/Sc de 60 kg",
    )


@pytest.fixture
def parser():
    return PhysicalMarketParser()


@pytest.fixture
def html():
    return (FIXTURE_DIR / "physical_soja.html").read_text(encoding="utf-8")


def test_parse_returns_records(parser, html, entry):
    records = parser.parse_html(html, entry)
    assert len(records) > 0


def test_parse_has_locations(parser, html, entry):
    records = parser.parse_html(html, entry)
    locations = {r.location for r in records}
    assert len(locations) > 5  # should have many locations
    # Check a known location
    assert any("Toque" in loc for loc in locations if loc)


def test_parse_has_preco_and_variacao(parser, html, entry):
    records = parser.parse_html(html, entry)
    col_names = {r.column_name for r in records}
    assert "preco" in col_names
    assert "variacao_pct" in col_names


def test_multiple_dates(parser, html, entry):
    records = parser.parse_html(html, entry)
    dates = {r.date for r in records}
    assert len(dates) >= 5  # should have multiple date-blocks
