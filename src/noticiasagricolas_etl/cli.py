"""Click CLI: backfill, update, status, test-parse, export, list, categories."""

import logging
import sys
from datetime import date
from typing import Optional

import click

from . import catalog as cat_module
from . import pipeline, storage
from .catalog import load_catalog
from .state import load_state
from .storage import _progress_bar, get_dashboard_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose):
    """Noticias Agricolas ETL - commodity price scraper."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity")
@click.option("--category", default=None, help="Filter by category (e.g. grains, oilseeds)")
@click.option("--start-date", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", default=None, help="End date (YYYY-MM-DD)")
@click.option("--slug", default=None, help="Specific indicator slug")
@click.option("--delay", default=None, type=float, help="Request delay in seconds (default: 1.0)")
@click.option("--no-resume", is_flag=True, help="Re-fetch all dates, ignoring existing data")
def backfill(commodity, category, start_date, end_date, slug, delay, no_resume):
    """Backfill historical data. Skips dates already in Parquet by default."""
    sd = date.fromisoformat(start_date) if start_date else None
    ed = date.fromisoformat(end_date) if end_date else None
    pipeline.backfill(
        commodity=commodity, slug=slug, category=category,
        start_date=sd, end_date=ed,
        delay=delay, resume=not no_resume,
    )


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity")
@click.option("--category", default=None, help="Filter by category (e.g. grains, oilseeds)")
def update(commodity, category):
    """Incremental update with latest data."""
    pipeline.update(commodity=commodity, category=category)


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity")
@click.option("--category", default=None, help="Filter by category")
@click.option("--gaps", is_flag=True, help="Show detailed gap analysis")
@click.option("--summary", is_flag=True, help="Show category-level summary only")
def status(commodity, category, gaps, summary):
    """Show data coverage dashboard."""
    entries = load_catalog()
    state = load_state()

    # Filter entries if needed
    if commodity:
        entries = [e for e in entries if e.commodity == commodity]
    elif category:
        entries = [e for e in entries if e.category and e.category.value == category]

    data = get_dashboard_data(entries, state)

    # Header
    click.echo()
    click.echo("=== Noticias Agricolas ETL \u2014 Data Dashboard ===")
    click.echo(
        f"  Total records: {data['total_records']:,} | "
        f"Indicators: {data['total_indicators_with_data']}/{data['total_indicators']} | "
        f"Since: {data['since']}"
    )

    # Category summary
    if data["categories"]:
        click.echo()
        click.echo("\u2500\u2500 Category Summary " + "\u2500" * 52)
        click.echo(
            f"{'Category':<14} {'Indicators':>11}  {'Records':>9}  {'Avg Coverage'}"
        )
        for cat in sorted(data["categories"], key=lambda c: -data["categories"][c]["avg_coverage"]):
            info = data["categories"][cat]
            bar = _progress_bar(info["avg_coverage"])
            click.echo(
                f"{cat.upper():<14} "
                f"{info['indicators_with_data']:>3} / {info['total_indicators']:<3}  "
                f"{info['total_records']:>9,}  "
                f"[{bar}] {info['avg_coverage']:>5.1f}%"
            )

    if summary:
        click.echo()
        return

    # Per-commodity detail
    # Group indicators by commodity
    by_commodity: dict[str, list[tuple[str, dict]]] = {}
    for slug, info in data["indicators"].items():
        c = info["commodity"]
        by_commodity.setdefault(c, []).append((slug, info))

    for c in sorted(by_commodity):
        slugs = by_commodity[c]
        with_data = sum(1 for _, i in slugs if i["n_records"] > 0)
        click.echo()
        click.echo(
            f"\u2500\u2500 {c.upper()} ({with_data}/{len(slugs)} indicators) "
            + "\u2500" * max(0, 50 - len(c))
        )
        click.echo(
            f"  {'Indicator':<50} {'Coverage':>8}  {'Records':>8}  {'Gaps':>5}  {'Last Run':<20}"
        )

        for slug, info in sorted(slugs, key=lambda x: -x[1]["coverage_pct"]):
            # Truncate long slugs
            display_slug = slug[:48] + ".." if len(slug) > 50 else slug
            cov = f"{info['coverage_pct']:>5.1f}%"
            records = f"{info['n_records']:>8,}"
            gap_str = f"{info['gap_count']:>5}" if info['gap_count'] else "    -"
            last_run = info.get("last_backfill") or info.get("last_update") or "never"
            if last_run != "never":
                last_run = last_run[:10]  # just the date part
            click.echo(f"  {display_slug:<50} {cov}  {records}  {gap_str}  {last_run}")

            if gaps and info["top_gaps"]:
                for g_start, g_end in info["top_gaps"]:
                    click.echo(f"      gap: {g_start} to {g_end}")

    click.echo()


@cli.command("test-parse")
@click.argument("slug")
@click.argument("target_date", default=None, required=False)
@click.option("--use-cache", is_flag=True,
              help="Read from data/cache/ instead of fetching live (for reproducing a past parse).")
def test_parse(slug, target_date, use_cache):
    """Debug: parse a single page and print results.

    By default fetches live so output reflects the current upstream page.
    Use --use-cache to read from local cache (warns: cache never expires).
    """
    td = date.fromisoformat(target_date) if target_date else None
    try:
        records = pipeline.test_parse(slug, td, use_cache=use_cache)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"Parsed {len(records)} records:\n")
    for r in records:
        parts = [f"date={r.date}"]
        if r.location:
            parts.append(f"loc={r.location}")
        if r.contract_month:
            parts.append(f"contract={r.contract_month}")
        parts.extend([
            f"col={r.column_name}",
            f"value={r.value}",
            f"raw={r.value_raw!r}",
            f"unit={r.unit}",
        ])
        click.echo("  " + " | ".join(parts))


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity")
@click.option("--category", default=None, help="Filter by category")
def export(commodity, category):
    """Regenerate CSV files from Parquet data."""
    if commodity:
        storage.export_csv(commodity)
    elif category:
        entries = load_catalog()
        commodities = {
            e.commodity for e in entries
            if e.category and e.category.value == category
        }
        for c in commodities:
            storage.export_csv(c)
    else:
        storage.export_all_csv()
    click.echo("CSV export complete.")


@cli.command("list")
@click.option("--category", default=None, help="Filter by category")
@click.option("--detail", is_flag=True, help="Show source, frequency, and description")
def list_catalog(category, detail):
    """Show all catalog entries."""
    entries = load_catalog()

    if category:
        entries = [e for e in entries if e.category and e.category.value == category]

    commodities = sorted({e.commodity for e in entries})

    for c in commodities:
        group = [e for e in entries if e.commodity == c and e.enabled]
        if not group:
            continue
        cat_label = group[0].category.value.upper() if group[0].category else "?"
        click.echo(f"\n{c.upper()} [{cat_label}] ({len(group)} indicators):")
        for e in group:
            status_str = "ON" if e.enabled else "OFF"
            click.echo(f"  [{status_str}] {e.slug:<55} {e.page_type.value:<16} {e.name}")
            if detail:
                if e.source:
                    click.echo(f"          source: {e.source}")
                if e.frequency:
                    click.echo(f"          frequency: {e.frequency}")
                if e.description:
                    click.echo(f"          {e.description}")


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity (e.g. soja, milho)")
@click.option("--force", is_flag=True, help="Rebuild from scratch even if output exists")
def basis(commodity, force):
    """Build materialized basis (physical - futures) time series."""
    from . import basis_builder

    commodities = [commodity] if commodity else None
    click.echo("Building basis time series...")
    summary = basis_builder.build_all(commodities=commodities, force=force)

    click.echo()
    click.echo("=== Basis Build Summary ===")
    total = 0
    for label, count in sorted(summary.items()):
        status = f"{count:>10,} rows" if count > 0 else "   skipped"
        click.echo(f"  {label:<20} {status}")
        total += count
    click.echo(f"  {'TOTAL':<20} {total:>10,} rows")
    click.echo()


@cli.command()
@click.option("-c", "--commodity", default=None, help="Filter by commodity")
@click.option("--category", default=None, help="Filter by category")
@click.option("--skip-basis", is_flag=True, help="Skip basis rebuild step")
@click.option("--skip-export", is_flag=True, help="Skip CSV export step")
def daily(commodity, category, skip_basis, skip_export):
    """Daily update: scrape latest prices, export CSVs, rebuild basis.

    \b
    Runs three steps in order:
      1. Update — scrape latest ~10 days from all indicators
      2. Export  — regenerate CSV files from Parquet
      3. Basis   — rebuild basis (physical - futures) time series

    \b
    Examples:
      na-etl daily              # full update, all commodities
      na-etl daily -c soja      # just soja
      na-etl daily --skip-basis # update + export only
    """
    from . import basis_builder

    # Step 1: Update prices
    click.echo("=" * 60)
    click.echo("Step 1/3: Updating prices (scraping latest pages)...")
    click.echo("=" * 60)
    pipeline.update(commodity=commodity, category=category)

    # Step 2: Export CSVs
    if not skip_export:
        click.echo()
        click.echo("=" * 60)
        click.echo("Step 2/3: Exporting CSVs from Parquet...")
        click.echo("=" * 60)
        if commodity:
            storage.export_csv(commodity)
        elif category:
            entries = load_catalog()
            commodities = {
                e.commodity for e in entries
                if e.category and e.category.value == category
            }
            for c in commodities:
                storage.export_csv(c)
        else:
            storage.export_all_csv()
        click.echo("CSV export complete.")
    else:
        click.echo("\nStep 2/3: Skipped CSV export.")

    # Step 3: Rebuild basis
    if not skip_basis:
        click.echo()
        click.echo("=" * 60)
        click.echo("Step 3/3: Rebuilding basis time series...")
        click.echo("=" * 60)
        commodities_list = [commodity] if commodity else None
        summary = basis_builder.build_all(commodities=commodities_list)

        total = 0
        for label, count in sorted(summary.items()):
            status_str = f"{count:>10,} rows" if count > 0 else "   skipped"
            click.echo(f"  {label:<20} {status_str}")
            total += count
        click.echo(f"  {'TOTAL':<20} {total:>10,} rows")
    else:
        click.echo("\nStep 3/3: Skipped basis rebuild.")

    click.echo()
    click.echo("Daily update complete.")


@cli.command("categories")
def list_categories():
    """List available categories with indicator counts."""
    entries = load_catalog()
    cats = cat_module.list_categories(entries)

    click.echo(f"\n{'Category':<14} {'Indicators':>11}  Commodities")
    click.echo("-" * 60)
    for cat in cats:
        cat_entries = cat_module.get_entries_by_category(entries, cat)
        commodities = sorted({e.commodity for e in cat_entries})
        click.echo(
            f"{cat.upper():<14} {len(cat_entries):>11}  {', '.join(commodities)}"
        )
    click.echo()


if __name__ == "__main__":
    cli()
