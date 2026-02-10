"""Type 4: B3 Futures parser.

Table structure:
    Contrato - Mês | Fechamento (US$/sc 60 kg) | Variação (%)
    Julho/2026 | 25,11 | 0,20

Multiple contracts per date-block.
"""

from ..cleaning import parse_brazilian_number, parse_variation, slugify_column
from ..models import CatalogEntry, PriceRecord
from .base import BaseParser, CotacaoBlock


class B3FuturesParser(BaseParser):
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        records = []
        unit = self._get_unit(block.headers, entry)

        # Headers: [Contrato - Mês, Fechamento (...), Variação (%)]
        # First column is contract month, remaining are data columns
        data_cols = []
        for i, h in enumerate(block.headers):
            if i == 0:
                continue  # skip contract column
            data_cols.append((i, slugify_column(h)))

        for row in block.rows:
            if not row:
                continue
            contract_month = row[0].strip()

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
                        location=None,
                        contract_month=contract_month,
                        column_name=col_name,
                        value=value,
                        value_raw=raw,
                        unit=unit if "variacao" not in col_name else "%",
                    )
                )
        return records
