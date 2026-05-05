"""Guardrail tests for normalize.normalize_measure.

The previous implementation silently fell through to "price" for any unknown
column_name — meaning a new parser variant could mis-classify forever. These
tests pin down the explicit-mapping behavior and assert the warning fires on
genuinely-novel slugs.
"""

from __future__ import annotations

import logging

import pytest

from noticiasagricolas_etl.models import Measure
from noticiasagricolas_etl.normalize import (
    _KNOWN_PRICE_COLUMNS,
    _unknown_warned,
    normalize_measure,
)


@pytest.fixture(autouse=True)
def reset_warning_cache():
    """Each test starts with a fresh warning cache so we can assert log emissions."""
    _unknown_warned.clear()
    yield
    _unknown_warned.clear()


class TestKnownMappings:
    @pytest.mark.parametrize("col,expected", [
        ("variacao_pct", Measure.CHANGE_PCT),
        ("variacao_diaria", Measure.CHANGE_PCT),
        ("variacao_semana", Measure.CHANGE_PCT),
        ("variacao_cents", Measure.CHANGE_ABS),
        ("variacao_pontos", Measure.CHANGE_ABS),
        ("taxa_efetiva", Measure.RATE),
        ("taxa_ao_ano", Measure.RATE),
        ("pontos", Measure.INDEX),
        ("investing", Measure.INDEX),
        ("fech_investing", Measure.INDEX),
    ])
    def test_specialized_columns(self, col: str, expected: Measure) -> None:
        assert normalize_measure(col) == expected.value

    @pytest.mark.parametrize("col", [
        "preco", "valor", "fechamento", "arroba", "kg", "valor_sc", "cents_lb",
    ])
    def test_known_price_columns_dont_warn(self, caplog, col: str) -> None:
        with caplog.at_level(logging.WARNING):
            assert normalize_measure(col) == Measure.PRICE.value
        # No "unknown column_name" warning for registered slugs
        assert not any("unknown column_name" in m for m in caplog.messages)


class TestUnknownColumns:
    def test_unknown_column_warns_once(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert normalize_measure("var_diaria_pct") == Measure.PRICE.value
            # Same column twice → only first call emits the warning
            assert normalize_measure("var_diaria_pct") == Measure.PRICE.value
        warnings = [m for m in caplog.messages if "unknown column_name" in m]
        assert len(warnings) == 1
        assert "var_diaria_pct" in warnings[0]

    def test_different_unknown_columns_warn_separately(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            normalize_measure("foo_unknown_a")
            normalize_measure("foo_unknown_b")
        warnings = [m for m in caplog.messages if "unknown column_name" in m]
        assert len(warnings) == 2

    def test_empty_column_doesnt_warn(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert normalize_measure("") == Measure.PRICE.value
        assert not any("unknown column_name" in m for m in caplog.messages)


class TestKnownPriceColumnsAreSeeded:
    """The seeded set should at minimum cover every column produced by current parsers."""

    def test_known_set_is_nonempty(self) -> None:
        assert len(_KNOWN_PRICE_COLUMNS) > 30

    def test_seeded_set_is_lowercase(self) -> None:
        # All entries should already be normalized to lowercase
        for c in _KNOWN_PRICE_COLUMNS:
            assert c == c.lower().strip()
