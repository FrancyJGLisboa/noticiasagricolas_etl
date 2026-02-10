"""Tests for indicator parser using real HTML fixture."""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.indicator import IndicatorParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def entry():
    return CatalogEntry(
        commodity="soja",
        slug="soja-indicador-cepea-esalq-porto-paranagua",
        name="Indicador da Soja ESALQ/B3 - Paranaguá",
        page_type=PageType.INDICATOR,
        unit="R$",
    )


@pytest.fixture
def parser():
    return IndicatorParser()


@pytest.fixture
def html():
    return (FIXTURE_DIR / "indicator_soja.html").read_text(encoding="utf-8")


def test_parse_returns_records(parser, html, entry):
    records = parser.parse_html(html, entry)
    assert len(records) > 0


def test_parse_has_valor_and_variacao(parser, html, entry):
    records = parser.parse_html(html, entry)
    col_names = {r.column_name for r in records}
    assert "valor" in col_names
    assert "variacao_pct" in col_names


def test_parse_10_dates(parser, html, entry):
    records = parser.parse_html(html, entry)
    dates = {r.date for r in records}
    assert len(dates) == 10  # default page returns ~10 dates


def test_first_record_value(parser, html, entry):
    records = parser.parse_html(html, entry)
    valor_records = [r for r in records if r.column_name == "valor"]
    # Most recent date should be 06/02/2026 with value 126.43
    valor_records.sort(key=lambda r: r.date, reverse=True)
    assert valor_records[0].value == 126.43
    assert valor_records[0].value_raw == "126,43"


def test_records_have_correct_metadata(parser, html, entry):
    records = parser.parse_html(html, entry)
    for r in records:
        assert r.commodity == "soja"
        assert r.indicator == "soja-indicador-cepea-esalq-porto-paranagua"
        assert r.location is None
        assert r.contract_month is None
