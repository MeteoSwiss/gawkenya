"""Regression tests: live NE-300 auto-flagging uses transient flag 2."""
from datetime import UTC, datetime, timedelta

import polars as pl

from processing.neph import Neph


def frame(states: list[int | None], *, step_min: int = 15) -> pl.DataFrame:
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    return pl.DataFrame({
        "dtm": [t0 + timedelta(minutes=i * step_min) for i in range(len(states))],
        "4035": states,
        "2635000": [float(i) for i in range(len(states))],
        "6635000": [float(i) for i in range(len(states))],
        "5002": [42.0] * len(states),
    }, schema_overrides={"dtm": pl.Datetime("us", "UTC")})


def test_literal_operation_codes() -> None:
    df = frame([0, 1, 2, 3, 4, 5, 6, 7])
    result = Neph("test-ne300").auto_flag_ne300_data(df)
    expected = [0, 2, 2, 3, 5, 4, 6, None]
    assert result["f_2635000"].to_list() == expected
    assert result["f_6635000"].to_list() == expected
    assert "f_5002" not in result.columns


def test_check_completion_does_not_change_transient_calibration_periods() -> None:
    df = frame([0, 1, 1, 4, 0, 2, 2, 6, 0], step_min=1)
    result = Neph("test-ne300").auto_flag_ne300_data(df)
    assert result["f_2635000"].to_list() == [0, 2, 2, 5, 2, 2, 2, 6, 2]


def test_manual_invalid_preserved_unless_overwrite_requested() -> None:
    df = frame([1, 4, 6]).with_columns(
        pl.Series("f_2635000", [1, None, 0], dtype=pl.Int8)
    )
    ne300 = Neph("test-ne300")
    safe = ne300.auto_flag_ne300_data(df)
    assert safe["f_2635000"].to_list() == [1, 5, 0]
    forced = ne300.auto_flag_ne300_data(df, overwrite=True)
    assert forced["f_2635000"].to_list() == [2, 5, 6]


def test_missing_state_column_is_safe() -> None:
    df = frame([0]).drop("4035")
    assert Neph("test-ne300").auto_flag_ne300_data(df).equals(df)


def test_interactive_check_flags_still_available() -> None:
    from toolbox.ez_flag_data import keys
    assert keys["5"]["meaning"] == "zero check"
    assert keys["6"]["meaning"] == "span check"
