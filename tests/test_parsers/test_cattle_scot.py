"""Tests for cattle Scot parser using real HTML fixture."""

from pathlib import Path

import pytest

from noticiasagricolas_etl.models import CatalogEntry, PageType
from noticiasagricolas_etl.parsers.cattle_scot import CattleScotParser

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def entry():
    return CatalogEntry(
        commodity="boi-gordo",
        slug="boi-gordo-scot-consultoria",
        name="Boi Gordo - Scot Consultoria",
        page_type=PageType.CATTLE_SCOT,
        unit="R$/@",
        has_date_nav=False,
    )


@pytest.fixture
def parser():
    return CattleScotParser()


@pytest.fixture
def html():
    return (FIXTURE_DIR / "cattle_scot.html").read_text(encoding="utf-8")


def test_parse_returns_records(parser, html, entry):
    records = parser.parse_html(html, entry)
    assert len(records) > 0


def test_parse_has_municipalities(parser, html, entry):
    records = parser.parse_html(html, entry)
    locations = {r.location for r in records}
    assert len(locations) >= 10  # many municipalities
    assert any("Barretos" in loc for loc in locations if loc)


def test_parse_has_multiple_columns(parser, html, entry):
    records = parser.parse_html(html, entry)
    col_names = {r.column_name for r in records}
    assert len(col_names) >= 3  # boi vista, boi prazo, vaca vista


def test_values_reasonable(parser, html, entry):
    records = parser.parse_html(html, entry)
    for r in records:
        if r.value is not None:
            # Some regions report R$/kg (e.g. RS Oeste ~10-15), most report R$/@ (~250-350)
            assert 1 < r.value < 1000
