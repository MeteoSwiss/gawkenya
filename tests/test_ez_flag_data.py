from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

import toolbox.ez_flag_data as ez


EXPECTED_AE33_GROUP = {
    "BC1",
    "b1_abs",
    "BC2",
    "b2_abs",
    "BC3",
    "b3_abs",
    "BC4",
    "b4_abs",
    "BC5",
    "b5_abs",
    "BC6",
    "b6_abs",
    "BC7",
    "b7_abs",
}


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
    assert set(ez.expand_linked_flags("BC1")) == EXPECTED_AE33_GROUP


def test_expand_linked_flags_from_absorption() -> None:
    assert set(ez.expand_linked_flags("b1_abs")) == EXPECTED_AE33_GROUP


def test_expand_linked_flags_leaves_unrelated_variable_alone() -> None:
    assert ez.expand_linked_flags("o3") == ["o3"]


def test_apply_flag_at_timestamps_updates_both_ae33_flag_columns() -> None:
    frame = _frame()
    timestamp = frame.get_column("dtm")[1]

    result = ez.apply_flag_at_timestamps(frame, "BC1", [timestamp], 1)

    assert result.get_column("f_BC1").to_list() == [None, 1]
    assert result.get_column("f_b1_abs").to_list() == [None, 1]


def test_reverse_ae33_flagging_is_also_coupled() -> None:
    frame = _frame()
    timestamp = frame.get_column("dtm")[0]

    result = ez.apply_flag_at_timestamps(frame, "b1_abs", [timestamp], 2)

    assert result.get_column("f_b1_abs").to_list() == [2, None]
    assert result.get_column("f_BC1").to_list() == [2, None]


def test_configured_three_member_group_is_supported(monkeypatch) -> None:
    start = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "dtm": [start],
            "a": [1.0],
            "b": [2.0],
            "c": [3.0],
        },
        schema_overrides={"dtm": pl.Datetime("us", "UTC")},
    )
    monkeypatch.setattr(ez, "linked_flag_groups", {"example": ("a", "b", "c")})

    result = ez.apply_flag_at_timestamps(frame, "b", [start], 4)

    assert result.get_column("f_a").to_list() == [4]
    assert result.get_column("f_b").to_list() == [4]
    assert result.get_column("f_c").to_list() == [4]
