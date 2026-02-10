"""Orchestration: backfill and incremental update."""

import logging
import time
from datetime import date, datetime
from typing import Optional

from .backfill import generate_backfill_dates, generate_uncovered_dates
from .catalog import (
    get_enabled_entries,
    get_entries_by_category,
    get_entries_by_commodity,
    get_entry_by_slug,
    load_catalog,
)
from .config import BACKFILL_BATCH_SIZE, BACKFILL_DELAY_SECONDS, BACKFILL_START_DATE
from .models import CatalogEntry, PriceRecord
from .parsers.registry import get_parser
from .scraper import Scraper
from .state import load_state, save_state
from .storage import upsert

logger = logging.getLogger(__name__)

NO_DATA_MARKER = "Não há cotações para esse dia"


def _process_entry(
    scraper: Scraper,
    entry: CatalogEntry,
    target_date: Optional[date] = None,
) -> list[PriceRecord]:
    """Fetch and parse a single catalog entry."""
    html = scraper.fetch_commodity_page(entry.commodity, entry.slug, target_date)
    if not html:
        logger.warning(f"No HTML for {entry.commodity}/{entry.slug} date={target_date}")
        return []

    # Fast check for "no data" pages (weekends, holidays, dates before data existed)
    if target_date and NO_DATA_MARKER in html:
        return []

    parser = get_parser(entry.page_type)
    records = parser.parse_html(html, entry)
    logger.debug(
        f"Parsed {len(records)} records from {entry.commodity}/{entry.slug} date={target_date}"
    )
    return records


def _format_eta(seconds: float) -> str:
    """Format seconds into human-readable ETA."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    hours = seconds / 3600
    return f"{hours:.1f}h"


def _resolve_entries(
    entries: list[CatalogEntry],
    slug: Optional[str] = None,
    commodity: Optional[str] = None,
    category: Optional[str] = None,
) -> list[CatalogEntry]:
    """Resolve target entries from slug, commodity, category, or all enabled."""
    if slug:
        entry = get_entry_by_slug(entries, slug)
        if not entry:
            logger.error(f"Slug not found: {slug}")
            return []
        return [entry]
    if commodity:
        return get_entries_by_commodity(entries, commodity)
    if category:
        return get_entries_by_category(entries, category)
    return get_enabled_entries(entries)


def backfill(
    commodity: Optional[str] = None,
    slug: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    delay: Optional[float] = None,
    resume: bool = True,
):
    """Run backfill for specified commodity/slug/category/date range.

    Args:
        commodity: Filter to specific commodity
        slug: Filter to specific indicator slug
        category: Filter to specific category (e.g. "grains", "oilseeds")
        start_date: Start of backfill range (default: 2020-01-01)
        end_date: End of backfill range (default: today)
        delay: Request delay in seconds (default: BACKFILL_DELAY_SECONDS)
        resume: If True, skip dates already in Parquet (default: True)
    """
    entries = load_catalog()
    start = start_date or date.fromisoformat(BACKFILL_START_DATE)
    end = end_date or date.today()
    scraper_delay = delay if delay is not None else BACKFILL_DELAY_SECONDS

    target_entries = _resolve_entries(entries, slug=slug, commodity=commodity, category=category)

    # Filter to entries with date navigation
    target_entries = [e for e in target_entries if e.has_date_nav]

    if not target_entries:
        logger.error("No entries to process (need has_date_nav=true)")
        return

    scraper = Scraper(delay=scraper_delay, use_cache=False)
    state = load_state()

    total_entries = len(target_entries)
    grand_total_records = 0
    grand_total_skipped = 0
    grand_total_empty = 0
    grand_total_errors = 0

    logger.info(
        f"Backfill: {total_entries} indicators, {start} to {end}, "
        f"delay={scraper_delay}s, resume={resume}"
    )

    for entry_idx, entry in enumerate(target_entries, 1):
        entry_key = f"{entry.commodity}/{entry.slug}"
        logger.info(f"[{entry_idx}/{total_entries}] Backfilling {entry_key}")

        if resume:
            dates = generate_uncovered_dates(entry.commodity, entry.slug, start, end)
        else:
            dates = generate_backfill_dates(start, end)

        if not dates:
            logger.info(f"  All dates already covered for {entry_key}")
            continue

        total_dates = len(dates)
        logger.info(f"  {total_dates} dates to fetch ({dates[0]} to {dates[-1]})")

        batch_records = []
        entry_records = 0
        entry_empty = 0
        entry_errors = 0
        t_start = time.time()

        for i, target_date in enumerate(dates):
            try:
                records = _process_entry(scraper, entry, target_date)
                if records:
                    batch_records.extend(records)
                    entry_records += len(records)
                else:
                    entry_empty += 1
            except Exception as e:
                logger.error(f"  Error {entry_key} date={target_date}: {e}")
                entry_errors += 1

            # Periodic save
            if batch_records and ((i + 1) % BACKFILL_BATCH_SIZE == 0 or i == total_dates - 1):
                upsert(entry.commodity, batch_records)
                batch_records = []

            # Progress every 25 dates
            if (i + 1) % 25 == 0 or i == total_dates - 1:
                elapsed = time.time() - t_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                remaining = (total_dates - i - 1) / rate if rate > 0 else 0
                logger.info(
                    f"  [{i + 1}/{total_dates}] "
                    f"{entry_records} records, {entry_empty} empty, {entry_errors} errors | "
                    f"ETA {_format_eta(remaining)}"
                )

        # Update state for this entry
        state[entry_key] = {
            **state.get(entry_key, {}),
            "last_backfill": datetime.now().isoformat(),
            "backfill_start": str(start),
            "backfill_end": str(end),
            "backfill_records": entry_records,
            "backfill_empty_dates": entry_empty,
            "backfill_errors": entry_errors,
        }
        save_state(state)

        grand_total_records += entry_records
        grand_total_skipped += 0  # could track per-entry
        grand_total_empty += entry_empty
        grand_total_errors += entry_errors

        logger.info(
            f"  Done {entry_key}: {entry_records} records, "
            f"{entry_empty} empty dates, {entry_errors} errors"
        )

    logger.info(
        f"Backfill complete: {grand_total_records} records across {total_entries} indicators, "
        f"{grand_total_empty} empty dates, {grand_total_errors} errors"
    )


def update(
    commodity: Optional[str] = None,
    category: Optional[str] = None,
):
    """Incremental update: fetch default page (latest ~10 dates) for all entries."""
    entries = load_catalog()

    target_entries = _resolve_entries(entries, commodity=commodity, category=category)

    if not target_entries:
        logger.error("No entries to process")
        return

    scraper = Scraper()
    state = load_state()

    total = len(target_entries)
    success_count = 0
    error_count = 0
    total_records = 0

    for i, entry in enumerate(target_entries, 1):
        logger.info(f"[{i}/{total}] Updating {entry.commodity}/{entry.slug}")
        entry_key = f"{entry.commodity}/{entry.slug}"

        try:
            # Fetch default page (no date) to get latest ~10 dates
            records = _process_entry(scraper, entry, None)
            if records:
                upsert(entry.commodity, records)
                total_records += len(records)
                success_count += 1
            else:
                logger.warning(f"  No records from {entry_key}")

            state[entry_key] = {
                **state.get(entry_key, {}),
                "last_update": datetime.now().isoformat(),
                "last_update_records": len(records),
            }
        except Exception as e:
            logger.error(f"Error updating {entry_key}: {e}")
            error_count += 1
            state[entry_key] = {
                **state.get(entry_key, {}),
                "last_update_error": str(e),
            }

        save_state(state)

    logger.info(
        f"Update complete: {success_count} ok, {error_count} errors, "
        f"{total_records} total records across {total} indicators"
    )


def test_parse(slug: str, target_date: Optional[date] = None) -> list[PriceRecord]:
    """Parse a single page for debugging."""
    entries = load_catalog()
    entry = get_entry_by_slug(entries, slug)
    if not entry:
        raise ValueError(f"Slug not found in catalog: {slug}")

    scraper = Scraper(use_cache=True)
    return _process_entry(scraper, entry, target_date)
