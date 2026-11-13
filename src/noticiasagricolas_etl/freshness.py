"""Fail-closed freshness checks for daily publication inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from . import storage

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class CriticalIndicator:
    label: str
    commodity: str
    indicator: str
    column_name: str
    location: str | None = None


CRITICAL_INDICATORS = (
    CriticalIndicator(
        label="soja CBOT",
        commodity="soja",
        indicator="soja-bolsa-de-chicago-cme-group",
        column_name="fechamento",
    ),
    CriticalIndicator(
        label="milho CBOT",
        commodity="milho",
        indicator="milho-bolsa-de-chicago-cme-group",
        column_name="fechamento",
    ),
    CriticalIndicator(
        label="PTAX",
        commodity="mercado-financeiro",
        indicator="cambio-ptax",
        column_name="valor",
        location="Dólar",
    ),
)


@dataclass(frozen=True)
class IndicatorFreshness:
    label: str
    indicator: str
    latest_date: date | None
    expected_date: date

    @property
    def is_fresh(self) -> bool:
        return self.latest_date is not None and self.latest_date >= self.expected_date


@dataclass(frozen=True)
class FreshnessReport:
    expected_date: date
    indicators: tuple[IndicatorFreshness, ...]

    @property
    def is_fresh(self) -> bool:
        return all(row.is_fresh for row in self.indicators)


class CriticalFreshnessError(RuntimeError):
    """One or more publication inputs are absent or stale."""

    def __init__(self, report: FreshnessReport):
        self.report = report
        problems = []
        for row in report.indicators:
            if row.is_fresh:
                continue
            latest = row.latest_date.isoformat() if row.latest_date else "missing"
            problems.append(f"{row.label} latest={latest}")
        detail = ", ".join(problems)
        super().__init__(
            f"Critical data is stale for expected date {report.expected_date}: {detail}"
        )


def default_expected_date(as_of: date | None = None) -> date:
    """Return the last weekday before the São Paulo run date."""
    local_date = as_of or datetime.now(SAO_PAULO).date()
    candidate = local_date - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _latest_date(frame: pd.DataFrame, spec: CriticalIndicator) -> date | None:
    required = {"date", "indicator", "column_name", "value"}
    if frame.empty or not required.issubset(frame.columns):
        return None

    mask = (
        (frame["indicator"] == spec.indicator)
        & (frame["column_name"] == spec.column_name)
        & frame["value"].notna()
    )
    if spec.location is not None:
        if "location" not in frame.columns:
            return None
        mask &= frame["location"] == spec.location

    dates = pd.to_datetime(frame.loc[mask, "date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def validate_critical_freshness(
    expected_date: date | None = None,
    reader: Callable[[str], pd.DataFrame] = storage.read_parquet,
) -> FreshnessReport:
    """Validate the latest persisted date for all publication-critical inputs."""
    expected = expected_date or default_expected_date()
    rows = tuple(
        IndicatorFreshness(
            label=spec.label,
            indicator=spec.indicator,
            latest_date=_latest_date(reader(spec.commodity), spec),
            expected_date=expected,
        )
        for spec in CRITICAL_INDICATORS
    )
    report = FreshnessReport(expected_date=expected, indicators=rows)
    if not report.is_fresh:
        raise CriticalFreshnessError(report)
    return report
