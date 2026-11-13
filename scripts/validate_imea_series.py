"""Build and validate the IMEA-CBOT series from an immutable Git data ref.

Run:
    uv run python scripts/validate_imea_series.py --git-ref origin/data

Use ``--output-dir`` to keep the generated CSV files for Site tests.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from noticiasagricolas_etl import config
from noticiasagricolas_etl.basis import output, quote_quality, sources
from noticiasagricolas_etl.basis_builder import build_all
from noticiasagricolas_etl.storage import SCHEMA
from noticiasagricolas_etl.viz.companion import compute_stats


EXPECTED_LATEST = {"soja-imea-cbot": 8, "milho-imea-cbot": 7}


def _dates_for_price(frame: pd.DataFrame, indicator: str, location: str | None = None) -> set[str]:
    mask = (frame["indicator"] == indicator) & (frame["measure"] == "price")
    if location is not None:
        mask &= frame["location"] == location
    return set(pd.to_datetime(frame.loc[mask, "date"]).dt.strftime("%Y-%m-%d"))


def _read_git_csv(repository: Path, git_ref: str, name: str) -> pd.DataFrame:
    payload = subprocess.check_output(
        ["git", "show", f"{git_ref}:csv/{name}.csv"],
        cwd=repository,
    )
    return pd.read_csv(pa.BufferReader(payload), low_memory=False)


def _write_source_parquet(frame: pd.DataFrame, root: Path, commodity: str) -> None:
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    destination = root / f"commodity={commodity}" / "data.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, destination)


def _write_stats(csv_dir: Path) -> None:
    frames: list[pd.DataFrame] = []
    for commodity in ("soja", "milho"):
        basis = pd.read_csv(csv_dir / f"basis-{commodity}.csv", low_memory=False)
        basis["date"] = pd.to_datetime(basis["date"])
        for pair, group in basis.groupby("basis_pair"):
            values = group.rename(columns={"basis_cents_bu_adj": "value", "basis_cents_bu": "value_raw"})
            stats = compute_stats(values)
            stats.insert(0, "pair", pair)
            frames.append(stats)
    pd.concat(frames, ignore_index=True).to_csv(csv_dir / "basis-stats.csv", index=False)


def validate(repository: Path, git_ref: str, output_dir: Path | None) -> None:
    with tempfile.TemporaryDirectory(prefix="imea-series-") as temporary:
        root = Path(temporary)
        parquet_dir = root / "parquet"
        basis_dir = root / "parquet_basis"
        csv_dir = root / "csv"
        source_frames = {
            commodity: _read_git_csv(repository, git_ref, commodity)
            for commodity in ("soja", "milho", "mercado-financeiro")
        }
        for commodity, frame in source_frames.items():
            _write_source_parquet(frame, parquet_dir, commodity)

        sources.PARQUET_DIR = parquet_dir
        output.PARQUET_BASIS_DIR = basis_dir
        output.CSV_DIR = csv_dir
        quote_quality.CSV_DIR = csv_dir
        config.PARQUET_DIR = parquet_dir
        config.PARQUET_BASIS_DIR = basis_dir
        config.CSV_DIR = csv_dir

        summary = build_all(commodities=["soja", "milho"], force=True)
        _write_stats(csv_dir)

        quality = pd.read_csv(csv_dir / "quote-quality.csv", low_memory=False)
        ptax_raw_dates = _dates_for_price(
            source_frames["mercado-financeiro"],
            "cambio-ptax",
            "Dólar",
        )
        assert ptax_raw_dates, "No PTAX dollar prices are available"
        ptax_dates = set(pd.date_range(min(ptax_raw_dates), max(ptax_raw_dates), freq="D").strftime("%Y-%m-%d"))
        for pair, expected in EXPECTED_LATEST.items():
            commodity = pair.split("-", 1)[0]
            basis = pd.read_csv(csv_dir / f"basis-{commodity}.csv", low_memory=False)
            selected = basis[basis["basis_pair"] == pair]
            physical = source_frames[commodity]
            raw_latest = physical[
                (physical["date"] == "2026-11-12")
                & (physical["indicator"] == f"{commodity}-disponivel-imea")
                & (physical["measure"] == "price")
            ]
            if not raw_latest.empty:
                assert raw_latest["location"].nunique() == expected
                snapshot_report = f"raw 2026-11-12: {expected} locations; "
            else:
                snapshot_report = "raw 2026-11-12: not present; "
            assert set(selected["physical_source"]) == {"imea"}
            assert set(selected["physical_indicator"]) == {f"{commodity}-disponivel-imea"}
            physical_dates = _dates_for_price(physical, f"{commodity}-disponivel-imea")
            futures_dates = _dates_for_price(physical, f"{commodity}-bolsa-de-chicago-cme-group")
            common_dates = physical_dates & futures_dates & ptax_dates
            assert common_dates, f"{pair}: no common physical, CBOT and PTAX date"
            expected_latest_date = max(common_dates)
            latest_date = selected["date"].max()
            assert latest_date == expected_latest_date, (
                pair,
                latest_date,
                expected_latest_date,
            )
            latest = selected[selected["date"] == latest_date]
            print(
                f"{pair}: {len(selected)} rows; {snapshot_report}"
                f"latest computed basis {latest_date}: {len(latest)} locations"
            )

        soy = pd.read_csv(csv_dir / "basis-soja.csv", low_memory=False)
        anomaly = soy[
            (soy["basis_pair"] == "soja-imea-cbot")
            & (soy["date"] == "2026-11-05")
            & (soy["location"] == "Campo Verde/MT")
        ]
        assert anomaly.empty, "Campo Verde 1399.01 entered the soybean basis"
        blocked = quality[quality["basis_pair"] == "soja-imea-cbot"]
        assert int(blocked["blocked_outlier_count"].max()) >= 1
        assert blocked["blocked_examples"].str.contains("1399.01", regex=False).any()
        print("Campo Verde/MT 2026-11-05 1399.01: blocked before basis and stats")
        print("build summary:", summary)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            for source_file in csv_dir.glob("*.csv"):
                shutil.copy2(source_file, output_dir / source_file.name)
            print(f"generated CSV: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--git-ref", default="origin/data")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    validate(args.repository.resolve(), args.git_ref, args.output_dir)


if __name__ == "__main__":
    main()
