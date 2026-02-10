"""Tests for B3 futures parser using real HTML fixture."""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.b3_futures import B3FuturesParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def entry():
    return CatalogEntry(
        commodity="soja",
        slug="soja-b3-pregao-regular",
        name="Soja CME - B3 (Pregão Regular)",
        page_type=PageType.B3_FUTURES,
        unit="US$/sc 60 kg",
    )


@pytest.fixture
def parser():
    return B3FuturesParser()


@pytest.fixture
def html():
    return (FIXTURE_DIR / "b3_soja.html").read_text(encoding="utf-8")


def test_parse_returns_records(parser, html, entry):
    records = parser.parse_html(html, entry)
    assert len(records) > 0


def test_parse_has_contract_months(parser, html, entry):
    records = parser.parse_html(html, entry)
    contracts = {r.contract_month for r in records}
    assert len(contracts) >= 1
    assert any("Julho" in c for c in contracts if c)


def test_parse_has_fechamento_and_variacao(parser, html, entry):
    records = parser.parse_html(html, entry)
    col_names = {r.column_name for r in records}
    assert "fechamento" in col_names
    assert "variacao_pct" in col_names


def test_no_location(parser, html, entry):
    records = parser.parse_html(html, entry)
    for r in records:
        assert r.location is None
