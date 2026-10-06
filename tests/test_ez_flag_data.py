from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from toolbox.ez_flag_data import apply_flag_at_timestamps, expand_linked_flags


def _frame() -> pl.DataFrame:
    start = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "dtm": [start, start + timedelta(minutes=1)],
            "BC1": [100.0, 101.0],
            "b1_abs": [1.0, 1.1],
            "o3": [40.0, 41.0],
        },
        schema_overrides={"dtm": pl.Datetime("us", "UTC")},
    )


def test_expand_linked_flags_from_bc() -> None:
    assert expand_linked_flags("BC1") == ["BC1", "b1_abs"]


def test_expand_linked_flags_from_absorption() -> None:
    assert expand_linked_flags("b1_abs") == ["b1_abs", "BC1"]


def test_expand_linked_flags_leaves_unrelated_variable_alone() -> None:
    assert expand_linked_flags("o3") == ["o3"]


def test_apply_flag_at_timestamps_updates_both_ae33_flag_columns() -> None:
    frame = _frame()
    timestamp = frame.get_column("dtm")[1]

    result = apply_flag_at_timestamps(frame, "BC1", [timestamp], 1)

    assert result.get_column("f_BC1").to_list() == [None, 1]
    assert result.get_column("f_b1_abs").to_list() == [None, 1]


def test_reverse_ae33_flagging_is_also_coupled() -> None:
    frame = _frame()
    timestamp = frame.get_column("dtm")[0]

    result = apply_flag_at_timestamps(frame, "b1_abs", [timestamp], 2)

    assert result.get_column("f_b1_abs").to_list() == [2, None]
    assert result.get_column("f_BC1").to_list() == [2, None]
