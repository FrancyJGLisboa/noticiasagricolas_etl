"""Basis pair configuration: physical × futures definitions with conversion logic."""

from dataclasses import dataclass, field
from typing import Callable

# Conversion constants (USDA/CME official)
LB_PER_KG = 2.20462
SOJA_BU_KG = 27.2155  # 60 lbs
CORN_BU_KG = 25.4012  # 56 lbs
WHEAT_BU_KG = 27.2155  # 60 lbs (same as soja)
SACA_KG = 60.0
ARROBA_KG = 15.0

# Derived ratios: how many bushels/lbs in 1 saca or 1 arroba
BU_PER_SC_SOJA = SACA_KG / SOJA_BU_KG   # 2.2046
BU_PER_SC_CORN = SACA_KG / CORN_BU_KG    # 2.3621
BU_PER_SC_WHEAT = SACA_KG / WHEAT_BU_KG  # 2.2046
LB_PER_SC_COFFEE = SACA_KG * LB_PER_KG   # 132.277
LB_PER_ARROBA = ARROBA_KG * LB_PER_KG    # 33.069


@dataclass(frozen=True)
class BasisPairConfig:
    """Configuration for one physical × futures basis pair."""

    commodity: str
    physical_indicators: tuple[str, ...]  # one or more physical indicator slugs
    futures_indicator: str
    label: str
    physical_unit: str
    futures_unit: str
    needs_ptax: bool
    convert_futures: Callable[[float, float], float]
    # (futures_price, ptax) -> price in BRL per same unit as physical
    # ptax arg is ignored when needs_ptax=False


# ── 9 pair definitions ────────────────────────────────────────────────────────

BASIS_PAIRS: list[BasisPairConfig] = [
    # 1. Soja B3: US$/sc60kg -> BRL/sc60kg (just currency)
    BasisPairConfig(
        commodity="soja",
        physical_indicators=(
            "soja-mercado-fisico-sindicatos-e-cooperativas",
            "soja-mercado-fisico-ms",
        ),
        futures_indicator="soja-b3-pregao-regular",
        label="soja-b3",
        physical_unit="R$/sc60kg",
        futures_unit="US$/sc60kg",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * ptax,
    ),
    # 2. Soja CBOT: US$/bu -> BRL/sc60kg (unit + currency)
    BasisPairConfig(
        commodity="soja",
        physical_indicators=(
            "soja-mercado-fisico-sindicatos-e-cooperativas",
            "soja-mercado-fisico-ms",
        ),
        futures_indicator="soja-bolsa-de-chicago-cme-group",
        label="soja-cbot",
        physical_unit="R$/sc60kg",
        futures_unit="US$/bu",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * BU_PER_SC_SOJA * ptax,
    ),
    # 3. Milho B3: R$/sc60kg -> R$/sc60kg (direct, no conversion)
    BasisPairConfig(
        commodity="milho",
        physical_indicators=("milho-mercado-fisico-sindicatos-e-cooperativas",),
        futures_indicator="milho-b3-prego-regular",
        label="milho-b3",
        physical_unit="R$/sc60kg",
        futures_unit="R$/sc60kg",
        needs_ptax=False,
        convert_futures=lambda fut, ptax: fut,
    ),
    # 4. Milho CBOT: US$/bu -> BRL/sc60kg (unit + currency)
    BasisPairConfig(
        commodity="milho",
        physical_indicators=("milho-mercado-fisico-sindicatos-e-cooperativas",),
        futures_indicator="milho-bolsa-de-chicago-cme-group",
        label="milho-cbot",
        physical_unit="R$/sc60kg",
        futures_unit="US$/bu",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * BU_PER_SC_CORN * ptax,
    ),
    # 5. Trigo CBOT: US$/bu -> BRL/sc60kg (unit + currency)
    BasisPairConfig(
        commodity="trigo",
        physical_indicators=("trigo-mercado-fisico",),
        futures_indicator="trigo-bolsa-de-chicago-cme-group",
        label="trigo-cbot",
        physical_unit="R$/sc60kg",
        futures_unit="US$/bu",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * BU_PER_SC_WHEAT * ptax,
    ),
    # 6. Algodao NYBOT: US¢/lb -> BRL/@ (unit + cents + currency)
    BasisPairConfig(
        commodity="algodao",
        physical_indicators=("algodo-em-pluma-ao-produtor",),
        futures_indicator="algodao-bolsa-de-nova-iorque-nybot",
        label="algodao-nybot",
        physical_unit="R$/@",
        futures_unit="US¢/lb",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * LB_PER_ARROBA / 100 * ptax,
    ),
    # 7. Cafe B3: US$/sc60kg -> BRL/sc60kg (just currency)
    BasisPairConfig(
        commodity="cafe",
        physical_indicators=("cafe-arabica-mercado-fisico-tipo-6-7",),
        futures_indicator="cafe-arabica-4-5-b3-prego-regular",
        label="cafe-b3",
        physical_unit="R$/sc60kg",
        futures_unit="US$/sc60kg",
        needs_ptax=True,
        convert_futures=lambda fut, ptax: fut * ptax,
    ),
    # 8. Cafe NYBOT: website pre-converts to R$/sc60kg (no conversion needed)
    #    Source labels as ¢/lb but values are already R$/sc60kg (~2000-2500).
    #    Cross-verified: NYBOT raw ÷ PTAX ≈ B3 US$/sc on same date.
    BasisPairConfig(
        commodity="cafe",
        physical_indicators=("cafe-arabica-mercado-fisico-tipo-6-7",),
        futures_indicator="cafe-bolsa-de-nova-iorque-nybot",
        label="cafe-nybot",
        physical_unit="R$/sc60kg",
        futures_unit="R$/sc60kg",
        needs_ptax=False,
        convert_futures=lambda fut, ptax: fut,
    ),
    # 9. Boi Gordo B3: R$/@ -> R$/@ (direct, no conversion)
    #    Two physical sources: scot-consultoria (33 praças, no historical backfill)
    #    and indicador-esalq-bmf (single reference price, full 2020+ history).
    BasisPairConfig(
        commodity="boi-gordo",
        physical_indicators=(
            "boi-gordo-scot-consultoria",
            "boi-gordo-indicador-esalq-bmf",
        ),
        futures_indicator="boi-gordo-b3-prego-regular",
        label="boi-gordo-b3",
        physical_unit="R$/@",
        futures_unit="R$/@",
        needs_ptax=False,
        convert_futures=lambda fut, ptax: fut,
    ),
]


def get_pairs(commodities: list[str] | None = None) -> list[BasisPairConfig]:
    """Return configured pairs, optionally filtered by commodity."""
    if commodities is None:
        return BASIS_PAIRS
    return [p for p in BASIS_PAIRS if p.commodity in commodities]
