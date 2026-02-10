"""Date generation for backfill: business-day strategies with smart skipping."""

from datetime import date

import pandas as pd

from .storage import read_parquet


def generate_backfill_dates(
    start_date: date,
    end_date: date,
) -> list[date]:
    """Generate business days for backfill, in chronological order.

    Each date-specific URL returns only 1 date of data,
    so we need to request each business day individually.
    """
    bdays = pd.bdate_range(start_date, end_date)
    return [d.date() for d in bdays]


def get_covered_dates(commodity: str, indicator_slug: str) -> set[date]:
    """Get dates already present in Parquet for a specific indicator."""
    df = read_parquet(commodity)
    if df.empty:
        return set()
    mask = df["indicator"] == indicator_slug
    if not mask.any():
        return set()
    return set(df.loc[mask, "date"].unique())


def generate_uncovered_dates(
    commodity: str,
    indicator_slug: str,
    start_date: date,
    end_date: date,
) -> list[date]:
    """Generate business days NOT yet covered in existing Parquet data."""
    all_dates = set(generate_backfill_dates(start_date, end_date))
    covered = get_covered_dates(commodity, indicator_slug)
    uncovered = sorted(all_dates - covered)
    return uncovered
