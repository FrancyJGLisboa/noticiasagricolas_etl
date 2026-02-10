"""Base parser: extract div.cotacao blocks and table.cot-fisicas."""

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..cleaning import extract_unit_from_header, parse_fechamento_date
from ..models import CatalogEntry, PriceRecord

logger = logging.getLogger(__name__)


class CotacaoBlock:
    """Represents a single div.cotacao block with its date and table."""

    def __init__(self, block_date: date, headers: list[str], rows: list[list[str]]):
        self.date = block_date
        self.headers = headers
        self.rows = rows


class BaseParser(ABC):
    """Abstract base parser for Noticias Agricolas pages."""

    def parse_html(self, html: str, entry: CatalogEntry) -> list[PriceRecord]:
        """Parse full HTML page into PriceRecord list."""
        soup = BeautifulSoup(html, "html.parser")
        blocks = self._extract_blocks(soup)
        records = []
        for block in blocks:
            records.extend(self.parse_block(block, entry))
        return records

    def _extract_blocks(self, soup: BeautifulSoup) -> list[CotacaoBlock]:
        """Extract all cotacao blocks from page."""
        blocks = []
        cotacao_divs = soup.select("div.cotacao")

        for div in cotacao_divs:
            # Extract date from div.fechamento
            fechamento = div.select_one("div.fechamento")
            if not fechamento:
                continue
            block_date = parse_fechamento_date(fechamento.get_text())
            if not block_date:
                continue

            # Extract table
            table = div.select_one("table.cot-fisicas")
            if not table:
                continue

            headers = self._extract_headers(table)
            rows = self._extract_rows(table)

            if headers and rows:
                blocks.append(CotacaoBlock(block_date, headers, rows))

        return blocks

    def _extract_headers(self, table: Tag) -> list[str]:
        """Extract header texts from table thead."""
        thead = table.select_one("thead")
        if not thead:
            return []
        ths = thead.select("th")
        return [th.get_text(strip=True) for th in ths]

    def _extract_rows(self, table: Tag) -> list[list[str]]:
        """Extract row data from table tbody."""
        tbody = table.select_one("tbody")
        if not tbody:
            return []
        rows = []
        for tr in tbody.select("tr"):
            cells = [td.get_text(strip=True) for td in tr.select("td")]
            if cells:
                rows.append(cells)
        return rows

    def _get_unit(self, headers: list[str], entry: CatalogEntry) -> str:
        """Extract unit from headers or fall back to catalog entry."""
        for h in headers:
            unit = extract_unit_from_header(h)
            if unit:
                return unit
        return entry.unit

    @abstractmethod
    def parse_block(
        self, block: CotacaoBlock, entry: CatalogEntry
    ) -> list[PriceRecord]:
        """Parse a single cotacao block into records. Implemented by subclasses."""
        ...
