"""Port basis tracker — basis percentile across all Brazilian export ports.

For one (commodity, futures_indicator), iterates the known export ports and
returns a list ranked by percentile so a trader sees at a glance which port is
in extreme territory (cheap basis = buy signal, expensive = wait or sell).

Composition over the existing `basis_percentile_service`. No new math —
the percentile/bucketing logic lives in `analytics.diagnostic`.
"""

from __future__ import annotations

from typing import Any

from . import basis_percentile_service
from .port_spread_service import PORT_LOCATIONS


def get_port_basis_tracker(
    commodity: str,
    futures_indicator: str | None = None,
    target_date: str | None = None,
    window_years: int = 5,
    column: str = "basis_brl",
) -> dict[str, Any]:
    """Compute basis percentile for every Brazilian export port.

    Args:
        commodity: 'soja' | 'milho' | etc.
        futures_indicator: e.g. 'soja-bolsa-de-chicago-cme-group'. None = whatever
            the underlying service finds first per port.
        target_date: ISO 'YYYY-MM-DD'; None = latest.
        window_years: history window for the percentile (default 5).
        column: 'basis_brl' | 'basis_usd' | 'basis_pct' | 'basis_centavos_sc' |
            'basis_cents_bu'.

    Returns:
        Dict with `commodity`, `futures_indicator`, `target_date`, `window_years`,
        `column`, and `ports`: list of per-port results sorted ascending by
        percentile (cheapest basis first). Each entry has `port`, `value`,
        `percentile`, `interpretation`, plus stats (mean, p25, p50, p75, min, max,
        n_obs). Ports without data appear at the end with `error` populated.
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for port in sorted(PORT_LOCATIONS):
        r = basis_percentile_service.get_basis_percentile(
            commodity=commodity,
            location=port,
            futures_indicator=futures_indicator,
            target_date=target_date,
            window_years=window_years,
            column=column,
        )
        if "error" in r:
            errors.append({"port": port, "error": r["error"]})
            continue

        results.append({
            "port": port,
            "futures_indicator": r.get("futures_indicator", futures_indicator),
            "target_date": r["target_date"],
            "value": r["value"],
            "percentile": r["percentile"],
            "n_obs": r["n_obs"],
            "mean": r["mean"],
            "p25": r["p25"],
            "p50": r["p50"],
            "p75": r["p75"],
            "min": r["min"],
            "max": r["max"],
            "interpretation": r["interpretation"],
        })

    # Cheapest basis first (low percentile = below typical = buy signal).
    results.sort(key=lambda r: r["percentile"])

    return {
        "commodity": commodity,
        "futures_indicator": futures_indicator,
        "target_date": target_date,
        "window_years": window_years,
        "column": column,
        "ports_with_data": len(results),
        "ports_missing": len(errors),
        "ports": results,
        "errors": errors,
    }
