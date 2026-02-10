"""Type 1: Indicator parser (CEPEA/ESALQ).

Table structure:
    Data | Valor R$ | Variação (%)
    06/02/2026 | 126,43 | +0,65

One row per date-block (single value + variation).
"""

from ..cleaning import parse_brazilian_number, parse_variation, slugify_column
from ..models import CatalogEntry, PriceRecord
from .base import BaseParser, CotacaoBlock


class IndicatorParser(BaseParser):
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        records = []
        unit = self._get_unit(block.headers, entry)

        # Headers: [Data, Valor R$, Variação (%)]
        # Map col index -> (column_name, parser_func)
        col_map = []
        for i, h in enumerate(block.headers):
            slug = slugify_column(h)
            if slug in ("data",):
                col_map.append(None)  # skip date column
            else:
                col_map.append(slug)

        for row in block.rows:
            for i, col_name in enumerate(col_map):
                if col_name is None or i >= len(row):
                    continue
                raw = row[i]
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
                        location=None,
                        contract_month=None,
                        column_name=col_name,
                        value=value,
                        value_raw=raw,
                        unit=unit if "variacao" not in col_name else "%",
                    )
                )
        return records
