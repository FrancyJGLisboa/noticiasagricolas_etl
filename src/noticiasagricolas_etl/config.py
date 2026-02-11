"""Paths, constants, and settings."""

from pathlib import Path

BASE_DIR = Path.home() / "noticiasagricolas_etl"
DATA_DIR = BASE_DIR / "data"
PARQUET_DIR = DATA_DIR / "parquet"
PARQUET_BASIS_DIR = DATA_DIR / "parquet_basis"
CSV_DIR = DATA_DIR / "csv"
CACHE_DIR = DATA_DIR / "cache"
STATE_DIR = DATA_DIR / "state"
CATALOG_PATH = BASE_DIR / "catalog.yaml"

BASE_URL = "https://www.noticiasagricolas.com.br"
COTACOES_URL = f"{BASE_URL}/cotacoes"

REQUEST_DELAY_SECONDS = 2.0
BACKFILL_DELAY_SECONDS = 1.0  # faster for backfill (1 date per request)
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0
REQUEST_TIMEOUT = 30

USER_AGENT = "noticiasagricolas-etl/0.1.0 (commodity price research)"

BACKFILL_START_DATE = "2020-01-01"
DEFAULT_PAGE_DATES = 10  # number of dates returned by default page
BACKFILL_BATCH_SIZE = 50  # save to parquet every N dates

# Maps commodity string to its default Category value.
# Entries in catalog.yaml can override with an explicit `category:` field.
COMMODITY_CATEGORY_DEFAULTS: dict[str, str] = {
    "milho": "grains",
    "trigo": "grains",
    "arroz": "grains",
    "sorgo": "grains",
    "feijao": "grains",
    "soja": "oilseeds",
    "algodao": "oilseeds",
    "amendoim": "oilseeds",
    "sucroenergetico": "sugar",  # default; ethanol entries override to biofuels
    "cafe": "coffee",
    "boi-gordo": "livestock",
    "frango": "livestock",
    "suinos": "livestock",
    "leite": "dairy",
    "ovos": "livestock",
    "laranja": "citrus",
    "frutas": "fruits",
    "legumes": "vegetables",
    "verduras": "vegetables",
    "mandioca": "tubers",
    "cacau": "cocoa",
    "mercado-financeiro": "financial",
    "latex": "industrial",
    "silvicultura": "forestry",
}
