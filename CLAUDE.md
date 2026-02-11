# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ETL system that scrapes Brazilian commodity prices from noticiasagricolas.com.br into Parquet/CSV files. 158 indicators across 23 commodities (grains, oilseeds, sugar, biofuels, coffee, livestock, etc.) with data from 2020+.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Run tests (unit only, no network)
pytest tests/ -m "not live"

# Run a single test file
pytest tests/test_cleaning.py -v

# Run live integration tests (hits real website)
pytest tests/ -m live

# CLI (installed as na-etl)
na-etl update                   # incremental daily update
na-etl backfill -c soja --start-date 2020-01-01  # historical backfill
na-etl status --summary         # coverage dashboard
na-etl list                     # catalog browser
na-etl test-parse <slug> [date] # debug single page parse
na-etl export                   # regenerate CSVs from Parquet

# Parallel backfill (4 streams)
./scripts/backfill_all.sh --delay 0.5
```

## Architecture

**Data flow**: HTTP fetch → HTML parse → clean values → store Parquet → normalize derived columns

```
cli.py          Click CLI, 8 commands, delegates to pipeline
pipeline.py     Orchestration: backfill (date-by-date) and update (latest page)
scraper.py      Rate-limited HTTP with retries, optional caching
parsers/        5 parser classes dispatched via registry.py by PageType enum
  indicator.py       CEPEA/ESALQ format
  physical_market.py Multi-location tables
  b3_futures.py      B3 contracts
  cme_futures.py     CME/CBOT contracts
  cattle_scot.py     Livestock variant
cleaning.py     Brazilian number ("126,43" → 126.43) and date parsing
normalize.py    Adds 7 derived columns (measure, currency, unit_std, price_basis, contract, state, market_type)
storage.py      Parquet/CSV I/O, deduplication on 5-tuple key, dashboard metrics
state.py        JSON checkpoint persistence (data/state/last_run.json)
catalog.py      Loads catalog.yaml (158 indicator definitions)
models.py       Pydantic: CatalogEntry, PriceRecord, PageType/Category enums
config.py       Paths, delays, URLs, commodity→category defaults
```

**Key design decisions:**
- All paths are rooted at `~/noticiasagricolas_etl/` (config.py `BASE_DIR`)
- Parquet partitioned by commodity: `data/parquet/commodity={name}/data.parquet`
- Backfill checkpoints every 50 dates to Parquet; on resume, reads existing Parquet to skip covered dates
- Parser selection is driven by `page_type` field in `catalog.yaml` entries, dispatched through `parsers/registry.py`
- Normalization is rule-based pattern matching on indicator slug, column name, and unit strings
- Tests use monkeypatch to redirect config paths to temp directories; HTML fixtures in `tests/fixtures/`

## Catalog

`catalog.yaml` at project root defines all 158 indicators. Each entry has: commodity, slug, name, page_type, unit, category, source. The slug maps directly to URL paths on the source website.
