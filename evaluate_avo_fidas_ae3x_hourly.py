from __future__ import annotations

"""Combine and plot hourly AVO, Fidas, and AE31/AE33 particulate data.

Discover and combine compiled parquet files for AVO, Fidas, and optionally
AE31/AE33 using the provided YAML configuration, then plot the data:

1. read AVO hourly parquet files directly,
2. read Fidas parquet files and aggregates PM1, PM2.5, and PM10 to hourly means,
3. read AE31 and/or AE33 parquet files and aggregates BC to hourly means,
4. appliy per-variable flag filtering when matching ``f_`` columns are present,
5. write a merged hourly parquet file,
6. optionally writes a CSV export, and
7. generate an interactive Plotly HTML time-series plot.

The script first checks for explicit keys such as
``level1_root`` or ``compiled_root`` and otherwise searches likely directories
under the configured ``nrb-aq.root`` ancestry for a ``level1/nrb`` tree.

Examples:
    python combine_avo_fidas_ae3x_hourly.py \
        --config mch-nrb.yml

    python combine_avo_fidas_ae3x_hourly.py \
        --config mch-nrb.yml \
        --level1-root /product_data/data/pay/Kenya/git/gawkenyadata/level1/nrb \
        --plot-columns pm1 pm25 pm10 bc \
        --write-csv

    python combine_avo_fidas_ae3x_hourly.py \
        --config mch-nrb.yml \
        --output-dir /product_data/data/pay/Kenya/git/gawkenyadata/level2/nrb

    python combine_avo_fidas_ae3x_hourly.py \
        --config mch-nrb.yml \
        --verbose
"""

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any, Iterable

import polars as pl
import yaml


CHANNELS = ("pm1", "pm25", "pm10", "bc")
CHANNEL_ALIASES = {
    "pm1": "pm1",
    "pm10": "pm10",
    "pm25": "pm25",
    "pm2.5": "pm25",
    "pm2_5": "pm25",
    "bc": "bc",
    "ebc": "bc",
    "bc880": "bc",
    "bc6": "bc",
    "ir880": "bc",
    "ir370": "bc",
}


INSTRUMENT_CHANNEL_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    "avo": {
        "pm1": {"value": "pm1", "flag": None, "scale": 1.0},
        "pm25": {"value": "pm25_conc", "flag": None, "scale": 1.0},
        "pm10": {"value": "pm10_conc", "flag": None, "scale": 1.0},
    },
    "fidas": {
        # Compiled Fidas parquet uses Palas parameter IDs as column names.
        # User-provided mapping:
        #   61 -> PM1 [mg/m³]
        #   62 -> PM2.5 [mg/m³]
        #   64 -> PM10 [mg/m³]
        # Convert mg/m³ to µg/m³ to align with AVO.
        "pm1": {"value": "61", "flag": "f_60", "scale": 1000.0},
        "pm25": {"value": "62", "flag": "f_60", "scale": 1000.0},
        "pm10": {"value": "64", "flag": "f_60", "scale": 1000.0},
    },
    "ae31": {
        "bc": {"value": "IR880", "flag": "f_IR880", "scale": 0.001},
    },
    "ae33": {
        "bc": {"value": "BC6", "flag": "f_BC6", "scale": 0.001},
    },
}


def normalize_plot_columns(columns: Iterable[str]) -> list[str]:
    """Normalize user-supplied plot-column names to logical channel names."""
    normalized: list[str] = []
    invalid: list[str] = []
    for column in columns:
        key = CHANNEL_ALIASES.get(str(column).strip().lower())
        if key is None:
            invalid.append(str(column))
            continue
        if key not in normalized:
            normalized.append(key)
    if invalid:
        valid = ", ".join(sorted(set(CHANNELS) | set(CHANNEL_ALIASES)))
        raise ValueError(f"Invalid plot column(s): {', '.join(invalid)}. Valid values include: {valid}")
    return normalized


def log(message: str, *, enabled: bool = True) -> None:
    """Print a timestamped progress message and flush immediately."""
    if not enabled:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


@dataclass(frozen=True)
class ChannelSpec:
    """Column-discovery metadata for a logical channel."""

    name: str
    candidates: tuple[str, ...]
    regex: str
    flag_candidates: tuple[str, ...] = ()


CHANNEL_SPECS: dict[str, ChannelSpec] = {
    "pm1": ChannelSpec(
        name="pm1",
        candidates=("pm1", "PM1 [ug/m3]", "PM1", "pm1_conc"),
        regex=r"(^|[^a-z0-9])pm\s*1([^0-9]|$)",
        flag_candidates=("f_pm1", "f_PM1", "f_pm1_conc"),
    ),
    "pm25": ChannelSpec(
        name="pm25",
        candidates=(
            "pm25_conc",
            "pm25",
            "pm2.5",
            "PM2.5 [ug/m3]",
            "PM2.5",
            "pm2_5",
            "pm_2_5",
        ),
        regex=r"pm\s*2\s*\.?\s*5",
        flag_candidates=("f_pm25", "f_pm25_conc", "f_pm2_5", "f_PM2.5"),
    ),
    "pm10": ChannelSpec(
        name="pm10",
        candidates=("pm10_conc", "pm10", "PM10 [ug/m3]", "PM10"),
        regex=r"pm\s*10",
        flag_candidates=("f_pm10", "f_pm10_conc", "f_PM10"),
    ),
    "bc": ChannelSpec(
        name="bc",
        candidates=(
            "IR880",
            "ir880",
            "IR370",
            "ir370",
            "BC6",
            "bc6",
            "BC880",
            "bc880",
            "eBC",
            "BC",
            "bc",
            "BC [ug/m3]",
        ),
        regex=r"(^|[^a-z0-9])(ir880|ir370|bc6|bc880|ebc|bc)([^a-z0-9]|$)",
        flag_candidates=("f_IR880", "f_ir880", "f_IR370", "f_ir370", "f_BC6", "f_bc6", "f_BC880", "f_eBC", "f_BC", "f_bc"),
    ),
}




CHANNEL_DISPLAY_NAMES = {
    "pm1": "PM1",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "bc": "BC",
}

CHANNEL_UNITS = {
    "pm1": "µg/m³",
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "bc": "µg/m³",
}

PLOT_FONT_SIZES = {
    "title": 24,
    "axis_title": 20,
    "tick": 16,
    "legend": 16,
    "menu": 16,
    "annotation": 16,
}


def pretty_channel_name(channel: str) -> str:
    """Return a human-friendly channel label."""
    return CHANNEL_DISPLAY_NAMES.get(channel, channel.upper())


def pretty_axis_label(channel: str) -> str:
    """Return a channel axis label including units."""
    return f"{pretty_channel_name(channel)} [{CHANNEL_UNITS.get(channel, 'µg/m³')}]"


def pretty_series_name(column: str) -> str:
    """Return a readable legend label including channel units."""
    parts = str(column).split("_", 1)
    if len(parts) != 2:
        return str(column)
    instrument, channel = parts
    instrument_label = instrument.upper()
    if instrument.lower() == "avo":
        instrument_label = "AVO"
    elif instrument.lower() == "fidas":
        instrument_label = "Fidas"
    elif instrument.lower() == "ae31":
        instrument_label = "AE31"
    elif instrument.lower() == "ae33":
        instrument_label = "AE33"
    return f"{instrument_label} {pretty_axis_label(channel)}"


def format_regression_equation(slope: float, intercept: float) -> str:
    """Format a regression equation for plot annotations."""
    if math.isnan(slope) or math.isnan(intercept):
        return "y = n/a"
    sign = "+" if intercept >= 0 else "-"
    return f"y = {slope:.3f}x {sign} {abs(intercept):.3f}"


def correlation_annotation_text(n_points: int, corr: float, slope: float, intercept: float) -> str:
    """Build the annotation text for a correlation plot."""
    if math.isnan(corr):
        r_text = "Pearson r = n/a"
        r2_text = "Pearson R² = n/a"
    else:
        r_text = f"Pearson r = {corr:.3f}"
        r2_text = f"Pearson R² = {corr * corr:.3f}"
    return "<br>".join(
        [
            f"n = {n_points}",
            format_regression_equation(slope, intercept),
            r_text,
            r2_text,
        ]
    )
def load_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed configuration dictionary.
    """
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def normalize_name(value: str) -> str:
    """Normalize a column name for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def normalize_requested_channels(values: Iterable[str]) -> list[str]:
    """Normalize requested plot channel names and aliases."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_name(value)
        channel = CHANNEL_ALIASES.get(key)
        if channel is None:
            allowed = ", ".join(sorted(set(CHANNEL_ALIASES)))
            raise ValueError(f"Unsupported plot column '{value}'. Supported names/aliases: {allowed}")
        if channel not in seen:
            seen.add(channel)
            normalized.append(channel)
    return normalized


def summarize_columns(df: pl.DataFrame, limit: int = 80) -> str:
    """Return a compact summary of dataframe columns for diagnostics."""
    cols = [str(c) for c in df.columns]
    if len(cols) <= limit:
        return ", ".join(cols)
    return ", ".join(cols[:limit]) + f", ... (+{len(cols) - limit} more)"


def unique_existing_paths(paths: Iterable[Path]) -> list[Path]:
    """Return unique existing paths while preserving order."""
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = str(path.expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        p = Path(resolved)
        if p.exists():
            result.append(p)
    return result


def discover_level1_root(config: dict[str, Any], explicit_root: Path | None = None) -> Path:
    """Discover the compiled ``level1/nrb`` root without broad recursive scans.

    The NRB case in this project stores compiled parquet files under
    ``/product_data/data/pay/Kenya/git/gawkenyadata/level1/nrb``. The config
    snippet shared in this chat exposes ``nrb-aq.root`` as
    ``/product_data/data/pay/Kenya/NRB``, so this function first tries direct,
    deterministic path derivations and only falls back to a few shallow checks.

    Args:
        config: Parsed YAML configuration.
        explicit_root: Optional user-provided override.

    Returns:
        Path to the discovered ``level1/nrb`` tree.

    Raises:
        FileNotFoundError: If no plausible compiled parquet root can be found.
    """
    if explicit_root is not None:
        candidate = explicit_root.expanduser()
        if not candidate.exists():
            raise FileNotFoundError(f"Explicit level1 root does not exist: {candidate}")
        return candidate

    section = config.get("nrb-aq", {})

    explicit_keys = (
        "level1_root",
        "compiled_root",
        "target",
        "target_root",
        "level1",
    )
    direct_candidates: list[Path] = []
    for key in explicit_keys:
        raw = section.get(key)
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.name == "nrb" and path.parent.name == "level1":
            direct_candidates.append(path)
        else:
            direct_candidates.append(path / "level1" / "nrb")

    aq_root_raw = section.get("root")
    if aq_root_raw:
        aq_root = Path(str(aq_root_raw)).expanduser()
        # Project-specific NRB compiled target.
        direct_candidates.append(aq_root.parent / "git" / "gawkenyadata" / "level1" / "nrb")
        # A few nearby direct alternatives, but no recursive walk.
        direct_candidates.extend(
            [
                aq_root / "level1" / "nrb",
                aq_root.parent / "level1" / "nrb",
                aq_root.parent.parent / "level1" / "nrb" if len(aq_root.parents) >= 2 else aq_root,
                Path.cwd() / "level1" / "nrb",
            ]
        )
    else:
        direct_candidates.append(Path.cwd() / "level1" / "nrb")

    for candidate in unique_existing_paths(direct_candidates):
        if candidate.exists():
            return candidate

    candidate_text = ", ".join(str(path) for path in direct_candidates)
    raise FileNotFoundError(
        "Could not determine the compiled 'level1/nrb' directory. "
        "For NRB, it is usually '/product_data/data/pay/Kenya/git/gawkenyadata/level1/nrb'. "
        "Pass --level1-root explicitly. Checked: "
        + candidate_text
    )


def discover_parquet_files(level1_root: Path, basename: str) -> list[Path]:
    """Find compiled parquet files recursively below ``level1_root``."""
    return sorted(path for path in level1_root.rglob(basename) if path.is_file())


def default_output_dir_from_level1(level1_root: Path) -> Path:
    """Derive the default level2 output directory from the level1 root.

    For a compiled parquet root like ``.../gawkenyadata/level1/nrb``, the
    evaluation products are written to the sibling path
    ``.../gawkenyadata/level2/nrb`` so that compiled source data and derived
    comparison products remain separated while staying in the same repository.

    Args:
        level1_root: Compiled level1 root, typically ``.../level1/nrb``.

    Returns:
        Derived level2 output directory.
    """
    level1_root = level1_root.expanduser()
    if level1_root.parent.name == 'level1':
        repo_root = level1_root.parent.parent
        return repo_root / 'level2' / level1_root.name
    if level1_root.name == 'level1':
        repo_root = level1_root.parent
        return repo_root / 'level2'
    return level1_root / 'level2_results'


def read_parquet_collection(
    paths: list[Path],
    label: str,
    *,
    verbose: bool = True,
    progress_every: int = 1,
) -> pl.DataFrame:
    """Read and concatenate a collection of parquet files with progress logging."""
    if not paths:
        log(f"No {label} parquet files to read.", enabled=verbose)
        return pl.DataFrame()

    start = time.perf_counter()
    log(f"Reading {len(paths)} {label} parquet file(s) ...", enabled=verbose)
    frames: list[pl.DataFrame] = []

    for index, path in enumerate(paths, start=1):
        if index == 1 or index == len(paths) or (progress_every > 0 and index % progress_every == 0):
            log(f"[{label}] reading file {index}/{len(paths)}: {path}", enabled=verbose)
        frame = pl.read_parquet(path)
        frames.append(frame)
        if index == 1 or index == len(paths) or (progress_every > 0 and index % progress_every == 0):
            log(
                f"[{label}] done file {index}/{len(paths)}: rows={frame.height:,}, cols={frame.width}",
                enabled=verbose,
            )

    df = pl.concat(frames, how="diagonal_relaxed") if len(frames) > 1 else frames[0]
    elapsed = time.perf_counter() - start
    log(
        f"Finished reading {label}: total rows={df.height:,}, cols={df.width}, elapsed={elapsed:.1f}s",
        enabled=verbose,
    )
    return df


def parse_dtm_expr(column: str = "dtm") -> pl.Expr:
    """Build a robust datetime parser yielding UTC microsecond timestamps."""
    source = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
    return pl.coalesce(
        [
            pl.col(column).cast(pl.Datetime(time_unit="us", time_zone="UTC"), strict=False),
            source.str.strptime(
                pl.Datetime(time_zone="UTC"),
                format="%Y-%m-%dT%H:%M:%S%.f%#z",
                strict=False,
            ),
            source.str.strptime(
                pl.Datetime(time_zone="UTC"),
                format="%Y-%m-%d %H:%M:%S%.f%#z",
                strict=False,
            ),
            source.str.strptime(
                pl.Datetime,
                format="%Y-%m-%dT%H:%M:%S%.f",
                strict=False,
            ).dt.replace_time_zone("UTC"),
            source.str.strptime(
                pl.Datetime,
                format="%Y-%m-%d %H:%M:%S%.f",
                strict=False,
            ).dt.replace_time_zone("UTC"),
            source.str.strptime(
                pl.Datetime,
                format="%Y-%m-%d %H:%M:%S",
                strict=False,
            ).dt.replace_time_zone("UTC"),
            source.str.strptime(
                pl.Date,
                format="%Y-%m-%d",
                strict=False,
            ).cast(pl.Datetime).dt.replace_time_zone("UTC"),
        ]
    ).alias("dtm")


def ensure_dtm(df: pl.DataFrame) -> pl.DataFrame:
    """Ensure a dataframe has a parsed ``dtm`` column."""
    if "dtm" not in df.columns:
        raise ValueError("Expected a 'dtm' column in compiled parquet data.")
    df = df.with_columns(parse_dtm_expr("dtm"))
    if df["dtm"].null_count() == len(df):
        raise ValueError("Could not parse any timestamps from the compiled parquet data.")
    return df.filter(pl.col("dtm").is_not_null())


def find_value_column(df: pl.DataFrame, spec: ChannelSpec) -> str | None:
    """Find the best matching value column for a channel."""
    columns = [column for column in df.columns if not str(column).startswith("f_")]
    by_normalized = {normalize_name(column): column for column in columns}

    for candidate in spec.candidates:
        normalized = normalize_name(candidate)
        if normalized in by_normalized:
            return by_normalized[normalized]

    matches = [column for column in columns if re.search(spec.regex, str(column), flags=re.IGNORECASE)]

    def heuristic_match() -> str | None:
        ranked: list[tuple[int, str]] = []
        for column in columns:
            norm = normalize_name(column)
            if not norm or norm in {"dtm", "ts", "time", "date", "source"}:
                continue
            score = 0
            if spec.name == "pm1":
                if "pm1" in norm and "pm10" not in norm and "pm25" not in norm and "aqi" not in norm:
                    score += 100
                if "mass" in norm or "conc" in norm: 
                    score += 10
            elif spec.name == "pm25":
                if "pm25" in norm and "aqi" not in norm:
                    score += 100
                if "mass" in norm or "conc" in norm: 
                    score += 10
            elif spec.name == "pm10":
                if "pm10" in norm and "aqi" not in norm:
                    score += 100
                if "mass" in norm or "conc" in norm: 
                    score += 10
            elif spec.name == "bc":
                if any(token in norm for token in ("ir880", "ir370", "bc6", "bc880", "ebc", "bc")):
                    score += 100
            if score:
                ranked.append((score, str(column)))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked[0][1]

    if not matches:
        return heuristic_match()

    filtered = []
    for column in matches:
        norm = normalize_name(column)
        if spec.name.startswith("pm") and "aqi" in norm:
            continue
        filtered.append(column)
    matches = filtered or matches

    if spec.name == "bc":
        preferred_order = ["IR880", "ir880", "IR370", "ir370", "BC6", "bc6", "BC880", "bc880", "eBC", "BC", "bc"]
        for preferred in preferred_order:
            for column in matches:
                if normalize_name(column) == normalize_name(preferred):
                    return column
    return heuristic_match() or sorted(matches)[0]


def find_flag_column(df: pl.DataFrame, value_column: str, spec: ChannelSpec) -> str | None:
    """Find the matching flag column for a value column, if present."""
    normalized_value = normalize_name(value_column)
    by_normalized = {normalize_name(column): column for column in df.columns}

    direct_candidates = [f"f_{value_column}", *spec.flag_candidates]
    for candidate in direct_candidates:
        normalized = normalize_name(candidate)
        if normalized in by_normalized:
            return by_normalized[normalized]

    for column in df.columns:
        if not str(column).startswith("f_"):
            continue
        normalized_flag = normalize_name(column)
        if normalized_value and normalized_value in normalized_flag:
            return column

    return None


def valid_value_expr(
    value_column: str,
    flag_column: str | None,
    alias: str,
    *,
    scale: float = 1.0,
) -> pl.Expr:
    """Build an expression that masks invalid values using the flag column."""
    value_expr = pl.col(value_column).cast(pl.Float64, strict=False)
    if scale != 1.0:
        value_expr = value_expr * scale
    if flag_column is None:
        return value_expr.alias(alias)
    flag_expr = pl.col(flag_column).cast(pl.Int64, strict=False)
    return pl.when(flag_expr == 0).then(value_expr).otherwise(None).alias(alias)


def aggregate_hourly(
    df: pl.DataFrame,
    instrument: str,
    channels: Iterable[str],
    *,
    verbose: bool = True,
) -> tuple[pl.DataFrame, dict[str, tuple[str, str | None]]]:
    """Aggregate selected channels to hourly means.

    Args:
        df: Input dataframe.
        instrument: Instrument prefix for output columns.
        channels: Logical channels to extract.
        verbose: Whether to emit progress messages.

    Returns:
        Tuple of ``(hourly_dataframe, selected_columns_metadata)``.
    """
    if df.is_empty():
        log(f"{instrument}: input dataframe is empty; skipping aggregation.", enabled=verbose)
        return pl.DataFrame(), {}

    start = time.perf_counter()
    log(f"{instrument}: parsing timestamps and selecting channels ...", enabled=verbose)
    df = ensure_dtm(df)
    selected: dict[str, tuple[str, str | None]] = {}
    exprs: list[pl.Expr] = []

    for channel in channels:
        spec = CHANNEL_SPECS[channel]
        override = INSTRUMENT_CHANNEL_OVERRIDES.get(instrument, {}).get(channel, {})
        value_column = override.get("value")
        if value_column is not None and value_column not in df.columns:
            log(
                f"{instrument}: configured value column '{value_column}' for channel '{channel}' not found; falling back to discovery.",
                enabled=verbose,
            )
            value_column = None
        if value_column is None:
            value_column = find_value_column(df, spec)
        if value_column is None:
            log(
                f"{instrument}: no value column found for channel '{channel}'. Available columns: {summarize_columns(df)}",
                enabled=verbose,
            )
            continue

        flag_column = override.get("flag")
        if flag_column is not None and flag_column not in df.columns:
            log(
                f"{instrument}: configured flag column '{flag_column}' for channel '{channel}' not found; falling back to discovery.",
                enabled=verbose,
            )
            flag_column = None
        if flag_column is None:
            flag_column = find_flag_column(df, value_column, spec)

        scale = float(override.get("scale", 1.0))
        alias = f"__{instrument}_{channel}_valid"
        exprs.append(valid_value_expr(value_column, flag_column, alias, scale=scale))
        selected[channel] = (value_column, flag_column)
        scale_msg = f", scale={scale:g}" if scale != 1.0 else ""
        log(
            f"{instrument}: channel '{channel}' -> value='{value_column}', flag='{flag_column}'{scale_msg}",
            enabled=verbose,
        )

    if not exprs:
        log(f"{instrument}: no matching channels found; nothing to aggregate.", enabled=verbose)
        return pl.DataFrame(), {}

    log(f"{instrument}: aggregating {df.height:,} row(s) to hourly means ...", enabled=verbose)
    hourly = (
        df.with_columns(exprs)
        .with_columns(pl.col("dtm").dt.truncate("1h").alias("dtm"))
        .group_by("dtm")
        .agg(
            [pl.col(f"__{instrument}_{channel}_valid").mean().alias(f"{instrument}_{channel}") for channel in selected]
        )
        .sort("dtm")
    )
    elapsed = time.perf_counter() - start
    log(
        f"{instrument}: hourly aggregation complete -> rows={hourly.height:,}, cols={hourly.width}, elapsed={elapsed:.1f}s",
        enabled=verbose,
    )
    return hourly, selected


def prepare_avo_hourly(
    df: pl.DataFrame,
    channels: Iterable[str],
    *,
    verbose: bool = True,
) -> tuple[pl.DataFrame, dict[str, tuple[str, str | None]]]:
    """Prepare compiled AVO hourly data for merging.

    The AVO product is already hourly, but duplicate timestamps are averaged to
    keep one row per hour.
    """
    return aggregate_hourly(df=df, instrument="avo", channels=channels, verbose=verbose)


def merge_on_dtm(frames: list[pl.DataFrame], *, verbose: bool = True) -> pl.DataFrame:
    """Outer-join multiple dataframes on ``dtm``."""
    non_empty = [frame for frame in frames if not frame.is_empty()]
    if not non_empty:
        log("No non-empty hourly dataframes available for merging.", enabled=verbose)
        return pl.DataFrame({"dtm": []})

    log(f"Merging {len(non_empty)} hourly dataframe(s) on dtm ...", enabled=verbose)
    start = time.perf_counter()
    merged = non_empty[0]
    for index, frame in enumerate(non_empty[1:], start=2):
        log(f"Merge step {index - 1}/{len(non_empty) - 1} ...", enabled=verbose)
        merged = merged.join(frame, on="dtm", how="full")
        if "dtm_right" in merged.columns:
            merged = merged.with_columns(pl.coalesce([pl.col("dtm"), pl.col("dtm_right")]).alias("dtm")).drop("dtm_right")
    merged = merged.sort("dtm")
    elapsed = time.perf_counter() - start
    log(f"Merge complete -> rows={merged.height:,}, cols={merged.width}, elapsed={elapsed:.1f}s", enabled=verbose)
    return merged


def build_plot(
    df: pl.DataFrame,
    output_html: Path,
    plot_channels: list[str],
    *,
    plot_title: str,
    verbose: bool = True,
) -> None:
    """Generate an interactive Plotly HTML with dropdown channel selectors."""
    try:
        import plotly.graph_objects as go
    except Exception as err:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Plotly is required for interactive output. Install it with 'pip install plotly'."
        ) from err

    if df.is_empty():
        raise ValueError("Merged dataframe is empty; nothing to plot.")

    log(f"Building interactive Plotly HTML for channels: {', '.join(plot_channels)} ...", enabled=verbose)
    start = time.perf_counter()
    x_values = df["dtm"].to_list()
    trace_channels: list[str] = []
    fig = go.Figure()

    channel_to_columns: dict[str, list[str]] = {
        "pm1": [column for column in df.columns if column.endswith("_pm1")],
        "pm25": [column for column in df.columns if column.endswith("_pm25")],
        "pm10": [column for column in df.columns if column.endswith("_pm10")],
        "bc": [column for column in df.columns if column.endswith("_bc")],
    }

    for channel in plot_channels:
        for column in channel_to_columns[channel]:
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=df[column].to_list(),
                    mode="lines",
                    name=pretty_series_name(column),
                    visible=(channel == plot_channels[0]),
                )
            )
            trace_channels.append(channel)

    buttons = []
    for channel in plot_channels:
        visible = [trace_channel == channel for trace_channel in trace_channels]
        label = pretty_channel_name(channel)
        buttons.append(
            {
                "label": label,
                "method": "update",
                "args": [
                    {"visible": visible},
                    {
                        "title": {"text": f"{plot_title}<br><sup>Hourly comparison: {label}</sup>"},
                        "yaxis": {"title": {"text": pretty_axis_label(channel), "font": {"size": PLOT_FONT_SIZES["axis_title"]}}},
                    },
                ],
            }
        )

    if len(plot_channels) > 1:
        buttons.insert(
            0,
            {
                "label": "All",
                "method": "update",
                "args": [
                    {"visible": [True] * len(trace_channels)},
                    {
                        "title": {"text": f"{plot_title}<br><sup>Hourly comparison: all selected channels</sup>"},
                        "yaxis": {"title": {"text": "Concentration [µg/m³]", "font": {"size": PLOT_FONT_SIZES["axis_title"]}}},
                    },
                ],
            },
        )

    initial_channel = plot_channels[0]
    fig.update_layout(
        title={"text": f"{plot_title}<br><sup>Hourly comparison: {pretty_channel_name(initial_channel)}</sup>", "font": {"size": PLOT_FONT_SIZES["title"]}},
        xaxis_title={"text": "Date/time [UTC]", "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
        yaxis_title={"text": pretty_axis_label(initial_channel), "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
        xaxis={"tickfont": {"size": PLOT_FONT_SIZES["tick"]}},
        yaxis={"tickfont": {"size": PLOT_FONT_SIZES["tick"]}},
        hovermode="x unified",
        updatemenus=[
            {
                "type": "dropdown",
                "x": 1.02,
                "y": 1.0,
                "showactive": True,
                "font": {"size": PLOT_FONT_SIZES["menu"]},
                "buttons": buttons,
            }
        ],
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0.0,
            "font": {"size": PLOT_FONT_SIZES["legend"]},
        },
        margin={"t": 120},
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_html), include_plotlyjs="cdn")
    elapsed = time.perf_counter() - start
    log(f"Interactive plot written: {output_html} (elapsed={elapsed:.1f}s)", enabled=verbose)

def _compute_regression_stats(x_values: list[float], y_values: list[float]) -> tuple[float, float, float]:
    """Compute Pearson correlation and least-squares line parameters."""
    if len(x_values) < 2 or len(y_values) < 2 or len(x_values) != len(y_values):
        return math.nan, math.nan, math.nan

    n = float(len(x_values))
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n
    var_x = sum((x - x_mean) ** 2 for x in x_values)
    var_y = sum((y - y_mean) ** 2 for y in y_values)
    if var_x <= 0.0 or var_y <= 0.0:
        return math.nan, math.nan, math.nan

    cov_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    slope = cov_xy / var_x
    intercept = y_mean - slope * x_mean
    corr = cov_xy / math.sqrt(var_x * var_y)
    return corr, slope, intercept


def build_correlation_plot(
    df: pl.DataFrame,
    output_html: Path,
    *,
    plot_title: str,
    verbose: bool = True,
) -> Path | None:
    """Generate an interactive Plotly HTML with pairwise correlation plots."""
    try:
        import plotly.graph_objects as go
    except Exception as err:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Plotly is required for interactive output. Install it with 'pip install plotly'."
        ) from err

    if df.is_empty():
        raise ValueError("Merged dataframe is empty; nothing to plot.")

    log("Building interactive correlation plots ...", enabled=verbose)
    start = time.perf_counter()

    candidate_pairs: list[tuple[str, str, str, str, str]] = []

    same_channel_pairs = [
        ("Fidas vs AVO PM1", "fidas_pm1", "avo_pm1", "Fidas PM1 [µg/m³]", "AVO PM1 [µg/m³]"),
        ("Fidas vs AVO PM2.5", "fidas_pm25", "avo_pm25", "Fidas PM2.5 [µg/m³]", "AVO PM2.5 [µg/m³]"),
        ("Fidas vs AVO PM10", "fidas_pm10", "avo_pm10", "Fidas PM10 [µg/m³]", "AVO PM10 [µg/m³]"),
    ]
    for pair in same_channel_pairs:
        if pair[1] in df.columns and pair[2] in df.columns:
            candidate_pairs.append(pair)

    bc_pairs: list[tuple[str, str, str, str, str]] = []
    if "ae31_bc" in df.columns:
        bc_pairs.extend(
            [
                ("AE31 BC vs AVO PM1", "ae31_bc", "avo_pm1", "AE31 BC [µg/m³]", "AVO PM1 [µg/m³]"),
                ("AE31 BC vs AVO PM2.5", "ae31_bc", "avo_pm25", "AE31 BC [µg/m³]", "AVO PM2.5 [µg/m³]"),
                ("AE31 BC vs AVO PM10", "ae31_bc", "avo_pm10", "AE31 BC [µg/m³]", "AVO PM10 [µg/m³]"),
                ("Fidas PM1 vs AE31 BC", "fidas_pm1", "ae31_bc", "Fidas PM1 [µg/m³]", "AE31 BC [µg/m³]"),
                ("Fidas PM2.5 vs AE31 BC", "fidas_pm25", "ae31_bc", "Fidas PM2.5 [µg/m³]", "AE31 BC [µg/m³]"),
                ("Fidas PM10 vs AE31 BC", "fidas_pm10", "ae31_bc", "Fidas PM10 [µg/m³]", "AE31 BC [µg/m³]"),
            ]
        )
    if "ae33_bc" in df.columns:
        bc_pairs.extend(
            [
                ("AE33 BC vs AVO PM1", "ae33_bc", "avo_pm1", "AE33 BC [µg/m³]", "AVO PM1 [µg/m³]"),
                ("AE33 BC vs AVO PM2.5", "ae33_bc", "avo_pm25", "AE33 BC [µg/m³]", "AVO PM2.5 [µg/m³]"),
                ("AE33 BC vs AVO PM10", "ae33_bc", "avo_pm10", "AE33 BC [µg/m³]", "AVO PM10 [µg/m³]"),
                ("Fidas PM1 vs AE33 BC", "fidas_pm1", "ae33_bc", "Fidas PM1 [µg/m³]", "AE33 BC [µg/m³]"),
                ("Fidas PM2.5 vs AE33 BC", "fidas_pm25", "ae33_bc", "Fidas PM2.5 [µg/m³]", "AE33 BC [µg/m³]"),
                ("Fidas PM10 vs AE33 BC", "fidas_pm10", "ae33_bc", "Fidas PM10 [µg/m³]", "AE33 BC [µg/m³]"),
            ]
        )
    for pair in bc_pairs:
        if pair[1] in df.columns and pair[2] in df.columns:
            candidate_pairs.append(pair)

    pair_payloads: list[dict[str, object]] = []
    for pair_label, x_col, y_col, x_label, y_label in candidate_pairs:
        pair_df = df.select([x_col, y_col]).drop_nulls()
        if pair_df.height < 2:
            continue
        x_values = [float(v) for v in pair_df[x_col].to_list()]
        y_values = [float(v) for v in pair_df[y_col].to_list()]
        corr, slope, intercept = _compute_regression_stats(x_values, y_values)

        line_min = min(min(x_values), min(y_values))
        line_max = max(max(x_values), max(y_values))
        one_to_one = [line_min, line_max]

        x_line = None
        y_line = None
        if x_values and not math.isnan(slope) and not math.isnan(intercept):
            x_line = [min(x_values), max(x_values)]
            y_line = [slope * x + intercept for x in x_line]

        pair_payloads.append(
            {
                "label": pair_label,
                "x_values": x_values,
                "y_values": y_values,
                "x_line": x_line,
                "y_line": y_line,
                "one_to_one_x": one_to_one,
                "one_to_one_y": one_to_one,
                "x_label": x_label,
                "y_label": y_label,
                "corr": corr,
                "slope": slope,
                "intercept": intercept,
                "n": pair_df.height,
                "annotation": correlation_annotation_text(pair_df.height, corr, slope, intercept),
            }
        )

    if not pair_payloads:
        log("No non-empty column pairs found for correlation plotting; skipping correlation HTML.", enabled=verbose)
        return None

    fig = go.Figure()
    trace_groups: list[str] = []
    for index, payload in enumerate(pair_payloads):
        is_visible = index == 0
        label = str(payload["label"])
        fig.add_trace(
            go.Scatter(
                x=payload["x_values"],
                y=payload["y_values"],
                mode="markers",
                name=f"{label} data",
                visible=is_visible,
                hovertemplate=f"{payload['x_label']}: %{{x:.3f}}<br>{payload['y_label']}: %{{y:.3f}}<extra></extra>",
            )
        )
        trace_groups.append(label)

        fig.add_trace(
            go.Scatter(
                x=payload["one_to_one_x"],
                y=payload["one_to_one_y"],
                mode="lines",
                name=f"{label} 1:1",
                line={"dash": "dot"},
                visible=is_visible,
                hoverinfo="skip",
            )
        )
        trace_groups.append(label)

        if payload["x_line"] is not None and payload["y_line"] is not None:
            fig.add_trace(
                go.Scatter(
                    x=payload["x_line"],
                    y=payload["y_line"],
                    mode="lines",
                    name=f"{label} fit",
                    visible=is_visible,
                    hoverinfo="skip",
                )
            )
            trace_groups.append(label)

    buttons: list[dict[str, object]] = []
    for payload in pair_payloads:
        label = str(payload["label"])
        buttons.append(
            {
                "label": label,
                "method": "update",
                "args": [
                    {"visible": [group == label for group in trace_groups]},
                    {
                        "title": {"text": f"{plot_title}<br><sup>Correlation: {label}</sup>"},
                        "xaxis": {
                            "title": {"text": str(payload["x_label"]), "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
                            "tickfont": {"size": PLOT_FONT_SIZES["tick"]},
                        },
                        "yaxis": {
                            "title": {"text": str(payload["y_label"]), "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
                            "tickfont": {"size": PLOT_FONT_SIZES["tick"]},
                            "scaleanchor": "x",
                            "scaleratio": 1,
                        },
                        "annotations": [
                            {
                                "text": str(payload["annotation"]),
                                "xref": "paper",
                                "yref": "paper",
                                "x": 0.02,
                                "y": 0.98,
                                "showarrow": False,
                                "align": "left",
                                "bgcolor": "rgba(255,255,255,0.85)",
                                "bordercolor": "rgba(0,0,0,0.25)",
                                "font": {"size": PLOT_FONT_SIZES["annotation"]},
                            }
                        ],
                    },
                ],
            }
        )

    first = pair_payloads[0]
    fig.update_layout(
        title={"text": f"{plot_title}<br><sup>Correlation: {first['label']}</sup>", "font": {"size": PLOT_FONT_SIZES["title"]}},
        xaxis={
            "title": {"text": str(first["x_label"]), "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
            "tickfont": {"size": PLOT_FONT_SIZES["tick"]},
        },
        yaxis={
            "title": {"text": str(first["y_label"]), "font": {"size": PLOT_FONT_SIZES["axis_title"]}},
            "tickfont": {"size": PLOT_FONT_SIZES["tick"]},
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        updatemenus=[
            {
                "type": "dropdown",
                "x": 1.02,
                "y": 1.0,
                "showactive": True,
                "font": {"size": PLOT_FONT_SIZES["menu"]},
                "buttons": buttons,
            }
        ],
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0.0,
            "font": {"size": PLOT_FONT_SIZES["legend"]},
        },
        annotations=[
            {
                "text": str(first["annotation"]),
                "xref": "paper",
                "yref": "paper",
                "x": 0.02,
                "y": 0.98,
                "showarrow": False,
                "align": "left",
                "bgcolor": "rgba(255,255,255,0.85)",
                "bordercolor": "rgba(0,0,0,0.25)",
                "font": {"size": PLOT_FONT_SIZES["annotation"]},
            }
        ],
        margin={"t": 120},
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_html), include_plotlyjs="cdn")
    elapsed = time.perf_counter() - start
    log(f"Interactive correlation plot written: {output_html} (elapsed={elapsed:.1f}s)", enabled=verbose)
    return output_html

def write_outputs(
    df: pl.DataFrame,
    output_dir: Path,
    write_csv: bool,
    plot_channels: list[str],
    *,
    plot_title: str,
    verbose: bool = True,
) -> tuple[Path, Path | None, Path | None, Path | None]:
    """Write merged parquet/CSV/HTML outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "nrb_pm_hourly_comparison.parquet"
    csv_path = output_dir / "nrb_pm_hourly_comparison.csv" if write_csv else None
    html_path = output_dir / "nrb_pm_hourly_comparison.html"
    corr_html_path = output_dir / "nrb_pm_hourly_correlation.html"

    log(f"Writing merged parquet: {parquet_path}", enabled=verbose)
    df.write_parquet(parquet_path)
    if csv_path is not None:
        log(f"Writing merged CSV: {csv_path}", enabled=verbose)
        df.write_csv(csv_path)

    build_plot(df=df, output_html=html_path, plot_channels=plot_channels, plot_title=plot_title, verbose=verbose)
    corr_written = build_correlation_plot(df=df, output_html=corr_html_path, plot_title=plot_title, verbose=verbose)
    return parquet_path, csv_path, html_path, corr_written

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="mch-nrb.yml", type=Path, help="Path to the YAML config file.")
    parser.add_argument(
        "--level1-root",
        type=Path,
        default=None,
        help="Optional explicit path to the compiled level1/nrb directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory where merged data and plots will be written. "
            "Default: sibling level2/nrb directory beside the resolved level1/nrb root."
        ),
    )
    parser.add_argument(
        "--plot-columns",
        nargs="+",
        default=list(CHANNELS),
        help="Logical channels to include in the interactive plot. Accepted aliases include pm2.5 and IR880.",
    )
    parser.add_argument(
        "--title",
        default="Regional GAW Station Nairobi (0-20008-0-NRB)",
        help="Plot title used for the interactive time-series and correlation plots.",
    )
    parser.add_argument(
        "--write-csv",
        action="store_true",
        help="Also write a CSV copy of the merged hourly dataset.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=True,
        help="Emit timestamped progress messages. This is enabled by default.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages and only print errors.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1,
        help="During parquet reads, print progress every N files. Default: 1.",
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    """Run the hourly comparison workflow."""
    args = parse_args(argv)
    args.plot_columns = normalize_plot_columns(args.plot_columns)
    verbose = bool(args.verbose and not args.quiet)
    args.plot_columns = normalize_requested_channels(args.plot_columns)

    overall_start = time.perf_counter()
    log("Starting hourly AVO/Fidas/AE31/AE33 comparison workflow ...", enabled=verbose)
    log(f"Config file : {args.config}", enabled=verbose)
    if args.level1_root is not None:
        log(f"Level1 root : {args.level1_root}", enabled=verbose)
    log(
        f"Output dir  : {args.output_dir if args.output_dir is not None else '[auto: level2 sibling of level1 root]'}",
        enabled=verbose,
    )
    log(f"Plot columns: {', '.join(args.plot_columns)}", enabled=verbose)
    log(f"Plot title  : {args.title}", enabled=verbose)

    log("Loading YAML configuration ...", enabled=verbose)
    config = load_config(args.config)

    log("Discovering compiled parquet root ...", enabled=verbose)
    level1_root = discover_level1_root(config=config, explicit_root=args.level1_root)
    log(f"Using compiled parquet root: {level1_root}", enabled=verbose)

    if args.output_dir is None:
        args.output_dir = default_output_dir_from_level1(level1_root)
        log(f"Resolved output dir from level1 root: {args.output_dir}", enabled=verbose)

    log("Discovering parquet files ...", enabled=verbose)
    avo_paths = discover_parquet_files(level1_root, "avo-hourly.parquet")
    fidas_paths = discover_parquet_files(level1_root, "fidas.parquet")
    ae31_paths = discover_parquet_files(level1_root, "ae31.parquet")
    ae33_paths = discover_parquet_files(level1_root, "ae33.parquet")

    if not avo_paths:
        raise FileNotFoundError(f"No AVO hourly parquet files found below {level1_root}")
    if not fidas_paths:
        raise FileNotFoundError(f"No Fidas parquet files found below {level1_root}")

    log(f"Found {len(avo_paths)} AVO hourly parquet file(s)", enabled=verbose)
    log(f"Found {len(fidas_paths)} Fidas parquet file(s)", enabled=verbose)
    log(f"Found {len(ae31_paths)} AE31 parquet file(s)", enabled=verbose)
    log(f"Found {len(ae33_paths)} AE33 parquet file(s)", enabled=verbose)

    avo_df = read_parquet_collection(avo_paths, "AVO", verbose=verbose, progress_every=max(1, args.progress_every))
    fidas_df = read_parquet_collection(fidas_paths, "Fidas", verbose=verbose, progress_every=max(1, args.progress_every))
    ae31_df = read_parquet_collection(ae31_paths, "AE31", verbose=verbose, progress_every=max(1, args.progress_every))
    ae33_df = read_parquet_collection(ae33_paths, "AE33", verbose=verbose, progress_every=max(1, args.progress_every))

    avo_hourly, avo_meta = prepare_avo_hourly(avo_df, channels=("pm1", "pm25", "pm10"), verbose=verbose)
    fidas_hourly, fidas_meta = aggregate_hourly(
        fidas_df,
        instrument="fidas",
        channels=("pm1", "pm25", "pm10"),
        verbose=verbose,
    )
    ae31_hourly, ae31_meta = aggregate_hourly(ae31_df, instrument="ae31", channels=("bc",), verbose=verbose)
    ae33_hourly, ae33_meta = aggregate_hourly(ae33_df, instrument="ae33", channels=("bc",), verbose=verbose)

    if avo_hourly.is_empty():
        raise RuntimeError(f"Could not extract PM channels from AVO hourly data. Available AVO columns: {summarize_columns(avo_df)}")
    if fidas_hourly.is_empty():
        raise RuntimeError(f"Could not extract PM channels from Fidas data. Available Fidas columns: {summarize_columns(fidas_df)}")

    merged = merge_on_dtm([avo_hourly, fidas_hourly, ae31_hourly, ae33_hourly], verbose=verbose)
    if merged.is_empty():
        raise RuntimeError("Merged output is empty.")

    plot_channels = [channel for channel in args.plot_columns if any(col.endswith(f"_{channel}") for col in merged.columns)]
    if not plot_channels:
        raise RuntimeError("None of the requested plot columns were found in the merged data.")

    parquet_path, csv_path, html_path, corr_html_path = write_outputs(
        df=merged,
        output_dir=args.output_dir,
        write_csv=args.write_csv,
        plot_channels=plot_channels,
        plot_title=args.title,
        verbose=verbose,
    )

    log("Selected columns:", enabled=verbose)
    log(f"  AVO   : {avo_meta}", enabled=verbose)
    log(f"  Fidas : {fidas_meta}", enabled=verbose)
    log(f"  AE31  : {ae31_meta}", enabled=verbose)
    log(f"  AE33  : {ae33_meta}", enabled=verbose)
    log(f"Wrote parquet: {parquet_path}", enabled=verbose)
    if csv_path is not None:
        log(f"Wrote CSV    : {csv_path}", enabled=verbose)
    log(f"Wrote plot   : {html_path}", enabled=verbose)
    if corr_html_path is not None:
        log(f"Wrote corr   : {corr_html_path}", enabled=verbose)
    elapsed = time.perf_counter() - overall_start
    log(f"Workflow complete. Total elapsed time: {elapsed:.1f}s", enabled=verbose)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr, flush=True)
        raise
