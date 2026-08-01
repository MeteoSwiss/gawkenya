from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import shutil
import zipfile

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class AVO(Instrument):
    """
    Processor for IQAir AirVisual Outdoor (AVO) data files.

    Supported input formats:
      - current ``.zip`` exports containing one or more ``.csv`` members
      - plain ``.csv`` or ``.txt`` exports
      - already aggregated ``.parquet`` files

    The extractor normalizes the dataframe to the compact column names used by
    the compiled AVO parquet products:

      - ``ts``: ISO-8601 UTC timestamp string
      - ``co2``: CO2 concentration
      - ``pm1``: PM1 concentration
      - ``pr``: pressure in pascal
      - ``hm``: relative humidity in percent
      - ``tp``: air temperature in degree Celsius
      - ``pm25_aqius`` / ``pm25_aqicn`` / ``pm25_conc``
      - ``pm10_aqius`` / ``pm10_aqicn`` / ``pm10_conc``
      - optional ``pnc`` when particle count is available
      - optional ``source`` when the export contains multiple device sources
      - ``dtm``: ``pl.Datetime('us', 'UTC')``

    Unlike the generic append-style processor path, this class batches all
    incoming files by target partition first and writes each target parquet only
    once per run. That avoids the silent slowdown where increasingly large
    monthly parquet files are repeatedly reopened, concatenated, sorted, and
    rewritten for every single source file.
    """

    _TEXT_SUFFIXES = {".csv", ".txt", ".zip"}
    _INPUT_SUFFIXES = {".csv", ".txt", ".zip", ".parquet"}
    _NULL_VALUES = ["", "nan", "NaN", "NAN", "null", "NULL"]

    _DROP_COLUMNS = {
        "Device timezone",
        "Datetime_end(UTC)",
        "Temperature (Fahrenheit)",
        "AQI US",
        "AQI CN",
    }

    _KNOWN_NUMERIC_COLUMNS = {
        "co2",
        "pm1",
        "pr",
        "hm",
        "tp",
        "pm25_aqius",
        "pm25_aqicn",
        "pm25_conc",
        "pm10_aqius",
        "pm10_aqicn",
        "pm10_conc",
        "pnc",
    }

    _RENAME_MAP = {
        # Timestamp and source fields.
        "Datetime_start(UTC)": "ts",
        "Timestamp": "ts",
        "DateTime": "ts",
        "Source": "source",
        # Meteorology and gases.
        "CO2": "co2",
        "CO2 (ppm)": "co2",
        "Temperature (Celsius)": "tp",
        "Humidity (%)": "hm",
        "Pressure (pascal)": "pr",
        # Particle concentrations.
        "PM1 (ug/m3)": "pm1",
        "PM2.5 (ug/m3)": "pm25_conc",
        "PM10 (ug/m3)": "pm10_conc",
        # AQI variants sometimes differ slightly between exports.
        "PM2.5 AQI US": "pm25_aqius",
        "PM2.5 AQI CN": "pm25_aqicn",
        "PM10 AQI US": "pm10_aqius",
        "PM10 AQI CN": "pm10_aqicn",
        "PM2.5 (AQI US)": "pm25_aqius",
        "PM2.5 (AQI CN)": "pm25_aqicn",
        "PM10 (AQI US)": "pm10_aqius",
        "PM10 (AQI CN)": "pm10_aqicn",
        "PM2.5 (AQI-US)": "pm25_aqius",
        "PM2.5 (AQI-CN)": "pm25_aqicn",
        "PM10 (AQI-US)": "pm10_aqius",
        "PM10 (AQI-CN)": "pm10_aqicn",
        # Optional particle count.
        "Particle Count": "pnc",
        "Particle count": "pnc",
    }

    _CADENCE_RE = re.compile(
        r"(?i)(?:^|_)avo_(instant|hourly|daily|weekly|monthly|yearly|annual)-"
    )

    def __init__(self, name: str = "avo", log_file: str = str()) -> None:
        super().__init__(name="avo", log_file=log_file)
        self.name = name

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """
        Extract AVO data from a file into a normalized Polars DataFrame.

        Args:
            path: Path to a ``.zip``, ``.csv``, ``.txt``, or ``.parquet`` file.

        Returns:
            Tuple of ``(dataframe, error_message_or_none)``.
        """
        df = pl.DataFrame()

        try:
            suffix = path.suffix.lower()
            if suffix == ".parquet":
                df = pl.read_parquet(path)
            elif suffix == ".zip":
                df = self._read_zip_export(path)
            elif suffix in {".csv", ".txt"}:
                df = self._read_csv_export(path.read_bytes(), origin=path.name)
            else:
                raise ValueError(
                    f"Unsupported AVO file format '{path.suffix}'. "
                    "Expected .zip, .csv, .txt, or .parquet."
                )

            if df.is_empty():
                return df, None

            df = self._normalize_dataframe(df)
            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            self.logger.error("Failed to extract %s: %s", path.name, err)
            return df, str(err)

    def compile_to_parquet(
        self,
        source: Path,
        target: Path,
        archive: Path | None = None,
        issues: Path | None = None,
        split: str = "month",
    ) -> None:
        """
        Compile incoming AVO files into partitioned parquet products.

        This override avoids the generic per-file append/rewrite pattern that
        causes AVO compilation to appear to stall as monthly outputs grow.
        Instead it:

        1. extracts all readable input files,
        2. batches them by ``cadence`` and target date partition,
        3. reads any existing target parquet only once per target file,
        4. writes each target parquet once,
        5. moves processed source files to archive or issues.

        Args:
            source: Incoming source directory.
            target: Station-level level1 target directory.
            archive: Optional archive directory for successfully processed files.
            issues: Optional directory for failed files.
            split: Partitioning mode. ``month`` means ``yyyy/mm``;
                ``day`` means ``yyyy/mm/dd``; ``year`` means ``yyyy``.
        """
        source = Path(source)
        target = Path(target)
        archive = Path(archive) if archive is not None else None
        issues = Path(issues) if issues is not None else None

        self._announce(f"[{self.name}] scanning source directory: {source}")
        if not source.exists():
            self._announce(f"[{self.name}] source directory does not exist; nothing to do.")
            return

        files = self._list_input_files(source)
        if not files:
            self._announce(f"[{self.name}] no supported input files found.")
            return

        self._announce(f"[{self.name}] found {len(files)} input file(s).")

        staged: dict[Path, list[pl.DataFrame]] = {}
        successes: list[Path] = []
        failures: list[tuple[Path, str]] = []

        for index, path in enumerate(files, start=1):
            self._announce(f"[{self.name}] extracting file {index}/{len(files)}: {path.name}")
            df, err = self.extract_to_dataframe(path)
            if err is not None:
                failures.append((path, err))
                self._announce(f"[{self.name}] extraction failed for {path.name}: {err}")
                continue
            if df.is_empty():
                failures.append((path, "Extracted dataframe is empty."))
                self._announce(f"[{self.name}] extracted dataframe is empty for {path.name}")
                continue

            cadence = self._infer_cadence(path)
            part_map = self._split_dataframe_by_partition(df, target_root=target / self.name, cadence=cadence, split=split)
            for out_path, part_df in part_map.items():
                staged.setdefault(out_path, []).append(part_df)

            successes.append(path)
            self._announce(
                f"[{self.name}] staged {path.name}: rows={df.height:,}, cadence={cadence}, partitions={len(part_map)}"
            )

        if not staged:
            self._announce(f"[{self.name}] no staged output partitions were produced.")
            self._move_failed_files(failures, issues)
            return

        self._announce(
            f"[{self.name}] writing {len(staged)} parquet target(s) from {len(successes)} successful input file(s)."
        )
        written = 0
        for out_index, (out_path, frames) in enumerate(sorted(staged.items(), key=lambda item: str(item[0])), start=1):
            self._announce(f"[{self.name}] writing target {out_index}/{len(staged)}: {out_path}")
            self._write_partition(out_path, frames)
            written += 1

        self._move_successful_files(successes, archive)
        self._move_failed_files(failures, issues)

        self._announce(
            f"[{self.name}] done. targets_written={written}, succeeded={len(successes)}, failed={len(failures)}"
        )

    def _read_zip_export(self, path: Path) -> pl.DataFrame:
        """
        Read all CSV members from an AVO ZIP export and concatenate them.

        Args:
            path: Path to the ZIP archive.

        Returns:
            Concatenated raw dataframe.
        """
        frames: list[pl.DataFrame] = []

        with zipfile.ZipFile(path, "r") as archive:
            for member_name in archive.namelist():
                if member_name.endswith("/") or not member_name.lower().endswith(".csv"):
                    continue

                with archive.open(member_name) as handle:
                    raw = handle.read()

                member_df = self._read_csv_export(raw, origin=f"{path.name}:{member_name}")
                if not member_df.is_empty():
                    frames.append(member_df)

        if not frames:
            raise ValueError("ZIP archive does not contain a readable AVO CSV member.")

        if len(frames) == 1:
            return frames[0]

        return pl.concat(frames, how="diagonal_relaxed")

    def _read_csv_export(self, raw: bytes, origin: str) -> pl.DataFrame:
        """
        Read a raw AVO CSV export.

        Args:
            raw: File content as bytes.
            origin: Human-readable origin used for logging context.

        Returns:
            Raw dataframe.
        """
        try:
            return pl.read_csv(
                BytesIO(raw),
                null_values=self._NULL_VALUES,
                infer_schema_length=5000,
                try_parse_dates=False,
                encoding="utf8-lossy",
            )
        except Exception as err:
            raise ValueError(f"Could not parse CSV member {origin}: {err}") from err

    def _normalize_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Normalize a raw AVO dataframe to the compiled schema.

        Args:
            df: Raw dataframe.

        Returns:
            Normalized dataframe.
        """
        rename_map = {column: self._canonical_name(column) for column in df.columns}
        df = df.rename(rename_map)

        drop_columns = [
            column
            for column in df.columns
            if not str(column).strip()
            or column in self._DROP_COLUMNS
            or str(column).startswith("slot.")
        ]
        if drop_columns:
            df = df.drop(drop_columns)

        # Remove columns that are entirely null with a single dataframe scan.
        if df.columns:
            non_null_flags = df.select([
                pl.col(column).is_not_null().any().alias(column)
                for column in df.columns
            ]).row(0, named=True)
            keep_columns = [
                column for column in df.columns if bool(non_null_flags.get(column, False))
            ]
            df = df.select(keep_columns)

        if "dtm" not in df.columns:
            timestamp_source = "ts" if "ts" in df.columns else None
            if timestamp_source is None:
                raise ValueError(
                    "Missing timestamp column. Expected one of 'dtm', 'ts', "
                    "'Datetime_start(UTC)', or 'Timestamp'."
                )
            df = df.with_columns(self._parse_timestamp_expr(timestamp_source).alias("dtm"))
        else:
            df = df.with_columns(self._parse_timestamp_expr("dtm").alias("dtm"))

        if df["dtm"].null_count() == len(df):
            raise ValueError("Could not parse any timestamps from the AVO input file.")

        df = df.filter(pl.col("dtm").is_not_null())

        # Standardize ts from dtm so raw CSV and parquet input behave the same.
        df = df.with_columns(
            pl.col("dtm").dt.strftime("%Y-%m-%dT%H:%M:%S.000Z").alias("ts")
        )

        if "pnc" in df.columns:
            # Convert particle count from 1/L to 1/cm3 to match notebook logic.
            df = df.with_columns((pl.col("pnc") / 1000.0).alias("pnc"))

        cast_exprs: list[pl.Expr] = []
        for column in df.columns:
            if column == "dtm":
                continue
            if column in {"ts", "source"}:
                cast_exprs.append(pl.col(column).cast(pl.Utf8, strict=False).alias(column))
            elif column in self._KNOWN_NUMERIC_COLUMNS:
                cast_exprs.append(pl.col(column).cast(pl.Float64, strict=False).alias(column))
        if cast_exprs:
            df = df.with_columns(cast_exprs)

        preferred_order = [
            "ts",
            "source",
            "co2",
            "pm1",
            "pr",
            "hm",
            "tp",
            "pm25_aqius",
            "pm25_aqicn",
            "pm25_conc",
            "pm10_aqius",
            "pm10_aqicn",
            "pm10_conc",
            "pnc",
            "dtm",
        ]
        selected = [column for column in preferred_order if column in df.columns]
        df = df.select(selected)

        return df.sort("dtm")

    def _canonical_name(self, column: str) -> str:
        """
        Convert a raw export column name to its canonical output name.

        Args:
            column: Raw column name.

        Returns:
            Canonical column name.
        """
        cleaned = str(column).strip().lstrip("\ufeff")
        return self._RENAME_MAP.get(cleaned, cleaned)

    def _parse_timestamp_expr(self, column: str) -> pl.Expr:
        """
        Build a robust parser for the timestamp column.

        Args:
            column: Name of the source timestamp column.

        Returns:
            Expression yielding ``pl.Datetime('us', 'UTC')``.
        """
        source = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()

        return pl.coalesce(
            [
                pl.col(column).cast(pl.Datetime(time_zone="UTC", time_unit="us"), strict=False),
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
                    format="%m/%d/%Y %H:%M",
                    strict=False,
                ).dt.replace_time_zone("UTC"),
                source.str.strptime(
                    pl.Date,
                    format="%Y-%m-%d",
                    strict=False,
                ).cast(pl.Datetime).dt.replace_time_zone("UTC"),
            ]
        ).dt.with_time_unit("us")

    def _list_input_files(self, source: Path) -> list[Path]:
        """Return supported input files below ``source`` in deterministic order."""
        files = [
            path for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in self._INPUT_SUFFIXES
        ]
        return files

    def _infer_cadence(self, path: Path) -> str:
        """Infer cadence token from the source filename."""
        match = self._CADENCE_RE.search(path.name)
        if match:
            cadence = match.group(1).lower()
            return "yearly" if cadence == "annual" else cadence
        return "unknown"

    def _split_dataframe_by_partition(
        self,
        df: pl.DataFrame,
        target_root: Path,
        cadence: str,
        split: str,
    ) -> dict[Path, pl.DataFrame]:
        """
        Split a dataframe by target date partition and return output-path mapping.

        Args:
            df: Normalized dataframe.
            target_root: Root output directory for this AVO source.
            cadence: Cadence token inferred from the filename.
            split: Partitioning mode.

        Returns:
            Mapping of output parquet path to partition dataframe.
        """
        split = str(split).strip().lower()
        if split == "month":
            df = df.with_columns([
                pl.col("dtm").dt.year().alias("_year"),
                pl.col("dtm").dt.month().alias("_month"),
            ])
            grouped = df.partition_by(["_year", "_month"], as_dict=False, maintain_order=True)
            result: dict[Path, pl.DataFrame] = {}
            for part_df in grouped:
                year = int(part_df["_year"][0])
                month = int(part_df["_month"][0])
                out_path = target_root / f"{year:04d}" / f"{month:02d}" / self._output_filename(cadence)
                result[out_path] = part_df.drop(["_year", "_month"])
            return result

        if split == "day":
            df = df.with_columns([
                pl.col("dtm").dt.year().alias("_year"),
                pl.col("dtm").dt.month().alias("_month"),
                pl.col("dtm").dt.day().alias("_day"),
            ])
            grouped = df.partition_by(["_year", "_month", "_day"], as_dict=False, maintain_order=True)
            result = {}
            for part_df in grouped:
                year = int(part_df["_year"][0])
                month = int(part_df["_month"][0])
                day = int(part_df["_day"][0])
                out_path = (
                    target_root
                    / f"{year:04d}"
                    / f"{month:02d}"
                    / f"{day:02d}"
                    / self._output_filename(cadence)
                )
                result[out_path] = part_df.drop(["_year", "_month", "_day"])
            return result

        if split == "year":
            df = df.with_columns(pl.col("dtm").dt.year().alias("_year"))
            grouped = df.partition_by(["_year"], as_dict=False, maintain_order=True)
            result = {}
            for part_df in grouped:
                year = int(part_df["_year"][0])
                out_path = target_root / f"{year:04d}" / self._output_filename(cadence)
                result[out_path] = part_df.drop(["_year"])
            return result

        # Fallback: no partitioning.
        return {target_root / self._output_filename(cadence): df}

    def _output_filename(self, cadence: str) -> str:
        """Return output parquet filename for a cadence token."""
        cadence = cadence.lower().strip()
        if cadence in {"instant", "hourly", "daily", "weekly", "monthly", "yearly"}:
            return f"avo-{cadence}.parquet"
        return "avo.parquet"

    def _write_partition(self, out_path: Path, frames: list[pl.DataFrame]) -> None:
        """Read existing parquet once, merge, deduplicate, and write once."""
        out_path.parent.mkdir(parents=True, exist_ok=True)

        incoming = pl.concat(frames, how="diagonal_relaxed") if len(frames) > 1 else frames[0]
        if out_path.exists():
            self._announce(f"[{self.name}] merging with existing parquet: {out_path}")
            existing = pl.read_parquet(out_path)
            combined = pl.concat([existing, incoming], how="diagonal_relaxed")
        else:
            combined = incoming

        dedupe_subset = ["dtm"]
        if "source" in combined.columns:
            dedupe_subset.append("source")

        combined = (
            combined
            .sort(dedupe_subset)
            .unique(subset=dedupe_subset, keep="last")
            .sort("dtm")
        )
        combined = pl_simplify_dtypes(combined)
        combined.write_parquet(out_path)

    def _move_successful_files(self, paths: list[Path], archive: Path | None) -> None:
        """Move successfully processed files to archive if requested."""
        if archive is None:
            return
        archive.mkdir(parents=True, exist_ok=True)
        for path in paths:
            destination = archive / path.name
            if destination.exists():
                destination.unlink()
            shutil.move(str(path), str(destination))

    def _move_failed_files(self, failures: list[tuple[Path, str]], issues: Path | None) -> None:
        """Move failed files to the issues directory if requested."""
        if not failures:
            return
        if issues is None:
            return
        issues.mkdir(parents=True, exist_ok=True)
        for path, err in failures:
            destination = issues / path.name
            if destination.exists():
                destination.unlink()
            shutil.move(str(path), str(destination))
            self.logger.error("Moved failed AVO file to issues: %s (%s)", path.name, err)

    def _announce(self, message: str) -> None:
        """Emit a visible progress message and also log it."""
        print(message, flush=True)
        try:
            self.logger.info(message)
        except Exception:
            pass
