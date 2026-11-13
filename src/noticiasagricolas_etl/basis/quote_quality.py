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


def summarize_quote_quality(
    rows: pd.DataFrame,
    commodity: str,
    snapshot_date: date | str,
    tolerance: float = 0.001,
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
        combined = combined.sort_values(["commodity", "date", "location"]).reset_index(drop=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info("Exported quote quality CSV: %s (%d rows)", path, len(combined))
    return combined
