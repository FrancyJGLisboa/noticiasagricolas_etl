from __future__ import annotations

from datetime import date

import pytest
from click.testing import CliRunner

from noticiasagricolas_etl.cli import cli
from noticiasagricolas_etl.models import CatalogEntry, PageType, PriceRecord
from noticiasagricolas_etl.pipeline import UpdateFailed, UpdateSummary, update
from noticiasagricolas_etl.scraper import FetchError


def _entry(commodity: str, slug: str) -> CatalogEntry:
    return CatalogEntry(
        commodity=commodity,
        slug=slug,
        name=slug,
        page_type=PageType.CME_FUTURES,
        unit="US$/bu",
    )


def _record(entry: CatalogEntry) -> PriceRecord:
    return PriceRecord(
        date=date(2026, 11, 12),
        commodity=entry.commodity,
        indicator=entry.slug,
        indicator_name=entry.name,
        contract_month="Janeiro/27",
        column_name="fechamento",
        value=12.19,
        value_raw="12,1900",
        unit=entry.unit,
    )


def _patch_update_dependencies(monkeypatch, entries) -> None:
    monkeypatch.setattr("noticiasagricolas_etl.pipeline.load_catalog", lambda: entries)
    monkeypatch.setattr("noticiasagricolas_etl.pipeline.load_state", lambda: {})
    monkeypatch.setattr("noticiasagricolas_etl.pipeline.save_state", lambda state: None)
    monkeypatch.setattr("noticiasagricolas_etl.pipeline.upsert", lambda *args: None)


def test_update_fails_after_any_fetch_error(monkeypatch) -> None:
    good = _entry("soja", "good")
    blocked = _entry("milho", "blocked")
    _patch_update_dependencies(monkeypatch, [good, blocked])

    def process(scraper, entry, target_date=None):
        if entry.slug == "blocked":
            raise FetchError("HTTP 403 for blocked")
        return [_record(entry)]

    monkeypatch.setattr("noticiasagricolas_etl.pipeline._process_entry", process)

    with pytest.raises(UpdateFailed, match="1 indicator fetch failed") as raised:
        update()

    summary = raised.value.summary
    assert summary.success_count == 1
    assert summary.error_count == 1
    assert summary.errors == {"milho/blocked": "HTTP 403 for blocked"}


def test_update_fails_when_no_indicator_returns_records(monkeypatch) -> None:
    entry = _entry("soja", "empty")
    _patch_update_dependencies(monkeypatch, [entry])
    monkeypatch.setattr(
        "noticiasagricolas_etl.pipeline._process_entry",
        lambda scraper, entry, target_date=None: [],
    )

    with pytest.raises(UpdateFailed, match="0 of 1 indicators returned records"):
        update()


def test_update_command_returns_nonzero_for_fetch_failure(monkeypatch) -> None:
    summary = UpdateSummary(error_count=1, indicators_attempted=1)

    def fail(**kwargs):
        raise UpdateFailed(summary)

    monkeypatch.setattr("noticiasagricolas_etl.cli.pipeline.update", fail)
    result = CliRunner().invoke(cli, ["update"])

    assert result.exit_code != 0
    assert "1 indicator fetch failed" in result.output
