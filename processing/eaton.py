"""Eaton UPS one-minute ZIP/CSV exports to monthly Level-1 Parquet.

All source fields are preserved, including status labels and SNMP status codes.
Timestamps in the exports are UTC; Level-1 uses timezone-aware UTC values.
Editable f_* flags are initialized to 0 for populated numeric measurements and
1 for absent/invalid readings. Re-importing identical timestamps preserves any
manual corrections or quality flags already present in Level-1.
"""
from __future__ import annotations

import csv
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

from toolbox.utils import setup_logging


NUMERIC = (
    "output_source_code", "on_battery", "battery_status_code",
    "battery_voltage", "battery_capacity_pct", "battery_runtime_min",
    "seconds_on_battery", "input_voltage", "input_frequency",
    "output_voltage", "output_frequency", "output_load", "active_alarms",
)
TEXT = ("output_source", "battery_status")
COLUMNS = ("dtm", "output_source_code", "output_source", "on_battery",
           "battery_status_code", "battery_status", "battery_voltage",
           "battery_capacity_pct", "battery_runtime_min", "seconds_on_battery",
           "input_voltage", "input_frequency", "output_voltage",
           "output_frequency", "output_load", "active_alarms")
INTEGER = {"output_source_code", "on_battery", "battery_status_code",
           "battery_capacity_pct", "battery_runtime_min", "seconds_on_battery",
           "input_voltage", "output_voltage", "output_load", "active_alarms"}
NAME_RE = re.compile(r"eaton-(\d{10})\.(zip|csv)$", re.I)


class Eaton:
    """Process MKN Eaton UPS hourly exports, using the standard processor API."""

    def __init__(self, config: dict[str, Any] | None = None, name: str = "eaton") -> None:
        self.name = name
        self.config = config or {}
        self.logger = setup_logging(logger_name=name)

    def should_process_file(self, path: Path) -> bool:
        return NAME_RE.fullmatch(path.name) is not None

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """Read one hourly export. Return an error without destroying its source."""
        try:
            m = NAME_RE.fullmatch(path.name)
            if m is None:
                raise ValueError(f"Unexpected Eaton filename: {path.name}")
            start = datetime.strptime(m.group(1), "%Y%m%d%H").replace(tzinfo=timezone.utc)
            if path.suffix.lower() == ".zip":
                with ZipFile(path) as archive:
                    members = [x for x in archive.namelist() if x.lower().endswith(".csv") and not x.endswith("/")]
                    if len(members) != 1:
                        raise ValueError("Expected exactly one CSV in Eaton ZIP")
                    if Path(members[0]).name.lower() != f"{path.stem.lower()}.csv":
                        raise ValueError("Eaton ZIP inner CSV filename differs from outer ZIP")
                    with archive.open(members[0]) as raw:
                        with TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                            records = self._records(csv.DictReader(stream), start)
            else:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    records = self._records(csv.DictReader(stream), start)
            if not records:
                raise ValueError("Empty Eaton export")
            schema: dict[str, pl.DataType] = {"dtm": pl.Datetime("us", "UTC")}
            schema.update({name: pl.String for name in TEXT})
            schema.update({name: (pl.Int64 if name in INTEGER else pl.Float64) for name in NUMERIC})
            schema.update({f"f_{name}": pl.Int8 for name in NUMERIC})
            return pl.DataFrame(records, schema=schema).sort("dtm"), None
        except Exception as exc:
            return pl.DataFrame(), f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _records(reader: csv.DictReader, start: datetime) -> list[dict[str, Any]]:
        if not reader.fieldnames or set(reader.fieldnames) != set(COLUMNS):
            raise ValueError(f"Unexpected Eaton columns: {reader.fieldnames!r}")
        out: list[dict[str, Any]] = []
        seen: set[datetime] = set()
        for record in reader:
            dtm = datetime.strptime(record["dtm"].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if dtm.strftime("%Y%m%d%H") != start.strftime("%Y%m%d%H"):
                raise ValueError(f"Timestamp outside source filename hour: {dtm}")
            if dtm in seen:
                raise ValueError(f"Duplicate timestamp in Eaton export: {dtm}")
            seen.add(dtm)
            item: dict[str, Any] = {"dtm": dtm}
            for name in TEXT:
                item[name] = record[name].strip() or None
            for name in NUMERIC:
                raw = record[name].strip()
                if not raw:
                    item[name] = None
                    item[f"f_{name}"] = 1
                    continue
                value = float(raw)
                if not (-float("inf") < value < float("inf")):
                    raise ValueError(f"Nonfinite Eaton value for {name}: {raw!r}")
                if name in INTEGER:
                    if not value.is_integer():
                        raise ValueError(f"Nonintegral value for {name}: {raw!r}")
                    item[name] = int(value)
                else:
                    item[name] = value
                item[f"f_{name}"] = 0
            out.append(item)
        return out

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if source.read_bytes() == destination.read_bytes():
                source.unlink()
                return
            raise FileExistsError(f"Archive name collision: {destination}")
        shutil.move(str(source), str(destination))

    def _write(self, frame: pl.DataFrame, target: Path, append: bool) -> dict[Path, int]:
        output: dict[Path, int] = {}
        for (year, month), part in frame.with_columns(
            pl.col("dtm").dt.year().alias("_year"),
            pl.col("dtm").dt.month().alias("_month"),
        ).group_by(["_year", "_month"]):
            path = target / f"{year:04d}" / f"{month:02d}" / f"{self.name}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            part = part.drop("_year", "_month")
            old_rows = 0
            if append and path.exists():
                old = pl.read_parquet(path)
                old_rows = old.height
                # Existing records take precedence so manually edited flags survive.
                combined = pl.concat([
                    old.with_columns(pl.lit(0).alias("_priority")),
                    part.with_columns(pl.lit(1).alias("_priority")),
                ], how="diagonal_relaxed")
                part = combined.sort(["dtm", "_priority"]).unique(
                    subset=["dtm"], keep="first", maintain_order=True,
                ).drop("_priority").sort("dtm")
            fd, tmp = tempfile.mkstemp(prefix=".eaton-", suffix=".parquet", dir=path.parent)
            os.close(fd)
            try:
                part.write_parquet(tmp, compression="zstd")
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            output[path] = part.height - old_rows
        return output

    def compile_to_parquet(
        self, source: str | Path, target: str | Path,
        archive: str | Path | None = None,
        issues: str | Path | None = None,
        append_parquet: bool = True,
        split: str = "month",
    ) -> tuple[pl.DataFrame, dict[str, str]]:
        if split != "month":
            raise ValueError("Eaton supports monthly partitioning only")
        source, target = Path(source), Path(target)
        errors: dict[str, str] = {}
        result = pl.DataFrame()
        counts: dict[Path, int] = defaultdict(int)
        if not source.exists():
            self.logger.warning("Eaton source directory not found: %s", source)
        else:
            for path in sorted(source.rglob("*")):
                if not path.is_file() or not self.should_process_file(path):
                    continue
                self.logger.info("Processing %s", path.name)
                frame, error = self.extract_to_dataframe(path)
                if error:
                    errors[str(path)] = error
                    self.logger.error("Invalid Eaton source %s: %s", path, error)
                    if issues is not None:
                        try:
                            self._move(path, Path(issues) / path.relative_to(source))
                        except OSError:
                            self.logger.exception("Unable to move invalid Eaton source to issues")
                    continue
                try:
                    written = self._write(frame, target, append_parquet)
                except Exception as exc:
                    errors[str(path)] = str(exc)
                    self.logger.exception("Could not save %s; keeping source in incoming", path)
                    continue
                for output_path, count in written.items():
                    counts[output_path] += count
                result = pl.concat([result, frame], how="diagonal_relaxed") if not result.is_empty() else frame
                if archive is not None:
                    first = frame["dtm"].min()
                    destination = Path(archive) / f"{first.year:04d}" / f"{first.month:02d}" / path.name
                    try:
                        self._move(path, destination)
                    except OSError:
                        self.logger.warning("Parquet saved but could not archive %s", path)
        for output_path, count in sorted(counts.items()):
            self.logger.info("✔ Written %d new rows to %s", count, output_path)
        self.logger.info("✔ Parquet compilation completed. Total rows: %d", result.height)
        return result, errors
