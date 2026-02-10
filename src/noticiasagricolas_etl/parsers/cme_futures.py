"""Type 5: CME Futures parser.

Table structure:
    Contrato - Mês | Fechamento (US$ / Bushel) | Variação (cents/bu) | Variação (%)
    Março/26 | 11,1525 | +3,00 | +0,27

Multiple contracts per date-block, 4 columns.
"""

from ..cleaning import parse_brazilian_number, parse_variation, slugify_column
from ..models import CatalogEntry, PriceRecord
from .base import BaseParser, CotacaoBlock


class CMEFuturesParser(BaseParser):
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        records = []
        unit = self._get_unit(block.headers, entry)

        # Headers: [Contrato - Mês, Fechamento (...), Variação (cents/bu), Variação (%)]
        data_cols = []
        for i, h in enumerate(block.headers):
            if i == 0:
                continue
            col_name = slugify_column(h)
            # Determine unit for this column
            if "cents" in col_name:
                col_unit = "cents/bu"
            elif "variacao" in col_name:
                col_unit = "%"
            else:
                col_unit = unit
            data_cols.append((i, col_name, col_unit))

        for row in block.rows:
            if not row:
                continue
            contract_month = row[0].strip()

            for col_idx, col_name, col_unit in data_cols:
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
                        unit=col_unit,
                    )
                )
        return records
