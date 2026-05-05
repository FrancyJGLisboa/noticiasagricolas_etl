"""Normalization layer: consistent column values across all indicators.

Adds 7 derived columns alongside originals for queryability:
  measure, currency, unit_std, price_basis, contract, state, market_type
"""

import logging
import math
import re
from typing import Optional

from .models import Measure

logger = logging.getLogger(__name__)


def _is_nan(val) -> bool:
    """Check if a value is NaN (handles float NaN from pandas)."""
    try:
        return val is not None and isinstance(val, float) and math.isnan(val)
    except (TypeError, ValueError):
        return False

# ── measure: what was measured ───────────────────────────────────────────────

# column_name → Measure mapping. The lookup is exhaustive over column_name
# slugs the current parsers produce. Anything not in these sets is treated as
# `Measure.PRICE`, but we WARN on first sighting of an unknown one — silent
# fallback used to mean a new parser variant could mis-classify forever.
_CHANGE_PCT = {
    "variacao_pct", "variacao", "variacao_diaria", "variacao_semana",
}

_CHANGE_ABS = {
    "variacao_cents", "variacao_pontos",
}

_RATE = {
    "taxa_efetiva", "taxa_ao_ano",
}

_INDEX = {
    "pontos", "investing", "fech_investing",
}

# All known column_names that map to PRICE. Enumerated from current parquet
# so silent fallback warnings only fire on truly novel slugs from new parsers.
_KNOWN_PRICE_COLUMNS: set[str] = {
    "30_dz", "a_prazo_r_prazo", "a_vista_r_vista", "acumulado_kg_ton", "arroba",
    "bezerra", "bezerro", "boi_gordo_prazo", "boi_gordo_vista", "boi_magro",
    "bu", "cabeca", "caixa_40_8_kg", "cents_lb", "cotacao_atual", "desmama",
    "fechamento", "fechamento_c_libra_peso", "garrote", "kg", "litro",
    "media_arroba", "mensal_kg_ton", "novilha", "preco",
    "preco_caixa_de_30_duzias", "preco_compra", "preco_kg", "preco_medio",
    "preco_medio_arroba", "preco_sc", "preco_sc_50_kg", "precos_em_kg",
    "r_a_prazocaixa_408_kg_prazo", "saca_de_50_kg", "sc", "t", "ton",
    "tonelada_curta", "troca", "vaca_gorda_vista", "vaca_magra", "valor",
    "valor_25kg", "valor_5kg", "valor_cent_lb", "valor_kg",
    "valor_saca_de_50_kg", "valor_saca_de_60_kg", "valor_sc", "valor_t",
}
_unknown_warned: set[str] = set()


def register_price_columns(*columns: str) -> None:
    """Mark these column_name slugs as legitimate `Measure.PRICE`. Idempotent."""
    _KNOWN_PRICE_COLUMNS.update(c.lower().strip() for c in columns)


def normalize_measure(column_name: str) -> str:
    """Map a parser-produced column_name to a canonical Measure value.

    Returns the string value of the `Measure` enum (kept as `str` for backward
    compatibility with stored Parquet columns).

    Logs a one-time warning if the column_name doesn't match any known set,
    so silently-misclassified parser output is observable.
    """
    cn = column_name.lower().strip()
    if cn in _CHANGE_PCT:
        return Measure.CHANGE_PCT.value
    if cn in _CHANGE_ABS:
        return Measure.CHANGE_ABS.value
    if cn in _RATE:
        return Measure.RATE.value
    if cn in _INDEX:
        return Measure.INDEX.value

    if cn and cn not in _KNOWN_PRICE_COLUMNS and cn not in _unknown_warned:
        logger.warning(
            "normalize_measure: unknown column_name %r — defaulting to PRICE. "
            "If this is a new measure type, register the slug; if it really "
            "is a price, call register_price_columns(%r) at import time.",
            column_name, column_name,
        )
        _unknown_warned.add(cn)

    return Measure.PRICE.value


# ── currency: BRL or USD ────────────────────────────────────────────────────

# Units that legitimately have no currency (pure quantity / index / ratio).
_NO_CURRENCY_UNITS: set[str] = {"", "%", "Pontos", "pontos", "8 dias"}

_currency_unknown_warned: set[str] = set()


def extract_currency(unit: str) -> Optional[str]:
    """Extract currency (BRL/USD) from a unit string.

    Returns None for currency-less units (percent, points, durations) or for
    inputs that don't match any known prefix. The latter case emits a one-time
    warning so a new parser-produced unit string doesn't quietly classify as
    "no currency".
    """
    if not unit:
        return None
    u = unit.strip()
    if u in _NO_CURRENCY_UNITS:
        return None
    if u.startswith("R$") or u.startswith("R$/"):
        return "BRL"
    if "US$" in u or "US /" in u:
        return "USD"
    if u.startswith("¢") or u.startswith("c/") or u.startswith("cents"):
        return "USD"

    if u not in _currency_unknown_warned:
        logger.warning(
            "extract_currency: unrecognized unit %r — returning None. "
            "Add a prefix branch or extend _NO_CURRENCY_UNITS if intentional.",
            unit,
        )
        _currency_unknown_warned.add(u)
    return None


# ── unit_std: physical unit without currency ─────────────────────────────────

_UNIT_PATTERNS = [
    # Saca
    (r"(?:sc|saca)\s*(?:de\s*)?60\s*kg", "sc60kg"),
    (r"(?:sc|saca)\s*(?:de\s*)?50\s*kg", "sc50kg"),
    (r"(?:sc|saca)\s*(?:de\s*)?40\s*kg", "sc40kg"),
    # Arroba
    (r"@", "arroba"),
    # Weight
    (r"(?:tonelada|short\s*ton|/ton\b|/t\b|/T\b)", "ton"),
    (r"(?:libra\s*peso|/lb\b)", "lb"),
    (r"/[Kk]g\b", "kg"),
    # Volume
    (r"/[Ll]itro", "litro"),
    (r"/m³", "m3"),
    (r"/gal\b", "gal"),
    # Count
    (r"/cab\b|cabeca", "cab"),
    (r"30\s*d[úu]?z", "30dz"),
    (r"[Cc]x\s*23\s*kg", "cx23kg"),
    (r"[Cc]aixa\s*40", "cx40kg"),
    # Grain
    (r"[Bb]ushel|/bu\b", "bu"),
    # Percent
    (r"^%$", "pct"),
    # Points
    (r"[Pp]ontos", "points"),
    # FX
    (r"R\$/US\$", "usd"),
    (r"R\$/€", "eur"),
]


_unit_std_unknown_warned: set[str] = set()


def normalize_unit_std(unit: str) -> str:
    """Extract physical unit (without currency) in canonical form.

    Returns empty string for inputs that don't match any pattern. A first
    sighting of an unrecognized non-empty unit emits a warning so new parser
    outputs can't silently lose their unit classification.
    """
    if not unit:
        return ""
    u = unit.strip()
    if u == "%":
        return "pct"
    for pattern, canonical in _UNIT_PATTERNS:
        if re.search(pattern, u, re.IGNORECASE):
            return canonical
    # Fallback: if unit is just R$ or US$ with no qualifier, it's a generic monetary value
    if re.match(r"^[RU]?\$?$", u) or u in ("R$", "US$"):
        return ""
    # For "sc" alone (R$/sc without kg qualifier), assume sc60kg (most common)
    if re.search(r"/sc\b", u) and "50" not in u and "40" not in u:
        return "sc60kg"

    if u not in _unit_std_unknown_warned:
        logger.warning(
            "normalize_unit_std: unrecognized unit %r — returning empty. "
            "Add a regex to _UNIT_PATTERNS if this represents a real physical unit.",
            unit,
        )
        _unit_std_unknown_warned.add(u)
    return ""


# ── price_basis: spot vs forward vs futures ──────────────────────────────────

def extract_price_basis(unit: str, contract_month: Optional[str] = None) -> str:
    """Determine price basis from unit and contract_month."""
    if contract_month and not _is_nan(contract_month) and str(contract_month).strip():
        # Clean out dirty values like "Dólar: 5,28"
        cm = str(contract_month).strip()
        if not re.match(r"^(Dólar|dólar|R\$)", cm):
            return "futures"
    if not unit:
        return "spot"
    u = unit.lower()
    if "prazo" in u:
        return "forward"
    if "vista" in u:
        return "spot"
    return "spot"


# ── contract month normalization ─────────────────────────────────────────────

_MONTH_MAP = {
    "janeiro": "01", "jan": "01",
    "fevereiro": "02", "fev": "02",
    "março": "03", "marco": "03", "mar": "03",
    "abril": "04", "abr": "04",
    "maio": "05", "mai": "05",
    "junho": "06", "jun": "06",
    "julho": "07", "jul": "07",
    "agosto": "08", "ago": "08",
    "setembro": "09", "set": "09",
    "outubro": "10", "out": "10",
    "novembro": "11", "nov": "11",
    "dezembro": "12", "dez": "12",
}


def normalize_contract_month(contract_month: Optional[str]) -> Optional[str]:
    """Normalize 'Janeiro/2025' or 'Jan/26' to '2025-01' format.

    Returns None for dirty values like 'Dólar: 5,28'.
    """
    if not contract_month or _is_nan(contract_month) or str(contract_month).strip() == "":
        return None
    cm = str(contract_month).strip()

    # Filter dirty values
    if re.match(r"^(Dólar|dólar|R\$|US\$|\d+[.,])", cm):
        return None

    # Parse month/year
    m = re.match(r"^(\w+)/(\d{2,4})$", cm)
    if not m:
        return None

    month_str = m.group(1).lower()
    year_str = m.group(2)

    month_num = _MONTH_MAP.get(month_str)
    if not month_num:
        return None

    if len(year_str) == 2:
        year = 2000 + int(year_str)
    else:
        year = int(year_str)

    return f"{year}-{month_num}"


# ── state extraction from location ───────────────────────────────────────────

_STATE_ABBREV = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
}

_STATE_NAME_TO_ABBREV = {
    "acre": "AC", "alagoas": "AL", "amazonas": "AM", "amapá": "AP", "amapa": "AP",
    "bahia": "BA", "ceará": "CE", "ceara": "CE", "distrito federal": "DF",
    "espírito santo": "ES", "espirito santo": "ES", "goiás": "GO", "goias": "GO",
    "maranhão": "MA", "maranhao": "MA", "minas gerais": "MG",
    "mato grosso do sul": "MS", "mato grosso": "MT",
    "pará": "PA", "para": "PA", "paraíba": "PB", "paraiba": "PB",
    "pernambuco": "PE", "piauí": "PI", "piaui": "PI", "paraná": "PR", "parana": "PR",
    "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rondônia": "RO", "rondonia": "RO", "roraima": "RR",
    "rio grande do sul": "RS", "santa catarina": "SC", "sergipe": "SE",
    "são paulo": "SP", "sao paulo": "SP", "tocantins": "TO",
}


def extract_state(location: Optional[str]) -> Optional[str]:
    """Extract 2-letter state abbreviation from location string.

    Handles:
      'Alto Garças/MT (Samir Rosa)' → 'MT'
      'Bahia' → 'BA'
      'Mato Grosso do Sul' → 'MS'
      'Porto Paranaguá' → None (no state info)
    """
    if not location or _is_nan(location) or str(location).strip() == "":
        return None
    loc = str(location).strip()

    # Pattern 1: City/XX — 2-letter state abbreviation after slash
    m = re.search(r"/([A-Z]{2})\b", loc)
    if m and m.group(1) in _STATE_ABBREV:
        return m.group(1)

    # Pattern 2: Full state name
    loc_lower = loc.lower().strip()
    # Try longest match first (e.g., "Mato Grosso do Sul" before "Mato Grosso")
    for name in sorted(_STATE_NAME_TO_ABBREV.keys(), key=len, reverse=True):
        if loc_lower == name or loc_lower.startswith(name):
            return _STATE_NAME_TO_ABBREV[name]

    return None


# ── market_type from indicator slug ──────────────────────────────────────────

_MARKET_TYPE_PATTERNS = [
    (r"b3|prego-regular", "b3"),
    (r"chicago|cme|cbot", "cme"),
    (r"nova-iorque|nybot", "nybot"),
    (r"londres|liffe", "liffe"),
    (r"mercado-fisico|ceasas|atacado|produtor|disponivel|imea|industria|iea|"
     r"bolsas-e-associac|fecula|farinha|raiz|mesa|beneficiad|vivo-estado|"
     r"scot|reposicao|macho-|femea-|bezerra-|indicador-d[aoe]-|"
     r"couro|sebo|carcaca|frango-sp|suino-sp|cnpc|cacau-mercado|"
     r"preco-medio|preco-feij|algodo-em-pluma|caroco", "physical"),
    (r"indicador|cepea|esalq|cotlook|indice-|cambio|taxa-|ptax|atr\b", "indicator"),
]


_market_type_unknown_warned: set[str] = set()


def classify_market_type(indicator_slug: str) -> str:
    """Classify an indicator slug into a market type.

    Returns 'other' as the catch-all. A first sighting of any slug that lands
    in 'other' emits a warning — usually a sign that a new indicator needs a
    matching pattern in _MARKET_TYPE_PATTERNS, not a legitimate "other".
    """
    slug = indicator_slug.lower()
    for pattern, mtype in _MARKET_TYPE_PATTERNS:
        if re.search(pattern, slug):
            return mtype

    if slug and slug not in _market_type_unknown_warned:
        logger.warning(
            "classify_market_type: slug %r matched no pattern — classified as 'other'. "
            "Add a regex to _MARKET_TYPE_PATTERNS if this is a real market type.",
            indicator_slug,
        )
        _market_type_unknown_warned.add(slug)
    return "other"


# ── Apply all normalizations to a DataFrame ──────────────────────────────────

def normalize_df(df):
    """Add 7 normalized columns to a DataFrame.

    Operates on a copy, returns the enriched DataFrame.
    """
    import pandas as pd

    if df.empty:
        for col in ("measure", "currency", "unit_std", "price_basis",
                     "contract", "state", "market_type"):
            df[col] = pd.Series(dtype="str")
        return df

    out = df.copy()
    out["measure"] = out["column_name"].apply(normalize_measure)
    out["currency"] = out["unit"].apply(extract_currency)
    out["unit_std"] = out["unit"].apply(normalize_unit_std)
    out["price_basis"] = out.apply(
        lambda r: extract_price_basis(r.get("unit", ""), r.get("contract_month")),
        axis=1,
    )
    out["contract"] = out["contract_month"].apply(normalize_contract_month)
    out["state"] = out["location"].apply(extract_state)
    out["market_type"] = out["indicator"].apply(classify_market_type)
    return out
