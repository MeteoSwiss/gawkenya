#!/usr/bin/env python3
"""Build the static GAW Kenya Level-1 dashboard.

The generator reads only parquet files in the current UTC YYYY/MM partition for
configured stations. It writes public, derived JSON plus a small static site;
raw parquet files are never copied to the output directory.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import polars as pl
import yaml

SCHEMA_VERSION = 1


def parse_duration_seconds(value: Any) -> float | None:
    """Parse a compact cadence value such as 10s, 1m, 5min, 1h or 1d."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds if seconds > 0 else None

    text = str(value).strip().lower()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([a-z]+)", text)
    if not match:
        raise ValueError(f"Unsupported cadence value: {value!r}")

    amount = float(match.group(1))
    unit = match.group(2)
    factors = {
        "ms": 0.001,
        "millisecond": 0.001,
        "milliseconds": 0.001,
        "s": 1.0,
        "sec": 1.0,
        "secs": 1.0,
        "second": 1.0,
        "seconds": 1.0,
        "m": 60.0,
        "min": 60.0,
        "mins": 60.0,
        "minute": 60.0,
        "minutes": 60.0,
        "h": 3600.0,
        "hr": 3600.0,
        "hour": 3600.0,
        "hours": 3600.0,
        "d": 86400.0,
        "day": 86400.0,
        "days": 86400.0,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported cadence unit in {value!r}")
    seconds = amount * factors[unit]
    return seconds if seconds > 0 else None


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    value = utc_datetime(value)
    if value is None:
        return None
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return utc_datetime(parsed) or datetime.now(UTC)


def expected_rows_for_month(now: datetime, cadence_seconds: float | None) -> int | None:
    """Expected records from month start through *now*, including month start."""
    if not cadence_seconds or cadence_seconds <= 0:
        return None
    now = utc_datetime(now) or datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    elapsed = max(0.0, (now - month_start).total_seconds())
    return int(math.floor(elapsed / cadence_seconds)) + 1


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if "dashboard" not in config or "stations" not in config:
        raise ValueError("Dashboard config must contain 'dashboard' and 'stations'.")
    return config


def source_override(config: dict[str, Any], station: str, source_id: str, stem: str) -> dict[str, Any]:
    overrides = config.get("source_overrides", {}) or {}
    merged: dict[str, Any] = {}
    # Generic first, station-specific last.
    for key in (stem, source_id, f"{station}/{source_id}"):
        value = overrides.get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _is_datetime_dtype(dtype: pl.DataType) -> bool:
    return isinstance(dtype, pl.Datetime) or dtype == pl.Date


def _is_string_dtype(dtype: pl.DataType) -> bool:
    return dtype == pl.String or dtype == pl.Utf8


def _is_numeric_dtype(dtype: pl.DataType) -> bool:
    # DataType.is_numeric() is available in current Polars; the string fallback
    # keeps this generator tolerant of minor API changes within Polars 1.x.
    checker = getattr(dtype, "is_numeric", None)
    if callable(checker):
        try:
            return bool(checker())
        except TypeError:
            pass
    return str(dtype).startswith(("Int", "UInt", "Float", "Decimal"))


def find_time_column(
    schema: dict[str, pl.DataType],
    override: dict[str, Any],
    dashboard_config: dict[str, Any],
) -> str:
    requested = override.get("time_column")
    if requested:
        if requested not in schema:
            raise ValueError(f"Configured time column {requested!r} is not present")
        return str(requested)

    names_by_lower = {name.lower(): name for name in schema}
    for candidate in dashboard_config.get("default_time_columns", ["dtm"]):
        found = names_by_lower.get(str(candidate).lower())
        if found:
            return found

    for name, dtype in schema.items():
        if _is_datetime_dtype(dtype):
            return name
    raise ValueError("No datetime column could be identified")


def time_expression(column: str, dtype: pl.DataType) -> pl.Expr:
    expr = pl.col(column)
    if isinstance(dtype, pl.Datetime):
        timezone = getattr(dtype, "time_zone", None)
        if timezone is None:
            expr = expr.dt.replace_time_zone("UTC")
        elif timezone != "UTC":
            expr = expr.dt.convert_time_zone("UTC")
        return expr.alias("_dt")
    if dtype == pl.Date:
        return expr.cast(pl.Datetime("us")).dt.replace_time_zone("UTC").alias("_dt")
    if _is_string_dtype(dtype):
        return expr.str.to_datetime(strict=False, time_zone="UTC").alias("_dt")
    # This is mostly a defensive fallback for legacy files with castable values.
    return expr.cast(pl.Datetime("us", "UTC"), strict=False).alias("_dt")


def infer_cadence_seconds(time_lazy: pl.LazyFrame, sample_rows: int) -> float | None:
    sample = (
        time_lazy.tail(max(2, int(sample_rows)))
        .collect()
        .drop_nulls()
        .unique()
        .sort("_dt")
    )
    values = [utc_datetime(v) for v in sample.get_column("_dt").to_list()]
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    diffs = [
        (later - earlier).total_seconds()
        for earlier, later in zip(values, values[1:])
        if later > earlier
    ]
    if not diffs:
        return None
    return float(statistics.median(diffs))


def excluded_column(name: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, name) for pattern in patterns)


def select_variables(
    schema: dict[str, pl.DataType],
    time_column: str,
    dashboard_config: dict[str, Any],
    override: dict[str, Any],
) -> list[str]:
    explicit = override.get("variables")
    if explicit is not None:
        missing = [name for name in explicit if name not in schema]
        if missing:
            raise ValueError(f"Configured variable(s) not present: {', '.join(missing)}")
        return [str(name) for name in explicit]

    patterns = list(dashboard_config.get("exclude_columns", []) or [])
    patterns.extend(override.get("exclude_columns", []) or [])
    variables: list[str] = []
    for name, dtype in schema.items():
        if name == time_column or excluded_column(name, patterns):
            continue
        if _is_numeric_dtype(dtype):
            variables.append(name)
    return variables


def clean_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def sample_series(
    lazy: pl.LazyFrame,
    time_expr: pl.Expr,
    variables: list[str],
    row_count: int,
    max_points: int,
) -> tuple[list[str], dict[str, list[int | float | None]]]:
    if not variables or row_count <= 0:
        return [], {name: [] for name in variables}

    stride = max(1, int(math.ceil(row_count / max(1, max_points))))
    projection = [time_expr]
    projection.extend(pl.col(name).cast(pl.Float64, strict=False).alias(name) for name in variables)
    source = lazy.select(projection).filter(pl.col("_dt").is_not_null())

    sampled = (
        source.with_row_index("_sample_row")
        .filter((pl.col("_sample_row") % stride) == 0)
        .drop("_sample_row")
        .collect()
        .sort("_dt")
    )

    # Always include the newest observation, even when it falls between sampled rows.
    newest = source.tail(1).collect()
    if newest.height:
        if not sampled.height or sampled.get_column("_dt")[-1] != newest.get_column("_dt")[-1]:
            sampled = pl.concat([sampled, newest], how="vertical_relaxed").sort("_dt")

    timestamps = [iso_utc(value) for value in sampled.get_column("_dt").to_list()]
    x = [value for value in timestamps if value is not None]

    # _dt is filtered non-null above, so x should have the same length as sampled.
    series: dict[str, list[int | float | None]] = {}
    for name in variables:
        series[name] = [clean_number(value) for value in sampled.get_column(name).to_list()]
    return x, series


def build_source(
    path: Path,
    data_root: Path,
    month_dir: Path,
    station: str,
    config: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dashboard_config = config["dashboard"]
    rel_month = path.relative_to(month_dir).with_suffix("").as_posix()
    source_id = rel_month
    override = source_override(config, station, source_id, path.stem)
    if override.get("publish", True) is False:
        return {}, []

    lazy = pl.scan_parquet(path)
    schema_obj = lazy.collect_schema()
    schema = dict(schema_obj.items())
    time_column = find_time_column(schema, override, dashboard_config)
    time_expr = time_expression(time_column, schema[time_column])
    variables = select_variables(schema, time_column, dashboard_config, override)

    row_count = int(lazy.select(pl.len().alias("n")).collect().item())
    time_lazy = lazy.select(time_expr).filter(pl.col("_dt").is_not_null())
    latest = time_lazy.select(pl.col("_dt").max()).collect().item()

    configured_cadence = parse_duration_seconds(override.get("cadence"))
    if configured_cadence is not None:
        cadence_seconds = configured_cadence
        cadence_source = "config"
    else:
        cadence_seconds = infer_cadence_seconds(
            time_lazy,
            int(dashboard_config.get("cadence_sample_rows", 10000)),
        )
        cadence_source = "median"

    expected_rows = expected_rows_for_month(now, cadence_seconds)
    availability = None
    if expected_rows and expected_rows > 0:
        availability = (row_count / expected_rows) * 100.0

    timestamps, series = sample_series(
        lazy,
        time_expr,
        variables,
        row_count,
        int(dashboard_config.get("max_plot_points", 3000)),
    )

    source_name = path.relative_to(data_root).as_posix()
    source_payload = {
        "source_id": source_id,
        "source_name": source_name,
        "time_column": time_column,
        "cadence_seconds": cadence_seconds,
        "cadence_source": cadence_source,
        "latest_entry": iso_utc(latest),
        "number_rows": row_count,
        "expected_rows": expected_rows,
        "availability_pct": round(availability, 3) if availability is not None else None,
        "timestamps": timestamps,
        "variables": series,
    }

    summary = [
        {
            "variable": variable,
            "source_id": source_id,
            "source_name": source_name,
            "latest_entry": iso_utc(latest),
            "number_rows": row_count,
            "expected_rows": expected_rows,
            "availability_pct": round(availability, 3) if availability is not None else None,
        }
        for variable in variables
    ]
    return source_payload, summary


def build_station(
    station: str,
    station_config: dict[str, Any],
    data_root: Path,
    config: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    level = str(config["dashboard"].get("level", "level1"))
    month_dir = data_root / level / station / f"{now.year:04d}" / f"{now.month:02d}"
    files = sorted(month_dir.rglob("*.parquet")) if month_dir.exists() else []

    sources: dict[str, Any] = {}
    summary: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for path in files:
        try:
            source_payload, source_summary = build_source(
                path=path,
                data_root=data_root,
                month_dir=month_dir,
                station=station,
                config=config,
                now=now,
            )
            if source_payload:
                sources[source_payload["source_id"]] = source_payload
                summary.extend(source_summary)
        except Exception as exc:  # one bad source must not prevent the dashboard
            message = str(exc).replace(str(data_root), "<data-root>")
            errors.append(
                {
                    "source_name": path.relative_to(data_root).as_posix(),
                    "error": f"{type(exc).__name__}: {message}",
                }
            )

    summary.sort(key=lambda row: (row["source_name"].lower(), row["variable"].lower()))
    return {
        "station": station,
        "label": station_config.get("label", station.upper()),
        "period": f"{now.year:04d}-{now.month:02d}",
        "partition": month_dir.relative_to(data_root).as_posix(),
        "file_count": len(files),
        "published_source_count": len(sources),
        "summary": summary,
        "sources": sources,
        "errors": errors,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def build_dashboard(
    data_root: Path,
    output: Path,
    config_path: Path,
    now: datetime | None = None,
    data_commit: str | None = None,
    generator_commit: str | None = None,
) -> dict[str, Any]:
    now = utc_datetime(now) or datetime.now(UTC)
    config = load_config(config_path)
    static_dir = Path(__file__).resolve().parent / "site"

    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(static_dir, output)
    (output / ".nojekyll").touch()
    (output / "data").mkdir(parents=True, exist_ok=True)

    station_index: list[dict[str, Any]] = []
    total_errors = 0
    for station, station_config in config["stations"].items():
        station = str(station).lower()
        station_payload = build_station(
            station=station,
            station_config=station_config or {},
            data_root=data_root,
            config=config,
            now=now,
        )
        data_file = f"data/{station}.json"
        write_json(output / data_file, station_payload)
        total_errors += len(station_payload["errors"])
        station_index.append(
            {
                "id": station,
                "label": station_payload["label"],
                "data_file": data_file,
                "file_count": station_payload["file_count"],
                "published_source_count": station_payload["published_source_count"],
                "variable_count": len(station_payload["summary"]),
                "error_count": len(station_payload["errors"]),
            }
        )

    dashboard_config = config["dashboard"]
    index_payload = {
        "schema_version": SCHEMA_VERSION,
        "title": dashboard_config.get("title", "GAW Kenya data dashboard"),
        "subtitle": dashboard_config.get("subtitle", "Current Level-1 parquet files"),
        "level": dashboard_config.get("level", "level1"),
        "timezone": dashboard_config.get("timezone", "UTC"),
        "period": f"{now.year:04d}-{now.month:02d}",
        "generated_at": iso_utc(now),
        "source_repository": dashboard_config.get("source_repository", "MeteoSwiss/gawkenyadata"),
        "data_commit": data_commit,
        "generator_commit": generator_commit,
        "stations": station_index,
        "error_count": total_errors,
    }
    write_json(output / "data" / "index.json", index_payload)
    return index_payload


def parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-root", type=Path, required=True, help="Root of gawkenyadata checkout")
    result.add_argument("--output", type=Path, required=True, help="Directory to create for GitHub Pages")
    result.add_argument("--config", type=Path, default=here / "config.yml", help="Dashboard YAML config")
    result.add_argument("--now", help="Override build time (ISO-8601); useful for tests/reproducibility")
    result.add_argument("--data-commit", default=os.environ.get("GITHUB_SHA"), help="gawkenyadata commit SHA")
    result.add_argument("--generator-commit", help="gawkenya dashboard source commit SHA")
    return result


def main() -> None:
    args = parser().parse_args()
    result = build_dashboard(
        data_root=args.data_root.resolve(),
        output=args.output.resolve(),
        config_path=args.config.resolve(),
        now=parse_now(args.now),
        data_commit=args.data_commit,
        generator_commit=args.generator_commit,
    )
    print(
        f"Dashboard built for {result['period']}: "
        f"{len(result['stations'])} station(s), {result['error_count']} source error(s)."
    )


if __name__ == "__main__":
    main()
