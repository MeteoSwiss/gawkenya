"""Aggregate level 1 parquet files into yearly level 2 parquet products.

The tool reads the ``level2`` block from a station YAML configuration and
creates hourly, daily, and/or monthly products. Each configured value column is
accompanied by ``n_<column>``: the number of non-null Level 1 observations that
passed the same flag-validity rule used for the aggregate itself.

By default, values are valid when their matching flag is ``0`` or null because
``accept_null_flags`` defaults to true. Set ``accept_null_flags: false`` for a
strict ``flag == 0`` rule. If no flag column exists, non-null values are used
and counted.

All cadences are aggregated directly from Level 1. Daily and monthly products
are therefore not averages of already aggregated hourly values; medians, sums,
circular means, and valid-observation counts retain their Level 1 semantics.

Dry-run example (the default)::

    python compile_level1_to_level2_files.py \
        --root /product_data/data/pay/Kenya/git/gawkenyadata \
        --station-config mch-mkn.yml


``--root`` may point to the gawkenyadata repository root, its ``level1``
directory, or the selected station directory below ``level1``. For example,
these three paths are equivalent for station ``mkn``::

    /product_data/data/pay/Kenya/git/gawkenyadata
    /product_data/data/pay/Kenya/git/gawkenyadata/level1
    /product_data/data/pay/Kenya/git/gawkenyadata/level1/mkn

The path is normalized internally back to the gawkenyadata root so Level 2
outputs always go below ``<gawkenyadata>/level2/<station>``.

For a multi-section config such as ``mch-nrb.yml``::

    python compile_level1_to_level2_files.py \
        --root /product_data/data/pay/Kenya/git/gawkenyadata \
        --station-config mch-nrb.yml \
        --config-section nrb-aq

Write the planned Parquet products only after inspecting the dry run::

    python compile_level1_to_level2_files.py \
        --root /product_data/data/pay/Kenya/git/gawkenyadata \
        --station-config mch-mkn.yml \
        --write

The default dry run still reads and aggregates the data so that the reported
row counts, valid-value statistics, and planned output files are the same checks
performed by a write run. Only ``--write`` creates or overwrites files. Parquet
is always the canonical output; ``--csv`` additionally writes plain CSV and
``--zip`` additionally writes ZIP-compressed CSV (``.csv.zip``). Parquet itself
is never ZIP-compressed.

IMPORTANT: Level 2 products are regenerated from Level 1. Existing Level 2
files are not merged back into the new product. In particular, any interactive
or manually assigned Level 2 ``f_*`` flag columns in an existing target are
lost when ``--write`` overwrites that target. Level 1 flags are still used to
decide which Level 1 observations enter each aggregate, but Level 2 flags must
be assigned again after regeneration. Optional CSV/ZIP exports produced by this
command are representations of the newly regenerated Level 2 dataframe and
therefore do not preserve old Level 2 flags either.

For instruments configured with ``reporting_condition_correction``, selected
concentration-like variables are normalized in memory from the row-specific
reporting pressure and temperature to a configured target condition before
validity filtering and aggregation. The Level 1 Parquet data are never changed.
For the AE33, the instrument manual defines ``Pressure`` and ``Temperature`` as
the conditions used to report flow. A typical target is 101325 Pa and 0 degC.
The compiler applies the ideal-gas conversion

    value_target = value_reported * (P_target / P_reported)
                   * ((T_reported + 273.15) / (T_target + 273.15))

only to explicitly listed concentration-like variables (for example BC1 ...
BC7 and b1_abs ... b7_abs). If the reporting ``Pressure`` and ``Temperature``
columns themselves are configured as Level 2 output variables, they are not
averaged at their original reporting condition: after the concentration
correction they are standardized in memory to ``P_target`` and ``T_target`` as
well. Thus an AE33 Level 2 product normalized to 101325 Pa and 0 degC reports
``Pressure = 101325`` and ``Temperature = 0`` for valid source rows. The
original Level 1 values remain unchanged and are still used to calculate the
correction factor.

Every run with reporting-condition normalization enabled emits an audit line
showing the source pressure/temperature range, the correction-factor range, and
the number of rows already at target, corrected, or invalid. After each
aggregation the compiler verifies that any exported reporting Pressure and
Temperature columns equal the configured target; a mismatch is a hard error.

Rows already at the target condition receive a factor of 1. Rows with missing
or physically invalid reporting pressure/temperature cannot be standardized;
the affected concentration values and, when exported, the standardized
Pressure/Temperature values are set to null in the in-memory Level 2 build and
therefore do not contribute to the aggregate or its ``n_*`` count.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import argparse
import logging
import math
import re
import sys
import zipfile
from typing import Any, Literal, TextIO

import polars as pl
import yaml

LOGGER = logging.getLogger("collect_level2")

GroupLabel = Literal["left", "right", "datapoint"]
ClosedInterval = Literal["left", "right", "both", "none"]
ParquetCompression = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]
Frequency = Literal["hourly", "daily", "monthly"]
FREQUENCIES: tuple[Frequency, ...] = ("hourly", "daily", "monthly")


@dataclass(frozen=True)
class AggregationSpec:
    """Aggregation settings for one output frequency."""

    every: str
    label: GroupLabel
    closed: ClosedInterval
    default_method: str


@dataclass(frozen=True)
class ReportingConditionCorrection:
    """Normalize selected variables to a target reporting condition."""

    pressure_column: str
    temperature_column: str
    target_pressure_pa: float
    target_temperature_c: float
    columns: tuple[str, ...]


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
    write_monthly: bool
    hourly: AggregationSpec
    daily: AggregationSpec
    monthly: AggregationSpec


@dataclass(frozen=True)
class ColumnSpec:
    """One configured output column for an instrument."""

    name: str
    output_name: str
    hourly_method: str
    daily_method: str
    monthly_method: str
    flag_column: str | None

    def method_for(self, frequency: Frequency) -> str:
        """Return the configured aggregation method for ``frequency``."""

        if frequency == "hourly":
            return self.hourly_method
        if frequency == "daily":
            return self.daily_method
        return self.monthly_method


@dataclass(frozen=True)
class InstrumentSpec:
    """Configuration for one instrument."""

    name: str
    columns: tuple[ColumnSpec, ...]
    source_parquet: str | None = None
    flag_mode: str | None = None
    flag_prefix: str | None = None
    reporting_condition_correction: ReportingConditionCorrection | None = None


@dataclass(frozen=True)
class StationConfig:
    """Resolved station configuration for level 2 processing."""

    station: str
    defaults: Defaults
    instruments: dict[str, InstrumentSpec]


@dataclass(frozen=True)
class ReportingConditionStats:
    """Audit statistics for one reporting-condition normalization."""

    already_target: int
    corrected: int
    invalid: int
    source_pressure_min_pa: float | None
    source_pressure_max_pa: float | None
    source_temperature_min_c: float | None
    source_temperature_max_c: float | None
    factor_min: float | None
    factor_max: float | None


@dataclass(frozen=True)
class ValueStats:
    """Level 1 availability/validity statistics for one output variable."""

    available: int
    valid: int


@dataclass
class JobStats:
    """Statistics for one station/instrument/year aggregation job."""

    station: str
    instrument: str
    year: int
    source_files: int = 0
    source_bytes: int = 0
    level1_rows: int = 0
    configured_columns: int = 0
    resolved_columns: int = 0
    missing_columns: tuple[str, ...] = ()
    values: dict[str, ValueStats] = field(default_factory=dict)
    reporting_condition_stats: ReportingConditionStats | None = None
    aggregate_rows: dict[Frequency, int] = field(default_factory=dict)
    # output_paths remains the canonical Parquet mapping for compatibility.
    output_paths: dict[Frequency, Path] = field(default_factory=dict)
    csv_paths: dict[Frequency, Path] = field(default_factory=dict)
    zip_paths: dict[Frequency, Path] = field(default_factory=dict)
    existing_outputs: set[Frequency] = field(default_factory=set)
    existing_csv_outputs: set[Frequency] = field(default_factory=set)
    existing_zip_outputs: set[Frequency] = field(default_factory=set)
    existing_level2_flags: dict[Frequency, tuple[str, ...]] = field(default_factory=dict)
    written_outputs: set[Frequency] = field(default_factory=set)
    written_csv_outputs: set[Frequency] = field(default_factory=set)
    written_zip_outputs: set[Frequency] = field(default_factory=set)
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def available_values(self) -> int:
        return sum(item.available for item in self.values.values())

    @property
    def valid_values(self) -> int:
        return sum(item.valid for item in self.values.values())


@dataclass
class RunStats:
    """Statistics for one complete CLI invocation."""

    write: bool = False
    csv: bool = False
    zip_csv: bool = False
    jobs: list[JobStats] = field(default_factory=list)

    @property
    def dry_run(self) -> bool:
        """Whether the run is non-writing."""

        return not self.write

    @property
    def errors(self) -> int:
        return sum(job.error is not None for job in self.jobs)


class ConfigError(ValueError):
    """Raised when the YAML configuration is invalid."""


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _parse_group_label(raw: Any) -> GroupLabel:
    if raw in ("left", "right", "datapoint"):
        return raw
    raise ConfigError(f"Unsupported group_by_dynamic label: {raw!r}")


def _parse_closed_interval(raw: Any) -> ClosedInterval:
    if raw in ("left", "right", "both", "none"):
        return raw
    raise ConfigError(f"Unsupported group_by_dynamic closed value: {raw!r}")


def _parse_parquet_compression(raw: Any) -> ParquetCompression:
    if raw in ("lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"):
        return raw
    raise ConfigError(f"Unsupported parquet compression: {raw!r}")


def _default_aggregation(every: str) -> dict[str, Any]:
    return {
        "default": "mean",
        "every": every,
        "label": "left",
        "closed": "left",
    }


def _default_level2_block() -> dict[str, Any]:
    """Return a starter ``level2`` mapping."""

    return {
        "station": "station_code",
        "datetime_column": "dtm",
        "timezone": "UTC",
        "valid_flag_value": 0,
        "accept_null_flags": True,
        "parquet_compression": "zstd",
        "output": {"hourly": True, "daily": True, "monthly": True},
        "flags": {"mode": "per_column_prefix", "prefix": "f_"},
        "aggregation": {
            "hourly": _default_aggregation("1h"),
            "daily": _default_aggregation("1d"),
            "monthly": _default_aggregation("1mo"),
        },
        "instruments": {
            "tei49c": {"columns": ["O3"]},
            "tei49i": {"columns": ["O3"]},
            "49i": {"columns": ["O3"]},
            "ae31": {
                "columns": ["UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950"]
            },
            "ae33/data": {
                "source_parquet": "ae33",
                "columns": [
                    "BC1", "BC2", "BC3", "BC4", "BC5", "BC6", "BC7",
                    "b1_abs", "b2_abs", "b3_abs", "b4_abs", "b5_abs",
                    "b6_abs", "b7_abs", "Pressure", "Temperature",
                ],
                "reporting_condition_correction": {
                    "pressure_column": "Pressure",
                    "temperature_column": "Temperature",
                    "target_pressure_pa": 101325,
                    "target_temperature_c": 0.0,
                    "columns": [
                        "BC1", "BC2", "BC3", "BC4", "BC5", "BC6", "BC7",
                        "b1_abs", "b2_abs", "b3_abs", "b4_abs", "b5_abs",
                        "b6_abs", "b7_abs",
                    ],
                },
            },
            "fidas": {"columns": ["PM1", "PM2.5", "PM4", "PM10"]},
        },
    }


def write_example_station_config(path: Path, section: str | None = None) -> None:
    """Write a starter station configuration with an embedded ``level2`` block."""

    payload: dict[str, Any]
    if section is None:
        payload = {"level2": _default_level2_block()}
    else:
        payload = {section: {"level2": _default_level2_block()}}

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)


def _resolve_level2_scope(
    raw: dict[str, Any],
    path: Path,
    config_section: str | None,
) -> dict[str, Any]:
    if config_section is not None:
        scope = raw.get(config_section)
        if not isinstance(scope, dict):
            raise ConfigError(
                f"Section '{config_section}' was not found or is not a mapping in {path}."
            )
        return scope

    if isinstance(raw.get("level2"), dict):
        return raw

    candidates = [
        name
        for name, value in raw.items()
        if isinstance(value, dict) and isinstance(value.get("level2"), dict)
    ]
    if len(candidates) == 1:
        return raw[candidates[0]]
    if len(candidates) > 1:
        raise ConfigError(
            f"Multiple sections contain a level2 block in {path}; use --config-section."
        )
    raise ConfigError(
        f"No level2 block found in {path}. Add one at the top level or select a section with --config-section."
    )


def _parse_aggregation_spec(raw: dict[str, Any], default_every: str) -> AggregationSpec:
    return AggregationSpec(
        every=raw.get("every", default_every),
        label=_parse_group_label(raw.get("label", "left")),
        closed=_parse_closed_interval(raw.get("closed", "left")),
        default_method=raw.get("default", "mean"),
    )


def _parse_column_spec(raw: Any, defaults: Defaults) -> ColumnSpec:
    if isinstance(raw, str):
        return ColumnSpec(
            name=raw,
            output_name=raw,
            hourly_method=defaults.hourly.default_method,
            daily_method=defaults.daily.default_method,
            monthly_method=defaults.monthly.default_method,
            flag_column=None,
        )

    if not isinstance(raw, dict):
        raise ConfigError(f"Column entry must be a string or dictionary, got {type(raw)!r}.")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError("Expanded column entries require a non-empty 'name'.")

    output_name = raw.get("rename", name)
    if not isinstance(output_name, str) or not output_name:
        raise ConfigError(f"Column '{name}' has an invalid rename value.")

    flag_column = raw.get("flag_column")
    if flag_column is not None and (not isinstance(flag_column, str) or not flag_column):
        raise ConfigError(f"Column '{name}' has an invalid flag_column value.")

    agg_raw = raw.get("agg", {}) or {}
    if not isinstance(agg_raw, dict):
        raise ConfigError(f"Column '{name}' agg must be a mapping.")

    return ColumnSpec(
        name=name,
        output_name=output_name,
        hourly_method=agg_raw.get("hourly", defaults.hourly.default_method),
        daily_method=agg_raw.get("daily", defaults.daily.default_method),
        monthly_method=agg_raw.get("monthly", defaults.monthly.default_method),
        flag_column=flag_column,
    )


def _validate_column_names(instrument_name: str, columns: list[ColumnSpec]) -> None:
    output_names = [column.output_name for column in columns]
    if len(output_names) != len(set(output_names)):
        raise ConfigError(f"Instrument '{instrument_name}' contains duplicate output column names.")

    value_names = set(output_names)
    count_names = {valid_count_column(name) for name in output_names}
    collisions = value_names & count_names
    if collisions:
        raise ConfigError(
            f"Instrument '{instrument_name}' has value/count name collisions: {sorted(collisions)}"
        )



def _parse_reporting_condition_correction(
    raw: Any,
    *,
    instrument_name: str,
    columns: list[ColumnSpec],
) -> ReportingConditionCorrection | None:
    """Parse an optional reporting-condition normalization mapping."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting_condition_correction must be a mapping."
        )

    pressure_column = raw.get("pressure_column", "Pressure")
    temperature_column = raw.get("temperature_column", "Temperature")
    if not isinstance(pressure_column, str) or not pressure_column:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting condition pressure_column must be a non-empty string."
        )
    if not isinstance(temperature_column, str) or not temperature_column:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting condition temperature_column must be a non-empty string."
        )

    try:
        target_pressure_pa = float(raw.get("target_pressure_pa", 101325.0))
        target_temperature_c = float(raw.get("target_temperature_c", 0.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting-condition targets must be numeric."
        ) from exc

    if not math.isfinite(target_pressure_pa) or target_pressure_pa <= 0.0:
        raise ConfigError(
            f"Instrument '{instrument_name}' target_pressure_pa must be > 0."
        )
    if not math.isfinite(target_temperature_c) or target_temperature_c <= -273.15:
        raise ConfigError(
            f"Instrument '{instrument_name}' target_temperature_c must be above absolute zero."
        )

    correction_columns = raw.get("columns")
    if not isinstance(correction_columns, list) or not correction_columns:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting_condition_correction must define a non-empty columns list."
        )
    if not all(isinstance(name, str) and name for name in correction_columns):
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting-condition columns must be non-empty strings."
        )

    configured_names = {column.name for column in columns}
    unknown = sorted(set(correction_columns) - configured_names)
    if unknown:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting-condition columns are not configured Level 2 variables: {unknown}"
        )
    if pressure_column in correction_columns or temperature_column in correction_columns:
        raise ConfigError(
            f"Instrument '{instrument_name}' reporting pressure/temperature columns "
            "must not appear in reporting_condition_correction.columns; configure "
            "them as ordinary Level 2 output columns instead, and they will be "
            "standardized automatically."
        )

    return ReportingConditionCorrection(
        pressure_column=pressure_column,
        temperature_column=temperature_column,
        target_pressure_pa=target_pressure_pa,
        target_temperature_c=target_temperature_c,
        columns=tuple(dict.fromkeys(correction_columns)),
    )

def load_station_config(path: Path, config_section: str | None = None) -> StationConfig:
    """Load and validate embedded level 2 settings from a station YAML file."""

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
    if not isinstance(aggregation_raw, dict):
        raise ConfigError("level2.aggregation must be a mapping.")
    if not isinstance(flags_raw, dict):
        raise ConfigError("level2.flags must be a mapping.")
    if not isinstance(output_raw, dict):
        raise ConfigError("level2.output must be a mapping.")

    hourly_raw = aggregation_raw.get("hourly", {}) or {}
    daily_raw = aggregation_raw.get("daily", {}) or {}
    monthly_raw = aggregation_raw.get("monthly", {}) or {}
    if not all(isinstance(item, dict) for item in (hourly_raw, daily_raw, monthly_raw)):
        raise ConfigError("Each level2 aggregation cadence must be a mapping.")

    defaults = Defaults(
        datetime_column=level2_raw.get("datetime_column", "dtm"),
        timezone=level2_raw.get("timezone"),
        valid_flag_value=level2_raw.get("valid_flag_value", 0),
        accept_null_flags=bool(level2_raw.get("accept_null_flags", True)),
        parquet_compression=_parse_parquet_compression(
            level2_raw.get("parquet_compression", "zstd")
        ),
        flag_mode=flags_raw.get("mode", "per_column_prefix"),
        flag_prefix=flags_raw.get("prefix", "f_"),
        write_hourly=bool(output_raw.get("hourly", True)),
        write_daily=bool(output_raw.get("daily", True)),
        write_monthly=bool(output_raw.get("monthly", True)),
        hourly=_parse_aggregation_spec(hourly_raw, "1h"),
        daily=_parse_aggregation_spec(daily_raw, "1d"),
        monthly=_parse_aggregation_spec(monthly_raw, "1mo"),
    )

    if not isinstance(defaults.datetime_column, str) or not defaults.datetime_column:
        raise ConfigError("level2.datetime_column must be a non-empty string.")
    if defaults.timezone is not None and not isinstance(defaults.timezone, str):
        raise ConfigError("level2.timezone must be a string or null.")
    if not isinstance(defaults.flag_prefix, str):
        raise ConfigError("level2.flags.prefix must be a string.")

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
        if not isinstance(instrument_flags, dict):
            raise ConfigError(f"Instrument '{instrument_name}' flags must be a mapping.")

        columns_raw = instrument_raw.get("columns")
        if not isinstance(columns_raw, list) or not columns_raw:
            raise ConfigError(f"Instrument '{instrument_name}' must define a non-empty columns list.")

        columns = [_parse_column_spec(column_raw, defaults) for column_raw in columns_raw]
        _validate_column_names(instrument_name, columns)

        source_parquet = instrument_raw.get("source_parquet")
        if source_parquet is not None and (
            not isinstance(source_parquet, str) or not source_parquet.strip()
        ):
            raise ConfigError(
                f"Instrument '{instrument_name}' has an invalid source_parquet; expected a non-empty string."
            )

        reporting_condition_correction = _parse_reporting_condition_correction(
            instrument_raw.get("reporting_condition_correction"),
            instrument_name=instrument_name,
            columns=columns,
        )

        instruments[instrument_name] = InstrumentSpec(
            name=instrument_name,
            columns=tuple(columns),
            source_parquet=source_parquet.strip() if isinstance(source_parquet, str) else None,
            flag_mode=instrument_flags.get("mode"),
            flag_prefix=instrument_flags.get("prefix"),
            reporting_condition_correction=reporting_condition_correction,
        )

    return StationConfig(station=station, defaults=defaults, instruments=instruments)


def resolve_data_root(root: Path, station: str) -> Path:
    """Normalize supported ``--root`` forms to the gawkenyadata root.

    ``--root`` may identify the gawkenyadata repository root, the repository's
    ``level1`` directory, or the selected station directory below ``level1``.

    Args:
        root: User-supplied root path.
        station: Station identifier from the Level 2 configuration.

    Returns:
        Canonical gawkenyadata repository root.

    Raises:
        FileNotFoundError: If ``root`` does not exist or cannot be interpreted
            as one of the supported directory levels.
    """
    candidate = root.expanduser()

    if not candidate.exists():
        raise FileNotFoundError(f"Root path does not exist: {candidate}")
    if not candidate.is_dir():
        raise FileNotFoundError(f"Root path is not a directory: {candidate}")

    if (candidate / "level1").is_dir():
        return candidate

    if candidate.name == "level1":
        return candidate.parent

    if candidate.name == station and candidate.parent.name == "level1":
        return candidate.parent.parent

    raise FileNotFoundError(
        "Could not interpret --root. Expected the gawkenyadata root, its "
        f"level1 directory, or level1/{station}; got: {candidate}"
    )


def discover_years(level1_root: Path, station: str) -> list[int]:
    """Discover available years for one station."""

    station_root = level1_root / station
    if not station_root.exists():
        return []
    return sorted(
        int(path.name)
        for path in station_root.iterdir()
        if path.is_dir() and path.name.isdigit()
    )


def source_parquet_candidates(instrument: InstrumentSpec) -> tuple[str, ...]:
    """Return candidate monthly parquet stems for one configured instrument."""

    if instrument.source_parquet:
        return (instrument.source_parquet,)

    candidates = [instrument.name]
    basename = Path(instrument.name).name
    if basename not in candidates:
        candidates.append(basename)
    return tuple(candidates)


def parquet_files_for(
    level1_root: Path,
    station: str,
    instrument: InstrumentSpec,
    year: int,
) -> list[Path]:
    """Return all parquet files for one station, instrument, and year."""

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


def _resolve_available_column(name: str, available_columns: set[str]) -> str | None:
    """Resolve a column name case-insensitively against available columns."""

    lookup = {column.casefold(): column for column in available_columns}
    return lookup.get(name.casefold())


def resolve_flag_column(
    column: ColumnSpec,
    instrument: InstrumentSpec,
    defaults: Defaults,
    available_columns: set[str],
) -> str | None:
    """Resolve the flag column for one value column, case-insensitively."""

    if column.flag_column:
        return _resolve_available_column(column.flag_column, available_columns)

    flag_mode = instrument.flag_mode or defaults.flag_mode
    if flag_mode == "per_column_prefix":
        prefix = instrument.flag_prefix or defaults.flag_prefix
        return _resolve_available_column(f"{prefix}{column.name}", available_columns)
    if flag_mode == "none":
        return None
    raise ConfigError(f"Unsupported flag mode: {flag_mode!r}")


def valid_count_column(output_name: str) -> str:
    """Return the output name for a valid-observation count column."""

    return f"n_{output_name}"


def _aggregation_expr(method: str, column_name: str, output_name: str) -> pl.Expr:
    """Build one Polars aggregation expression."""

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
        return series.drop_nulls().first().alias(output_name)
    if method_lower == "last":
        return series.drop_nulls().last().alias(output_name)
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


def _spec_for(defaults: Defaults, frequency: Frequency) -> AggregationSpec:
    if frequency == "hourly":
        return defaults.hourly
    if frequency == "daily":
        return defaults.daily
    return defaults.monthly


def _write_enabled(defaults: Defaults, frequency: Frequency) -> bool:
    if frequency == "hourly":
        return defaults.write_hourly
    if frequency == "daily":
        return defaults.write_daily
    return defaults.write_monthly


def _normalize_datetime(df: pl.DataFrame, defaults: Defaults) -> pl.DataFrame:
    """Normalize the configured timestamp column to a Polars Datetime."""

    name = defaults.datetime_column
    dtype = df.schema[name]

    if dtype == pl.Utf8:
        expr = pl.col(name).str.to_datetime(strict=False)
        df = df.with_columns(expr.alias(name))
        dtype = df.schema[name]
    elif dtype == pl.Date:
        df = df.with_columns(pl.col(name).cast(pl.Datetime("us")).alias(name))
        dtype = df.schema[name]

    if not str(dtype).startswith("Datetime"):
        raise ConfigError(f"Column '{name}' cannot be interpreted as datetime (dtype={dtype}).")

    if defaults.timezone:
        time_zone = getattr(dtype, "time_zone", None)
        if time_zone:
            df = df.with_columns(pl.col(name).dt.convert_time_zone(defaults.timezone))
        else:
            df = df.with_columns(pl.col(name).dt.replace_time_zone(defaults.timezone))

    return df


def _valid_condition(value_column: str, flag_column: str | None, defaults: Defaults) -> pl.Expr:
    """Return the validity expression used for both aggregation and counts."""

    condition = pl.col(value_column).is_not_null()
    if flag_column is None:
        return condition

    flag = pl.col(flag_column)
    flag_numeric = flag.cast(pl.Float64, strict=False)
    flag_valid = flag_numeric == float(defaults.valid_flag_value)
    if defaults.accept_null_flags:
        flag_valid = flag.is_null() | flag_valid
    return condition & flag_valid


def _load_level1_frame(
    files: list[Path],
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> tuple[pl.DataFrame, dict[str, tuple[str, str | None]]]:
    """Read only required Level 1 columns and resolve value/flag names."""

    if not files:
        return pl.DataFrame(), {}

    scan = pl.scan_parquet(
        [str(path) for path in files],
        cast_options=pl.ScanCastOptions(integer_cast="upcast", float_cast="upcast"),
        missing_columns="insert",
        extra_columns="ignore",
    )
    available_columns = set(scan.collect_schema().names())

    actual_datetime = _resolve_available_column(defaults.datetime_column, available_columns)
    if actual_datetime is None:
        LOGGER.warning(
            "Skipping %s because timestamp column %s is missing.",
            instrument.name,
            defaults.datetime_column,
        )
        return pl.DataFrame(), {}

    resolved: dict[str, tuple[str, str | None]] = {}
    needed_columns = {actual_datetime}
    reporting_renames: dict[str, str] = {}
    correction = instrument.reporting_condition_correction
    if correction is not None:
        actual_pressure = _resolve_available_column(
            correction.pressure_column, available_columns
        )
        actual_temperature = _resolve_available_column(
            correction.temperature_column, available_columns
        )
        if actual_pressure is None or actual_temperature is None:
            missing = [
                name
                for name, actual in (
                    (correction.pressure_column, actual_pressure),
                    (correction.temperature_column, actual_temperature),
                )
                if actual is None
            ]
            raise ConfigError(
                f"Reporting-condition correction for '{instrument.name}' requires "
                f"missing Level 1 column(s): {', '.join(missing)}"
            )
        needed_columns.update({actual_pressure, actual_temperature})
        if actual_pressure != correction.pressure_column:
            reporting_renames[actual_pressure] = correction.pressure_column
        if actual_temperature != correction.temperature_column:
            reporting_renames[actual_temperature] = correction.temperature_column
    for column in instrument.columns:
        actual_value = _resolve_available_column(column.name, available_columns)
        if actual_value is None:
            LOGGER.warning(
                "Input is missing configured column %s for %s.",
                column.name,
                instrument.name,
            )
            continue
        actual_flag = resolve_flag_column(column, instrument, defaults, available_columns)
        resolved[column.name] = (actual_value, actual_flag)
        needed_columns.add(actual_value)
        if actual_flag is not None:
            needed_columns.add(actual_flag)

    if not resolved:
        return pl.DataFrame(), {}

    df = scan.select(sorted(needed_columns)).collect()
    renames = dict(reporting_renames)
    if actual_datetime != defaults.datetime_column:
        renames[actual_datetime] = defaults.datetime_column
    if renames:
        df = df.rename(renames)
        resolved = {
            source_name: (
                renames.get(actual_value, actual_value),
                renames.get(actual_flag, actual_flag) if actual_flag is not None else None,
            )
            for source_name, (actual_value, actual_flag) in resolved.items()
        }

    if df.is_empty():
        return df, resolved

    df = _normalize_datetime(df, defaults)
    df = df.filter(pl.col(defaults.datetime_column).is_not_null()).sort(defaults.datetime_column)
    return df, resolved



def _apply_reporting_condition_correction(
    df: pl.DataFrame,
    resolved: dict[str, tuple[str, str | None]],
    instrument: InstrumentSpec,
) -> tuple[pl.DataFrame, ReportingConditionStats | None]:
    """Normalize selected variables to the configured reporting condition.

    Concentration-like variables listed in
    ``reporting_condition_correction.columns`` are multiplied by the
    row-specific ideal-gas correction factor. If the configured reporting
    pressure and temperature columns are themselves Level 2 output variables,
    their in-memory values are replaced by the configured target pressure and
    temperature for rows with valid reporting conditions. This keeps the Level
    2 metadata consistent with the condition to which the concentrations were
    normalized.

    The original pressure/temperature values are used to compute the correction
    factor before they are replaced. Source Level 1 Parquet files are never
    modified.
    """

    correction = instrument.reporting_condition_correction
    if correction is None or df.is_empty():
        return df, None

    pressure = pl.col(correction.pressure_column).cast(pl.Float64, strict=False)
    temperature_c = pl.col(correction.temperature_column).cast(pl.Float64, strict=False)
    conditions_valid = (
        pressure.is_not_null()
        & temperature_c.is_not_null()
        & pressure.is_finite()
        & temperature_c.is_finite()
        & (pressure > 0.0)
        & (temperature_c > -273.15)
    )

    at_target = (
        conditions_valid
        & ((pressure - correction.target_pressure_pa).abs() <= 0.5)
        & ((temperature_c - correction.target_temperature_c).abs() <= 0.01)
    )
    factor = (
        pl.lit(correction.target_pressure_pa)
        / pressure
        * ((temperature_c + 273.15) / pl.lit(correction.target_temperature_c + 273.15))
    )

    expressions: list[pl.Expr] = []
    for source_name in correction.columns:
        names = resolved.get(source_name)
        if names is None:
            continue
        actual_value, _ = names
        expressions.append(
            pl.when(conditions_valid & pl.col(actual_value).is_not_null())
            .then(pl.col(actual_value).cast(pl.Float64, strict=False) * factor)
            .otherwise(None)
            .alias(actual_value)
        )

    # Pressure and Temperature describe the reporting condition used by the
    # AE33, not ambient meteorology. If they are configured as Level 2 output
    # variables, report the target condition alongside the corrected
    # concentrations. Polars evaluates these expressions against the original
    # dataframe, so the factor above still uses the unmodified Level 1 values.
    pressure_names = resolved.get(correction.pressure_column)
    if pressure_names is not None:
        actual_pressure_value, _ = pressure_names
        expressions.append(
            pl.when(conditions_valid)
            .then(pl.lit(correction.target_pressure_pa))
            .otherwise(None)
            .alias(actual_pressure_value)
        )

    temperature_names = resolved.get(correction.temperature_column)
    if temperature_names is not None:
        actual_temperature_value, _ = temperature_names
        expressions.append(
            pl.when(conditions_valid)
            .then(pl.lit(correction.target_temperature_c))
            .otherwise(None)
            .alias(actual_temperature_value)
        )

    audit = df.select(
        [
            at_target.sum().alias("already_target"),
            (conditions_valid & ~at_target).sum().alias("corrected"),
            (~conditions_valid).sum().alias("invalid"),
            pl.when(conditions_valid)
            .then(pressure)
            .otherwise(None)
            .min()
            .alias("source_pressure_min_pa"),
            pl.when(conditions_valid)
            .then(pressure)
            .otherwise(None)
            .max()
            .alias("source_pressure_max_pa"),
            pl.when(conditions_valid)
            .then(temperature_c)
            .otherwise(None)
            .min()
            .alias("source_temperature_min_c"),
            pl.when(conditions_valid)
            .then(temperature_c)
            .otherwise(None)
            .max()
            .alias("source_temperature_max_c"),
            pl.when(conditions_valid)
            .then(factor)
            .otherwise(None)
            .min()
            .alias("factor_min"),
            pl.when(conditions_valid)
            .then(factor)
            .otherwise(None)
            .max()
            .alias("factor_max"),
        ]
    ).row(0, named=True)
    stats = ReportingConditionStats(
        already_target=int(audit["already_target"] or 0),
        corrected=int(audit["corrected"] or 0),
        invalid=int(audit["invalid"] or 0),
        source_pressure_min_pa=audit["source_pressure_min_pa"],
        source_pressure_max_pa=audit["source_pressure_max_pa"],
        source_temperature_min_c=audit["source_temperature_min_c"],
        source_temperature_max_c=audit["source_temperature_max_c"],
        factor_min=audit["factor_min"],
        factor_max=audit["factor_max"],
    )

    return (df.with_columns(expressions) if expressions else df), stats

def _aggregate_loaded_frame(
    df: pl.DataFrame,
    resolved: dict[str, tuple[str, str | None]],
    defaults: Defaults,
    instrument: InstrumentSpec,
    frequency: Frequency,
) -> pl.DataFrame | None:
    """Aggregate an already loaded Level 1 frame to one cadence."""

    if df.is_empty() or not resolved:
        return None

    cleaned_exprs: list[pl.Expr] = []
    aggregation_exprs: list[pl.Expr] = []
    output_pairs: list[tuple[str, str]] = []

    for column in instrument.columns:
        names = resolved.get(column.name)
        if names is None:
            continue
        actual_value, actual_flag = names
        valid = _valid_condition(actual_value, actual_flag, defaults)
        clean_name = f"__clean__{column.output_name}"
        count_name = valid_count_column(column.output_name)

        cleaned_exprs.append(
            pl.when(valid).then(pl.col(actual_value)).otherwise(None).alias(clean_name)
        )
        aggregation_exprs.extend(
            [
                _aggregation_expr(column.method_for(frequency), clean_name, column.output_name),
                valid.sum().cast(pl.UInt32).alias(count_name),
            ]
        )
        output_pairs.append((column.output_name, count_name))

    if not aggregation_exprs:
        return None

    working = df.with_columns(cleaned_exprs)
    spec = _spec_for(defaults, frequency)
    out = (
        working.group_by_dynamic(
            index_column=defaults.datetime_column,
            every=spec.every,
            label=spec.label,
            closed=spec.closed,
        )
        .agg(aggregation_exprs)
        .sort(defaults.datetime_column)
    )

    # In particular, Polars sum() can yield 0 for an all-null group. All
    # aggregate values must be null when no valid Level 1 observation existed.
    out = out.with_columns(
        [
            pl.when(pl.col(count_name) > 0)
            .then(pl.col(value_name))
            .otherwise(None)
            .alias(value_name)
            for value_name, count_name in output_pairs
        ]
    )

    selected = [defaults.datetime_column]
    for value_name, count_name in output_pairs:
        selected.extend([value_name, count_name])
    return out.select(selected)



def _output_name_for_source(
    instrument: InstrumentSpec,
    source_name: str,
) -> str | None:
    """Return the Level 2 output name for one configured source variable."""

    for column in instrument.columns:
        if column.name == source_name:
            return column.output_name
    return None


def _verified_constant_range(
    df: pl.DataFrame,
    column_name: str,
    expected: float,
    *,
    tolerance: float,
    label: str,
    frequency: Frequency,
    instrument_name: str,
) -> tuple[float, float] | None:
    """Verify every non-null output value equals the expected constant."""

    if column_name not in df.columns:
        return None

    values = df.select(
        [
            pl.col(column_name).drop_nulls().min().alias("minimum"),
            pl.col(column_name).drop_nulls().max().alias("maximum"),
        ]
    ).row(0, named=True)
    minimum = values["minimum"]
    maximum = values["maximum"]
    if minimum is None or maximum is None:
        return None

    minimum_f = float(minimum)
    maximum_f = float(maximum)
    if (
        abs(minimum_f - expected) > tolerance
        or abs(maximum_f - expected) > tolerance
    ):
        raise RuntimeError(
            f"Reporting-condition verification failed for {instrument_name} "
            f"{frequency}: {label} expected {expected}, observed "
            f"{minimum_f} .. {maximum_f}."
        )
    return minimum_f, maximum_f


def _verify_reporting_condition_aggregate(
    df: pl.DataFrame,
    instrument: InstrumentSpec,
    frequency: Frequency,
) -> None:
    """Fail if exported reporting P/T do not match the configured target."""

    correction = instrument.reporting_condition_correction
    if correction is None or df.is_empty():
        return

    pressure_output = _output_name_for_source(
        instrument, correction.pressure_column
    )
    temperature_output = _output_name_for_source(
        instrument, correction.temperature_column
    )

    pressure_range = (
        _verified_constant_range(
            df,
            pressure_output,
            correction.target_pressure_pa,
            tolerance=0.5,
            label="pressure",
            frequency=frequency,
            instrument_name=instrument.name,
        )
        if pressure_output is not None
        else None
    )
    temperature_range = (
        _verified_constant_range(
            df,
            temperature_output,
            correction.target_temperature_c,
            tolerance=0.01,
            label="temperature",
            frequency=frequency,
            instrument_name=instrument.name,
        )
        if temperature_output is not None
        else None
    )

    details: list[str] = []
    if pressure_output is not None:
        details.append(
            f"{pressure_output}="
            + (
                "all-null"
                if pressure_range is None
                else f"{pressure_range[0]:.3f}..{pressure_range[1]:.3f} Pa"
            )
        )
    if temperature_output is not None:
        details.append(
            f"{temperature_output}="
            + (
                "all-null"
                if temperature_range is None
                else f"{temperature_range[0]:.3f}..{temperature_range[1]:.3f} degC"
            )
        )

    if details:
        LOGGER.info(
            "VERIFIED  reporting condition instrument=%s frequency=%s "
            "target=(%.1f Pa, %.2f degC) %s",
            instrument.name,
            frequency,
            correction.target_pressure_pa,
            correction.target_temperature_c,
            " ".join(details),
        )


def build_aggregate_dataframe(
    files: list[Path],
    defaults: Defaults,
    instrument: InstrumentSpec,
    frequency: Frequency,
) -> pl.DataFrame | None:
    """Aggregate Level 1 files directly to one requested cadence.

    Each output value column is paired with ``n_<output_name>``. The count is
    the number of non-null Level 1 values admitted by the exact same validity
    condition as the aggregate.
    """

    df, resolved = _load_level1_frame(files, defaults, instrument)
    df, _ = _apply_reporting_condition_correction(df, resolved, instrument)
    out = _aggregate_loaded_frame(df, resolved, defaults, instrument, frequency)
    if out is not None:
        _verify_reporting_condition_aggregate(out, instrument, frequency)
    return out

def build_hourly_dataframe(
    files: list[Path],
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> pl.DataFrame | None:
    """Backward-compatible helper for direct Level 1 -> hourly aggregation."""

    return build_aggregate_dataframe(files, defaults, instrument, "hourly")


def build_daily_dataframe(
    hourly_df: pl.DataFrame,
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> pl.DataFrame | None:
    """Legacy helper to aggregate an already-hourly frame to daily values.

    The command-line workflow no longer uses this helper: daily products are
    built directly from Level 1 to preserve exact aggregation semantics. This
    helper remains for imports that relied on the previous public function.
    Existing ``n_<column>`` counts are summed into each day.
    """

    if hourly_df.is_empty():
        return None

    exprs: list[pl.Expr] = []
    selected = [defaults.datetime_column]
    for column in instrument.columns:
        value_name = column.output_name
        if value_name not in hourly_df.columns:
            continue
        count_name = valid_count_column(value_name)
        exprs.append(_aggregation_expr(column.daily_method, value_name, value_name))
        if count_name in hourly_df.columns:
            exprs.append(pl.col(count_name).sum().cast(pl.UInt32).alias(count_name))
            selected.extend([value_name, count_name])
        else:
            selected.append(value_name)

    if not exprs:
        return None

    out = (
        hourly_df.sort(defaults.datetime_column)
        .group_by_dynamic(
            index_column=defaults.datetime_column,
            every=defaults.daily.every,
            label=defaults.daily.label,
            closed=defaults.daily.closed,
        )
        .agg(exprs)
        .sort(defaults.datetime_column)
    )
    return out.select([name for name in selected if name in out.columns])


def _station_year_output_dir(root: Path, station: str, year: int) -> Path:
    return root / "level2" / station / str(year)


def _instrument_output_stem(instrument: str) -> str:
    return instrument.replace("/", "-")


def output_path(
    root: Path,
    station: str,
    instrument: str,
    frequency: Frequency,
    year: int,
) -> Path:
    """Return a yearly level 2 parquet output path."""

    safe_instrument = _instrument_output_stem(instrument)
    return (
        _station_year_output_dir(root, station, year)
        / f"{station}_{safe_instrument}_{frequency}_{year}.parquet"
    )



def existing_level2_flag_columns(path: Path) -> tuple[str, ...]:
    """Return existing Level 2 ``f_*`` columns that a rebuild would discard."""

    if not path.exists():
        return ()
    try:
        names = pl.scan_parquet(path).collect_schema().names()
    except Exception as exc:
        LOGGER.warning("Could not inspect existing Level 2 schema %s: %s", path, exc)
        return ()
    return tuple(name for name in names if name.startswith("f_"))

def write_parquet(df: pl.DataFrame, path: Path, compression: ParquetCompression) -> None:
    """Write one parquet file, creating the target directory first."""

    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression=compression)


def csv_output_path(parquet_path: Path) -> Path:
    """Return the CSV sibling of a Level 2 Parquet path."""

    return parquet_path.with_suffix(".csv")


def zip_output_path(parquet_path: Path) -> Path:
    """Return the ZIP-compressed CSV sibling of a Level 2 Parquet path."""

    csv_path = csv_output_path(parquet_path)
    return csv_path.with_name(f"{csv_path.name}.zip")


def write_csv(df: pl.DataFrame, path: Path) -> None:
    """Write one CSV export, creating the target directory first."""

    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(path)


def write_csv_zip(
    df: pl.DataFrame,
    path: Path,
    *,
    csv_name: str,
    source_csv: Path | None = None,
) -> None:
    """Write a ZIP archive containing exactly one CSV export.

    If ``source_csv`` is supplied, that already-written CSV is archived.
    Otherwise the dataframe is serialized directly into the archive so
    ``--zip`` does not require an uncompressed CSV to be left on disk.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        if source_csv is not None:
            archive.write(source_csv, arcname=csv_name)
        else:
            csv_text = df.write_csv()
            if csv_text is None:
                raise RuntimeError("Polars did not return CSV text for in-memory export.")
            archive.writestr(csv_name, csv_text)


def _source_bytes(files: list[Path]) -> int:
    """Return the total size of discovered source parquet files."""

    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def _collect_value_stats(
    df: pl.DataFrame,
    resolved: dict[str, tuple[str, str | None]],
    defaults: Defaults,
    instrument: InstrumentSpec,
) -> dict[str, ValueStats]:
    """Count non-null available and flag-valid Level 1 values per variable."""

    exprs: list[pl.Expr] = []
    names: list[tuple[str, str, str]] = []
    for index, column in enumerate(instrument.columns):
        resolved_names = resolved.get(column.name)
        if resolved_names is None:
            continue
        actual_value, actual_flag = resolved_names
        available_name = f"__available_{index}"
        valid_name = f"__valid_{index}"
        exprs.extend(
            [
                pl.col(actual_value).is_not_null().sum().alias(available_name),
                _valid_condition(actual_value, actual_flag, defaults)
                .sum()
                .alias(valid_name),
            ]
        )
        names.append((column.output_name, available_name, valid_name))

    if not exprs:
        return {}

    counts = df.select(exprs).row(0, named=True)
    return {
        output_name: ValueStats(
            available=int(counts[available_name] or 0),
            valid=int(counts[valid_name] or 0),
        )
        for output_name, available_name, valid_name in names
    }


def _format_optional_number(value: float | None, decimals: int) -> str:
    """Format an optional floating-point audit value."""

    return "n/a" if value is None else f"{float(value):.{decimals}f}"


def _format_bytes(size: int) -> str:
    """Return a compact IEC byte-size string."""

    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{size} B"


def _format_validity(valid: int, available: int) -> str:
    """Format a valid/available count and percentage."""

    if available == 0:
        return f"{valid:,}/{available:,}"
    return f"{valid:,}/{available:,} ({100.0 * valid / available:.1f}%)"


def _log_job_stats(job: JobStats) -> None:
    """Log concise per-job statistics; variable detail is DEBUG-level."""

    if job.error is not None:
        return
    if job.skipped_reason is not None:
        LOGGER.info(
            "Skipped station=%s instrument=%s year=%s: %s",
            job.station,
            job.instrument,
            job.year,
            job.skipped_reason,
        )
        return

    LOGGER.info(
        "Level1 station=%s instrument=%s year=%s files=%s rows=%s data=%s valid=%s",
        job.station,
        job.instrument,
        job.year,
        job.source_files,
        f"{job.level1_rows:,}",
        _format_bytes(job.source_bytes),
        _format_validity(job.valid_values, job.available_values),
    )
    for name, stats in job.values.items():
        LOGGER.debug(
            "  %s: valid/available=%s",
            name,
            _format_validity(stats.valid, stats.available),
        )
    if job.reporting_condition_stats is not None:
        condition_stats = job.reporting_condition_stats
        LOGGER.info(
            "Reporting-condition normalization ACTIVE station=%s instrument=%s year=%s "
            "already_target=%s corrected=%s invalid=%s "
            "source_P=%s..%s Pa source_T=%s..%s degC factor=%s..%s",
            job.station,
            job.instrument,
            job.year,
            f"{condition_stats.already_target:,}",
            f"{condition_stats.corrected:,}",
            f"{condition_stats.invalid:,}",
            _format_optional_number(condition_stats.source_pressure_min_pa, 2),
            _format_optional_number(condition_stats.source_pressure_max_pa, 2),
            _format_optional_number(condition_stats.source_temperature_min_c, 3),
            _format_optional_number(condition_stats.source_temperature_max_c, 3),
            _format_optional_number(condition_stats.factor_min, 6),
            _format_optional_number(condition_stats.factor_max, 6),
        )
    if job.missing_columns:
        LOGGER.warning(
            "Missing configured columns for station=%s instrument=%s year=%s: %s",
            job.station,
            job.instrument,
            job.year,
            ", ".join(job.missing_columns),
        )


def _process_station_instrument_year(
    root: Path,
    station: str,
    defaults: Defaults,
    instrument: InstrumentSpec,
    year: int,
    *,
    write: bool,
    export_csv: bool = False,
    zip_csv: bool = False,
) -> JobStats:
    """Build one instrument/year and return detailed statistics."""

    job = JobStats(
        station=station,
        instrument=instrument.name,
        year=year,
        configured_columns=len(instrument.columns),
    )
    files = parquet_files_for(root / "level1", station, instrument, year)
    job.source_files = len(files)
    job.source_bytes = _source_bytes(files)
    if not files:
        job.skipped_reason = "no Level 1 parquet files found"
        _log_job_stats(job)
        return job

    if (
        instrument.reporting_condition_correction is None
        and (
            instrument.name.casefold().startswith("ae33")
            or (instrument.source_parquet or "").casefold().startswith("ae33")
        )
        and any(
            column.name in {"Pressure", "Temperature"}
            for column in instrument.columns
        )
    ):
        LOGGER.warning(
            "AE33 reporting-condition normalization is NOT configured for %s. "
            "Pressure/Temperature and concentration values will be aggregated unchanged. "
            "Add reporting_condition_correction to the instrument config.",
            instrument.name,
        )

    level1_df, resolved = _load_level1_frame(files, defaults, instrument)
    job.level1_rows = level1_df.height
    job.resolved_columns = len(resolved)
    job.missing_columns = tuple(
        column.name for column in instrument.columns if column.name not in resolved
    )
    if level1_df.is_empty():
        job.skipped_reason = "Level 1 input contains no usable timestamped rows"
        _log_job_stats(job)
        return job
    if not resolved:
        job.skipped_reason = "none of the configured variables were found"
        _log_job_stats(job)
        return job

    level1_df, job.reporting_condition_stats = _apply_reporting_condition_correction(
        level1_df, resolved, instrument
    )
    job.values = _collect_value_stats(level1_df, resolved, defaults, instrument)
    _log_job_stats(job)

    for frequency in FREQUENCIES:
        if not _write_enabled(defaults, frequency):
            continue

        aggregated = _aggregate_loaded_frame(
            level1_df,
            resolved,
            defaults,
            instrument,
            frequency,
        )
        if aggregated is None or aggregated.is_empty():
            LOGGER.info(
                "No usable %s output for station=%s instrument=%s year=%s",
                frequency,
                station,
                instrument.name,
                year,
            )
            continue

        _verify_reporting_condition_aggregate(
            aggregated,
            instrument,
            frequency,
        )

        path = output_path(root, station, instrument.name, frequency, year)
        csv_path = csv_output_path(path)
        zipped_csv_path = zip_output_path(path)
        job.aggregate_rows[frequency] = aggregated.height
        job.output_paths[frequency] = path
        if path.exists():
            job.existing_outputs.add(frequency)
            existing_flags = existing_level2_flag_columns(path)
            if existing_flags:
                job.existing_level2_flags[frequency] = existing_flags
                LOGGER.warning(
                    "Existing Level 2 flags will be discarded by regeneration: %s -> %s",
                    path,
                    ", ".join(existing_flags),
                )
        if export_csv:
            job.csv_paths[frequency] = csv_path
            if csv_path.exists():
                job.existing_csv_outputs.add(frequency)
        if zip_csv:
            job.zip_paths[frequency] = zipped_csv_path
            if zipped_csv_path.exists():
                job.existing_zip_outputs.add(frequency)

        if not write:
            LOGGER.info(
                "WOULD     parquet %-7s rows=%s -> %s%s",
                frequency,
                f"{aggregated.height:,}",
                path,
                " (overwrite)" if path.exists() else "",
            )
            if export_csv:
                LOGGER.info(
                    "WOULD     csv     %-7s rows=%s -> %s%s",
                    frequency,
                    f"{aggregated.height:,}",
                    csv_path,
                    " (overwrite)" if csv_path.exists() else "",
                )
            if zip_csv:
                LOGGER.info(
                    "WOULD     csv.zip %-7s rows=%s -> %s%s",
                    frequency,
                    f"{aggregated.height:,}",
                    zipped_csv_path,
                    " (overwrite)" if zipped_csv_path.exists() else "",
                )
            continue

        # Parquet is canonical and is always written on a real write run.
        write_parquet(aggregated, path, defaults.parquet_compression)
        job.written_outputs.add(frequency)
        LOGGER.info(
            "WRITTEN   parquet %-7s rows=%s -> %s",
            frequency,
            f"{aggregated.height:,}",
            path,
        )

        if export_csv:
            write_csv(aggregated, csv_path)
            job.written_csv_outputs.add(frequency)
            LOGGER.info(
                "WRITTEN   csv     %-7s rows=%s -> %s",
                frequency,
                f"{aggregated.height:,}",
                csv_path,
            )

        if zip_csv:
            write_csv_zip(
                aggregated,
                zipped_csv_path,
                csv_name=csv_path.name,
                source_csv=csv_path if export_csv else None,
            )
            job.written_zip_outputs.add(frequency)
            LOGGER.info(
                "WRITTEN   csv.zip %-7s rows=%s -> %s",
                frequency,
                f"{aggregated.height:,}",
                zipped_csv_path,
            )

    return job


def process_station_instrument_year(
    root: Path,
    station: str,
    defaults: Defaults,
    instrument: InstrumentSpec,
    year: int,
    *,
    write: bool = False,
    csv: bool = False,
    zip_csv: bool = False,
) -> dict[Frequency, Path]:
    """Build configured Level 2 cadences for one instrument/year.

    Existing Level 2 targets are regenerated, not merged. Therefore any
    pre-existing Level 2 ``f_*`` flag columns are discarded on a write run and
    must be assigned again after regeneration.

    Args:
        root: gawkenyadata repository root.
        station: Station code.
        defaults: Resolved Level 2 defaults.
        instrument: Instrument specification.
        year: Four-digit year.
        write: If true, write or overwrite the planned outputs. Parquet is
            always written. The default is a dry run.
        csv: Also export uncompressed CSV siblings.
        zip_csv: Also export ZIP-compressed CSV siblings. This never zips Parquet.

    Returns:
        Mapping of output cadence to planned/written output path. In the default
        dry-run mode, paths are returned even though the files are not created.
    """

    job = _process_station_instrument_year(
        root,
        station,
        defaults,
        instrument,
        year,
        write=write,
        export_csv=csv,
        zip_csv=zip_csv,
    )
    return job.output_paths


def print_summary(stats: RunStats) -> None:
    """Print an AE33-housekeeping-style end-of-run summary."""

    jobs = stats.jobs
    processed = [job for job in jobs if job.error is None and job.skipped_reason is None]
    skipped = [job for job in jobs if job.skipped_reason is not None]
    source_files = sum(job.source_files for job in jobs)
    source_bytes = sum(job.source_bytes for job in jobs)
    level1_rows = sum(job.level1_rows for job in jobs)
    configured_columns = sum(job.configured_columns for job in jobs)
    resolved_columns = sum(job.resolved_columns for job in jobs)
    missing_columns = sum(len(job.missing_columns) for job in jobs)
    available_values = sum(job.available_values for job in jobs)
    valid_values = sum(job.valid_values for job in jobs)
    parquet_planned = sum(len(job.output_paths) for job in jobs)
    csv_planned = sum(len(job.csv_paths) for job in jobs)
    zip_planned = sum(len(job.zip_paths) for job in jobs)
    planned_outputs = parquet_planned + csv_planned + zip_planned

    parquet_written = sum(len(job.written_outputs) for job in jobs)
    csv_written = sum(len(job.written_csv_outputs) for job in jobs)
    zip_written = sum(len(job.written_zip_outputs) for job in jobs)
    written_outputs = parquet_written + csv_written + zip_written

    parquet_existing = sum(len(job.existing_outputs) for job in jobs)
    csv_existing = sum(len(job.existing_csv_outputs) for job in jobs)
    zip_existing = sum(len(job.existing_zip_outputs) for job in jobs)
    existing_outputs = parquet_existing + csv_existing + zip_existing
    condition_already_target = sum(
        job.reporting_condition_stats.already_target
        for job in jobs
        if job.reporting_condition_stats is not None
    )
    condition_corrected = sum(
        job.reporting_condition_stats.corrected
        for job in jobs
        if job.reporting_condition_stats is not None
    )
    condition_invalid = sum(
        job.reporting_condition_stats.invalid
        for job in jobs
        if job.reporting_condition_stats is not None
    )
    existing_level2_flag_columns_count = sum(
        len(columns) for job in jobs for columns in job.existing_level2_flags.values()
    )

    print()
    print("Summary")
    print("-------")
    print(f"Mode                     : {'write' if stats.write else 'dry run (no files written)'}")
    print(f"Instrument-years checked : {len(jobs):,}")
    print(f"Processed                : {len(processed):,}")
    print(f"Skipped                  : {len(skipped):,}")
    print(f"Source parquet files     : {source_files:,}")
    print(f"Source parquet size      : {_format_bytes(source_bytes)}")
    print(f"Level 1 rows loaded      : {level1_rows:,}")
    print(f"Configured variables     : {configured_columns:,}")
    print(f"Resolved variables       : {resolved_columns:,}")
    print(f"Missing variables        : {missing_columns:,}")
    print(f"Valid / available values : {_format_validity(valid_values, available_values)}")
    if condition_already_target or condition_corrected or condition_invalid:
        print(
            "Reporting conditions     : "
            f"target={condition_already_target:,}, "
            f"corrected={condition_corrected:,}, invalid={condition_invalid:,}"
        )
    if existing_level2_flag_columns_count:
        print(
            "Existing L2 flags at risk: "
            f"{existing_level2_flag_columns_count:,} column(s) will be discarded on write"
        )
    for frequency in FREQUENCIES:
        rows = sum(job.aggregate_rows.get(frequency, 0) for job in jobs)
        outputs = sum(frequency in job.output_paths for job in jobs)
        print(f"{frequency.capitalize():<25}: {rows:,} rows in {outputs:,} file(s)")
    if not stats.write:
        print(f"Parquet planned          : {parquet_planned:,}")
        if stats.csv:
            print(f"CSV planned              : {csv_planned:,}")
        if stats.zip_csv:
            print(f"CSV ZIP planned          : {zip_planned:,}")
        print(f"Outputs planned          : {planned_outputs:,}")
        print(f"Would overwrite          : {existing_outputs:,}")
    else:
        print(f"Parquet written          : {parquet_written:,}")
        if stats.csv:
            print(f"CSV written              : {csv_written:,}")
        if stats.zip_csv:
            print(f"CSV ZIP written          : {zip_written:,}")
        print(f"Outputs written          : {written_outputs:,}")
        print(f"Existing overwritten     : {existing_outputs:,}")
    print(f"Errors                   : {stats.errors:,}")


def run(
    root: Path,
    station_config_path: Path,
    config_section: str | None = None,
    instrument_name: str | None = None,
    year: int | None = None,
    *,
    write: bool = False,
    csv: bool = False,
    zip_csv: bool = False,
) -> RunStats:
    """Run the Level 1 -> Level 2 aggregation workflow and return statistics."""

    station_cfg = load_station_config(station_config_path, config_section=config_section)
    defaults = station_cfg.defaults
    station = station_cfg.station

    root = resolve_data_root(root, station)
    level1_root = root / "level1"
    if not level1_root.exists():
        raise FileNotFoundError(f"Missing level1 directory: {level1_root}")

    years = [year] if year is not None else discover_years(level1_root, station)
    if instrument_name is not None:
        instrument = station_cfg.instruments.get(instrument_name)
        if instrument is None:
            raise ConfigError(
                f"Instrument '{instrument_name}' is not configured in {station_config_path}."
            )
        instruments = [instrument]
    else:
        instruments = list(station_cfg.instruments.values())

    stats = RunStats(write=write, csv=csv, zip_csv=zip_csv)
    if not years:
        LOGGER.info("No years found for station=%s", station)
        return stats

    for instrument in instruments:
        for one_year in years:
            try:
                job = _process_station_instrument_year(
                    root=root,
                    station=station,
                    defaults=defaults,
                    instrument=instrument,
                    year=one_year,
                    write=write,
                    export_csv=csv,
                    zip_csv=zip_csv,
                )
            except Exception as exc:
                job = JobStats(
                    station=station,
                    instrument=instrument.name,
                    year=one_year,
                    configured_columns=len(instrument.columns),
                    error=f"{type(exc).__name__}: {exc}",
                )
                LOGGER.error(
                    "ERROR station=%s instrument=%s year=%s: %s",
                    station,
                    instrument.name,
                    one_year,
                    job.error,
                )
                LOGGER.debug("Aggregation failure", exc_info=True)
            stats.jobs.append(job)

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help=(
            "Path to the gawkenyadata root, its level1 directory, or the "
            "selected station directory below level1."
        ),
    )
    parser.add_argument(
        "--station-config",
        type=Path,
        help="Path to a station configuration YAML that contains a level2 block.",
    )
    parser.add_argument(
        "--config-section",
        type=str,
        default=None,
        help="Optional top-level section containing level2, e.g. nrb-aq.",
    )
    parser.add_argument(
        "--instrument",
        type=str,
        default=None,
        help="Optional configured instrument name, e.g. 49i or ae31.",
    )
    parser.add_argument("--year", type=int, default=None, help="Optional year, e.g. 2026.")
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write or overwrite the planned Level 2 files. Parquet is always "
            "written. Existing Level 2 f_* flags are NOT preserved because the "
            "product is regenerated from Level 1. Without this flag the command "
            "is a dry run."
        ),
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also export an uncompressed CSV sibling for every Parquet product.",
    )
    parser.add_argument(
        "--zip",
        dest="zip_csv",
        action="store_true",
        help=(
            "Also export a ZIP-compressed CSV (.csv.zip) for every Parquet product. "
            "Parquet files are never ZIP-compressed; --zip does not require --csv."
        ),
    )
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
        help="Optional section name used with --write-example-station-config.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable variable-level debug statistics.")

    args = parser.parse_args(argv)
    if args.write_example_station_config is None and (
        args.root is None or args.station_config is None
    ):
        parser.error(
            "--root and --station-config are required unless --write-example-station-config is used."
        )
    return args


class TeeStream:
    """Write text to two streams, flushing both together."""

    def __init__(self, primary: TextIO, secondary: TextIO) -> None:
        self.primary = primary
        self.secondary = secondary

    def write(self, text: str) -> int:
        self.primary.write(text)
        self.secondary.write(text)
        return len(text)

    def flush(self) -> None:
        self.primary.flush()
        self.secondary.flush()

    def isatty(self) -> bool:
        return self.primary.isatty()


def _safe_log_token(value: str) -> str:
    """Return a filesystem-safe token for processing-log filenames."""

    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return token.strip("-._") or "all"


def processing_log_path(
    instrument_name: str | None,
    *,
    when: datetime | None = None,
    log_dir: Path | None = None,
) -> Path:
    """Return the processing-log path for a write run.

    Args:
        instrument_name: Selected instrument, or ``None`` when all configured
            instruments are processed.
        when: Timestamp to use in the filename. Defaults to current UTC.
        log_dir: Optional log directory. Defaults to ``<repo>/logs``.

    Returns:
        Timestamped log path such as
        ``logs/compile_level1_to_level2_ae33_20261007T093645Z.log``.
    """

    timestamp = (when or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    instrument = _safe_log_token(instrument_name or "all")
    target_dir = log_dir or (Path(__file__).resolve().parent / "logs")
    return target_dir / f"compile_level1_to_level2_{instrument}_{timestamp}.log"


def _run_cli(args: argparse.Namespace) -> int:
    """Execute a parsed CLI invocation."""

    setup_logging(args.verbose)

    if args.write_example_station_config is not None:
        write_example_station_config(
            args.write_example_station_config,
            section=args.example_section,
        )
        LOGGER.info("Wrote example station config to %s", args.write_example_station_config)
        return 0

    stats = run(
        root=args.root,
        station_config_path=args.station_config,
        config_section=args.config_section,
        instrument_name=args.instrument,
        year=args.year,
        write=args.write,
        csv=args.csv,
        zip_csv=args.zip_csv,
    )
    print_summary(stats)
    return 2 if stats.errors else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Dry runs write only to the terminal. Real write runs additionally tee the
    complete stdout/stderr stream to a timestamped processing log.
    """

    args = parse_args(argv)
    if not args.write:
        return _run_cli(args)

    log_path = processing_log_path(args.instrument)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as log_handle:
        stdout_tee = TeeStream(sys.stdout, log_handle)
        stderr_tee = TeeStream(sys.stderr, log_handle)
        with redirect_stdout(stdout_tee), redirect_stderr(stderr_tee):
            print(f"Processing log           : {log_path}")
            return _run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
