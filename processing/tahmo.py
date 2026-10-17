"""TAHMO ZENTRA long-table CSV/ZIP to monthly Level-1 Parquet.

Native measurement units (no conversions): air_temperature °C,
 atmospheric_pressure kPa, battery_percent %, battery_voltage mV,
 gust_speed m/s, lightning_activity dimensionless (as reported),
 lightning_distance km, logger_temperature °C, max_precip_rate mm/h,
 precipitation_amount mm, rh_sensor_temp °C, reference_pressure kPa,
 solar_radiation W/m², vpd kPa, vapor_pressure kPa,
 wind_direction degrees, wind_speed m/s, x_axis_level degrees,
 y_axis_level degrees.

``dtm`` is UTC. Each ``<column>_err`` is the source TAHMO error_flag
(0/1), or null when no reading was supplied. The separately editable
``f_<column>`` is initialized to 1 for source errors or absent values,
otherwise 0. Subsequent manual QC never changes the source error flag. Raw errors flagged by
TAHMO retain their numerical value, allowing later examination. Each output
row retains device_sn and mrid. Metadata warnings alone do not change flags.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import polars as pl


class TAHMO:
    """Compile TAHMO ZENTRA exports into month-partitioned Level-1 data."""

    def __init__(self, config: dict[str, Any], name: str = "tahmo") -> None:
        self.name = name
        self.variables: dict[str, str] = dict(config["variables"])
        self.device_sn = str(config["device_sn"])
        self.logger = logging.getLogger(name)
        if len(set(self.variables.values())) != len(self.variables):
            raise ValueError("TAHMO variable mappings must be one-to-one")
        if not all(re.fullmatch(r"[a-z][a-z0-9_]*", x) for x in self.variables.values()):
            raise ValueError("TAHMO target variables must use lowercase snake_case")

    def should_process_file(self, path: Path) -> bool:
        """Accept ZIP or CSV exports for the configured device only."""
        return bool(re.fullmatch(rf"tahmo-{re.escape(self.device_sn)}-mrid\d+-\d+(?:\(\d+\))?\.(?:zip|csv)", path.name, re.I))

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """Pivot all readings, retaining UTC timestamps, mrids and quality flags."""
        try:
            columns = list(self.variables.values())
            by_key: dict[tuple[int, str], tuple[int, float | None, int, int]] = {}
            mrids: dict[int, int] = {}
            if path.suffix.lower() == ".zip":
                with ZipFile(path) as archive:
                    members = [x for x in archive.namelist() if x.lower().endswith(".csv") and not x.endswith("/")]
                    if len(members) != 1:
                        raise ValueError("Expected exactly one CSV in TAHMO ZIP")
                    with archive.open(members[0]) as raw:
                        with TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                            self._collect(csv.DictReader(stream), by_key, mrids)
            else:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    self._collect(csv.DictReader(stream), by_key, mrids)
            if not by_key:
                raise ValueError("No recognized TAHMO measurements found")
            readings: dict[int, dict[str, Any]] = {}
            for (timestamp, variable), (_, value, flag, error) in by_key.items():
                item = readings.setdefault(timestamp, {"dtm": datetime.fromtimestamp(timestamp, tz=timezone.utc),
                                                       "device_sn": self.device_sn, "mrid": mrids[timestamp]})
                item[variable] = value
                item[f"f_{variable}"] = flag
                item[f"{variable}_err"] = error
            for item in readings.values():
                for name in columns:
                    item.setdefault(name, None)
                    item.setdefault(f"f_{name}", 1)
                    item.setdefault(f"{name}_err", None)
            schema: dict[str, pl.DataType] = {"dtm": pl.Datetime("us", "UTC"), "device_sn": pl.String, "mrid": pl.Int64}
            for name in columns:
                schema[name] = pl.Float64
                schema[f"f_{name}"] = pl.Int8
                schema[f"{name}_err"] = pl.Int8
            df = pl.DataFrame(list(readings.values()), schema=schema).sort("dtm")
            return df, None
        except Exception as exc:
            return pl.DataFrame(), f"{type(exc).__name__}: {exc}"

    def _collect(self, reader: csv.DictReader, by_key: dict, mrids: dict[int, int]) -> None:
        required = {"measurement", "device_sn", "timestamp_utc", "value", "mrid", "error_flag", "units"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Missing TAHMO CSV headers: {sorted(required - set(reader.fieldnames or []))}")
        expected_units = {
            "Air Temperature": "°C", "Atmospheric Pressure": "kPa", "Battery Percent": "%",
            "Battery Voltage": "mV", "Gust Speed": "m/s", "Lightning Activity": "",
            "Lightning Distance": "km", "Logger Temperature": "°C", "Max Precip Rate": "mm/h",
            "Precipitation": "mm", "RH Sensor Temp": "°C", "Reference Pressure": "kPa",
            "Solar Radiation": "W/m²", "VPD": "kPa", "Vapor Pressure": "kPa",
            "Wind Direction": "°", "Wind Speed": "m/s", "X-axis Level": "°", "Y-axis Level": "°",
        }
        for record in reader:
            if record["device_sn"].strip() != self.device_sn:
                raise ValueError(f"Unexpected device_sn: {record['device_sn']!r}")
            measurement = record["measurement"].strip()
            if measurement not in self.variables:
                raise ValueError(f"Unconfigured TAHMO measurement: {measurement!r}")
            actual_units = record["units"].strip()
            if measurement in expected_units and actual_units != expected_units[measurement]:
                raise ValueError(f"Unexpected unit for {measurement}: {actual_units!r}")
            ts = int(record["timestamp_utc"])
            mrid = int(record["mrid"])
            error = record["error_flag"].strip().lower()
            if error not in {"true", "false", "0", "1"}:
                raise ValueError(f"Invalid TAHMO error_flag: {error!r}")
            raw = record["value"].strip()
            value = float(raw) if raw else None
            source_error = int(error in {"true", "1"})
            flagged = int(source_error == 1 or value is None)
            var = self.variables[measurement]
            key = (ts, var)
            if key not in by_key or mrid > by_key[key][0]:
                by_key[key] = (mrid, value, flagged, source_error)
            elif mrid == by_key[key][0] and (value, flagged, source_error) != by_key[key][1:]:
                raise ValueError(f"Conflicting readings for {measurement}, timestamp {ts}, mrid {mrid}")
            mrids[ts] = max(mrids.get(ts, mrid), mrid)

    def compile_to_parquet(
        self,
        source: str | Path,
        target: str | Path,
        archive: str | Path | None = None,
        issues: str | Path | None = None,
        append_parquet: bool = True,
        split: str = "month",
    ) -> tuple[pl.DataFrame, dict[str, str]]:
        """Merge imports safely before archiving; supports historical overlap/retries."""
        if split != "month":
            raise ValueError("TAHMO supports monthly partitioning only")
        source = Path(source)
        target = Path(target)
        errors: dict[str, str] = {}
        result = pl.DataFrame()
        if not source.exists():
            return result, errors
        for path in sorted(source.rglob("*")):
            if not path.is_file() or not self.should_process_file(path):
                continue
            df, err = self.extract_to_dataframe(path)
            if err:
                errors[str(path)] = err
                self.logger.error("Invalid TAHMO source %s: %s", path, err)
                if issues is not None:
                    self._move(path, Path(issues) / path.relative_to(source))
                continue
            try:
                self._write(df, target, append_parquet)
            except Exception as exc:
                errors[str(path)] = str(exc)
                self.logger.exception("Could not save %s; keeping source in incoming", path)
                continue
            result = pl.concat([result, df], how="diagonal_relaxed") if not result.is_empty() else df
            if archive is not None:
                first = df["dtm"].min()
                dst = Path(archive) / f"{first.year:04d}" / f"{first.month:02d}" / path.name
                try:
                    self._move(path, dst)
                except OSError:
                    self.logger.warning("Parquet saved but could not archive %s", path)
        return result, errors

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # An identical repeated export should not overwrite its archived copy.
            if source.read_bytes() == destination.read_bytes():
                source.unlink()
                return
            raise FileExistsError(f"Archive name collision: {destination}")
        shutil.move(str(source), str(destination))

    def _write(self, df: pl.DataFrame, target: Path, append: bool) -> None:
        for keys, group in df.with_columns(
            pl.col("dtm").dt.year().alias("_year"),
            pl.col("dtm").dt.month().alias("_month"),
        ).group_by(["_year", "_month"]):
            year, month = keys
            path = target / f"{year:04d}" / f"{month:02d}" / f"{self.name}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            group = group.drop(["_year", "_month"])
            if append and path.exists():
                old = pl.read_parquet(path)
                # Older Level-1 files have f_* but no *_err columns.
                # Their original source error_flag cannot be reconstructed
                # reliably from an editable QC flag. Retain null for old rows
                # until source ZIPs are reprocessed or a newer MRID arrives.
                for variable in self.variables.values():
                    error_column = f"{variable}_err"
                    if error_column not in old.columns:
                        old = old.with_columns(
                            pl.lit(None, dtype=pl.Int8).alias(error_column)
                        )
                # Existing rows take priority at matching mrid (preserve interactive edits).
                # A strictly larger mrid represents a revised observation.
                incoming = group.with_columns(pl.lit(1).alias("_priority"))
                original = old.with_columns(pl.lit(0).alias("_priority"))
                combined = pl.concat([incoming, original], how="diagonal_relaxed")
                group = (combined.sort(["dtm", "mrid", "_priority"], descending=[False, True, False])
                         .unique(subset=["dtm"], keep="first", maintain_order=True)
                         .drop("_priority").sort("dtm"))
            fd, temporary = tempfile.mkstemp(prefix=".tahmo-", suffix=".parquet", dir=path.parent)
            os.close(fd)
            try:
                group.write_parquet(temporary, compression="zstd")
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.logger.info("Saved %s: %s readings", path, group.height)
