from datetime import UTC, datetime
import json
from pathlib import Path

import polars as pl

from monitoring.dashboard.build_dashboard import (
    build_dashboard,
    expected_rows_for_month,
    parse_duration_seconds,
)


def test_parse_duration_seconds():
    assert parse_duration_seconds("30s") == 30
    assert parse_duration_seconds("1m") == 60
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds(15) == 15


def test_expected_rows_from_month_start():
    now = datetime(2026, 8, 1, 0, 4, tzinfo=UTC)
    assert expected_rows_for_month(now, 60) == 5


def test_build_dashboard_current_partition(tmp_path: Path):
    data_root = tmp_path / "gawkenyadata"
    month = data_root / "level1" / "mkn" / "2026" / "08"
    month.mkdir(parents=True)

    frame = pl.DataFrame(
        {
            "dtm": [
                datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
                datetime(2026, 8, 1, 0, 2, tzinfo=UTC),
                datetime(2026, 8, 1, 0, 3, tzinfo=UTC),
                datetime(2026, 8, 1, 0, 4, tzinfo=UTC),
            ],
            "BC1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "BC2": [2.0, 3.0, 4.0, 5.0, 6.0],
            "status": [0, 0, 0, 0, 0],
        }
    )
    frame.write_parquet(month / "ae33.parquet")

    config = tmp_path / "config.yml"
    config.write_text(
        """
dashboard:
  title: Test dashboard
  level: level1
  timezone: UTC
  max_plot_points: 100
  cadence_sample_rows: 100
  default_time_columns: [dtm]
  exclude_columns: ['(?i)^status$']
stations:
  mkn: {label: MKN}
source_overrides: {}
""",
        encoding="utf-8",
    )

    output = tmp_path / "site"
    build_dashboard(
        data_root=data_root,
        output=output,
        config_path=config,
        now=datetime(2026, 8, 1, 0, 4, tzinfo=UTC),
        data_commit="data123",
        generator_commit="code456",
    )

    index = json.loads((output / "data" / "index.json").read_text())
    station = json.loads((output / "data" / "mkn.json").read_text())

    assert index["period"] == "2026-08"
    assert index["data_commit"] == "data123"
    assert station["file_count"] == 1
    assert station["published_source_count"] == 1
    assert [row["variable"] for row in station["summary"]] == ["BC1", "BC2"]

    source = station["sources"]["ae33"]
    assert source["source_name"] == "level1/mkn/2026/08/ae33.parquet"
    assert source["latest_entry"] == "2026-08-01T00:04:00Z"
    assert source["number_rows"] == 5
    assert source["expected_rows"] == 5
    assert source["availability_pct"] == 100.0
    assert source["cadence_source"] == "median"
    assert source["cadence_seconds"] == 60.0
    assert set(source["variables"]) == {"BC1", "BC2"}
    assert len(source["timestamps"]) == 5
