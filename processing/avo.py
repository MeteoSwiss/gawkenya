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

        Output files follow the same directory structure as the other
        instruments:

            <target>/<year>/<month>/avo-<name>-<cadence>.parquet

        For example:

            level1/nrb/2026/08/avo-roof-instant.parquet
            level1/nrb/2026/08/avo-roof-hourly.parquet
            level1/nrb/2026/08/avo-roof-daily.parquet
            level1/nrb/2026/08/avo-roof-monthly.parquet

        All readable input files are staged by cadence and date partition.
        Each target parquet is read and written only once per processing run.

        Extraction and parquet-writing errors remain fatal where appropriate.
        Archive and issues-directory move failures are housekeeping failures:
        they are reported, but do not stop processing.

        Args:
            source:
                Incoming source directory for one AVO sensor.
            target:
                Station-level level1 directory, for example
                ``level1/nrb``. The sensor name is included in the output
                filename, not added as another directory.
            archive:
                Optional archive directory for successfully processed files.
            issues:
                Optional issues directory for failed input files.
            split:
                Date partitioning mode. ``month`` creates ``yyyy/mm``;
                ``day`` creates ``yyyy/mm/dd``; ``year`` creates ``yyyy``.
        """
        source = Path(source)
        target = Path(target)
        archive = Path(archive) if archive is not None else None
        issues = Path(issues) if issues is not None else None

        self._announce(
            f"[{self.name}] scanning source directory: {source}"
        )

        if not source.exists():
            self._announce(
                f"[{self.name}] source directory does not exist; "
                "nothing to do."
            )
            return

        files = self._list_input_files(source)

        if not files:
            self._announce(
                f"[{self.name}] no supported input files found."
            )
            return

        self._announce(
            f"[{self.name}] found {len(files)} input file(s)."
        )

        staged: dict[Path, list[pl.DataFrame]] = {}
        successes: list[Path] = []
        failures: list[tuple[Path, str]] = []

        for index, path in enumerate(files, start=1):
            self._announce(
                f"[{self.name}] extracting file "
                f"{index}/{len(files)}: {path.name}"
            )

            df, err = self.extract_to_dataframe(path)

            if err is not None:
                failures.append((path, err))
                self._announce(
                    f"[{self.name}] extraction failed for "
                    f"{path.name}: {err}"
                )
                continue

            if df.is_empty():
                error = "Extracted dataframe is empty."
                failures.append((path, error))
                self._announce(
                    f"[{self.name}] extracted dataframe is empty "
                    f"for {path.name}"
                )
                continue

            cadence = self._infer_cadence(path)

            if cadence == "unknown":
                error = (
                    "Could not infer AVO cadence from filename. Expected "
                    "one of instant, hourly, daily, weekly, monthly, yearly "
                    "or annual after the 'avo_' filename component."
                )
                failures.append((path, error))
                self._announce(
                    f"[{self.name}] rejected {path.name}: {error}"
                )
                continue

            # Important:
            # ``target`` is already the station-level root, for example
            # level1/nrb. Do not append self.name as another directory.
            part_map = self._split_dataframe_by_partition(
                df,
                target_root=target,
                cadence=cadence,
                split=split,
            )

            for out_path, part_df in part_map.items():
                staged.setdefault(out_path, []).append(part_df)

            successes.append(path)

            self._announce(
                f"[{self.name}] staged {path.name}: "
                f"rows={df.height:,}, "
                f"cadence={cadence}, "
                f"partitions={len(part_map)}"
            )

        if not staged:
            self._announce(
                f"[{self.name}] no staged output partitions were produced."
            )

            issue_move_failures = self._move_failed_files(
                failures,
                issues,
            )

            self._announce(
                f"[{self.name}] done. "
                f"targets_written=0, "
                f"succeeded=0, "
                f"failed={len(failures)}, "
                f"archive_move_failed=0, "
                f"issues_move_failed={len(issue_move_failures)}"
            )
            return

        self._announce(
            f"[{self.name}] writing {len(staged)} parquet target(s) "
            f"from {len(successes)} successful input file(s)."
        )

        written = 0

        sorted_targets = sorted(
            staged.items(),
            key=lambda item: str(item[0]),
        )

        for out_index, (out_path, frames) in enumerate(
            sorted_targets,
            start=1,
        ):
            self._announce(
                f"[{self.name}] writing target "
                f"{out_index}/{len(staged)}: {out_path}"
            )

            self._write_partition(
                out_path,
                frames,
            )
            written += 1

        # These helpers catch PermissionError and other filesystem errors.
        # They return failed moves instead of terminating the processor.
        archive_move_failures = self._move_successful_files(
            successes,
            archive,
        )
        issue_move_failures = self._move_failed_files(
            failures,
            issues,
        )

        self._announce(
            f"[{self.name}] done. "
            f"targets_written={written}, "
            f"succeeded={len(successes)}, "
            f"failed={len(failures)}, "
            f"archive_move_failed={len(archive_move_failures)}, "
            f"issues_move_failed={len(issue_move_failures)}"
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
        Split a dataframe into date partitions.

        ``target_root`` must be the station-level directory, for example:

            level1/nrb

        Resulting monthly paths are:

            level1/nrb/YYYY/MM/avo-<sensor>-<cadence>.parquet
        """
        target_root = Path(target_root)
        split = str(split).strip().lower()

        if split == "month":
            partitioned = df.with_columns(
                [
                    pl.col("dtm").dt.year().alias("_year"),
                    pl.col("dtm").dt.month().alias("_month"),
                ]
            )

            result: dict[Path, pl.DataFrame] = {}

            for part_df in partitioned.partition_by(
                ["_year", "_month"],
                as_dict=False,
                maintain_order=True,
            ):
                year = int(part_df["_year"][0])
                month = int(part_df["_month"][0])

                out_path = (
                    target_root
                    / f"{year:04d}"
                    / f"{month:02d}"
                    / self._output_filename(cadence)
                )

                result[out_path] = part_df.drop(
                    ["_year", "_month"]
                )

            return result

        if split == "day":
            partitioned = df.with_columns(
                [
                    pl.col("dtm").dt.year().alias("_year"),
                    pl.col("dtm").dt.month().alias("_month"),
                    pl.col("dtm").dt.day().alias("_day"),
                ]
            )

            result = {}

            for part_df in partitioned.partition_by(
                ["_year", "_month", "_day"],
                as_dict=False,
                maintain_order=True,
            ):
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

                result[out_path] = part_df.drop(
                    ["_year", "_month", "_day"]
                )

            return result

        if split == "year":
            partitioned = df.with_columns(
                pl.col("dtm").dt.year().alias("_year")
            )

            result = {}

            for part_df in partitioned.partition_by(
                ["_year"],
                as_dict=False,
                maintain_order=True,
            ):
                year = int(part_df["_year"][0])

                out_path = (
                    target_root
                    / f"{year:04d}"
                    / self._output_filename(cadence)
                )

                result[out_path] = part_df.drop("_year")

            return result

        if split in {"none", "", "false"}:
            return {
                target_root / self._output_filename(cadence): df
            }

        raise ValueError(
            f"Unsupported split mode {split!r}. "
            "Expected 'month', 'day', 'year', or 'none'."
        )

    def _output_filename(self, cadence: str) -> str:
        """
        Return the complete AVO sensor/cadence parquet filename.

        Examples:
            avo-roof-hourly.parquet
            avo-huduma-monthly.parquet
        """
        normalized_cadence = cadence.strip().lower()

        if normalized_cadence == "annual":
            normalized_cadence = "yearly"

        valid_cadences = {
            "instant",
            "hourly",
            "daily",
            "weekly",
            "monthly",
            "yearly",
        }

        if normalized_cadence not in valid_cadences:
            raise ValueError(
                f"Unsupported AVO cadence {cadence!r}. "
                f"Expected one of {sorted(valid_cadences)}."
            )

        sensor_name = self.name.strip().lower()

        if not sensor_name:
            raise ValueError(
                "AVO processor name must not be empty."
            )

        if not sensor_name.startswith("avo-"):
            sensor_name = f"avo-{sensor_name}"

        return f"{sensor_name}-{normalized_cadence}.parquet"
    
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

    def _move_successful_files(
        self,
        paths: list[Path],
        archive: Path | None,
    ) -> list[tuple[Path, str]]:
        """
        Move successfully processed files to the archive.

        Archiving is housekeeping. Permission and filesystem errors are
        reported but never propagated, because the parquet output has already
        been written successfully.

        Returns:
            A list of source paths that could not be moved, together with
            their error messages.
        """
        move_failures: list[tuple[Path, str]] = []

        if archive is None or not paths:
            return move_failures

        try:
            archive.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            error = f"{type(err).__name__}: {err}"

            self._warn(
                f"[{self.name}] cannot create or access archive directory "
                f"{archive}: {error}"
            )

            return [(path, error) for path in paths]

        for path in paths:
            destination = archive / path.name

            try:
                if not path.exists():
                    self._warn(
                        f"[{self.name}] source file disappeared before "
                        f"archiving: {path}"
                    )
                    continue

                if destination.exists():
                    destination.unlink()

                shutil.move(
                    str(path),
                    str(destination),
                )

            except (OSError, shutil.Error) as err:
                error = f"{type(err).__name__}: {err}"
                move_failures.append((path, error))

                self._warn(
                    f"[{self.name}] data were processed successfully, but "
                    f"the source file could not be archived: "
                    f"{path} -> {destination} | {error}. "
                    f"The source file remains in incoming."
                )

        return move_failures
    
    def _move_failed_files(
        self,
        failures: list[tuple[Path, str]],
        issues: Path | None,
    ) -> list[tuple[Path, str]]:
        """
        Move failed input files to the issues directory.

        Moving an input file is housekeeping. Permission and filesystem
        errors are reported but never propagated.

        Returns:
            A list of source paths that could not be moved, together with
            their move error messages.
        """
        move_failures: list[tuple[Path, str]] = []

        if not failures or issues is None:
            return move_failures

        try:
            issues.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            error = f"{type(err).__name__}: {err}"

            self._warn(
                f"[{self.name}] cannot create or access issues directory "
                f"{issues}: {error}"
            )

            return [
                (path, error)
                for path, _processing_error in failures
            ]

        for path, processing_error in failures:
            destination = issues / path.name

            try:
                if not path.exists():
                    self._warn(
                        f"[{self.name}] failed source file disappeared before "
                        f"it could be moved: {path}"
                    )
                    continue

                if destination.exists():
                    destination.unlink()

                shutil.move(
                    str(path),
                    str(destination),
                )

                self.logger.error(
                    "Moved failed AVO file to issues: %s (%s)",
                    path.name,
                    processing_error,
                )

            except (OSError, shutil.Error) as err:
                move_error = f"{type(err).__name__}: {err}"
                move_failures.append((path, move_error))

                self._warn(
                    f"[{self.name}] failed source file could not be moved "
                    f"to issues: {path} -> {destination} | {move_error}. "
                    f"Original processing error: {processing_error}"
                )

        return move_failures
    
    def _announce(self, message: str) -> None:
        """Emit a visible progress message and also log it."""
        print(message, flush=True)
        try:
            self.logger.info(message)
        except Exception:
            pass

    def _warn(self, message: str) -> None:
        """Emit a visible warning and write it to the processor log."""
        print(f"WARNING: {message}", flush=True)

        try:
            self.logger.warning(message)
        except Exception:
            pass
