"""Pipeline orchestrators that compose lower-level modules into named flows.

`daily.DailyPipeline` is the canonical scrape-then-export-then-basis-then-charts
sequence used by `na-etl daily`. Lifting it out of the CLI gives it a result
object suitable for programmatic invocation, scheduled jobs, and unit testing.
"""

from .daily import DailyConfig, DailyPipeline, DailySummary

__all__ = ["DailyConfig", "DailyPipeline", "DailySummary"]
