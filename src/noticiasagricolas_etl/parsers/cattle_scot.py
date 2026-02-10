"""Type 3: Cattle Scot Consultoria parser.

Table structure:
    Município | Boi Gordo - (R$/@ - à vista) | Boi Gordo - (R$/@ - prazo 30 dias) | Vaca Gorda (R$/@ - à vista)
    SP Barretos | 326,00 | 330,00 | 308,50

Multiple municipalities per block. Usually only ONE date-block (no date nav).
"""

from ..cleaning import (
    extract_unit_from_header,
    parse_brazilian_number,
    slugify_column,
)
from ..models import CatalogEntry, PriceRecord
from .base import BaseParser, CotacaoBlock


class CattleScotParser(BaseParser):
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        records = []

        # Headers: [Município, Boi Gordo vista, Boi Gordo prazo, Vaca Gorda vista, ...]
        # First column is location, remaining are data columns
        data_cols = []
        for i, h in enumerate(block.headers):
            if i == 0:
                continue  # skip municipality column
            col_name = slugify_column(h)
            col_unit = extract_unit_from_header(h) or entry.unit
            data_cols.append((i, col_name, col_unit))

        for row in block.rows:
            if not row:
                continue
            location = row[0].strip()

            for col_idx, col_name, col_unit in data_cols:
                if col_idx >= len(row):
                    continue
                raw = row[col_idx]
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
                        unit=col_unit,
                    )
                )
        return records
