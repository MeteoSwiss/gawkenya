from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from compile_level1_to_level2_files import (
    AggregationSpec,
    ColumnSpec,
    Defaults,
    InstrumentSpec,
    build_aggregate_dataframe,
    load_station_config,
    process_station_instrument_year,
)


def _agg(every: str, default: str = "mean") -> AggregationSpec:
    return AggregationSpec(every=every, label="left", closed="left", default_method=default)


def _defaults(*, accept_null_flags: bool = True) -> Defaults:
    return Defaults(
        datetime_column="dtm",
        timezone="UTC",
        valid_flag_value=0,
        accept_null_flags=accept_null_flags,
        parquet_compression="zstd",
        flag_mode="per_column_prefix",
        flag_prefix="f_",
        write_hourly=True,
        write_daily=True,
        write_monthly=True,
        hourly=_agg("1h"),
        daily=_agg("1d"),
        monthly=_agg("1mo"),
    )


def _instrument(*, method: str = "mean") -> InstrumentSpec:
    return InstrumentSpec(
        name="tei49i",
        columns=(
            ColumnSpec(
                name="O3",
                output_name="O3",
                hourly_method=method,
                daily_method=method,
                monthly_method=method,
                flag_column=None,
            ),
        ),
    )


def _write_flagged_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "dtm": [
                datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 40, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 1, 0, 20, tzinfo=timezone.utc),
            ],
            # Lower-case source names deliberately test case-insensitive lookup
            # for configured O3 and its inferred f_O3 flag.
            "o3": [10.0, 30.0, 90.0, 100.0, 50.0, 70.0, None],
            "f_o3": [0, None, 1, 0, 0, 0, 0],
        }
    ).write_parquet(path)


def test_hourly_counts_follow_same_validity_rule(tmp_path: Path) -> None:
    source = tmp_path / "tei49i.parquet"
    _write_flagged_source(source)

    out = build_aggregate_dataframe([source], _defaults(), _instrument(), "hourly")
    assert out is not None

    first = out.row(0, named=True)
    assert first["O3"] == pytest.approx(20.0)
    assert first["n_O3"] == 2


def test_strict_flag_zero_excludes_null_flags(tmp_path: Path) -> None:
    source = tmp_path / "tei49i.parquet"
    _write_flagged_source(source)

    out = build_aggregate_dataframe(
        [source],
        _defaults(accept_null_flags=False),
        _instrument(),
        "hourly",
    )
    assert out is not None

    first = out.row(0, named=True)
    assert first["O3"] == pytest.approx(10.0)
    assert first["n_O3"] == 1


def test_daily_and_monthly_are_aggregated_directly_from_level1(tmp_path: Path) -> None:
    source = tmp_path / "tei49i.parquet"
    _write_flagged_source(source)
    defaults = _defaults()
    instrument = _instrument()

    daily = build_aggregate_dataframe([source], defaults, instrument, "daily")
    monthly = build_aggregate_dataframe([source], defaults, instrument, "monthly")
    assert daily is not None
    assert monthly is not None

    jan_1 = daily.row(0, named=True)
    # Direct Level 1 mean of 10, 30, 100. Averaging hourly means instead would
    # incorrectly produce 60, so this assertion catches that regression.
    assert jan_1["O3"] == pytest.approx(140.0 / 3.0)
    assert jan_1["n_O3"] == 3

    january = monthly.row(0, named=True)
    assert january["O3"] == pytest.approx((10.0 + 30.0 + 100.0 + 50.0) / 4.0)
    assert january["n_O3"] == 4

    february = monthly.row(1, named=True)
    assert february["O3"] == pytest.approx(70.0)
    assert february["n_O3"] == 1


def test_no_flag_column_counts_non_null_values(tmp_path: Path) -> None:
    source = tmp_path / "unflagged.parquet"
    pl.DataFrame(
        {
            "dtm": [
                datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc),
            ],
            "O3": [1.0, None, 3.0],
        }
    ).write_parquet(source)

    out = build_aggregate_dataframe([source], _defaults(), _instrument(), "hourly")
    assert out is not None
    row = out.row(0, named=True)
    assert row["O3"] == pytest.approx(2.0)
    assert row["n_O3"] == 2


def test_sum_is_null_when_no_valid_values_exist(tmp_path: Path) -> None:
    source = tmp_path / "invalid.parquet"
    pl.DataFrame(
        {
            "dtm": [datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)],
            "O3": [5.0],
            "f_O3": [1],
        }
    ).write_parquet(source)

    out = build_aggregate_dataframe(
        [source],
        _defaults(accept_null_flags=False),
        _instrument(method="sum"),
        "hourly",
    )
    assert out is not None
    row = out.row(0, named=True)
    assert row["O3"] is None
    assert row["n_O3"] == 0


def test_process_writes_hourly_daily_and_monthly_products(tmp_path: Path) -> None:
    root = tmp_path / "gawkenyadata"
    source = root / "level1" / "mkn" / "2026" / "01" / "tei49i.parquet"
    _write_flagged_source(source)

    written = process_station_instrument_year(
        root=root,
        station="mkn",
        defaults=_defaults(),
        instrument=_instrument(),
        year=2026,
        write=True,
    )

    assert set(written) == {"hourly", "daily", "monthly"}
    for frequency, path in written.items():
        assert path.exists(), frequency
        frame = pl.read_parquet(path)
        assert frame.columns == ["dtm", "O3", "n_O3"]


def test_yaml_parses_monthly_and_column_specific_method(tmp_path: Path) -> None:
    config = tmp_path / "station.yml"
    config.write_text(
        """
level2:
  station: mkn
  datetime_column: dtm
  timezone: UTC
  output:
    hourly: true
    daily: true
    monthly: true
  aggregation:
    hourly: {default: mean, every: 1h, label: left, closed: left}
    daily: {default: mean, every: 1d, label: left, closed: left}
    monthly: {default: mean, every: 1mo, label: left, closed: left}
  instruments:
    tei49i:
      columns:
        - name: O3
          agg:
            monthly: median
""".lstrip(),
        encoding="utf-8",
    )

    loaded = load_station_config(config)
    assert loaded.defaults.write_monthly is True
    assert loaded.defaults.monthly.every == "1mo"
    assert loaded.instruments["tei49i"].columns[0].monthly_method == "median"


def test_process_is_dry_run_by_default(tmp_path: Path) -> None:
    root = tmp_path / "gawkenyadata"
    source = root / "level1" / "mkn" / "2026" / "01" / "tei49i.parquet"
    _write_flagged_source(source)

    planned = process_station_instrument_year(
        root=root,
        station="mkn",
        defaults=_defaults(),
        instrument=_instrument(),
        year=2026,
    )

    assert set(planned) == {"hourly", "daily", "monthly"}
    assert all(not path.exists() for path in planned.values())


def test_run_dry_run_returns_statistics_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from compile_level1_to_level2_files import print_summary, run

    root = tmp_path / "gawkenyadata"
    source = root / "level1" / "mkn" / "2026" / "01" / "tei49i.parquet"
    _write_flagged_source(source)

    config = tmp_path / "station.yml"
    config.write_text(
        """
level2:
  station: mkn
  datetime_column: dtm
  timezone: UTC
  valid_flag_value: 0
  accept_null_flags: true
  output:
    hourly: true
    daily: true
    monthly: true
  aggregation:
    hourly: {default: mean, every: 1h, label: left, closed: left}
    daily: {default: mean, every: 1d, label: left, closed: left}
    monthly: {default: mean, every: 1mo, label: left, closed: left}
  instruments:
    tei49i:
      columns:
        - O3
""".lstrip(),
        encoding="utf-8",
    )

    stats = run(root, config)
    assert stats.dry_run is True
    assert stats.errors == 0
    assert len(stats.jobs) == 1

    job = stats.jobs[0]
    assert job.source_files == 1
    assert job.level1_rows == 7
    assert job.values["O3"].available == 6
    assert job.values["O3"].valid == 5
    assert job.aggregate_rows == {"hourly": 4, "daily": 3, "monthly": 2}
    assert set(job.output_paths) == {"hourly", "daily", "monthly"}
    assert not job.written_outputs
    assert all(not path.exists() for path in job.output_paths.values())

    print_summary(stats)
    output = capsys.readouterr().out
    assert "Mode                     : dry run (no files written)" in output
    assert "Source parquet files     : 1" in output
    assert "Level 1 rows loaded      : 7" in output
    assert "Valid / available values : 5/6 (83.3%)" in output
    assert "Outputs planned          : 3" in output


def test_cli_is_dry_run_by_default_and_write_is_explicit() -> None:
    from compile_level1_to_level2_files import parse_args

    dry_args = parse_args(
        [
            "--root",
            "/tmp/gawkenyadata",
            "--station-config",
            "mch-mkn.yml",
        ]
    )
    assert dry_args.write is False

    write_args = parse_args(
        [
            "--root",
            "/tmp/gawkenyadata",
            "--station-config",
            "mch-mkn.yml",
            "--write",
        ]
    )
    assert write_args.write is True


def test_processing_log_path_contains_instrument_and_utc_timestamp(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from compile_level1_to_level2_files import processing_log_path

    path = processing_log_path(
        "ae33/data",
        when=datetime(2026, 10, 7, 9, 36, 45, tzinfo=UTC),
        log_dir=tmp_path,
    )
    assert path == tmp_path / "compile_level1_to_level2_ae33-data_20261007T093645Z.log"


def test_cli_creates_processing_log_only_with_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import compile_level1_to_level2_files as module

    root = tmp_path / "gawkenyadata"
    source = root / "level1" / "mkn" / "2026" / "01" / "tei49i.parquet"
    _write_flagged_source(source)

    config = tmp_path / "station.yml"
    config.write_text(
        """
level2:
  station: mkn
  datetime_column: dtm
  timezone: UTC
  valid_flag_value: 0
  accept_null_flags: true
  output:
    hourly: true
    daily: false
    monthly: false
  aggregation:
    hourly: {default: mean, every: 1h, label: left, closed: left}
  instruments:
    tei49i:
      columns:
        - O3
""".lstrip(),
        encoding="utf-8",
    )

    log_dir = tmp_path / "logs"
    monkeypatch.setattr(
        module,
        "processing_log_path",
        lambda instrument_name: log_dir / f"run_{instrument_name or 'all'}.log",
    )

    base_args = [
        "--root",
        str(root),
        "--station-config",
        str(config),
        "--instrument",
        "tei49i",
        "--year",
        "2026",
    ]

    assert module.main(base_args) == 0
    assert not log_dir.exists()

    assert module.main([*base_args, "--write"]) == 0
    log_path = log_dir / "run_tei49i.log"
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "Processing log" in log_text
    assert "Mode                     : write" in log_text
    assert "Summary" in log_text
