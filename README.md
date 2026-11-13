# Noticias Agricolas — Brazilian Ag Price Platform

A daily-updated price platform for Brazilian agricultural commodities, with a
catalog of analytics services exposed over **CLI**, **REST API**, and **MCP**
(Model Context Protocol) — built so AI agents and founders can ship alerting,
reporting, and decision-support products without re-doing the data layer.

```
                ┌───────────────────────┐
                │ noticiasagricolas.com │
                └───────────┬───────────┘
                            │  daily scrape
                ┌───────────▼───────────┐    Parquet + CSV
                │    ETL pipeline       │──▶ data/parquet/...
                │    (na-etl daily)     │    data/parquet_basis/...
                └───────────┬───────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
       ┌────▼────┐    ┌─────▼─────┐   ┌────▼─────┐
       │   CLI   │    │ REST API  │   │ MCP tool │
       │ na-etl  │    │  na-api   │   │  na-mcp  │
       └─────────┘    └─────┬─────┘   └────┬─────┘
                            │              │
                       FastAPI/Auth    Claude / GPT /
                       /v1/analytics   any MCP client
```

**Coverage:** 158 indicators · 23 commodities · ~2,200 praças · 6 years history · 9 materialized basis pairs.

---

## For builders — pick your transport

| You're building... | Use | Why |
|---|---|---|
| AI assistant / chatbot / Claude Desktop tool | **MCP** (`na-mcp`) | Tool docstrings written for LLM tool-selection, in PT |
| Web dashboard / mobile app / 3rd-party integration | **REST API** (`na-api`) | OpenAPI auto-docs at `/docs`, API key auth with tiers |
| Cron jobs / Python notebooks / on-host services | **Direct import** | `from noticiasagricolas_etl.api.services import ...` — zero network overhead |
| Operational tasks (scrape, backfill, charts) | **CLI** (`na-etl`) | Idempotent, resumable, single-machine |

### Quickstart — first AI agent in 5 minutes

```bash
git clone https://github.com/FrancyJGLisboa/noticiasagricolas_etl
cd noticiasagricolas_etl
uv sync
na-etl daily              # one-time data refresh (~6 min)
```

**Try the MCP server** (Claude Desktop):

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "noticiasagricolas": {
      "command": "na-mcp"
    }
  }
}
```

Restart Claude Desktop, then ask: *"Onde está o basis da soja em Sorriso/MT vs CBOT hoje?"*

**Try the REST API**:

```bash
na-api &                 # serves on http://localhost:8000
open http://localhost:8000/docs   # OpenAPI playground
curl "http://localhost:8000/v1/analytics/basis-percentile?commodity=soja&location=Sorriso/MT"
curl "http://localhost:8000/v1/analytics/basis-opportunities?commodity=soja"
```

**Try direct import** (fastest, no HTTP):

```bash
python examples/daily_briefing.py
```

---

## The 18 services

All return JSON with a Portuguese **`interpretation`** field already written —
your agent quotes the string instead of composing prose.

### Discovery (catalog + raw queries)

| Service | What it answers |
|---|---|
| `list_commodities` | What commodities + indicators exist |
| `list_locations` | Praças (cities/regions) available, optionally filtered |
| `get_prices` | Raw price series with filters (date range, location, measure) |
| `get_latest_prices` | Most recent prices for one commodity / indicator |

### Basis (physical − futures)

| Service | What it answers |
|---|---|
| `get_basis` | Basis time series for a commodity-pair-praça |
| `get_basis_panel` | Query the materialized basis panel (BRL, USD, ¢/bu, %) |
| `get_basis_percentile` | "Is today's basis cheap or expensive vs typical?" (P0-100 + interp) |
| `basis-opportunities` REST endpoint | Seasonal ranking with change, anomaly, hedge, coverage, and freshness |
| `get_port_basis_tracker` | Basis percentile across all Brazilian export ports, ranked from low to high |
| `get_price_attribution` | Decompose ΔP_local into FX vs CBOT vs basis buckets |
| `get_fx_adjusted` | Convert prices BRL ↔ USD via PTAX |

### Curva de futuros

| Service | What it answers |
|---|---|
| `get_futures_curve` | All active contracts on a date with contango/backwardation label |
| `get_term_structure` | Slope of the curve + regime (contango forte / leve / flat / back. leve / forte) — **snapshot today** |
| `get_curve_seasonal` | Today's slope vs ±2-week seasonal window across all past years (z-score + regime: muito_abaixo / abaixo / tipico / acima / muito_acima) — **fora do padrão?** |

### Crush margin (esmagamento de soja)

| Service | What it answers |
|---|---|
| `get_crush_margin` | (farelo + óleo) − soja, time series |
| `get_crush_percentile` | Where today's margin sits in N-year history |

### Distribuição regional

| Service | What it answers |
|---|---|
| `get_regional_spread` | Price dispersion across praças (mean, std, IQR, by state) |
| `get_rankings` | Praças ranked cheapest → most expensive |
| `get_port_spread` | Porto vs interior premium + percentile (export window indicator) |

### Análise quantitativa

| Service | What it answers |
|---|---|
| `get_seasonal` | Multi-year seasonal averages with current-year comparison |
| `get_ratio` | Ratio between 2 indicators (e.g. soja:milho) for safra decisions |
| `get_vol_regime` | Volatility regime classification (low / med-low / med-high / high) |
| `get_anomaly` | Z-score outlier detection (data quality + market signal) |
| `get_hedge_fit` | OLS β + R² + hedge quality (POBRE/MARGINAL/BOM/EXCELENTE) |

Every percentile-based service returns a **plain-Portuguese interpretation** like:

> `"Basis no percentil 92, acima da faixa histórica usual dos últimos 5 anos."`

The agent quotes it; no prompt-engineering needed for narrative output.

---

## Data layers

| Layer | Path | What's in it |
|---|---|---|
| **Raw normalized** | `data/parquet/commodity={name}/data.parquet` | One row per observation. 9 base cols + 7 derived (`measure`, `currency`, `unit_std`, `price_basis`, `contract`, `state`, `market_type`). |
| **Materialized basis** | `data/parquet_basis/commodity={name}/data.parquet` | 9 pairs × 2,200 praças × dates. PTAX-converted, unit-converted (BRL/USD/¢/bu/%). |
| **Charts** | `data/charts/*.html` | 5 Plotly viz: seasonality (combined), multi-location, deviation map, heatmap z-score, companion CSV. |

Daily refresh: `na-etl daily` runs scrape → CSV export → basis rebuild → chart regen as one transactional sequence.

### Daily quote quality snapshot

Each basis rebuild also writes `data/csv/quote-quality.csv`.
The file contains one row for each `(commodity, date, location)` needed by the latest rebuilt basis references.
It preserves the number, minimum, maximum, mean, range, indicators, and raw labels behind each physical mean.

`classification` uses four values:

- `single`: one physical quote.
- `consensus`: multiple quotes with the same value.
- `source_dispersion`: multiple quotes with different values.
- `mixed_delivery`: source labels explicitly contain both a spot quote and a dated delivery quote.

The ETL does not infer delivery terms from an unspecified label.
A filtered commodity build replaces that commodity and preserves the other commodity rows already in the file.
Consumers must reject a row when its date or mean does not match the basis snapshot.

### Roll-adjusted basis columns

Every `basis-*.csv` appends roll metadata and four adjusted basis columns.
The ETL detects a contract change inside each `(location, futures_indicator)` series.
It measures the futures gap on the last prior source date when both contracts have quotes.
The search uses at most five source trading dates.

`basis_brl_adj`, `basis_usd_adj`, `basis_centavos_sc_adj`, and
`basis_cents_bu_adj` use the current contract as their anchor.
The adjusted value equals the raw value on the latest date of each series.
Earlier segments subtract the gaps from all later rolls.

If the ETL cannot measure a roll gap, `roll_gap_missing` is true.
The adjusted series keeps that contract step unchanged.
Valid rolls on both sides remain adjusted, and the missing gap creates no null rows.

Adjusted levels are analytical series for changes, swings, and anomaly detection.
They are not prices that a market participant traded.
Current-level percentiles must continue to use the unadjusted basis columns.

---

## Auth (REST API only)

API keys stored in SQLite (`data/auth.db`), with tiers + per-endpoint rate limits.

```bash
# Mint a key (run from server host)
python -c "from noticiasagricolas_etl.api.auth import create_api_key; print(create_api_key('mycompany', tier='paid'))"

# Use it
curl -H "Authorization: Bearer na_xxx" http://localhost:8000/v1/analytics/basis-percentile?...
```

Free tier (no key) gets a lower rate limit. MCP and direct-import bypass auth (local-only).

---

## Common patterns for AI services

### Daily alert agent (cron-style)

Walk pairs/praças, fire only on extreme percentiles or anomalies. The
`interpretation` string is your alert body — no prose composition needed.

```python
from noticiasagricolas_etl.api.services import (
    basis_percentile_service, anomaly_service, vol_regime_service,
)

for praca in ["Sorriso/MT", "Rio Verde/GO"]:
    bp = basis_percentile_service.get_basis_percentile(
        commodity="soja", location=praca,
        futures_indicator="soja-bolsa-de-chicago-cme-group",
    )
    if bp.get("percentile", 50) >= 90 or bp.get("percentile", 50) <= 10:
        send_alert(bp["interpretation"])
```

### Daily briefing report

See `examples/daily_briefing.py` — composes a markdown report from `get_basis_percentile`, `get_term_structure`, `get_crush_percentile`, and `get_price_attribution`. Runs as-is.

### Decision support / position sizing

Combine `get_vol_regime` (size) + `get_hedge_fit` (which contract) +
`get_ratio` (crop allocation) for a structured decision input.

---

## Operational reference (ETL / data engineering)

### Daily refresh

```bash
na-etl daily                     # full: scrape + export + basis + charts
na-etl daily --skip-charts       # skip viz step
na-etl daily -c soja             # single commodity
```

### Historical backfill

```bash
na-etl backfill -c soja --start-date 2020-01-01
na-etl backfill --slug soja-indicador-cepea-esalq-porto-paranagua --start-date 2020-01-01
./scripts/backfill_all.sh --delay 0.5    # parallel 4 streams
```

Resumable: shutting down mid-backfill is safe. Re-running the same command skips dates already in parquet (loses ≤50 seconds of unsaved batch).

### Status & inspection

```bash
na-etl status --summary          # category-level dashboard
na-etl list                      # full catalog
na-etl test-parse <slug> [date]  # debug a single page parse
```

---

## Setup

```bash
git clone https://github.com/FrancyJGLisboa/noticiasagricolas_etl
cd noticiasagricolas_etl
uv sync                          # or: pip install -e ".[dev]"
```

Python 3.11+. Dependencies: `requests`, `beautifulsoup4`, `pandas`, `pyarrow`, `duckdb`, `click`, `pydantic`, `fastapi`, `mcp`.

### Docker

```bash
docker build -t na-etl .
docker run -p 8000:8000 -v $(pwd)/data:/app/data na-etl
# defaults to na-api on $PORT (8000)
```

### Tests

```bash
uv run pytest tests/ -m "not live"      # fast, no network (default)
uv run pytest tests/ -m live            # hit the live website
```

400+ tests across parsing, cleaning, basis math, services, viz reshapes.

---

## What's still rough (next steps for builders)

- **Service responses are typed dicts, not Pydantic models** — TypeScript clients have to hand-type. Migrating the 16 services to Pydantic response models would unlock auto-generated client SDKs.
- **No webhook / event layer** — alert agents poll. A push channel (Slack/email/webhook) would be a natural add.
- **No multi-tenant data scope** — all keys see all commodities. Fine for single-org use; needs isolation for multi-tenant SaaS.
- **MCP server is stdio-only** — for hosted multi-user MCP, switch to FastMCP's SSE/streamable mode.

PRs welcome on these.

---

## Data sources

Aggregated from [noticiasagricolas.com.br](https://www.noticiasagricolas.com.br):
CEPEA/ESALQ (USP), B3, CME/CBOT/NYBOT, regional cooperatives, Scot Consultoria.
