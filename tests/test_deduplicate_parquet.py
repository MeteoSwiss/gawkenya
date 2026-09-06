from datetime import datetime, timezone

import polars as pl

from housekeeping.deduplicate_parquet import process_file


UTC = timezone.utc


def _dt(hour: int) -> datetime:
    return datetime(2026, 9, 1, hour, tzinfo=UTC)


def test_exact_and_complementary_duplicates_are_resolved_idempotently(tmp_path):
    path = tmp_path / "sample.parquet"
    pl.DataFrame(
        {
            "dtm": [_dt(0), _dt(0), _dt(1), _dt(1), None, None],
            "value": [1.0, 1.0, 2.0, None, 9.0, 10.0],
            "flag": [0, 0, None, 2, 0, 0],
            "note": ["same", "same", "merge", "merge", "unknown-a", "unknown-b"],
        }
    ).write_parquet(path)

    stats = process_file(
        path,
        requested_time_column=None,
        write=True,
        interactive=False,
        verbose=False,
    )

    assert stats.exact_groups == 1
    assert stats.mergeable_groups == 1
    assert stats.conflict_groups == 0
    assert stats.rows_removed == 2
    assert stats.changed is True

    result = pl.read_parquet(path)
    assert result.height == 4
    merged = result.filter(pl.col("dtm") == _dt(1)).row(0, named=True)
    assert merged["value"] == 2.0
    assert merged["flag"] == 2
    # Null timestamps are deliberately not collapsed.
    assert result.get_column("dtm").null_count() == 2

    second = process_file(
        path,
        requested_time_column=None,
        write=True,
        interactive=False,
        verbose=False,
    )
    assert second.duplicate_groups == 0
    assert second.changed is False
    assert pl.read_parquet(path).height == 4


def test_conflict_requires_choice_and_selected_row_wins(tmp_path, monkeypatch):
    path = tmp_path / "conflict.parquet"
    pl.DataFrame(
        {
            "dtm": [_dt(2), _dt(2)],
            "value": [1.0, 2.0],
            "aux": [5.0, None],
            "note": ["same", "same"],
        }
    ).write_parquet(path)

    monkeypatch.setattr("builtins.input", lambda _: "2")
    stats = process_file(
        path,
        requested_time_column="dtm",
        write=True,
        interactive=True,
        verbose=False,
    )

    assert stats.conflict_groups == 1
    assert stats.resolved_groups == 1
    assert stats.unresolved_groups == 0

    result = pl.read_parquet(path)
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["value"] == 2.0  # selected row is authoritative
    assert row["aux"] == 5.0  # safe null fill from the other row


def test_noninteractive_conflict_is_left_untouched(tmp_path):
    path = tmp_path / "conflict.parquet"
    original = pl.DataFrame(
        {
            "dtm": [_dt(3), _dt(3)],
            "value": [1.0, 2.0],
        }
    )
    original.write_parquet(path)

    stats = process_file(
        path,
        requested_time_column=None,
        write=True,
        interactive=False,
        verbose=False,
    )

    assert stats.conflict_groups == 1
    assert stats.unresolved_groups == 1
    assert stats.changed is False
    assert pl.read_parquet(path).to_dicts() == original.to_dicts()


def test_conflict_display_includes_complete_candidate_rows(tmp_path, capsys):
    path = tmp_path / "display.parquet"
    pl.DataFrame(
        {
            "dtm": [_dt(4), _dt(4)],
            "source": ["ae33", "ae33"],
            "value": [1.0, 2.0],
            "flag": [0, 0],
            "aux": [5.0, None],
        }
    ).write_parquet(path)

    stats = process_file(
        path,
        requested_time_column="dtm",
        write=False,
        interactive=False,
        verbose=False,
    )

    assert stats.conflict_groups == 1
    output = capsys.readouterr().out
    # Full row context is shown, not just the truly conflicting column.
    assert "source: 'ae33'" in output
    assert "flag: 0" in output
    assert "! value: 1.0" in output
    assert "! value: 2.0" in output
    assert "+ aux: 5.0" in output
    assert "+ aux: NULL" in output


def test_remembered_source_choice_is_stable_when_candidate_order_swaps(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "source-preference.parquet"
    pl.DataFrame(
        {
            "dtm": [_dt(5), _dt(5), _dt(6), _dt(6)],
            # Candidate order reverses in the second conflict.
            "source": ["source-a.zip", "source-b.zip", "source-b.zip", "source-a.zip"],
            "value": [1.0, 2.0, 20.0, 10.0],
        }
    ).write_parquet(path)

    answers = iter(["2", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    stats = process_file(
        path,
        requested_time_column="dtm",
        write=True,
        interactive=True,
        verbose=False,
    )

    assert stats.conflict_groups == 2
    assert stats.resolved_groups == 2
    assert stats.unresolved_groups == 0

    result = pl.read_parquet(path).sort("dtm")
    assert result.height == 2
    assert result.get_column("source").to_list() == ["source-b.zip", "source-b.zip"]
    assert result.get_column("value").to_list() == [2.0, 20.0]

    output = capsys.readouterr().out
    assert "CONFLICT 1/2" in output
    assert "same 'source' alternatives occur in 1 remaining conflict group" in output
    assert "AUTO      conflict 2/2" in output
    assert "source='source-b.zip'" in output
