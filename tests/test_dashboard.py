"""Tests for the dashboard: gap detection, progress bar, get_dashboard_data."""

from datetime import date

import pandas as pd
import pytest

from noticiasagricolas_etl.models import Category, CatalogEntry, PageType
from noticiasagricolas_etl.storage import (
    _find_gaps,
    _progress_bar,
    _total_business_days,
    get_dashboard_data,
    upsert,
)
from noticiasagricolas_etl.models import PriceRecord


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def temp_data_dirs(tmp_path, monkeypatch):
    """Redirect all storage to a temp directory for each test."""
    parquet_dir = tmp_path / "parquet"
    csv_dir = tmp_path / "csv"
    parquet_dir.mkdir()
    csv_dir.mkdir()
    monkeypatch.setattr("noticiasagricolas_etl.storage.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.storage.CSV_DIR", csv_dir)
    return {"parquet": parquet_dir, "csv": csv_dir}


def _make_entry(slug="test-indicator", commodity="test-commodity", category=None):
    return CatalogEntry(
        commodity=commodity,
        slug=slug,
        name="Test Indicator",
        page_type=PageType.INDICATOR,
        unit="R$",
        has_date_nav=True,
        enabled=True,
        category=category,
    )


def _make_record(d: date, slug="test-indicator", commodity="test-commodity", value=100.0):
    return PriceRecord(
        date=d,
        commodity=commodity,
        indicator=slug,
        indicator_name="Test Indicator",
        location=None,
        contract_month=None,
        column_name="preco",
        value=value,
        value_raw=f"{value:.2f}".replace(".", ","),
        unit="R$",
    )


# ── _total_business_days ─────────────────────────────────────────────────────


class TestTotalBusinessDays:
    def test_full_week(self):
        # Mon Jan 1 to Fri Jan 5 2024 = 5 business days
        assert _total_business_days(date(2024, 1, 1), date(2024, 1, 5)) == 5

    def test_weekend_only(self):
        # Sat to Sun
        assert _total_business_days(date(2024, 1, 6), date(2024, 1, 7)) == 0

    def test_single_day(self):
        # Monday
        assert _total_business_days(date(2024, 1, 1), date(2024, 1, 1)) == 1


# ── _find_gaps ───────────────────────────────────────────────────────────────


class TestFindGaps:
    def test_no_gaps_when_all_dates_present(self):
        dates = {date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3),
                 date(2024, 1, 4), date(2024, 1, 5)}  # Mon-Fri
        gaps = _find_gaps(dates, date(2024, 1, 1), date(2024, 1, 5))
        assert gaps == []

    def test_single_gap_in_middle(self):
        # Missing Wed Jan 3
        dates = {date(2024, 1, 1), date(2024, 1, 2),
                 date(2024, 1, 4), date(2024, 1, 5)}
        gaps = _find_gaps(dates, date(2024, 1, 1), date(2024, 1, 5))
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 3), date(2024, 1, 3))

    def test_multi_day_gap(self):
        # Missing Wed + Thu
        dates = {date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 5)}
        gaps = _find_gaps(dates, date(2024, 1, 1), date(2024, 1, 5))
        assert len(gaps) == 1
        assert gaps[0] == (date(2024, 1, 3), date(2024, 1, 4))

    def test_multiple_separate_gaps(self):
        # Week 1: Mon present, Tue-Fri missing
        # Week 2: Mon present, Tue present, rest missing
        dates = {date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 9)}
        gaps = _find_gaps(dates, date(2024, 1, 1), date(2024, 1, 12))
        # Gap 1: Jan 2-5 (Tue-Fri), Gap 2: Jan 10-12 (Wed-Fri)
        assert len(gaps) == 2

    def test_empty_dates_returns_empty(self):
        gaps = _find_gaps(set(), date(2024, 1, 1), date(2024, 1, 5))
        assert gaps == []


# ── _progress_bar ────────────────────────────────────────────────────────────


class TestProgressBar:
    def test_zero_percent(self):
        bar = _progress_bar(0.0)
        assert "\u2588" not in bar
        assert len(bar) == 20

    def test_hundred_percent(self):
        bar = _progress_bar(100.0)
        assert "\u2591" not in bar
        assert len(bar) == 20

    def test_fifty_percent(self):
        bar = _progress_bar(50.0)
        assert bar.count("\u2588") == 10
        assert bar.count("\u2591") == 10

    def test_custom_width(self):
        bar = _progress_bar(50.0, width=10)
        assert len(bar) == 10


# ── get_dashboard_data ───────────────────────────────────────────────────────


class TestGetDashboardData:
    def test_empty_catalog_returns_zeros(self):
        data = get_dashboard_data([])
        assert data["total_records"] == 0
        assert data["total_indicators"] == 0
        assert data["indicators"] == {}

    def test_catalog_without_data_shows_zero_coverage(self):
        entries = [_make_entry(category=Category.OILSEEDS)]
        data = get_dashboard_data(entries)
        assert data["total_indicators"] == 1
        assert data["total_indicators_with_data"] == 0
        ind = data["indicators"]["test-indicator"]
        assert ind["n_records"] == 0
        assert ind["coverage_pct"] == 0.0

    def test_with_synthetic_data(self, temp_data_dirs):
        # Insert 5 records for 5 business days
        records = [_make_record(date(2024, 1, d)) for d in [1, 2, 3, 4, 5]]
        upsert("test-commodity", records)

        entries = [_make_entry(category=Category.OILSEEDS)]
        data = get_dashboard_data(entries)

        ind = data["indicators"]["test-indicator"]
        assert ind["n_dates"] == 5
        assert ind["n_records"] == 5
        assert ind["coverage_pct"] > 0
        assert ind["category"] == "oilseeds"

    def test_category_aggregation(self, temp_data_dirs):
        records = [_make_record(date(2024, 1, d)) for d in [1, 2, 3]]
        upsert("test-commodity", records)

        entries = [_make_entry(category=Category.OILSEEDS)]
        data = get_dashboard_data(entries)

        assert "oilseeds" in data["categories"]
        cat = data["categories"]["oilseeds"]
        assert cat["total_indicators"] == 1
        assert cat["indicators_with_data"] == 1
        assert cat["total_records"] == 3

    def test_state_merging(self, temp_data_dirs):
        entries = [_make_entry(category=Category.OILSEEDS)]
        state = {
            "test-commodity/test-indicator": {
                "last_backfill": "2024-01-05T12:00:00",
                "last_update": "2024-01-06T08:00:00",
                "backfill_errors": 2,
            }
        }
        data = get_dashboard_data(entries, state)
        ind = data["indicators"]["test-indicator"]
        assert ind["last_backfill"] == "2024-01-05T12:00:00"
        assert ind["last_update"] == "2024-01-06T08:00:00"
        assert ind["errors"] == 2

    def test_null_detection(self, temp_data_dirs):
        records = [
            _make_record(date(2024, 1, 1), value=100.0),
            PriceRecord(
                date=date(2024, 1, 2),
                commodity="test-commodity",
                indicator="test-indicator",
                indicator_name="Test Indicator",
                location=None,
                contract_month=None,
                column_name="preco",
                value=None,
                value_raw="-",
                unit="R$",
            ),
        ]
        upsert("test-commodity", records)

        entries = [_make_entry(category=Category.OILSEEDS)]
        data = get_dashboard_data(entries)
        ind = data["indicators"]["test-indicator"]
        assert ind["null_count"] == 1
        assert ind["null_pct"] == 50.0
