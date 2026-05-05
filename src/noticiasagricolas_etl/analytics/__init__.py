"""Shared analytics primitives consumed by api.services and elsewhere.

Concentrates the percentile/window-stats and bucket-classification logic that
five percentile-based services (basis, crush, port_spread, ratio, vol_regime)
were each implementing inline. A few non-percentile services (anomaly,
hedge_fit, term_structure) reuse the Bucket classifier for their score→label
step.
"""

from .diagnostic import (
    PERCENTILE_3,
    PERCENTILE_5,
    Bucket,
    WindowStats,
    compute_window_stats,
)

__all__ = [
    "Bucket",
    "PERCENTILE_3",
    "PERCENTILE_5",
    "WindowStats",
    "compute_window_stats",
]
