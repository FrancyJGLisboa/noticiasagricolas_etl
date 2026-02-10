# Noticias Agricolas ETL

Historical commodity price database for Brazilian agricultural markets. Extracts daily prices from [noticiasagricolas.com.br](https://www.noticiasagricolas.com.br) into tidy Parquet/CSV files.

## Coverage

| Category | Commodities | Indicators | Sources |
|----------|------------|------------|---------|
| **Grains** | Corn (milho), Wheat (trigo), Rice (arroz), Sorghum (sorgo) | 21 | CEPEA/ESALQ, B3, CME, cooperatives |
| **Oilseeds** | Soybeans (soja), Cotton (algodao), Peanuts (amendoim) | 20 | CEPEA/ESALQ, B3, CME, CBOT, physical markets |
| **Sugar** | Crystal, Refined, ATR, Cane | 6 | CEPEA, NYBOT, producers |
| **Biofuels** | Ethanol (anhydrous, hydrated) | 5 | CEPEA, B3, CME |

158 indicators total across 23 commodity categories. Historical data from 2020 onwards, updated daily.

## Data Format

One observation per row (tidy format):

| Column | Type | Example |
|--------|------|---------|
| `date` | date | 2024-06-15 |
| `commodity` | str | soja |
| `indicator` | str | soja-mercado-fisico-sindicatos-e-cooperativas |
| `indicator_name` | str | Soja - Mercado Físico |
| `location` | str | Paranaguá/PR (Insoy Commodities) |
| `contract_month` | str | Julho/2024 |
| `column_name` | str | preco |
| `value` | float | 136.43 |
| `value_raw` | str | 136,43 |
| `unit` | str | R$/Sc de 60 kg |

Output files:
- `data/parquet/commodity={name}/data.parquet` — partitioned by commodity
- `data/csv/{name}.csv` — one CSV per commodity

## Setup

```bash
cd ~/noticiasagricolas_etl
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Commands

### Daily Update (latest ~10 dates for all indicators)

```bash
na-etl update                   # all indicators
na-etl update -c soja           # single commodity
```

Takes ~6 minutes for all 158 indicators.

### Historical Backfill

```bash
# Single commodity
na-etl backfill -c soja --start-date 2020-01-01

# Single indicator
na-etl backfill --slug soja-indicador-cepea-esalq-porto-paranagua --start-date 2020-01-01

# Custom delay (default: 1s)
na-etl backfill -c milho --start-date 2020-01-01 --delay 0.5

# Force re-fetch (ignore existing data)
na-etl backfill -c soja --start-date 2020-01-01 --no-resume
```

### Full Backfill (Grains + Oilseeds + Sugar + Biofuels)

```bash
na-etl backfill -c soja --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c milho --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c trigo --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c arroz --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c sorgo --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c algodao --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c amendoim --start-date 2020-01-01 --delay 1.0 && \
na-etl backfill -c sucroenergetico --start-date 2020-01-01 --delay 1.0
```

Estimated time: ~23 hours at 1s/request for 52 indicators x ~1,600 business days.

**Resumable**: You can shut down at any point. Re-run the exact same command and it skips dates already in Parquet, continuing from where it stopped. You lose at most ~50 seconds of work (the current unsaved batch).

### Other Commands

```bash
na-etl status                   # show date coverage per indicator
na-etl status -c soja           # single commodity
na-etl list                     # show all catalog entries
na-etl export                   # regenerate CSVs from Parquet
na-etl test-parse <slug> [date] # debug a single page
```

## How Resume Works

1. Every 50 dates, records are checkpointed to Parquet
2. On restart, the backfill reads existing Parquet to find covered dates
3. Only uncovered business days are fetched
4. State is saved per indicator in `data/state/last_run.json`

## Data Sources

All data is scraped from [noticiasagricolas.com.br](https://www.noticiasagricolas.com.br), which aggregates prices from:

- **CEPEA/ESALQ** (USP) — benchmark indicators for soy, corn, cotton, ethanol, coffee, cattle
- **B3** (Brazilian exchange) — futures contracts
- **CME/CBOT/NYBOT** — Chicago/New York futures
- **Regional cooperatives** — physical market prices at 30+ locations
- **Scot Consultoria** — cattle prices

## Tests

```bash
# Unit tests (no network)
.venv/bin/python -m pytest tests/ -m "not live"

# Include live integration tests
.venv/bin/python -m pytest tests/ -m live
```

115 tests covering parsing, cleaning, resume logic, and edge cases.
