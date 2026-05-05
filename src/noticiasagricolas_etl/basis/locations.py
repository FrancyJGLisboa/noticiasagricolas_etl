"""Praça (location) name normalization for basis output.

Source data has noisy location strings: brokers, contract months, parenthetical
qualifiers, bare city names without state codes. This module produces a
canonical form so all downstream consumers can rely on a single label per
physical praça.

Three transforms in order of priority:
  1. Port aliases  (Porto Santos/SP (Fev/Mar) (Dellagro)  →  Porto Santos/SP)
  2. Bare cities   (Paranaguá  →  Paranaguá/PR)
  3. Parenthetical strip  (Rio Verde/GO (Comigo)  →  Rio Verde/GO)
"""

from __future__ import annotations

import re

import pandas as pd

# Patterns: "Porto Santos/SP (Fev/Mar-2025) (Dellagro)" -> "Porto Santos/SP"
#           "Porto Paranaguá (disponível) (Insoy Commodities)" -> "Porto Paranaguá/PR"
_PORT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^Porto Santos/SP\b.*"), "Porto Santos/SP"),
    (re.compile(r"^Porto Paranagu[áa]\b.*"), "Porto Paranaguá/PR"),
    (re.compile(r"^Porto de São Francisco do Sul/SC\b.*"), "Porto São Francisco do Sul/SC"),
    (re.compile(r"^Porto Imbituba/SC\b.*"), "Porto Imbituba/SC"),
    (re.compile(r"^Porto Rio Grande\b.*"), "Porto Rio Grande/RS"),
]

# Bare city names from soja-mercado-fisico-ms (no state code attached upstream).
_BARE_CITY_STATE: dict[str, str] = {
    "Paranaguá": "PR",
    "Maringá": "PR",
    "Campo Grande": "MS",
    "Dourados": "MS",
    "Maracaju": "MS",
    "Ponta Porã": "MS",
    "Sidrolândia": "MS",
    "São Gabriel do Oeste": "MS",
    "Chapadão do Sul": "MS",
    "Caarapó": "MS",
    "Sonora": "MS",
    "Oeste da Bahia": "BA",
}

# Indicators that have no per-row location but should map to a synthetic
# location string in the basis output (so downstream queries can group by
# location even for ESALQ-style indicator-only references).
_INDICATOR_LOCATIONS: dict[str, str] = {
    "boi-gordo-indicador-esalq-bmf": "Indicador ESALQ/SP",
}


def indicator_location(indicator: str) -> str:
    """Map an indicator slug to a synthetic location for indicators without location."""
    return _INDICATOR_LOCATIONS.get(indicator, f"Indicador {indicator}")


def normalize_location(location: str) -> str:
    """Normalize a raw location string to canonical form.

      - Port variants collapse to their canonical Porto X/SS form.
      - Bare city names (no state code) get their state code appended via the
        _BARE_CITY_STATE map.
      - Trailing parentheticals (broker, contract month) are stripped.
        e.g. "Rio Verde/GO (Comigo)" → "Rio Verde/GO"
             "Sorriso/MT (Sindicato) Transgênica Balcão" → "Sorriso/MT"
    """
    if not location:
        return location

    for pattern, canonical in _PORT_PATTERNS:
        if pattern.match(location):
            return canonical

    stripped = location.strip()
    if "/" not in stripped and "(" not in stripped:
        for city, state in _BARE_CITY_STATE.items():
            if stripped == city:
                return f"{city}/{state}"

    if "(" in location:
        cleaned = re.sub(r"\s*\(.*$", "", location).strip()
        if cleaned:
            if "/" not in cleaned:
                for city, state in _BARE_CITY_STATE.items():
                    if cleaned == city:
                        return f"{city}/{state}"
            return cleaned

    return location


def normalize_and_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize location strings, convert R$/kg locations to R$/@, average duplicates.

    Some praças quote in R$/kg ("RS Oeste (kg)") and need ×15 to become R$/@.
    Multiple port variants on the same date (e.g. two Santos broker entries)
    collapse to one row by averaging their physical price.
    """
    if df.empty:
        return df

    out = df.copy()

    kg_mask = out["location"].str.contains(r"\(kg\)", na=False)
    if kg_mask.any():
        out.loc[kg_mask, "physical_price_brl"] = out.loc[kg_mask, "physical_price_brl"] * 15.0

    # Filter zero/negative prices (holiday anomalies, bad parses)
    out = out[out["physical_price_brl"] > 0]

    out["location"] = out["location"].apply(normalize_location)

    # Re-extract state from the normalized location so it stays in sync.
    from ..normalize import extract_state
    out["state"] = out["location"].apply(extract_state)

    grouped = out.groupby(["date", "location"], as_index=False).agg({
        "state": "first",
        "physical_indicator": "first",
        "physical_price_brl": "mean",
    })
    return grouped
