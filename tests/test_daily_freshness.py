from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from click.testing import CliRunner

from noticiasagricolas_etl.cli import cli
from noticiasagricolas_etl.freshness import (
    CriticalFreshnessError,
    default_expected_date,
    validate_critical_freshness,
)


CRITICAL_ROWS = {
    "soja": pd.DataFrame(
        [
            {
                "date": date(2026, 11, 12),
                "indicator": "soja-bolsa-de-chicago-cme-group",
                "column_name": "fechamento",
                "location": None,
                "value": 12.27,
            }
        ]
    ),
    "milho": pd.DataFrame(
        [
            {
                "date": date(2026, 11, 12),
                "indicator": "milho-bolsa-de-chicago-cme-group",
                "column_name": "fechamento",
                "location": None,
                "value": 4.425,
            }
        ]
    ),
    "mercado-financeiro": pd.DataFrame(
        [
            {
                "date": date(2026, 11, 12),
                "indicator": "cambio-ptax",
                "column_name": "valor",
                "location": "Dólar",
                "value": 5.6143,
            }
        ]
    ),
}


def _reader(rows):
    return lambda commodity: rows.get(commodity, pd.DataFrame())


def test_default_expected_date_skips_weekend() -> None:
    assert default_expected_date(date(2026, 11, 16)) == date(2026, 11, 13)
    assert default_expected_date(date(2026, 11, 13)) == date(2026, 11, 12)


def test_critical_freshness_passes_when_all_dates_reach_expected() -> None:
    report = validate_critical_freshness(
        expected_date=date(2026, 11, 12),
        reader=_reader(CRITICAL_ROWS),
    )

    assert report.is_fresh is True
    assert {row.latest_date for row in report.indicators} == {date(2026, 11, 12)}


def test_critical_freshness_blocks_stale_indicator() -> None:
    rows = dict(CRITICAL_ROWS)
    rows["milho"] = rows["milho"].assign(date=date(2026, 11, 11))

    with pytest.raises(CriticalFreshnessError, match="milho CBOT.*2026-11-11"):
        validate_critical_freshness(
            expected_date=date(2026, 11, 12),
            reader=_reader(rows),
        )


def test_critical_freshness_blocks_missing_indicator() -> None:
    rows = dict(CRITICAL_ROWS)
    rows["mercado-financeiro"] = pd.DataFrame()

    with pytest.raises(CriticalFreshnessError, match="PTAX.*missing"):
        validate_critical_freshness(
            expected_date=date(2026, 11, 12),
            reader=_reader(rows),
        )


def test_validate_freshness_command_returns_nonzero_for_stale_data(monkeypatch) -> None:
    rows = dict(CRITICAL_ROWS)
    rows["soja"] = rows["soja"].assign(date=date(2026, 11, 11))

    def validate(expected_date=None):
        return validate_critical_freshness(expected_date, reader=_reader(rows))

    monkeypatch.setattr(
        "noticiasagricolas_etl.freshness.validate_critical_freshness",
        validate,
    )
    result = CliRunner().invoke(
        cli,
        ["validate-freshness", "--expected-date", "2026-11-12"],
    )

    assert result.exit_code != 0
    assert "soja CBOT latest=2026-11-11" in result.output
