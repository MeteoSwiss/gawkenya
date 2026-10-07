from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from housekeeping.backfill_linked_flags import (
    LinkedFlagConflictError,
    process_file,
    reconcile_linked_flags,
)


GROUPS = {"example": ("a", "b", "c")}


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dtm": [1, 2, 3],
            "a": [10.0, 11.0, 12.0],
            "b": [20.0, 21.0, 22.0],
            "c": [30.0, 31.0, 32.0],
            "source": ["x", "x", "x"],
        }
    )


def test_reconcile_propagates_one_existing_flag_to_all_members() -> None:
    frame = _frame().with_columns(pl.Series("f_b", [None, 1, 2], dtype=pl.Int8))

    result, relevant = reconcile_linked_flags(frame, GROUPS)

    assert relevant == ("example",)
    assert result.get_column("f_a").to_list() == [None, 1, 2]
    assert result.get_column("f_b").to_list() == [None, 1, 2]
    assert result.get_column("f_c").to_list() == [None, 1, 2]
    assert_frame_equal(
        frame.select(["dtm", "a", "b", "c", "source"]),
        result.select(["dtm", "a", "b", "c", "source"]),
    )


def test_reconcile_combines_matching_non_null_flags() -> None:
    frame = _frame().with_columns(
        [
            pl.Series("f_a", [None, 1, None], dtype=pl.Int8),
            pl.Series("f_c", [2, 1, None], dtype=pl.Int8),
        ]
    )

    result, _ = reconcile_linked_flags(frame, GROUPS)

    expected = [2, 1, None]
    assert result.get_column("f_a").to_list() == expected
    assert result.get_column("f_b").to_list() == expected
    assert result.get_column("f_c").to_list() == expected


def test_reconcile_rejects_conflicting_existing_flags() -> None:
    frame = _frame().with_columns(
        [
            pl.Series("f_a", [None, 1, None], dtype=pl.Int8),
            pl.Series("f_c", [None, 2, None], dtype=pl.Int8),
        ]
    )

    with pytest.raises(LinkedFlagConflictError, match="conflicting non-null flags"):
        reconcile_linked_flags(frame, GROUPS)


def test_process_file_write_is_verified_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    _frame().with_columns(
        pl.Series("f_a", [0, 1, None], dtype=pl.Int8)
    ).write_parquet(path)

    first, first_groups = process_file(path, GROUPS, write=True)
    second, second_groups = process_file(path, GROUPS, write=False)

    assert first == "written"
    assert second == "correct"
    assert first_groups == ("example",)
    assert second_groups == ("example",)

    actual = pl.read_parquet(path)
    assert actual.get_column("f_a").to_list() == [0, 1, None]
    assert actual.get_column("f_b").to_list() == [0, 1, None]
    assert actual.get_column("f_c").to_list() == [0, 1, None]
