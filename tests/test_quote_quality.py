"""Tests for the compact daily physical-quote quality snapshot."""

from datetime import date

import pandas as pd
import pytest

from noticiasagricolas_etl.basis.quote_quality import (
    QUOTE_QUALITY_COLUMNS,
    classify_quote_type,
    export_quote_quality_csv,
    summarize_quote_quality,
)


def quote(location, price, label=None, indicator="fisico", day=date(2026, 11, 11)):
    return {
        "date": day,
        "location": location,
        "state": location.rsplit("/", 1)[-1] if "/" in location else None,
        "physical_indicator": indicator,
        "physical_price_brl": price,
        "source_label": label or location,
    }


def summarize(rows):
    return summarize_quote_quality(pd.DataFrame(rows), "soja", date(2026, 11, 11))


def test_single_quote():
    result = summarize([quote("A/MT", 100)])
    row = result.iloc[0]
    assert row["classification"] == "single"
    assert row["n_quotes"] == 1
    assert row["price_min_brl"] == row["price_mean_brl"] == row["price_max_brl"] == 100


def test_consensus_quotes():
    result = summarize([
        quote("A/MT", 100, "A/MT (Fonte 1)"),
        quote("A/MT", 100, "A/MT (Fonte 2)"),
    ])
    assert result.iloc[0]["classification"] == "consensus"
    assert result.iloc[0]["price_range_brl"] == 0


def test_source_dispersion_preserves_mean_and_labels():
    result = summarize([
        quote("A/MT", 100, "A/MT (Fonte 1)", "fonte-a"),
        quote("A/MT", 104, "A/MT (Fonte 2)", "fonte-b"),
    ])
    row = result.iloc[0]
    assert row["classification"] == "source_dispersion"
    assert row["price_min_brl"] == 100
    assert row["price_max_brl"] == 104
    assert row["price_mean_brl"] == 102
    assert row["physical_indicators"] == "fonte-a|fonte-b"
    assert row["source_labels"] == "A/MT (Fonte 1)|A/MT (Fonte 2)"


def test_mixed_delivery_requires_explicit_spot_and_dated_labels():
    result = summarize([
        quote("Porto X/PR", 160, "Porto X (disponível)"),
        quote("Porto X/PR", 162, "Porto X (Dez/26)"),
    ])
    row = result.iloc[0]
    assert row["classification"] == "mixed_delivery"
    assert row["quote_types"] == "dated_delivery|spot"


def test_unspecified_and_dated_quotes_are_dispersion_not_mixed_delivery():
    result = summarize([
        quote("Porto X/PR", 160, "Porto X (Insoy)"),
        quote("Porto X/PR", 162, "Porto X (Dez/26)"),
    ])
    assert result.iloc[0]["classification"] == "source_dispersion"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Porto Paranaguá (disponível)", "spot"),
        ("Porto Paranaguá (Dez/26)", "dated_delivery"),
        ("Sorriso/MT Transgênica Balcão", "balcao"),
        ("Maracaju/MS (Corretora)", "unspecified"),
    ],
)
def test_quote_type_classification(label, expected):
    assert classify_quote_type(label) == expected


def test_export_preserves_unprocessed_commodity(tmp_path, monkeypatch):
    monkeypatch.setattr("noticiasagricolas_etl.basis.quote_quality.CSV_DIR", tmp_path)
    old = summarize_quote_quality(
        pd.DataFrame([quote("M/GO", 60, day=date(2026, 11, 10))]),
        "milho",
        date(2026, 11, 10),
    )
    old.to_csv(tmp_path / "quote-quality.csv", index=False)
    soy = summarize([quote("S/MT", 100)])
    result = export_quote_quality_csv([soy], {"soja"})
    assert list(result["commodity"]) == ["milho", "soja"]
    assert list(result.columns) == QUOTE_QUALITY_COLUMNS


def test_empty_processed_commodity_removes_stale_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("noticiasagricolas_etl.basis.quote_quality.CSV_DIR", tmp_path)
    summarize([quote("S/MT", 100)]).to_csv(tmp_path / "quote-quality.csv", index=False)
    result = export_quote_quality_csv([], {"soja"})
    assert result.empty
    assert list(pd.read_csv(tmp_path / "quote-quality.csv").columns) == QUOTE_QUALITY_COLUMNS
