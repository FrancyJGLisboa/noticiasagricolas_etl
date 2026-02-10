"""Pydantic models and enums."""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PageType(str, Enum):
    INDICATOR = "indicator"
    PHYSICAL_MARKET = "physical_market"
    CATTLE_SCOT = "cattle_scot"
    B3_FUTURES = "b3_futures"
    CME_FUTURES = "cme_futures"


class Category(str, Enum):
    GRAINS = "grains"
    OILSEEDS = "oilseeds"
    SUGAR = "sugar"
    BIOFUELS = "biofuels"
    COFFEE = "coffee"
    LIVESTOCK = "livestock"
    DAIRY = "dairy"
    CITRUS = "citrus"
    FRUITS = "fruits"
    VEGETABLES = "vegetables"
    TUBERS = "tubers"
    COCOA = "cocoa"
    FINANCIAL = "financial"
    INDUSTRIAL = "industrial"
    FORESTRY = "forestry"


class CatalogEntry(BaseModel):
    commodity: str
    slug: str
    name: str
    page_type: PageType
    unit: str = ""
    has_date_nav: bool = True
    enabled: bool = True
    category: Optional[Category] = None
    source: Optional[str] = None
    frequency: Optional[str] = None
    description: Optional[str] = None


class PriceRecord(BaseModel):
    date: date
    commodity: str
    indicator: str
    indicator_name: str
    location: Optional[str] = None
    contract_month: Optional[str] = None
    column_name: str
    value: Optional[float] = None
    value_raw: str
    unit: str
