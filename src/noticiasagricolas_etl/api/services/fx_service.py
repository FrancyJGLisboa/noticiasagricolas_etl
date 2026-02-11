"""FX conversion using PTAX (BRL/USD) from the mercado-financeiro indicators."""

import functools

from .. import database as db
from .query_builder import WhereBuilder

# Common PTAX indicator slugs in the catalog
PTAX_INDICATORS = [
    "cambio-ptax-venda",
    "cambio-ptax",
    "dolar-ptax-venda",
]


@functools.lru_cache(maxsize=1)
def _find_ptax_indicator() -> str | None:
    """Find the PTAX indicator available in the data. Cached after first call."""
    for slug in PTAX_INDICATORS:
        rows = db.query(
            "SELECT 1 FROM prices WHERE indicator = ? LIMIT 1",
            [slug],
        )
        if rows:
            return slug
    # Fallback: any mercado-financeiro indicator with 'ptax' or 'dolar' in name
    rows = db.query("""
        SELECT DISTINCT indicator FROM prices
        WHERE commodity = 'mercado-financeiro'
          AND (indicator LIKE '%ptax%' OR indicator LIKE '%dolar%')
          AND measure = 'price'
        LIMIT 1
    """)
    return rows[0]["indicator"] if rows else None


def get_fx_adjusted(
    indicator: str,
    target_currency: str = "USD",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Convert indicator prices BRL<->USD using PTAX.

    If source is BRL and target is USD: divide by PTAX.
    If source is USD and target is BRL: multiply by PTAX.
    """
    ptax_slug = _find_ptax_indicator()
    if not ptax_slug:
        return {"error": "No PTAX indicator found in data", "data": []}

    wb = WhereBuilder()
    wb.add("indicator", indicator)
    wb.add("measure", "price")
    wb.add_date_range(date_from=date_from, date_to=date_to)
    where, params = wb.build()

    wb2 = WhereBuilder()
    wb2.add("indicator", ptax_slug)
    wb2.add("measure", "price")
    wb2.add_date_range(date_from=date_from, date_to=date_to)
    ptax_where, ptax_params = wb2.build()

    sql = f"""
        WITH source AS (
            SELECT date, location, value AS original_price, currency, unit
            FROM prices {where}
        ),
        ptax AS (
            SELECT date, value AS ptax_rate
            FROM prices {ptax_where}
        )
        SELECT s.date, s.location, s.original_price, s.currency AS original_currency,
               pt.ptax_rate,
               CASE
                   WHEN s.currency = 'BRL' AND ? = 'USD'
                        THEN s.original_price / NULLIF(pt.ptax_rate, 0)
                   WHEN s.currency = 'USD' AND ? = 'BRL'
                        THEN s.original_price * pt.ptax_rate
                   ELSE s.original_price
               END AS adjusted_price,
               ? AS target_currency,
               s.unit
        FROM source s
        INNER JOIN ptax pt ON s.date = pt.date
        ORDER BY s.date DESC, s.location
    """
    all_params = params + ptax_params + [target_currency, target_currency, target_currency]
    rows = db.query(sql, all_params)

    for row in rows:
        row["date"] = str(row["date"])

    return {
        "indicator": indicator,
        "target_currency": target_currency,
        "ptax_indicator": ptax_slug,
        "data": rows,
    }
