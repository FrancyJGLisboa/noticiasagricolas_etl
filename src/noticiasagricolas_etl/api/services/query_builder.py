"""Parameterized SQL WHERE-clause builder to prevent injection."""

from datetime import date


class WhereBuilder:
    """Builds parameterized SQL WHERE clauses safely."""

    def __init__(self):
        self.conditions: list[str] = []
        self.params: list = []

    def add(self, column: str, value, op: str = "=") -> "WhereBuilder":
        if value is not None:
            self.conditions.append(f"{column} {op} ?")
            self.params.append(value)
        return self

    def add_in(self, column: str, values: list | None) -> "WhereBuilder":
        if values:
            placeholders = ", ".join("?" for _ in values)
            self.conditions.append(f"{column} IN ({placeholders})")
            self.params.extend(values)
        return self

    def add_date_range(
        self,
        column: str = "date",
        date_from: str | date | None = None,
        date_to: str | date | None = None,
    ) -> "WhereBuilder":
        if date_from:
            self.conditions.append(f"{column} >= ?")
            self.params.append(str(date_from))
        if date_to:
            self.conditions.append(f"{column} <= ?")
            self.params.append(str(date_to))
        return self

    def build(self) -> tuple[str, list]:
        """Return (WHERE clause string, params list). Empty string if no conditions."""
        if not self.conditions:
            return "", []
        return "WHERE " + " AND ".join(self.conditions), self.params
