from __future__ import annotations

"""Collect and aggregate level 1 parquet files into level 2 parquet files.

This utility crawls a ``gawkenyadata`` repository that follows a level 1 layout
such as either::

    gawkenyadata/
      level1/
        nrb/
          2026/
            03/
              49i/
                *.parquet
              ae31/
                *.parquet

or flat monthly parquet files such as::

    gawkenyadata/
      level1/
        mkn/
          2022/
            11/
              ae33.parquet
              g2401.parquet

and writes yearly level 2 parquet files to::

    gawkenyadata/
      level2/
        nrb/
          2026/
            nrb_49i_hourly_2026.parquet
            nrb_49i_daily_2026.parquet

The level 2 rules are read from the station configuration YAML. For a single-
station file such as ``mch-mkn.yml``, the ``level2`` block can live at the top
level. For multi-block files such as ``mch-nrb.yml``, the ``level2`` block can
live inside a section such as ``nrb-aq`` and be selected with
``--config-section nrb-aq``.

Only configured columns are kept. A value is considered valid when the
associated flag column is either ``0`` or null. When no flag column exists,
non-null values are accepted.

Daily aggregates are computed from the hourly aggregates, not directly from the
raw level 1 files.

Example calls:
    Build MKN level 2 files using the embedded ``level2`` block::

        python compile_level1_to_level2_files.py             --root /product_data/data/pay/Kenya/git/gawkenyadata             --station-config mch-mkn.yml

    Build Nairobi air-quality level 2 files from the ``nrb-aq`` section::

        python compile_level1_to_level2_files.py             --root /product_data/data/pay/Kenya/git/gawkenyadata             --station-config mch-nrb.yml             --config-section nrb-aq

    Restrict processing to one configured instrument::

        python compile_level1_to_level2_files.py             --root /product_data/data/pay/Kenya/git/gawkenyadata             --station-config mch-nrb.yml             --config-section nrb-aq             --instrument ae31

    Restrict processing to one year::

        python compile_level1_to_level2_files.py             --root /product_data/data/pay/Kenya/git/gawkenyadata             --station-config mch-mkn.yml             --year 2025
"""

from dataclasses import dataclass
from pathlib import Path
import argparse
import logging
import math
from typing import Any, Literal

import polars as pl
import yaml

LOGGER = logging.getLogger("collect_level2")


GroupLabel = Literal["left", "right", "datapoint"]
ClosedInterval = Literal["left", "right", "both", "none"]
ParquetCompression = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]


@dataclass(frozen=True)
class AggregationSpec:
    """Aggregation settings for one output frequency."""

    every: str
    label: GroupLabel
    closed: ClosedInterval
    default_method: str


@dataclass(frozen=True)
class Defaults:
    """Top-level defaults loaded from the YAML configuration."""

    datetime_column: str
    timezone: str | None
    valid_flag_value: int | float
    accept_null_flags: bool
    parquet_compression: ParquetCompression
    flag_mode: str
    flag_prefix: str
    write_hourly: bool
    write_daily: bool
    hourly: AggregationSpec
    daily: AggregationSpec


@dataclass(frozen=True)
class ColumnSpec:
    """One configured output column for an instrument.

    Attributes:
        name: Source column name in the level 1 parquet file.
        output_name: Column name to use in level 2 output. Defaults to ``name``.
        hourly_method: Hourly aggregation method.
        daily_method: Daily aggregation method.
        flag_column: Explicit flag column. If not given, the global flag rules
            are used to infer the flag column.

    Example:
        ``ColumnSpec(name="precip", output_name="precip", hourly_method="sum",
        daily_method="sum", flag_column="f_precip")``
    """

    name: str
    output_name: str
    hourly_method: str
    daily_method: str
    flag_column: str | None


@dataclass(frozen=True)
class InstrumentSpec:
    """Configuration for one instrument.

    Attributes:
        name: Logical instrument key from the station config, for example
            ``ae33/data``.
        columns: Selected output columns for level 2.
        source_parquet: Optional monthly parquet stem to look for under
            ``level1/<station>/<year>/<month>``. When omitted, the loader tries
            the full instrument key and its basename.
        flag_mode: Optional instrument-specific flag mode override.
        flag_prefix: Optional instrument-specific flag prefix override.
    """

    name: str
    columns: tuple[ColumnSpec, ...]
    source_parquet: str | None = None
    flag_mode: str | None = None
    flag_prefix: str | None = None


@dataclass(frozen=True)
class StationConfig:
    """Resolved station configuration for level 2 processing.

    Attributes:
        station: Station code such as ``mkn`` or ``nrb``.
        defaults: Global level 2 defaults.
        instruments: Configured instruments.
    """

    station: str
    defaults: Defaults
    instruments: dict[str, InstrumentSpec]


class ConfigError(ValueError):
    """Raised when the YAML configuration is invalid."""


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging.

    Args:
        verbose: If true, enable DEBUG logging.

    Example:
        ``setup_logging(verbose=True)``
    """

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse_group_label(raw: Any) -> GroupLabel:
    """Validate a Polars dynamic-group label value."""

    if raw in ("left", "right", "datapoint"):
        return raw
    raise ConfigError(f"Unsupported group_by_dynamic label: {raw!r}")


def _parse_closed_interval(raw: Any) -> ClosedInterval:
    """Validate a Polars dynamic-group closed value."""

    if raw in ("left", "right", "both", "none"):
        return raw
    raise ConfigError(f"Unsupported group_by_dynamic closed value: {raw!r}")


def _parse_parquet_compression(raw: Any) -> ParquetCompression:
    """Validate a parquet compression codec."""

    if raw in ("lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"):
        return raw
    raise ConfigError(f"Unsupported parquet compression: {raw!r}")


def _default_level2_block() -> dict[str, Any]:
    """Return a default ``level2`` mapping.

    Returns:
        Starter level 2 configuration for embedding in station YAML files.
    """

    return {
        "station": "station_code",
        "datetime_column": "dtm",
        "timezone": "UTC",
        "valid_flag_value": 0,
        "accept_null_flags": True,
        "parquet_compression": "zstd",
        "output": {"hourly": True, "daily": True},
        "flags": {"mode": "per_column_prefix", "prefix": "f_"},
        "aggregation": {
            "hourly": {
                "default": "mean",
                "every": "1h",
                "label": "left",
                "closed": "left",
            },
            "daily": {
                "default": "mean",
                "every": "1d",
                "label": "left",
                "closed": "left",
            },
        },
        "instruments": {
            "tei49c": {"columns": ["O3"]},
            "tei49i": {"columns": ["O3"]},
            "49i": {"columns": ["O3"]},
            "ae31": {
                "columns": [
                    "UV370",
                    "B470",
                    "G520",
                    "Y590",
                    "R660",
                    "IR880",
                    "IR950",
                ]
            },
            "ae33/data": {
                "source_parquet": "ae33",
                "columns": ["BC1", "BC2", "BC3", "BC4", "BC5", "BC6"],
            },
            "fidas": {"columns": ["PM1", "PM2.5", "PM4", "PM10"]},
        },
    }


def write_example_station_config(path: Path, section: str | None = None) -> None:
    """Write a starter station configuration with an embedded ``level2`` block.

    Args:
        path: Target YAML path.
        section: Optional section name. When given, the ``level2`` block is
            placed inside that section.

    Example:
        ``write_example_station_config(Path("mch-mkn.yml"))``
        ``write_example_station_config(Path("mch-nrb.yml"), section="nrb-aq")``
    """

    payload: dict[str, Any]
    if section is None:
        payload = {"level2": _default_level2_block()}
    else:
        payload = {section: {"level2": _default_level2_block()}}

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)


def load_station_config(path: Path, config_section: str | None = None) -> StationConfig:
    """Load and validate embedded level 2 settings from a station YAML file.

    Args:
        path: Path to a station configuration file such as ``mch-mkn.yml``.
        config_section: Optional top-level section containing the ``level2``
            block, for example ``nrb-aq``.

    Returns:
        Resolved ``StationConfig``.

    Raises:
        ConfigError: If the configuration is invalid.

    Example:
        ``cfg = load_station_config(Path("mch-mkn.yml"))``
        ``cfg = load_station_config(Path("mch-nrb.yml"), config_section="nrb-aq")``
    """

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError("Station configuration must be a YAML mapping.")

    scope = _resolve_level2_scope(raw, path, config_section)
    level2_raw = scope.get("level2")
    if not isinstance(level2_raw, dict):
        raise ConfigError("Missing or invalid 'level2' mapping in station configuration.")

    station = level2_raw.get("station")
    if not isinstance(station, str) or not station.strip():
        raise ConfigError("The embedded level2 block must define a non-empty 'station'.")
    station = station.strip()

    aggregation_raw = level2_raw.get("aggregation", {}) or {}
    flags_raw = level2_raw.get("flags", {}) or {}
    output_raw = level2_raw.get("output", {}) or {}

    hourly_raw = aggregation_raw.get("hourly", {}) or {}
    daily_raw = aggregation_raw.get("daily", {}) or {}

    defaults = Defaults(
        datetime_column=level2_raw.get("datetime_column", "dtm"),
        timezone=level2_raw.get("timezone"),
        valid_flag_value=level2_raw.get("valid_flag_value", 0),
        accept_null_flags=bool(level2_raw.get("accept_null_flags", True)),
        parquet_compression=_parse_parquet_compression(level2_raw.get("parquet_compression", "zstd")),
        flag_mode=flags_raw.get("mode", "per_column_prefix"),
        flag_prefix=flags_raw.get("prefix", "f_"),
        write_hourly=bool(output_raw.get("hourly", True)),
        write_daily=bool(output_raw.get("daily", True)),
        hourly=AggregationSpec(
            every=hourly_raw.get("every", "1h"),
            label=_parse_group_label(hourly_raw.get("label", "left")),
            closed=_parse_closed_interval(hourly_raw.get("closed", "left")),
            default_method=hourly_raw.get("default", "mean"),
        ),
        daily=AggregationSpec(
            every=daily_raw.get("every", "1d"),
            label=_parse_group_label(daily_raw.get("label", "left")),
            closed=_parse_closed_interval(daily_raw.get("closed", "left")),
            default_method=daily_raw.get("default", "mean"),
        ),
    )

    instruments_raw = level2_raw.get("instruments")
    if not isinstance(instruments_raw, dict) or not instruments_raw:
        raise ConfigError("Embedded level2 configuration must contain a non-empty 'instruments' mapping.")

    instruments: dict[str, InstrumentSpec] = {}
    for instrument_name, instrument_raw in instruments_raw.items():
        if not isinstance(instrument_name, str) or not instrument_name:
            raise ConfigError("Instrument names in level2.instruments must be non-empty strings.")

        if not isinstance(instrument_raw, dict):
            raise ConfigError(f"Instrument '{instrument_name}' must map to a dictionary.")

        instrument_flags = instrument_raw.get("flags", {}) or {}
        columns_raw = instrument_raw.get("columns")
        if not isinstance(columns_raw, list) or not columns_raw:
            raise ConfigError(f"Instrument '{instrument_name}' must define a non-empty columns list.")

        columns: list[ColumnSpec] = []
        for column_raw in columns_raw:
            columns.append(_parse_column_spec(column_raw, defaults))

        source_parquet = instrument_raw.get("source_parquet")
        if source_parquet is not None and (not isinstance(source_parquet, str) or not source_parquet.strip()):
            raise ConfigError(
                f"Instrument '{instrument_name}' has an invalid source_parquet; expected a non-empty string."
            )

        instruments[instrument_name] = InstrumentSpec(
            name=instrument_name,
            columns=tuple(columns),
            source_parquet=source_parquet.strip() if isinstance(source_parquet, str) else None,
            flag_mode=instrument_flags.get("mode"),
            flag_prefix=instrument_flags.get("prefix"),
        )

    return StationConfig(station=station, defaults=defaults, instruments=instruments)


def _resolve_level2_scope(
    raw: dict[str, Any],
    path: Path,
    config_section: str | None,
) -> dict[str, Any]:
    """Resolve the YAML scope that contains the ``level2`` mapping.

    Args:
        raw: Full YAML mapping.
        path: Source configuration path.
        config_section: Optional top-level section name.

    Returns:
        Mapping that contains ``level2``.

    Raises:
        ConfigError: If the scope cannot be resolved unambiguously.
    """

    if config_section is not None:
        scope = raw.get(config_section)
        if not isinstance(scope, dict):
            raise ConfigError(
                f"Section '{config_section}' was not found or is not a mapping in {path}."
            )
        return scope

    if isinstance(raw.get("level2"), dict):
        return raw

    candidate_sections = [
        name for name, value in raw.items() if isinstance(value, dict) and isinstance(value.get("level2"), dict)
    ]
    if len(candidate_sections) == 1:
        return raw[candidate_sections[0]]
    if len(candidate_sections) > 1:
        raise ConfigError(
            f"Multiple sections contain a level2 block in {path}; use --config-section."
        )

    raise ConfigError(
        f"No level2 block found in {path}. Add one at the top level or select a section with --config-section."
    )


def _parse_column_spec(raw: Any, defaults: Defaults) -> ColumnSpec:
    """Parse one configured column specification.

    Args:
        raw: Raw YAML value for one item in ``columns``.
        defaults: Global defaults.

    Returns:
        Normalized ``ColumnSpec``.
    """

    if isinstance(raw, str):
        return ColumnSpec(
            name=raw,
            output_name=raw,
            hourly_method=defaults.hourly.default_method,
            daily_method=defaults.daily.default_method,
            flag_column=None,
        )

    if not isinstance(raw, dict):
        raise ConfigError(f"Column entry must be a string or dictionary, got {type(raw)!r}.")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError("Expanded column entries require a non-empty 'name'.")

    agg_raw = raw.get("agg", {}) or {}
    return ColumnSpec(
        name=name,
        output_name=raw.get("rename", name),
        hourly_method=agg_raw.get("hourly", defaults.hourly.default_method),
        daily_method=agg_raw.get("daily", defaults.daily.default_method),
        flag_column=raw.get("flag_column"),
    )


def discover_years(level1_root: Path, station: str) -> list[int]:
    """Discover available years for one station.

    Args:
        level1_root: Path to ``level1``.
        station: Station code such as ``nrb``.

    Returns:
        Sorted integer years.
    """

    station_root = level1_root / station
    years: list[int] = []
    if not station_root.exists():
        return years

    for path in station_root.iterdir():
        if path.is_dir() and path.name.isdigit():
            years.append(int(path.name))
    return sorted(years)


def source_parquet_candidates(instrument: InstrumentSpec) -> tuple[str, ...]:
    """Return candidate monthly parquet stems for one configured instrument.

    The explicit ``source_parquet`` value takes precedence. When it is omitted,
    the loader tries both the full instrument key and its basename.

    Args:
        instrument: Instrument configuration.

    Returns:
        Candidate monthly parquet stems in priority order.

    Example:
        ``source_parquet_candidates(instruments["ae33/data"])``
    """

    if instrument.source_parquet:
        return (instrument.source_parquet,)

    candidates: list[str] = [instrument.name]
    basename = Path(instrument.name).name
    if basename not in candidates:
        candidates.append(basename)
    return tuple(candidates)


def parquet_files_for(level1_root: Path, station: str, instrument: InstrumentSpec, year: int) -> list[Path]:
    """Return all parquet files for one station, instrument, and year.

    Supports both layouts:

    1. Flat monthly files such as
       ``level1/<station>/<year>/<month>/<source>.parquet``

    2. Instrument subdirectories such as
       ``level1/<station>/<year>/<month>/<instrument>/**/*.parquet``

    Args:
        level1_root: Path to ``level1``.
        station: Station code.
        instrument: Instrument configuration.
        year: Four-digit year.

    Returns:
        Sorted parquet paths.

    Example:
        ``files = parquet_files_for(level1_root, "mkn", instruments["ae33/data"], 2022)``
    """

    year_root = level1_root / station / str(year)
    if not year_root.exists():
        return []

    paths: list[Path] = []
    candidates = source_parquet_candidates(instrument)

    for month_root in sorted(path for path in year_root.iterdir() if path.is_dir()):
        for candidate in candidates:
            direct_file = month_root / f"{candidate}.parquet"
            if direct_file.exists():
                paths.append(direct_file)

            instrument_root = month_root / candidate
            if instrument_root.is_dir():
                paths.extend(sorted(instrument_root.rglob("*.parquet")))

    return sorted(set(paths))


def resolve_flag_column(
    column: ColumnSpec,
    instrument: InstrumentSpec,
    defaults: Defaults,
    available_columns: set[str],
) -> str | None:
    """Resolve the flag column for one value column.

    Args:
        column: Column definition.
        instrument: Instrument configuration.
        defaults: Global defaults.
        available_columns: Columns present in the input parquet files.

    Returns:
        A flag column name or ``None`` if no suitable flag column exists.
    """

    if column.flag_column:
        return column.flag_column if column.flag_column in available_columns else None

    flag_mode = instrument.flag_mode or defaults.flag_mode
    if flag_mode == "per_column_prefix":
        prefix = instrument.flag_prefix or defaults.flag_prefix
        candidate = f"{prefix}{column.name}"
        return candidate if candidate in available_columns else None

    if flag_mode == "none":
        return None

    raise ConfigError(f"Unsupported flag mode: {flag_mode!r}")


def _safe_timestamp_expr(datetime_column: str, timezone: str | None) -> pl.Expr:
    """Return an expression that converts the datetime column to Polars datetime.

    Args:
        datetime_column: Name of the timestamp column.
        timezone: Optional target timezone.

    Returns:
        Polars expression.
    """

    expr = pl.col(datetime_column)
    if timezone:
        return expr.str.to_datetime(strict=False).dt.replace_time_zone(timezone)
    return expr.str.to_datetime(strict=False)


def _aggregation_expr(method: str, column_name: str, output_name: str) -> pl.Expr:
    """Build one Polars aggregation expression.

    Supported methods are ``mean``, ``sum``, ``median``, ``min``, ``max``,
    ``first``, ``last``, and ``circular_mean``.

    Args:
        method: Aggregation method.
        column_name: Source column name.
        output_name: Output column name.

    Returns:
        Aggregation expression.

    Raises:
        ConfigError: If the method is unsupported.
    """

    series = pl.col(column_name)
    method_lower = method.lower()

    if method_lower == "mean":
        return series.mean().alias(output_name)
    if method_lower == "sum":
        return series.sum().alias(output_name)
    if method_lower == "median":
        return series.median().alias(output_name)
    if method_lower == "min":
        return series.min().alias(output_name)
    if method_lower == "max":
        return series.max().alias(output_name)
    if method_lower == "first":
        return series.first().alias(output_name)
    if method_lower == "last":
        return series.last().alias(output_name)
    if method_lower == "circular_mean":
        radians = series * math.pi / 180.0
        return (
            pl.struct(
                radians.sin().mean().alias("sin_mean"),
                radians.cos().mean().alias("cos_mean"),
            )
            .map_elements(
                lambda values: (
                    math.degrees(math.atan2(values["sin_mean"], values["cos_mean"])) % 360.0
                    if values["sin_mean"] is not None and values["cos_mean"] is not None
                    else None
                ),
                return_dtype=pl.Float64,
            )
            .alias(output_name)
        )

    raise ConfigError(f"Unsupported aggregation method: {method!r}")


from pathlib import Path

import polars as pl


def _resolve_available_column(name: str, available_columns: set[str]) -> str | None:
    """Resolve a column name case-insensitively against available columns."""
    lookup = {column.lower(): column for column in available_columns}
    return lookup.get(name.lower())


def build_hourly_dataframe(
    files: list[Path],
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> pl.DataFrame | None:
    """Build one yearly hourly dataframe from level 1 parquet files.

    Args:
        files: Parquet files for one station, instrument, and year.
        defaults: Global defaults.
        instrument: Instrument configuration.

    Returns:
        Hourly dataframe or ``None`` when no usable input exists.

    Example:
        ``hourly_df = build_hourly_dataframe(files, defaults, instruments["49i"])``
    """
    if not files:
        return None

    scan = pl.scan_parquet(
        [str(path) for path in files],
        cast_options=pl.ScanCastOptions(
            integer_cast="upcast",
            float_cast="upcast",
        ),
        missing_columns="insert",
        extra_columns="ignore",
    )

    available_columns = set(scan.collect_schema().names())

    actual_datetime_column = _resolve_available_column(defaults.datetime_column, available_columns)
    if actual_datetime_column is None:
        LOGGER.warning(
            "Skipping %s because %s is missing.",
            instrument.name,
            defaults.datetime_column,
        )
        return None

    alias_exprs: list[pl.Expr] = []
    if actual_datetime_column != defaults.datetime_column:
        alias_exprs.append(pl.col(actual_datetime_column).alias(defaults.datetime_column))

    needed_columns: set[str] = {actual_datetime_column}
    resolved_flags: dict[str, str | None] = {}

    for column in instrument.columns:
        actual_column_name = _resolve_available_column(column.name, available_columns)
        if actual_column_name is None:
            LOGGER.warning(
                "Input is missing configured column %s for %s.",
                column.name,
                instrument.name,
            )
            continue

        needed_columns.add(actual_column_name)

        if actual_column_name != column.name:
            alias_exprs.append(pl.col(actual_column_name).alias(column.name))

        resolved_flag = resolve_flag_column(column, instrument, defaults, available_columns)
        resolved_flags[column.name] = resolved_flag
        if resolved_flag:
            needed_columns.add(resolved_flag)

    selected_columns = sorted(needed_columns)
    df = scan.select(selected_columns).collect()

    if alias_exprs:
        df = df.with_columns(alias_exprs)

    if defaults.datetime_column not in df.columns:
        return None

    if df.is_empty():
        return None

    dt_series = df.get_column(defaults.datetime_column)
    if dt_series.dtype == pl.Utf8:
        dt_expr = _safe_timestamp_expr(defaults.datetime_column, defaults.timezone)
        df = df.with_columns(dt_expr.alias(defaults.datetime_column))
    elif defaults.timezone and str(dt_series.dtype).startswith("Datetime"):
        try:
            df = df.with_columns(
                pl.col(defaults.datetime_column).dt.convert_time_zone(defaults.timezone)
            )
        except Exception:
            pass

    df = df.sort(defaults.datetime_column)

    # Normalize integer flag columns after scan/collect as an extra safeguard.
    flag_casts = {
        name: pl.Int32
        for name, dtype in df.schema.items()
        if name.startswith("f_") and dtype.is_integer()
    }
    if flag_casts:
        df = df.cast(flag_casts, strict=False)

    cleaned_exprs: list[pl.Expr] = []
    aggregation_exprs: list[pl.Expr] = []

    for column in instrument.columns:
        if column.name not in df.columns:
            continue

        flag_column = resolved_flags.get(column.name)
        valid_condition = pl.col(column.name).is_not_null()
        if flag_column and flag_column in df.columns:
            if defaults.accept_null_flags:
                valid_condition = valid_condition & (
                    pl.col(flag_column).is_null()
                    | (pl.col(flag_column) == defaults.valid_flag_value)
                )
            else:
                valid_condition = valid_condition & (
                    pl.col(flag_column) == defaults.valid_flag_value
                )

        clean_name = f"__clean__{column.output_name}"
        cleaned_exprs.append(
            pl.when(valid_condition)
            .then(pl.col(column.name))
            .otherwise(None)
            .alias(clean_name)
        )
        aggregation_exprs.append(
            _aggregation_expr(column.hourly_method, clean_name, column.output_name)
        )

    if not aggregation_exprs:
        return None

    df = df.with_columns(cleaned_exprs)

    hourly = (
        df.group_by_dynamic(
            index_column=defaults.datetime_column,
            every=defaults.hourly.every,
            label=defaults.hourly.label,
            closed=defaults.hourly.closed,
        )
        .agg(aggregation_exprs)
        .sort(defaults.datetime_column)
    )

    selected = [defaults.datetime_column] + [
        column.output_name
        for column in instrument.columns
        if column.output_name in hourly.columns
    ]
    return hourly.select(selected)

def build_daily_dataframe(
    hourly_df: pl.DataFrame,
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> pl.DataFrame | None:
    """Build one daily dataframe from the hourly dataframe.

    Args:
        hourly_df: Hourly level 2 dataframe.
        defaults: Global defaults.
        instrument: Instrument configuration.

    Returns:
        Daily dataframe or ``None``.

    Example:
        ``daily_df = build_daily_dataframe(hourly_df, defaults, instruments["49i"])``
    """

    if hourly_df.is_empty():
        return None

    aggregation_exprs: list[pl.Expr] = []
    for column in instrument.columns:
        if column.output_name not in hourly_df.columns:
            continue
        aggregation_exprs.append(
            _aggregation_expr(column.daily_method, column.output_name, column.output_name)
        )

    if not aggregation_exprs:
        return None

    daily = (
        hourly_df.group_by_dynamic(
            index_column=defaults.datetime_column,
            every=defaults.daily.every,
            label=defaults.daily.label,
            closed=defaults.daily.closed,
        )
        .agg(aggregation_exprs)
        .sort(defaults.datetime_column)
    )

    selected = [defaults.datetime_column] + [
        column.output_name for column in instrument.columns if column.output_name in daily.columns
    ]
    return daily.select(selected)


def _station_year_output_dir(root: Path, station: str, year: int) -> Path:
    """Return the yearly station directory under ``level2``.

    Args:
        root: Repo root.
        station: Station code.
        year: Four-digit year.

    Returns:
        Base yearly output directory for the station.
    """

    return root / "level2" / station / str(year)


def _instrument_output_stem(instrument: str) -> str:
    """Return a filesystem-safe file stem for an instrument name.

    Args:
        instrument: Instrument folder path, possibly containing ``/``.

    Returns:
        Safe file stem.
    """

    return instrument.replace("/", "-")


def output_path(root: Path, station: str, instrument: str, frequency: str, year: int) -> Path:
    """Return the target parquet path for one level 2 output file.

    Args:
        root: Repo root.
        station: Station code.
        instrument: Instrument folder path.
        frequency: ``hourly`` or ``daily``.
        year: Four-digit year.

    Returns:
        Output parquet path under ``level2/<station>/<year>``.

    Example:
        ``path = output_path(root, "nrb", "49i", "hourly", 2026)``
    """

    safe_instrument = _instrument_output_stem(instrument)
    return _station_year_output_dir(root, station, year) / f"{station}_{safe_instrument}_{frequency}_{year}.parquet"


def write_parquet(df: pl.DataFrame, path: Path, compression: ParquetCompression) -> None:
    """Write one parquet file, creating the target directory first.

    Args:
        df: Output dataframe.
        path: Target parquet path.
        compression: Parquet compression codec.

    Example:
        ``write_parquet(df, path, compression="zstd")``
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression=compression)


def process_station_instrument_year(
    root: Path,
    station: str,
    defaults: Defaults,
    instrument: InstrumentSpec,
    year: int,
) -> tuple[Path | None, Path | None]:
    """Build and write level 2 files for one station, instrument, and year.

    Args:
        root: Repo root containing ``level1`` and ``level2``.
        station: Station code.
        defaults: Global defaults.
        instrument: Instrument definition.
        year: Four-digit year.

    Returns:
        Tuple ``(hourly_path, daily_path)``. Each element may be ``None``.

    Example:
        ``process_station_instrument_year(root, "mkn", defaults, instruments["ae33/data"], 2022)``
    """

    files = parquet_files_for(root / "level1", station, instrument, year)
    if not files:
        LOGGER.info("No level1 parquet files for station=%s instrument=%s year=%s", station, instrument.name, year)
        return None, None

    LOGGER.info(
        "Processing station=%s instrument=%s year=%s from %s parquet files",
        station,
        instrument.name,
        year,
        len(files),
    )

    hourly_path: Path | None = None
    daily_path: Path | None = None

    hourly_df = build_hourly_dataframe(files, defaults, instrument)
    if hourly_df is None or hourly_df.is_empty():
        LOGGER.info("No usable hourly output for station=%s instrument=%s year=%s", station, instrument.name, year)
        return None, None

    if defaults.write_hourly:
        hourly_path = output_path(root, station, instrument.name, "hourly", year)
        write_parquet(hourly_df, hourly_path, defaults.parquet_compression)

    if defaults.write_daily:
        daily_df = build_daily_dataframe(hourly_df, defaults, instrument)
        if daily_df is not None and not daily_df.is_empty():
            daily_path = output_path(root, station, instrument.name, "daily", year)
            write_parquet(daily_df, daily_path, defaults.parquet_compression)

    LOGGER.info("Wrote hourly=%s daily=%s", hourly_path, daily_path)
    return hourly_path, daily_path


def run(
    root: Path,
    station_config_path: Path,
    config_section: str | None = None,
    instrument_name: str | None = None,
    year: int | None = None,
) -> None:
    """Run the level 2 collection workflow.

    Args:
        root: Repo root containing ``level1``.
        station_config_path: Path to the station configuration YAML.
        config_section: Optional section name inside the station configuration.
        instrument_name: Optional instrument filter.
        year: Optional year filter.

    Example:
        ``run(Path("/repo/gawkenyadata"), Path("mch-mkn.yml"), year=2026)``
        ``run(Path("/repo/gawkenyadata"), Path("mch-nrb.yml"), config_section="nrb-aq", instrument_name="49i")``
    """

    station_cfg = load_station_config(station_config_path, config_section=config_section)
    defaults = station_cfg.defaults
    instruments = station_cfg.instruments
    station = station_cfg.station

    level1_root = root / "level1"
    if not level1_root.exists():
        raise FileNotFoundError(f"Missing level1 directory: {level1_root}")

    years = [year] if year is not None else discover_years(level1_root, station)
    if not years:
        LOGGER.info("No years found for station=%s", station)
        return

    if instrument_name is not None:
        instrument = instruments.get(instrument_name)
        if instrument is None:
            raise ConfigError(f"Instrument '{instrument_name}' is not configured in {station_config_path}.")
        station_instruments = [instrument]
    else:
        station_instruments = list(instruments.values())

    for one_instrument in station_instruments:
        for one_year in years:
            process_station_instrument_year(
                root=root,
                station=station,
                defaults=defaults,
                instrument=one_instrument,
                year=one_year,
            )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed command-line namespace.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Path to the gawkenyadata repository root.")
    parser.add_argument(
        "--station-config",
        type=Path,
        help="Path to a station configuration YAML that contains a level2 block.",
    )
    parser.add_argument(
        "--config-section",
        type=str,
        default=None,
        help="Optional top-level section name that contains the level2 block, e.g. nrb-aq.",
    )
    parser.add_argument("--instrument", type=str, default=None, help="Optional instrument name, e.g. 49i.")
    parser.add_argument("--year", type=int, default=None, help="Optional year, e.g. 2026.")
    parser.add_argument(
        "--write-example-station-config",
        type=Path,
        default=None,
        help="Write a starter station YAML with an embedded level2 block and exit.",
    )
    parser.add_argument(
        "--example-section",
        type=str,
        default=None,
        help="Optional section name to use together with --write-example-station-config.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()
    if args.write_example_station_config is None and (args.root is None or args.station_config is None):
        parser.error("--root and --station-config are required unless --write-example-station-config is used.")
    return args


def main() -> None:
    """CLI entry point.

    Example:
        ``python compile_level1_to_level2_files.py --root /path/to/gawkenyadata --station-config mch-mkn.yml``
    """

    args = parse_args()
    setup_logging(args.verbose)

    if args.write_example_station_config is not None:
        write_example_station_config(args.write_example_station_config, section=args.example_section)
        LOGGER.info("Wrote example station config to %s", args.write_example_station_config)
        return

    run(
        root=args.root,
        station_config_path=args.station_config,
        config_section=args.config_section,
        instrument_name=args.instrument,
        year=args.year,
    )


if __name__ == "__main__":
    main()
