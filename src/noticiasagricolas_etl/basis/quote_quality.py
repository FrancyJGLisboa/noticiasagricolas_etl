"""Build the compact daily physical-quote quality snapshot."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

import pandas as pd

from ..config import CSV_DIR

logger = logging.getLogger(__name__)

QUOTE_QUALITY_COLUMNS = [
    "commodity",
    "date",
    "location",
    "n_quotes",
    "price_min_brl",
    "price_max_brl",
    "price_mean_brl",
    "price_range_brl",
    "classification",
    "quote_types",
    "physical_indicators",
    "source_labels",
    "basis_pair",
    "physical_source",
    "source_name",
    "source_url",
    "methodology_url",
    "blocked_outlier_count",
    "outlier_rule",
    "blocked_examples",
]

_MONTH_YEAR = re.compile(
    r"\b(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\s*[/ -]\s*\d{2,4}\b"
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def classify_quote_type(source_label: str) -> str:
    """Classify only delivery evidence that appears in the source label."""
    label = _fold(source_label)
    if "disponivel" in label:
        return "spot"
    if _MONTH_YEAR.search(label):
        return "dated_delivery"
    if "balcao" in label:
        return "balcao"
    return "unspecified"


def filter_physical_outliers(
    rows: pd.DataFrame,
    policy: str = "none",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split valid quotes from source anomalies without correcting values.

    The IMEA policy compares positive prices from the same indicator and date.
    It needs at least three municipalities. A quote outside 0.5 to 2 times the
    cross-sectional median is blocked before basis computation.
    """
    if rows.empty or policy == "none":
        return rows.copy(), pd.DataFrame(columns=[*rows.columns, "blocked_reason"])
    if policy != "cross_section_ratio":
        raise ValueError(f"Unsupported physical outlier policy: {policy}")

    working = rows.copy()
    prices = pd.to_numeric(working["physical_price_brl"], errors="coerce")
    working["_positive_price"] = prices.where(prices > 0)
    grouped = working.groupby(
        ["date", "physical_indicator"],
        dropna=False,
    )["_positive_price"]
    medians = grouped.transform("median")
    counts = grouped.transform("count")
    ratios = prices / medians
    blocked_mask = (
        (counts >= 3)
        & medians.notna()
        & ((ratios < 0.5) | (ratios > 2.0))
    )
    valid = working.loc[~blocked_mask, rows.columns].reset_index(drop=True)
    blocked = working.loc[blocked_mask, rows.columns].copy()
    blocked["blocked_reason"] = "cross_section_ratio"
    return valid, blocked.reset_index(drop=True)


def summarize_quote_quality(
    rows: pd.DataFrame,
    commodity: str,
    snapshot_date: date | str,
    tolerance: float = 0.001,
    *,
    basis_pair: str = "",
    physical_source: str = "mercado-fisico",
    source_name: str = "Notícias Agrícolas",
    source_url: str = "",
    methodology_url: str = "",
    blocked_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Summarize individual quotes for one commodity and basis date."""
    if rows.empty:
        return pd.DataFrame(columns=QUOTE_QUALITY_COLUMNS)

    target = pd.Timestamp(snapshot_date).date()
    current = rows.copy()
    current["date"] = pd.to_datetime(current["date"]).dt.date
    current = current[current["date"] == target].copy()
    if current.empty:
        return pd.DataFrame(columns=QUOTE_QUALITY_COLUMNS)

    current["quote_type"] = current["source_label"].map(classify_quote_type)
    blocked = blocked_rows if blocked_rows is not None else pd.DataFrame()
    blocked_count = len(blocked)
    blocked_reasons = (
        "|".join(sorted(set(blocked["blocked_reason"].astype(str))))
        if blocked_count and "blocked_reason" in blocked
        else ""
    )
    examples: list[str] = []
    if blocked_count:
        ordered_blocked = blocked.copy()
        ordered_blocked["date"] = pd.to_datetime(ordered_blocked["date"]).dt.date
        ordered_blocked = ordered_blocked.sort_values(["date", "location"])
        for row in ordered_blocked.head(5).itertuples(index=False):
            examples.append(
                f"{row.date.isoformat()} {row.location} {float(row.physical_price_brl):.2f}"
            )
    records: list[dict] = []
    for location, group in current.groupby("location", sort=True):
        quote_types = sorted(set(group["quote_type"].astype(str)))
        prices = group["physical_price_brl"].astype(float)
        minimum = float(prices.min())
        maximum = float(prices.max())
        if {"spot", "dated_delivery"}.issubset(quote_types):
            classification = "mixed_delivery"
        elif len(group) == 1:
            classification = "single"
        elif maximum - minimum <= tolerance:
            classification = "consensus"
        else:
            classification = "source_dispersion"
        records.append({
            "commodity": commodity,
            "date": target.isoformat(),
            "location": location,
            "n_quotes": len(group),
            "price_min_brl": minimum,
            "price_max_brl": maximum,
            "price_mean_brl": float(prices.mean()),
            "price_range_brl": maximum - minimum,
            "classification": classification,
            "quote_types": "|".join(quote_types),
            "physical_indicators": "|".join(sorted(set(group["physical_indicator"].astype(str)))),
            "source_labels": "|".join(sorted(set(group["source_label"].astype(str)))),
            "basis_pair": basis_pair,
            "physical_source": physical_source,
            "source_name": source_name,
            "source_url": source_url,
            "methodology_url": methodology_url,
            "blocked_outlier_count": blocked_count,
            "outlier_rule": blocked_reasons,
            "blocked_examples": "|".join(examples),
        })
    return pd.DataFrame(records, columns=QUOTE_QUALITY_COLUMNS)


def export_quote_quality_csv(
    frames: list[pd.DataFrame],
    processed_commodities: set[str],
) -> pd.DataFrame:
    """Write quality rows and preserve commodities outside a filtered build."""
    path = CSV_DIR / "quote-quality.csv"
    new_rows = [frame for frame in frames if not frame.empty]
    parts: list[pd.DataFrame] = []
    if path.exists():
        existing = pd.read_csv(path, dtype={"date": str})
        if set(QUOTE_QUALITY_COLUMNS).issubset(existing.columns):
            parts.append(existing[~existing["commodity"].isin(processed_commodities)][QUOTE_QUALITY_COLUMNS])
        else:
            logger.warning("Ignoring incompatible existing quote quality CSV: %s", path)
    parts.extend(frame[QUOTE_QUALITY_COLUMNS] for frame in new_rows)
    combined = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=QUOTE_QUALITY_COLUMNS)
    if not combined.empty:
        combined = combined.sort_values(
            ["commodity", "basis_pair", "date", "location"]
        ).reset_index(drop=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info("Exported quote quality CSV: %s (%d rows)", path, len(combined))
    return combined
