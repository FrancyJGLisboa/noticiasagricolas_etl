"""Query service for precomputed basis panel data."""

from .. import database as db
from .query_builder import WhereBuilder


def get_basis_panel(
    commodity: str | None = None,
    location: str | None = None,
    state: str | None = None,
    futures_indicator: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> dict:
    """Query the precomputed basis view with full filtering + pagination."""
    wb = WhereBuilder()
    wb.add("commodity", commodity)
    wb.add("location", location)
    wb.add("state", state)
    wb.add("futures_indicator", futures_indicator)
    wb.add_date_range(date_from=date_from, date_to=date_to)
    where, params = wb.build()

    # Count
    count_sql = f"SELECT COUNT(*) AS total FROM basis {where}"
    total = db.query(count_sql, params)[0]["total"]

    # Data
    data_sql = f"""
        SELECT * FROM basis
        {where}
        ORDER BY date DESC, commodity, location
        LIMIT ? OFFSET ?
    """
    rows = db.query(data_sql, params + [limit, offset])

    for row in rows:
        if row.get("date") is not None:
            row["date"] = str(row["date"])

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": rows,
    }
