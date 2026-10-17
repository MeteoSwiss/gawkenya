"""Backfill monthly TAHMO Level-1 Parquet from ZENTRA batch-download exports.

Input: a ZIP containing one or several sets of calibrated ``Configuration N``
CSV plus ``Raw-Configuration N`` CSV (and optional ``Metadata`` CSV), or a
folder of ZIPs. Nested ZIPs and extracted CSV sets are supported. The raw CSV
supplies the per-record UTC offset and Device RID; its *raw sensor values*
are never used as calibrated measurements.

Calibrated columns/units (unchanged):
 air_temperature °C; atmospheric_pressure kPa; battery_percent %;
 battery_voltage mV; gust_speed m/s; lightning_activity (unitless);
 lightning_distance km; logger_temperature °C; max_precip_rate mm/h;
 precipitation_amount mm; rh_sensor_temp °C; reference_pressure kPa;
 solar_radiation W/m²; vpd kPa; vapor_pressure kPa; wind_direction °;
 wind_speed m/s; x_axis_level °; y_axis_level °.

The CLI defaults to MKN's historical Configuration 7, starts on 2023-10-01
(UTC) and omits records tagged ``UTC+00:00`` as requested for the installation
period. Other configurations are skipped *before parsing*, so their different
sensor/header layouts and ``Not Set`` offsets do not interfere. The exclusions
are logged and counted. The BatchBackfill Python API remains general-purpose
unless these filters are passed explicitly.

Raw CSV ``UTC Offset`` values may be ``Not Set`` in other exports. Those
records still require an explicit, verified ``--utc-offset`` fallback; a real
raw offset must match the provided fallback unless the record is explicitly
excluded. Unknown offsets are never assumed to mean UTC or automatically
inferred from neighboring records.

The batch-download format has NO source ``error_flag`` field: newly backfilled
``<parameter>_err`` is null (unknown), not fabricated as 0/1. For a *new*
timestamp ``f_<parameter>`` is 0 for a present value and 1 if absent;
existing manually editable ``f_*`` and existing source ``*_err`` values are
NEVER overwritten. ``Device RID`` is stored as ``device_rid`` and is NOT a
ZENTRA ``mrid``. The existing ``mrid`` field is preserved on overlap.

By default only missing measurement values are filled. ``--replace-values``
replaces existing non-null measurements where the batch download provides a
non-null value, but retains existing QC flags and source errors. Existing
unrelated columns (including manually added fields) are retained. All writes
are atomic at individual monthly-Parquet-file granularity. Run in dry-run
mode first; pass ``--write`` to modify files. Large ZIPs are read as streams
in configurable row batches, rather than inflated into RAM.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import re
import shutil
import tempfile
from collections import defaultdict
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterator
from zipfile import ZipFile, ZipInfo

import polars as pl
import yaml

LOGGER = logging.getLogger("tahmo_backfill")

# Source-variable-to-native-unit mapping, used to validate column headers.
# Full ZENTRA downloads may spell °C as degree_C, ° as degrees, and W/m²
# as W/m2. _normal_header accepts those known unit synonyms only.
# Level-1 names come from config/mch-mkn.yml; no unit conversions are applied.
SOURCE_UNITS: dict[str, str] = {
    "Air Temperature": "°C",
    "Atmospheric Pressure": "kPa",
    "Battery Percent": "%",
    "Battery Voltage": "mV",
    "Gust Speed": "m/s",
    "Lightning Activity": "",
    "Lightning Distance": "km",
    "Logger Temperature": "°C",
    "Max Precip Rate": "mm/h",
    "Precipitation": "mm",
    "RH Sensor Temp": "°C",
    "Reference Pressure": "kPa",
    "Solar Radiation": "W/m²",
    "VPD": "kPa",
    "Vapor Pressure": "kPa",
    "Wind Direction": "°",
    "Wind Speed": "m/s",
    "X-axis Level": "°",
    "Y-axis Level": "°",
}

_CONFIG_FILE = re.compile(
    r"^(?P<base>.+?)-(?P<raw>Raw-)?Configuration\s+"
    r"(?P<configuration>\d+)-(?P<stamp>\d+(?:\.\d+)?)\.csv$",
    re.IGNORECASE,
)
_OFFSET = re.compile(r"^UTC(?P<sign>[+-])(?P<hours>\d{1,2}):(?P<minutes>\d{2})$")


# ZENTRA's CSV export varies between symbolic and ASCII unit spelling.
# These are spelling aliases only: no conversion of values or units occurs.
# Match whole unit prefixes, never substrings in the measurement name.
_CALIBRATED_UNIT_ALIASES: dict[str, str] = {
    "degree_C": "°C",
    "degrees": "°",
    "W/m2": "W/m²",
}


def _normal_header(value: str) -> str:
    """Normalize whitespace and known ZENTRA *unit spellings* in headers.

    ``degree_C Air Temperature`` and ``°C Air Temperature`` refer to the
    same native-unit variable. Unexpected units and variable names remain
    distinct and are rejected by ``_source_column_indices``.
    """
    header = " ".join(value.strip().replace("\u00a0", " ").split())
    for alias, canonical in _CALIBRATED_UNIT_ALIASES.items():
        prefix = f"{alias} "
        if header.startswith(prefix):
            return f"{canonical} {header[len(prefix):]}"
    return header


def _parse_offset(value: str) -> timezone:
    match = _OFFSET.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Invalid UTC Offset {value!r}; expected UTC+03:00, etc.")
    hour = int(match["hours"])
    minute = int(match["minutes"])
    if hour > 14 or minute > 59 or (hour == 14 and minute != 0):
        raise ValueError(f"Out-of-range UTC Offset {value!r}")
    delta = timedelta(hours=hour, minutes=minute)
    if match["sign"] == "-":
        delta = -delta
    return timezone(delta)


def _header(reader: Iterator[list[str]], label: str) -> tuple[list[str], str, int | None]:
    """Return third-row column labels, first-row device id, claimed count."""
    try:
        device = next(reader)[0].strip().lstrip("\ufeff")
        second = next(reader)
        names = [_normal_header(x) for x in next(reader)]
    except (StopIteration, IndexError) as exc:
        raise ValueError(f"{label}: expected three header rows") from exc
    match = re.search(r"# Records:\s*(\d+)", second[0]) if second else None
    return names, device, int(match[1]) if match else None


def _source_column_indices(headers: list[str], mapping: dict[str, str]) -> dict[str, int]:
    normalized = [_normal_header(header) for header in headers]
    expected = {
        _normal_header(f"{SOURCE_UNITS[name]} {name}"): column
        for name, column in mapping.items()
    }
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate calibrated CSV column headers")
    unknown = set(normalized) - {"Timestamps"} - set(expected)
    missing = set(expected) - set(normalized)
    if unknown or missing:
        raise ValueError(f"Calibrated CSV header mismatch: unknown={sorted(unknown)}; missing={sorted(missing)}")
    if normalized.count("Timestamps") != 1:
        raise ValueError("Missing/duplicated Timestamps header")
    return {column: normalized.index(header) for header, column in expected.items()}


def _parse_number(raw: str, column: str, n: int) -> float | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Record {n}: bad {column} number {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Record {n}: nonfinite {column} number {value!r}")
    return parsed


def iter_calibrated_rows(
    calibrated: BinaryIO,
    raw: BinaryIO | None,
    *,
    variable_map: dict[str, str],
    device_sn: str,
    explicit_utc_offset: str | None = None,
    start_date: date | None = None,
    skip_utc_offsets: frozenset[timezone] = frozenset(),
    skip_counts: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream one calibrated/raw CSV pair as wide UTC measurement records.

    Raw CSV is used only for timezone and device_rid; never for measurements.
    Offset and UTC-date filters apply before decoding measured values. Record
    count and raw/calibrated timestamp matching still validate the full CSV.
    When the raw CSV is missing, or its UTC Offset field is blank/Not Set,
    an explicitly supplied, verified offset is mandatory. Explicit raw offsets
    must agree with it when supplied, except for expressly excluded records.
    """
    with ExitStack() as stack:
        calibrated_text = stack.enter_context(TextIOWrapper(calibrated, encoding="utf-8-sig", newline=""))
        decoded_reader = csv.reader(calibrated_text)
        decoded_headers, device, decoded_claim = _header(decoded_reader, "Calibrated")
        if device != device_sn:
            raise ValueError(f"Unexpected calibrated device {device!r}; expected {device_sn!r}")
        locations = _source_column_indices(decoded_headers, variable_map)
        dtm_index = decoded_headers.index("Timestamps")
        raw_reader = None
        raw_claim = None
        raw_timestamp_index = raw_offset_index = raw_rid_index = -1
        if raw is not None:
            raw_text = stack.enter_context(TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            raw_reader = csv.reader(raw_text)
            raw_headers, raw_device, raw_claim = _header(raw_reader, "Raw")
            if raw_device != device_sn:
                raise ValueError(f"Unexpected raw device {raw_device!r}")
            for field in ("Timestamps", "Device RID", "UTC Offset"):
                if raw_headers.count(field) != 1:
                    raise ValueError(f"Raw CSV must contain exactly one {field!r} header")
            raw_timestamp_index = raw_headers.index("Timestamps")
            raw_offset_index = raw_headers.index("UTC Offset")
            raw_rid_index = raw_headers.index("Device RID")
        elif explicit_utc_offset is None:
            raise ValueError("Raw CSV is missing; supply --utc-offset explicitly")

        fixed_offset = _parse_offset(explicit_utc_offset) if explicit_utc_offset else None
        fallback_reported = False
        count = 0
        for count, decoded in enumerate(decoded_reader, start=1):
            if len(decoded) != len(decoded_headers):
                raise ValueError(f"Calibrated record {count}: expected {len(decoded_headers)} fields, got {len(decoded)}")
            local_text = decoded[dtm_index].strip()
            device_rid: int | None = None
            if raw_reader is not None:
                try:
                    raw_row = next(raw_reader)
                except StopIteration as exc:
                    raise ValueError(f"Raw CSV ends before calibrated record {count}") from exc
                if len(raw_row) != len(raw_headers):
                    raise ValueError(f"Raw record {count}: expected {len(raw_headers)} fields, got {len(raw_row)}")
                if raw_row[raw_timestamp_index].strip() != local_text:
                    raise ValueError(f"Record {count}: calibrated/raw timestamps do not match")
                raw_offset = raw_row[raw_offset_index].strip()
                if not raw_offset or raw_offset.casefold() == "not set":
                    if fixed_offset is None:
                        raise ValueError(
                            f"Record {count} ({local_text}): raw UTC Offset "
                            f"{raw_offset!r} is unset; supply --utc-offset "
                            "only after verifying the source timestamps' timezone"
                        )
                    offset = fixed_offset
                    if not fallback_reported:
                        LOGGER.warning(
                            "Raw UTC Offset is %r starting at record %d (%s); "
                            "using verified --utc-offset %s for unset offsets in this CSV",
                            raw_offset, count, local_text, explicit_utc_offset,
                        )
                        fallback_reported = True
                else:
                    offset = _parse_offset(raw_offset)
                    if offset in skip_utc_offsets:
                        if skip_counts is not None:
                            skip_counts["skipped_utc_offset"] = skip_counts.get("skipped_utc_offset", 0) + 1
                        continue
                    if fixed_offset is not None and offset != fixed_offset:
                        raise ValueError(
                            f"Record {count} ({local_text}): raw UTC Offset "
                            f"{raw_offset!r} disagrees with --utc-offset"
                        )
                raw_rid = raw_row[raw_rid_index].strip()
                device_rid = int(raw_rid) if raw_rid else None
            else:
                assert fixed_offset is not None
                offset = fixed_offset
            if offset in skip_utc_offsets:
                if skip_counts is not None:
                    skip_counts["skipped_utc_offset"] = skip_counts.get("skipped_utc_offset", 0) + 1
                continue
            try:
                local = datetime.strptime(local_text, "%Y/%m/%d %H:%M:%S")
            except ValueError as exc:
                raise ValueError(f"Record {count}: bad local timestamp {local_text!r}") from exc
            dtm = local.replace(tzinfo=offset).astimezone(timezone.utc)
            if start_date is not None and dtm.date() < start_date:
                if skip_counts is not None:
                    skip_counts["skipped_before_start"] = skip_counts.get("skipped_before_start", 0) + 1
                continue
            row: dict[str, Any] = {
                "dtm": dtm,
                "device_sn": device_sn,
                "mrid": None,       # distinct from Device RID
                "device_rid": device_rid,
            }
            for column, index in locations.items():
                value = _parse_number(decoded[index], column, count)
                row[column] = value
                row[f"{column}_err"] = None  # download contains no Boolean source error flag
                row[f"f_{column}"] = int(value is None)
            yield row

        if decoded_claim is not None and count != decoded_claim:
            raise ValueError(f"Calibrated CSV claims {decoded_claim} records; got {count}")
        if raw_reader is not None:
            if next(raw_reader, None) is not None:
                raise ValueError("Raw CSV has extra records")
            if raw_claim is not None and count != raw_claim:
                raise ValueError(f"Raw CSV claims {raw_claim} records; got {count}")


def _expected_schema(variable_map: dict[str, str]) -> dict[str, pl.DataType]:
    schema: dict[str, pl.DataType] = {
        "dtm": pl.Datetime("us", "UTC"),
        "device_sn": pl.String,
        "mrid": pl.Int64,
        "device_rid": pl.Int64,
    }
    for variable in variable_map.values():
        schema[variable] = pl.Float64
        schema[f"{variable}_err"] = pl.Int8
        schema[f"f_{variable}"] = pl.Int8
    return schema


def _merge_partition(
    rows: list[dict[str, Any]],
    *,
    path: Path,
    schema: dict[str, pl.DataType],
    variables: list[str],
    replace_values: bool,
) -> tuple[int, int, int]:
    """Atomically merge one chunk. Returns new rows, filled, replaced cells."""
    existing = pl.read_parquet(path) if path.exists() else None
    combined: dict[datetime, dict[str, Any]] = {}
    if existing is not None:
        for row in existing.iter_rows(named=True):
            timestamp = row["dtm"]
            if timestamp in combined:
                raise ValueError(f"Existing duplicate dtm at {path}: {timestamp}")
            if row.get("device_sn") not in (None, rows[0]["device_sn"]):
                raise ValueError(f"Unexpected device_sn in {path}: {row['device_sn']}")
            combined[timestamp] = row
    added = filled = replaced = metadata_filled = 0
    for incoming in rows:
        stamp = incoming["dtm"]
        current = combined.get(stamp)
        if current is None:
            combined[stamp] = incoming.copy()
            added += 1
            continue
        for variable in variables:
            value = incoming[variable]
            prior = current.get(variable)
            if value is not None and (prior is None or (replace_values and prior != value)):
                current[variable] = value
                if prior is None:
                    filled += 1
                else:
                    replaced += 1
            # Never overwrite f_<variable> or <variable>_err for existing rows.
            qc_key = f"f_{variable}"
            if qc_key not in current:
                current[qc_key] = int(current.get(variable) is None)
            current.setdefault(f"{variable}_err", None)
        for key in ("device_sn", "device_rid"):
            if current.get(key) is None and incoming.get(key) is not None:
                current[key] = incoming[key]
                metadata_filled += 1
        current.setdefault("mrid", None)

    target_schema = dict(existing.schema) if existing is not None else {}
    for column, dtype in schema.items():
        if column not in target_schema or target_schema[column] == pl.Null:
            target_schema[column] = dtype
    schema_change = existing is not None and target_schema != dict(existing.schema)
    updated = added > 0 or filled > 0 or replaced > 0 or metadata_filled > 0 or schema_change
    if not updated:
        return 0, 0, 0
    frame = pl.DataFrame(list(combined.values()), schema=target_schema, strict=False).sort("dtm")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tahmo-backfill-", suffix=".parquet", dir=path.parent)
    os.close(fd)
    try:
        frame.write_parquet(temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return added, filled, replaced


class BatchBackfill:
    """Use bounded-size batches to backfill data without inflating large ZIPs."""

    def __init__(
        self,
        config: dict[str, Any],
        target_root: Path,
        *,
        write: bool,
        replace_values: bool = False,
        batch_rows: int = 5000,
        utc_offset: str | None = None,
        configuration: int | None = None,
        start_date: date | None = None,
        skip_utc_offsets: tuple[str, ...] = (),
    ) -> None:
        self.device_sn = str(config["device_sn"])
        self.variable_map = dict(config["variables"])
        if set(self.variable_map) != set(SOURCE_UNITS):
            raise ValueError("Configured TAHMO variables do not match supported calibrated export variables")
        if len(self.variable_map) != len(set(self.variable_map.values())):
            raise ValueError("TAHMO output variable names must be unique")
        self.target_root = target_root
        self.write = write
        self.replace_values = replace_values
        self.batch_rows = batch_rows
        if batch_rows < 1:
            raise ValueError("batch_rows must be positive")
        self.utc_offset = utc_offset
        if configuration is not None and configuration < 1:
            raise ValueError("configuration must be a positive integer")
        self.configuration = configuration
        self.start_date = start_date
        self.skip_utc_offsets = frozenset(_parse_offset(v) for v in skip_utc_offsets)
        self.schema = _expected_schema(self.variable_map)
        self.stats = defaultdict(int)
        self.touched: set[str] = set()

    def _ingest(self, readings: Iterator[dict[str, Any]], source_label: str) -> None:
        batch: list[dict[str, Any]] = []
        first = last = None
        count = 0
        try:
            self._ingest_stream(readings, source_label, batch, first, last, count)
        except ValueError as exc:
            raise ValueError(f"{source_label}: {exc}") from exc

    def _ingest_stream(
        self,
        readings: Iterator[dict[str, Any]],
        source_label: str,
        batch: list[dict[str, Any]],
        first: datetime | None,
        last: datetime | None,
        count: int,
    ) -> None:
        for reading in readings:
            stamp = reading["dtm"]
            first = stamp if first is None else min(first, stamp)
            last = stamp if last is None else max(last, stamp)
            batch.append(reading)
            count += 1
            if len(batch) >= self.batch_rows:
                self._flush(batch)
                batch = []
        if batch:
            self._flush(batch)
        LOGGER.info("%s: %d readings, UTC %s to %s", source_label, count, first, last)
        self.stats["exports"] += 1
        self.stats["input_rows"] += count

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        by_month: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for reading in batch:
            date = reading["dtm"]
            by_month[(date.year, date.month)].append(reading)
        for (year, month), monthly in by_month.items():
            target = self.target_root / f"{year:04d}" / f"{month:02d}" / "tahmo.parquet"
            self.touched.add(str(target))
            if self.write:
                added, filled, replaced = _merge_partition(
                    monthly, path=target, schema=self.schema,
                    variables=list(self.variable_map.values()),
                    replace_values=self.replace_values,
                )
                self.stats["new_rows"] += added
                self.stats["filled_values"] += filled
                self.stats["replaced_values"] += replaced
            else:
                LOGGER.info("WOULD merge %d candidate timestamps -> %s", len(monthly), target)

    def process_zip(self, path: Path, *, depth: int = 0) -> None:
        if depth > 2:
            raise ValueError(f"Nested ZIP depth exceeds limit: {path}")
        with ZipFile(path) as archive:
            self._process_zip_members(archive, label=str(path), depth=depth)

    def _process_zip_members(self, archive: ZipFile, *, label: str, depth: int) -> None:
        groups: dict[tuple[str, str, str, str], dict[str, ZipInfo]] = defaultdict(dict)
        nested: list[ZipInfo] = []
        for member in archive.infolist():
            if member.is_dir():
                continue
            basename = PurePosixPath(member.filename).name
            match = _CONFIG_FILE.fullmatch(basename)
            if match:
                key = (str(PurePosixPath(member.filename).parent), match["base"], match["configuration"], match["stamp"])
                role = "raw" if match["raw"] else "calibrated"
                if role in groups[key]:
                    raise ValueError(f"Duplicate {role} member in {label}: {basename}")
                groups[key][role] = member
            elif basename.lower().endswith(".zip") and not basename.startswith("__MACOSX"):
                nested.append(member)
        if not groups and not nested:
            raise ValueError(f"No calibrated TAHMO export found in {label}")
        for key, group in sorted(groups.items()):
            if self.configuration is not None and int(key[2]) != self.configuration:
                self.stats["skipped_configurations"] += 1
                continue
            if "calibrated" not in group:
                # Orphan raw export is not useful without calibrated values.
                raise ValueError(f"Raw-only TAHMO export in {label}: {key}")
            with ExitStack() as stack:
                calibrated = stack.enter_context(archive.open(group["calibrated"]))
                raw = stack.enter_context(archive.open(group["raw"])) if "raw" in group else None
                source_label = f"{label}::{group['calibrated'].filename}"
                self._ingest(
                    iter_calibrated_rows(
                        calibrated, raw,
                        variable_map=self.variable_map,
                        device_sn=self.device_sn,
                        explicit_utc_offset=self.utc_offset,
                        start_date=self.start_date,
                        skip_utc_offsets=self.skip_utc_offsets,
                        skip_counts=self.stats,
                    ),
                    source_label,
                )
        # Nested ZIP bytes go to disk, never memory. Remove each after processing.
        for member in nested:
            fd, tmp = tempfile.mkstemp(prefix="tahmo-inner-", suffix=".zip")
            os.close(fd)
            try:
                with archive.open(member) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                self.process_zip(Path(tmp), depth=depth + 1)
            finally:
                Path(tmp).unlink(missing_ok=True)

    def process_directory(self, path: Path) -> None:
        zipped = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".zip")
        for candidate in zipped:
            self.process_zip(candidate)
        # Also support extracted sets of CSVs under the source directory.
        csv_groups: dict[tuple[Path, str, str, str], dict[str, Path]] = defaultdict(dict)
        for candidate in sorted(path.rglob("*.csv")):
            match = _CONFIG_FILE.fullmatch(candidate.name)
            if match:
                key = (candidate.parent, match["base"], match["configuration"], match["stamp"])
                role = "raw" if match["raw"] else "calibrated"
                if role in csv_groups[key]:
                    raise ValueError(f"Duplicate CSV source in {path}: {candidate}")
                csv_groups[key][role] = candidate
        for key, group in sorted(csv_groups.items()):
            if self.configuration is not None and int(key[2]) != self.configuration:
                self.stats["skipped_configurations"] += 1
                continue
            if "calibrated" not in group:
                raise ValueError(f"Raw-only TAHMO export: {key}")
            with ExitStack() as stack:
                decoded = stack.enter_context(group["calibrated"].open("rb"))
                raw = stack.enter_context(group["raw"].open("rb")) if "raw" in group else None
                self._ingest(iter_calibrated_rows(
                    decoded, raw, variable_map=self.variable_map,
                    device_sn=self.device_sn, explicit_utc_offset=self.utc_offset,
                    start_date=self.start_date,
                    skip_utc_offsets=self.skip_utc_offsets,
                    skip_counts=self.stats,
                ), str(group["calibrated"]))
        if not zipped and not csv_groups:
            raise ValueError(f"No TAHMO ZIP or CSV data in {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="ZENTRA batch ZIP or directory containing ZIPs/CSV sets")
    parser.add_argument("--target", type=Path, required=True, help="Level-1 station root, e.g. gawkenyadata/level1/mkn")
    parser.add_argument("--station-config", type=Path, default=Path("config/mch-mkn.yml"))
    parser.add_argument("--write", action="store_true", help="Actually write monthly Parquet files (otherwise validate/dry-run)")
    parser.add_argument("--replace-values", action="store_true", help="Replace existing measurements with non-null calibrated download values; retain flags")
    parser.add_argument(
        "--utc-offset", type=str,
        help="Verified offset for missing/Not Set raw UTC Offset (e.g. UTC+03:00); "
             "must match explicit raw offsets",
    )
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument(
        "--configuration", type=int, default=7,
        help="ZENTRA configuration to import (default: 7 for MKN)",
    )
    parser.add_argument(
        "--start-date", type=date.fromisoformat, default=date(2023, 10, 1),
        metavar="YYYY-MM-DD",
        help="Earliest UTC date to retain (default: 2023-10-01)",
    )
    parser.add_argument(
        "--skip-utc-offset", action="append", default=None, metavar="UTC+HH:MM",
        help="Exclude raw records tagged with this UTC offset (repeatable; default: UTC+00:00)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.replace_values and not args.write:
        parser.error("--replace-values requires --write")
    if not args.source.exists():
        parser.error(f"Source does not exist: {args.source}")
    config = yaml.safe_load(args.station_config.read_text(encoding="utf-8"))["tahmo"]
    backfill = BatchBackfill(
        config, args.target,
        write=args.write, replace_values=args.replace_values,
        batch_rows=args.batch_rows, utc_offset=args.utc_offset,
        configuration=args.configuration, start_date=args.start_date,
        skip_utc_offsets=tuple(args.skip_utc_offset if args.skip_utc_offset is not None else ["UTC+00:00"]),
    )
    LOGGER.info(
        "Filter: configuration=%d start_date_utc=%s skip_utc_offsets=%s",
        args.configuration, args.start_date,
        args.skip_utc_offset if args.skip_utc_offset is not None else ["UTC+00:00"],
    )
    if args.source.is_dir():
        backfill.process_directory(args.source)
    else:
        if args.source.suffix.lower() != ".zip":
            parser.error("A single --source file must be a ZIP; use a directory for extracted CSVs")
        backfill.process_zip(args.source)
    LOGGER.info(
        "%s: %d exports, %d accepted records, %d skipped configurations, "
        "%d skipped before cutoff, %d skipped by UTC offset, %d touched partitions, "
        "%d added timestamps, %d filled values, %d replaced values",
        "WROTE" if args.write else "DRY RUN",
        backfill.stats["exports"], backfill.stats["input_rows"],
        backfill.stats["skipped_configurations"],
        backfill.stats["skipped_before_start"], backfill.stats["skipped_utc_offset"],
        len(backfill.touched), backfill.stats["new_rows"],
        backfill.stats["filled_values"], backfill.stats["replaced_values"],
    )


if __name__ == "__main__":
    main()
