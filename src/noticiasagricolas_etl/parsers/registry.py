"""Parser registry: maps PageType to parser instance."""

from ..models import PageType
from .b3_futures import B3FuturesParser
from .base import BaseParser
from .cattle_scot import CattleScotParser
from .cme_futures import CMEFuturesParser
from .indicator import IndicatorParser
from .physical_market import PhysicalMarketParser

_PARSERS: dict[PageType, BaseParser] = {
    PageType.INDICATOR: IndicatorParser(),
    PageType.PHYSICAL_MARKET: PhysicalMarketParser(),
    PageType.CATTLE_SCOT: CattleScotParser(),
    PageType.B3_FUTURES: B3FuturesParser(),
    PageType.CME_FUTURES: CMEFuturesParser(),
}


def get_parser(page_type: PageType) -> BaseParser:
    """Get parser instance for given page type."""
    return _PARSERS[page_type]
