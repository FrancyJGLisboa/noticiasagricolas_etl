"""Daily orchestrator: scrape → export → basis → charts.

Holds the four steps that `na-etl daily` runs in order. Each step is one of
the existing modules — this wrapper exists to (a) consolidate the skip-flag
plumbing in one place, (b) return a structured summary instead of printing,
and (c) be invokable programmatically (cron jobs, healthcheck scripts) without
spawning the CLI subprocess.

Step contracts:
  1. update     — pipeline.update(commodity, category) — scrapes latest pages
  2. export     — storage.export_csv / export_all_csv  — regenerates CSVs
  3. basis      — basis_builder.build_all(commodities) → {pair: row_count}
  4. charts     — viz.orchestrator.generate(commodities, viz="all") → dict

Failure semantics: any step's exception bubbles through. The summary records
which steps completed before the exception, so a partial run is observable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .. import basis_builder, pipeline, storage
from ..catalog import load_catalog
from ..pipeline import UpdateSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyConfig:
    """Inputs that select what `DailyPipeline` does.

    `commodity` and `category` are mutually-exclusive scope filters (commodity
    wins if both are set). The three `skip_*` flags let an operator run a
    partial flow when, for example, the basis rebuild already happened earlier
    in the day.
    """

    commodity: str | None = None
    category: str | None = None
    skip_export: bool = False
    skip_basis: bool = False
    skip_charts: bool = False


@dataclass
class DailySummary:
    """What actually happened, suitable for printing or JSON-serializing.

    Field semantics:
      - steps_run: ordered list of step names that completed successfully.
      - basis_summary: pair label → row count (from basis_builder.build_all).
      - chart_summary: orchestrator output, free-form because it nests.
      - csvs_exported: list of commodity slugs whose CSVs were regenerated.
      - error: populated if a step raised; the exception is also re-raised.
    """

    started_at: datetime
    finished_at: datetime | None = None
    steps_run: list[str] = field(default_factory=list)
    update_summary: UpdateSummary | None = None
    basis_summary: dict[str, int] = field(default_factory=dict)
    chart_summary: Any = None
    csvs_exported: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def basis_total_rows(self) -> int:
        return sum(self.basis_summary.values())


class DailyPipeline:
    """The canonical daily flow.

    Construction is config-only (no I/O). Side effects happen in `.run()`.
    """

    def __init__(self, config: DailyConfig | None = None) -> None:
        self.config = config or DailyConfig()

    def run(self) -> DailySummary:
        cfg = self.config
        summary = DailySummary(started_at=datetime.now())

        try:
            summary.update_summary = self._run_update()
            summary.steps_run.append("update")

            if not cfg.skip_export:
                summary.csvs_exported = self._run_export()
                summary.steps_run.append("export")

            if not cfg.skip_basis:
                summary.basis_summary = self._run_basis()
                summary.steps_run.append("basis")

            if not cfg.skip_charts:
                summary.chart_summary = self._run_charts()
                summary.steps_run.append("charts")
        except Exception as exc:
            summary.error = f"{type(exc).__name__}: {exc}"
            summary.finished_at = datetime.now()
            raise
        else:
            summary.finished_at = datetime.now()

        return summary

    def _run_update(self) -> UpdateSummary:
        return pipeline.update(commodity=self.config.commodity, category=self.config.category)

    def _run_export(self) -> list[str]:
        cfg = self.config
        if cfg.commodity:
            storage.export_csv(cfg.commodity)
            return [cfg.commodity]
        if cfg.category:
            entries = load_catalog()
            commodities = sorted({
                e.commodity for e in entries
                if e.category and e.category.value == cfg.category
            })
            for c in commodities:
                storage.export_csv(c)
            return commodities
        storage.export_all_csv()
        return ["<all>"]

    def _run_basis(self) -> dict[str, int]:
        commodities = [self.config.commodity] if self.config.commodity else None
        return basis_builder.build_all(commodities=commodities)

    def _run_charts(self) -> Any:
        # Import lazily — viz.orchestrator pulls plotly which is heavy at startup.
        from ..viz import orchestrator

        commodities = [self.config.commodity] if self.config.commodity else None
        return orchestrator.generate(commodities=commodities, viz="all")
