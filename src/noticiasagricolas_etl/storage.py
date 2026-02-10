"""Parquet read/write, dedup, CSV export, and dashboard metrics."""

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import BACKFILL_START_DATE, CSV_DIR, PARQUET_DIR
from .models import PriceRecord
from .normalize import normalize_df

logger = logging.getLogger(__name__)

DEDUP_COLS = ["date", "indicator", "location", "contract_month", "column_name"]

SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("commodity", pa.string()),
        ("indicator", pa.string()),
        ("indicator_name", pa.string()),
        ("location", pa.string()),
        ("contract_month", pa.string()),
        ("column_name", pa.string()),
        ("value", pa.float64()),
        ("value_raw", pa.string()),
        ("unit", pa.string()),
        # Normalized columns
        ("measure", pa.string()),
        ("currency", pa.string()),
        ("unit_std", pa.string()),
        ("price_basis", pa.string()),
        ("contract", pa.string()),
        ("state", pa.string()),
        ("market_type", pa.string()),
    ]
)


def records_to_df(records: list[PriceRecord]) -> pd.DataFrame:
    """Convert PriceRecord list to DataFrame."""
    if not records:
        return pd.DataFrame(columns=[f.name for f in SCHEMA])
    data = [r.model_dump() for r in records]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _parquet_path(commodity: str) -> Path:
    """Get Parquet file path for a commodity."""
    path = PARQUET_DIR / f"commodity={commodity}"
    path.mkdir(parents=True, exist_ok=True)
    return path / "data.parquet"


def read_parquet(commodity: str) -> pd.DataFrame:
    """Read existing Parquet data for a commodity."""
    path = _parquet_path(commodity)
    if not path.exists():
        return pd.DataFrame(columns=[f.name for f in SCHEMA])
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def write_parquet(commodity: str, df: pd.DataFrame):
    """Write DataFrame to Parquet, overwriting existing file."""
    path = _parquet_path(commodity)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, path)
    logger.info(f"Wrote {len(df)} rows to {path}")


def upsert(commodity: str, new_records: list[PriceRecord]):
    """Upsert new records into existing Parquet, deduplicating."""
    new_df = records_to_df(new_records)
    if new_df.empty:
        return

    existing = read_parquet(commodity)
    if existing.empty:
        combined = new_df
    else:
        combined = pd.concat([existing, new_df], ignore_index=True)

    # Dedup: keep last (newest) entry for each key
    combined = combined.drop_duplicates(subset=DEDUP_COLS, keep="last")
    combined = combined.sort_values(["date", "indicator", "location", "contract_month", "column_name"])
    combined = combined.reset_index(drop=True)

    # Apply normalization (recompute on full dataset for consistency)
    combined = normalize_df(combined)

    write_parquet(commodity, combined)
    export_csv(commodity, combined)


def export_csv(commodity: str, df: pd.DataFrame = None):
    """Export commodity data as CSV."""
    if df is None:
        df = read_parquet(commodity)
    if df.empty:
        return

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"{commodity}.csv"
    df.to_csv(path, index=False)
    logger.info(f"Exported CSV: {path} ({len(df)} rows)")


def export_all_csv():
    """Export CSVs for all commodities with existing Parquet data."""
    if not PARQUET_DIR.exists():
        return
    for d in PARQUET_DIR.iterdir():
        if d.is_dir() and d.name.startswith("commodity="):
            commodity = d.name.split("=", 1)[1]
            export_csv(commodity)


def get_coverage(commodity: str = None) -> dict:
    """Get date coverage statistics per indicator."""
    if commodity:
        commodities = [commodity]
    else:
        if not PARQUET_DIR.exists():
            return {}
        commodities = [
            d.name.split("=", 1)[1]
            for d in PARQUET_DIR.iterdir()
            if d.is_dir() and d.name.startswith("commodity=")
        ]

    coverage = {}
    for c in commodities:
        df = read_parquet(c)
        if df.empty:
            continue
        for indicator, group in df.groupby("indicator"):
            dates = group["date"]
            coverage[indicator] = {
                "commodity": c,
                "min_date": str(min(dates)),
                "max_date": str(max(dates)),
                "n_dates": len(set(dates)),
                "n_records": len(group),
            }
    return coverage


# ── Dashboard helpers ────────────────────────────────────────────────────────


def _total_business_days(start: date, end: date) -> int:
    """Count business days between start and end (inclusive)."""
    bdays = pd.bdate_range(start, end)
    return len(bdays)


def _find_gaps(dates: set[date], min_date: date, max_date: date) -> list[tuple[date, date]]:
    """Find contiguous business-day gaps within [min_date, max_date].

    Returns a list of (gap_start, gap_end) tuples sorted by date.
    Each tuple represents a contiguous stretch of business days missing from *dates*.
    """
    if not dates or min_date > max_date:
        return []

    all_bdays = {d.date() for d in pd.bdate_range(min_date, max_date)}
    missing = sorted(all_bdays - dates)
    if not missing:
        return []

    gaps: list[tuple[date, date]] = []
    gap_start = missing[0]
    prev = missing[0]
    for d in missing[1:]:
        # Check if `d` is the next business day after `prev`
        next_bdays = pd.bdate_range(prev, periods=2)
        if len(next_bdays) >= 2 and d == next_bdays[1].date():
            prev = d
        else:
            gaps.append((gap_start, prev))
            gap_start = d
            prev = d
    gaps.append((gap_start, prev))
    return gaps


def _progress_bar(pct: float, width: int = 20) -> str:
    """Render ASCII progress bar like [████████░░░░░░░░░░░░]."""
    filled = round(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


def get_dashboard_data(
    catalog_entries: list,
    state: Optional[dict] = None,
) -> dict:
    """Compute per-indicator dashboard metrics.

    Args:
        catalog_entries: List of CatalogEntry objects (from load_catalog)
        state: Optional state dict (from load_state); merged into results

    Returns:
        {
            "total_records": int,
            "total_indicators_with_data": int,
            "total_indicators": int,
            "since": str,
            "indicators": {slug: {...metrics...}},
            "commodities": {commodity: {...aggregated...}},
            "categories": {category: {...aggregated...}},
        }
    """
    state = state or {}
    start_date = date.fromisoformat(BACKFILL_START_DATE)
    today = date.today()
    total_bdays = _total_business_days(start_date, today)

    # Build lookup: slug → CatalogEntry
    entry_map = {e.slug: e for e in catalog_entries}

    # Read all available Parquet data grouped by commodity
    commodity_dfs: dict[str, pd.DataFrame] = {}
    if PARQUET_DIR.exists():
        for d in PARQUET_DIR.iterdir():
            if d.is_dir() and d.name.startswith("commodity="):
                c = d.name.split("=", 1)[1]
                df = read_parquet(c)
                if not df.empty:
                    commodity_dfs[c] = df

    # Per-indicator metrics
    indicators: dict[str, dict] = {}
    for entry in catalog_entries:
        slug = entry.slug
        commodity = entry.commodity
        df = commodity_dfs.get(commodity)

        if df is not None and not df.empty:
            mask = df["indicator"] == slug
            group = df[mask]
        else:
            group = pd.DataFrame()

        if group.empty:
            indicators[slug] = {
                "commodity": commodity,
                "category": entry.category.value if entry.category else None,
                "name": entry.name,
                "n_dates": 0,
                "n_records": 0,
                "min_date": None,
                "max_date": None,
                "coverage_pct": 0.0,
                "null_count": 0,
                "null_pct": 0.0,
                "gap_count": 0,
                "top_gaps": [],
                "last_backfill": None,
                "last_update": None,
                "errors": 0,
            }
        else:
            unique_dates = set(group["date"])
            n_dates = len(unique_dates)
            n_records = len(group)
            min_d = min(unique_dates)
            max_d = max(unique_dates)
            coverage_pct = (n_dates / total_bdays * 100) if total_bdays > 0 else 0.0
            null_count = int(group["value"].isna().sum())
            null_pct = (null_count / n_records * 100) if n_records > 0 else 0.0

            gaps = _find_gaps(unique_dates, min_d, max_d)
            gap_count = sum(
                _total_business_days(g[0], g[1]) for g in gaps
            )

            indicators[slug] = {
                "commodity": commodity,
                "category": entry.category.value if entry.category else None,
                "name": entry.name,
                "n_dates": n_dates,
                "n_records": n_records,
                "min_date": str(min_d),
                "max_date": str(max_d),
                "coverage_pct": round(coverage_pct, 1),
                "null_count": null_count,
                "null_pct": round(null_pct, 1),
                "gap_count": gap_count,
                "top_gaps": [(str(g[0]), str(g[1])) for g in gaps[:5]],
                "last_backfill": None,
                "last_update": None,
                "errors": 0,
            }

        # Merge state info
        entry_key = f"{commodity}/{slug}"
        if entry_key in state:
            s = state[entry_key]
            indicators[slug]["last_backfill"] = s.get("last_backfill")
            indicators[slug]["last_update"] = s.get("last_update")
            indicators[slug]["errors"] = s.get("backfill_errors", 0)

    # Aggregate by commodity
    commodities: dict[str, dict] = {}
    for slug, info in indicators.items():
        c = info["commodity"]
        if c not in commodities:
            commodities[c] = {
                "total_indicators": 0,
                "indicators_with_data": 0,
                "total_records": 0,
                "coverage_sum": 0.0,
                "category": info["category"],
            }
        commodities[c]["total_indicators"] += 1
        if info["n_records"] > 0:
            commodities[c]["indicators_with_data"] += 1
        commodities[c]["total_records"] += info["n_records"]
        commodities[c]["coverage_sum"] += info["coverage_pct"]

    for c, agg in commodities.items():
        n = agg["total_indicators"]
        agg["avg_coverage"] = round(agg["coverage_sum"] / n, 1) if n > 0 else 0.0

    # Aggregate by category
    categories: dict[str, dict] = {}
    for slug, info in indicators.items():
        cat = info["category"]
        if cat is None:
            continue
        if cat not in categories:
            categories[cat] = {
                "total_indicators": 0,
                "indicators_with_data": 0,
                "total_records": 0,
                "coverage_sum": 0.0,
            }
        categories[cat]["total_indicators"] += 1
        if info["n_records"] > 0:
            categories[cat]["indicators_with_data"] += 1
        categories[cat]["total_records"] += info["n_records"]
        categories[cat]["coverage_sum"] += info["coverage_pct"]

    for cat, agg in categories.items():
        n = agg["total_indicators"]
        agg["avg_coverage"] = round(agg["coverage_sum"] / n, 1) if n > 0 else 0.0

    total_records = sum(info["n_records"] for info in indicators.values())
    total_with_data = sum(1 for info in indicators.values() if info["n_records"] > 0)

    return {
        "total_records": total_records,
        "total_indicators_with_data": total_with_data,
        "total_indicators": len(indicators),
        "since": BACKFILL_START_DATE,
        "indicators": indicators,
        "commodities": commodities,
        "categories": categories,
    }
