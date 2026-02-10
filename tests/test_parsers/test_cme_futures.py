"""Tests for CME futures parser using real HTML fixture."""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.cme_futures import CMEFuturesParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def entry():
    return CatalogEntry(
        commodity="soja",
        slug="soja-bolsa-de-chicago-cme-group",
        name="Soja - Bolsa de Chicago",
        page_type=PageType.CME_FUTURES,
        unit="US$ / Bushel",
    )


@pytest.fixture
def parser():
    return CMEFuturesParser()


@pytest.fixture
def html():
    return (FIXTURE_DIR / "cme_soja.html").read_text(encoding="utf-8")


def test_parse_returns_records(parser, html, entry):
    records = parser.parse_html(html, entry)
    assert len(records) > 0


def test_parse_has_contract_months(parser, html, entry):
    records = parser.parse_html(html, entry)
    contracts = {r.contract_month for r in records}
    assert len(contracts) >= 2
    assert any("Março" in c or "Marco" in c or "Maio" in c for c in contracts if c)


def test_parse_has_three_data_columns(parser, html, entry):
    records = parser.parse_html(html, entry)
    col_names = {r.column_name for r in records}
    assert "fechamento" in col_names
    assert "variacao_cents" in col_names
    assert "variacao_pct" in col_names


def test_fechamento_values_reasonable(parser, html, entry):
    records = parser.parse_html(html, entry)
    fechamento = [r for r in records if r.column_name == "fechamento"]
    assert all(8.0 < r.value < 20.0 for r in fechamento if r.value)
