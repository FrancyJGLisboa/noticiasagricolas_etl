"""Type 2: Physical Market parser.

Table structure:
    Praça | Preço (R$/Sc de 60 kg) | Variação (%)
    Não-Me-Toque/RS (Cotrijal) | 117,00 | 0,00

Also handles variant first-column names:
    Estado, Bolsa, Moeda, Tipo, Região/Tipo, etc.

And 4-column variants:
    Data | Região | Valor (R$/T) | Variação (%)

Multiple locations per date-block, multiple date-blocks per page.
Subheader rows (with *** or all-empty data) are skipped.
"""

from ..cleaning import parse_brazilian_number, parse_variation, slugify_column
from ..models import CatalogEntry, PriceRecord
from .base import BaseParser, CotacaoBlock

# Headers that indicate a "location-like" first column (not a data column)
_LOCATION_HEADERS = {
    "praca", "estado", "estados", "bolsa", "moeda", "tipo",
    "regiao", "regiao_tipo", "municipio", "cidade",
    "referencia", "produto", "local", "variedade",
    "mes", "vencimento", "mes_referencia",
}


def _is_subheader_row(row: list[str], data_start: int) -> bool:
    """Check if row is a section subheader (all data cells are *** or empty)."""
    data_cells = row[data_start:]
    if not data_cells:
        return True
    return all(
        c.strip() in ("", "***", "**", "*", "-", "--", "---")
        for c in data_cells
    )


class PhysicalMarketParser(BaseParser):
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        records = []
        unit = self._get_unit(block.headers, entry)

        if not block.headers:
            return records

        # Determine which columns are "label" columns vs data columns.
        # Some tables have: [Praça, Preço, Variação]  (1 label col)
        # Others have: [Data, Região, Valor, Variação]  (2 label cols)
        # Detect by checking header slugs
        label_cols = 0
        data_cols = []
        for i, h in enumerate(block.headers):
            slug = slugify_column(h)
            if slug in _LOCATION_HEADERS or slug == "data":
                label_cols = i + 1
            else:
                data_cols.append((i, slug))

        # If no label cols detected, assume first col is label
        if label_cols == 0:
            label_cols = 1
            data_cols = [
                (i, slugify_column(h))
                for i, h in enumerate(block.headers)
                if i > 0
            ]

        for row in block.rows:
            if not row or len(row) <= label_cols:
                continue

            # Skip subheader/section-divider rows
            if _is_subheader_row(row, label_cols):
                continue

            # Build location string from label columns (skip "Data"-type cols)
            location_parts = []
            for i in range(label_cols):
                slug = slugify_column(block.headers[i]) if i < len(block.headers) else ""
                cell = row[i].strip() if i < len(row) else ""
                if slug != "data" and cell:
                    location_parts.append(cell)
            location = " - ".join(location_parts) if location_parts else row[0].strip()

            for col_idx, col_name in data_cols:
                if col_idx >= len(row):
                    continue
                raw = row[col_idx]
                if "variacao" in col_name:
                    value = parse_variation(raw)
                else:
                    value = parse_brazilian_number(raw)

                records.append(
                    PriceRecord(
                        date=block.date,
                        commodity=entry.commodity,
                        indicator=entry.slug,
                        indicator_name=entry.name,
                        location=location,
                        contract_month=None,
                        column_name=col_name,
                        value=value,
                        value_raw=raw,
                        unit=unit if "variacao" not in col_name else "%",
                    )
                )
        return records
