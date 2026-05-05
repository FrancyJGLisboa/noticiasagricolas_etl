"""Daily Brazilian-ag market briefing.

Composes a markdown report from four services:
  - basis_percentile (where each praça's basis sits in 5y history)
  - term_structure   (futures curve regime per pair)
  - vol_regime       (volatility regime per indicator)
  - crush_percentile (soja crush margin vs history)

Designed as a starting point any founder can fork. Imports services
DIRECTLY (no HTTP, no MCP) — the lowest-overhead path. Same call shape
works over MCP or REST if you prefer those transports.

Usage:
    python examples/daily_briefing.py              # all default praças
    python examples/daily_briefing.py --md briefing.md   # save to file

Run after `na-etl daily` to ensure fresh data.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import datetime

# The services depend on the FastAPI database layer being initialized.
# Calling get_connection() once at startup hands the duckdb conn to every
# subsequent service call.
from noticiasagricolas_etl.api import database as db
from noticiasagricolas_etl.api.services import (
    basis_percentile_service,
    crush_percentile_service,
    term_structure_service,
    vol_regime_service,
)


# What to cover in the briefing — edit to fit your portfolio.
PRACAS: list[tuple[str, str, str]] = [
    # (commodity, location, futures_indicator)
    ("soja",   "Sorriso/MT",       "soja-bolsa-de-chicago-cme-group"),
    ("soja",   "Rio Verde/GO",     "soja-bolsa-de-chicago-cme-group"),
    ("soja",   "Cascavel/PR",      "soja-b3-pregao-regular"),
    ("milho",  "Sorriso/MT",       "milho-bolsa-de-chicago-cme-group"),
    ("milho",  "Rio Verde/GO",     "milho-b3-prego-regular"),
]

FUTURES_PAIRS_FOR_CURVE: list[str] = [
    "soja-bolsa-de-chicago-cme-group",
    "soja-b3-pregao-regular",
    "milho-bolsa-de-chicago-cme-group",
    "milho-b3-prego-regular",
]

VOL_INDICATORS: list[tuple[str, str | None]] = [
    # (indicator_slug, optional location)
    ("soja-bolsa-de-chicago-cme-group", None),
    ("milho-bolsa-de-chicago-cme-group", None),
]


# ── Block builders ───────────────────────────────────────────────────────────

def _basis_block(rows: Iterable[tuple[str, str, str]]) -> list[str]:
    out = ["## Basis percentile (5y history)\n"]
    out.append("| Commodity | Praça | Pair | Basis hoje | Pctl | Sinal |")
    out.append("|---|---|---|---:|---:|---|")
    for commodity, location, futures_indicator in rows:
        r = basis_percentile_service.get_basis_percentile(
            commodity=commodity, location=location,
            futures_indicator=futures_indicator,
        )
        if "error" in r:
            out.append(f"| {commodity} | {location} | {futures_indicator.split('-')[1]} | — | — | _{r['error']}_ |")
            continue
        pair_label = futures_indicator.split("-")[1]  # 'b3' or 'bolsa' (cbot/nybot)
        if "chicago" in futures_indicator:
            pair_label = "CBOT"
        elif "b3" in futures_indicator:
            pair_label = "B3"
        elif "nybot" in futures_indicator:
            pair_label = "NYBOT"
        out.append(
            f"| {commodity} | {location} | {pair_label} "
            f"| R$ {r['value']:.2f} | P{r['percentile']:.0f} "
            f"| {r['interpretation'].split('—')[0].strip()} |"
        )
    return out


def _curve_block(pairs: Iterable[str]) -> list[str]:
    out = ["\n## Curva de futuros (term structure)\n"]
    out.append("| Pair | Regime | Slope/mês | Front | Back |")
    out.append("|---|---|---:|---|---|")
    for pair in pairs:
        r = term_structure_service.get_term_structure(futures_indicator=pair)
        if "error" in r:
            out.append(f"| {pair} | — | — | — | _{r['error']}_ |")
            continue
        out.append(
            f"| {pair} | **{r['regime']}** "
            f"| {r['relative_slope_pct_per_month']:+.2f}% "
            f"| {r['front_contract']} ({r['front_value']:.2f}) "
            f"| {r['back_contract']} ({r['back_value']:.2f}) |"
        )
    return out


def _vol_block(indicators: Iterable[tuple[str, str | None]]) -> list[str]:
    out = ["\n## Regime de volatilidade (20d, vs 5y)\n"]
    out.append("| Indicator | Location | Regime | Vol | Pctl | Days in regime |")
    out.append("|---|---|---|---:|---:|---:|")
    for indicator, location in indicators:
        r = vol_regime_service.get_vol_regime(
            indicator=indicator, location=location,
        )
        if "error" in r:
            out.append(f"| {indicator} | {location or 'avg'} | — | — | — | _{r['error']}_ |")
            continue
        out.append(
            f"| {indicator} | {location or 'avg'} "
            f"| **{r['regime']}** | {r['current_vol_annualized']:.3f} "
            f"| P{r['percentile']:.0f} | {r['days_in_regime']} |"
        )
    return out


def _crush_block() -> list[str]:
    out = ["\n## Soja crush margin (esmagamento)\n"]
    r = crush_percentile_service.get_crush_percentile()
    if "error" in r:
        out.append(f"_{r['error']}_")
        return out
    pct = r.get("percentile")
    target_date = r.get("target_date", "?")
    out.append(f"Margem em **{target_date}**: P{pct:.0f}")
    if "interpretation" in r:
        out.append(f"\n> {r['interpretation']}")
    return out


# ── Compose ──────────────────────────────────────────────────────────────────

def build_briefing() -> str:
    db.get_connection()  # one-time DuckDB warmup

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections: list[str] = [
        f"# Briefing diário — {today}",
        "",
        "_Generated from `noticiasagricolas_etl` services. Each row's signal is"
        " written by the platform; this script just composes them._",
        "",
    ]
    sections.extend(_basis_block(PRACAS))
    sections.extend(_curve_block(FUTURES_PAIRS_FOR_CURVE))
    sections.extend(_vol_block(VOL_INDICATORS))
    sections.extend(_crush_block())
    sections.append("")
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--md", help="Write output to this markdown file (default: stdout)")
    args = parser.parse_args()

    briefing = build_briefing()

    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(briefing)
        print(f"Wrote {args.md} ({len(briefing)} bytes)")
    else:
        print(briefing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
