from __future__ import annotations

import re
import shutil
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Iterable

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class AVO(Instrument):
    """
    Processor for IQAir AirVisual Outdoor (AVO) data files.

    Supported input formats:
      - ``.zip`` exports containing one or more ``.csv`` or ``.txt`` members
      - plain ``.csv`` or ``.txt`` exports
      - pre-compiled ``.parquet`` files such as instant, hourly, daily,
        weekly, monthly, and yearly products

    The extractor normalizes raw exports and pre-compiled parquet files to a
    compact schema centered on ``dtm`` (UTC, microsecond precision) and writes
    separate compiled parquet products such as ``avo-hourly.parquet`` and
    ``avo-daily.parquet``.

    When ``split='month'``, compiled files are stored below the provided target
    root as ``<target>/<YYYY>/<MM>/avo-<product>.parquet``. The processor does
    not inject its own ``avo`` subdirectory; the caller-controlled target path
    remains authoritative.
    """

    _TEXT_SUFFIXES = {".csv", ".txt", ".zip"}
    _SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | {".parquet"}
    _NULL_VALUES = ["", "nan", "NaN", "NAN", "null", "NULL"]

    _DROP_COLUMNS = {
        "Device timezone",
        "Datetime_end(UTC)",
        "Temperature (Fahrenheit)",
        "AQI US",
        "AQI CN",
        "slot.2.co",
    }

    _NUMERIC_COLUMNS = {
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

    _PRODUCT_ALIASES = {
        "instant": "instant",
        "inst": "instant",
        "realtime": "instant",
        "real-time": "instant",
        "live": "instant",
        "hourly": "hourly",
        "hour": "hourly",
        "daily": "daily",
        "day": "daily",
        "weekly": "weekly",
        "week": "weekly",
        "monthly": "monthly",
        "month": "monthly",
        "annual": "yearly",
        "yearly": "yearly",
        "year": "yearly",
    }

    _PRODUCT_PATTERN = re.compile(
        r"(?:^|[_\-.])(instant|inst|realtime|real-time|live|hourly|hour|daily|day|weekly|week|monthly|month|annual|yearly|year)(?:[_\-.]|$)",
        re.IGNORECASE,
    )

    _RENAME_MAP = {
        "Datetime_start(UTC)": "ts",
        "Timestamp": "ts",
        "DateTime": "ts",
        "Source": "source",
        "CO2": "co2",
        "CO2 (ppm)": "co2",
        "Temperature (Celsius)": "tp",
        "Humidity (%)": "hm",
        "Pressure (pascal)": "pr",
        "PM1 (ug/m3)": "pm1",
        "PM2.5 (ug/m3)": "pm25_conc",
        "PM10 (ug/m3)": "pm10_conc",
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
        "Particle Count": "pnc",
        "Particle count": "pnc",
    }

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
        archive: Path,
        issues: Path,
        split: bool | str | Iterable[str] = True,
    ) -> None:
        """
        Compile AVO files to parquet, keeping each aggregation product in its
        own compiled parquet file.

        With ``split='month'``, output is written as:

            ``<target>/<YYYY>/<MM>/avo-<product>.parquet``

        Args:
            source: Directory containing incoming AVO files.
            target: Root directory for compiled parquet output.
            archive: Directory where successfully processed source files are moved.
            issues: Directory where problematic source files are moved.
            split: Partitioning scheme. Supported values are falsy for no split,
                ``True`` or ``'month'`` for year/month, ``'year'`` for year only,
                ``'day'`` for year/month/day, or an iterable of explicit parts.
        """
        source = Path(source)
        target = Path(target)
        archive = Path(archive)
        issues = Path(issues)
        split_parts = self._normalize_split(split)

        files = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in self._SUPPORTED_SUFFIXES
        ]

        if not files:
            self.logger.info("No AVO files found in %s", source)
            return

        grouped: dict[str, list[pl.DataFrame]] = defaultdict(list)
        archived_paths: list[Path] = []

        for path in files:
            df, err = self.extract_to_dataframe(path)
            if err is not None:
                self.logger.error("Failed to compile %s: %s", path.name, err)
                self._move_processed_file(path=path, source_root=source, destination_root=issues)
                continue

            if df.is_empty():
                self.logger.warning("Skipping empty AVO file %s", path.name)
                self._move_processed_file(path=path, source_root=source, destination_root=archive)
                continue

            product = self._infer_product_kind(path)
            grouped[product].append(df)
            archived_paths.append(path)

        for product, frames in grouped.items():
            combined = self._combine_frames(frames)
            if combined.is_empty():
                continue
            self._write_product_partitions(
                df=combined,
                product=product,
                target_root=target,
                split_parts=split_parts,
            )

        for path in archived_paths:
            self._move_processed_file(path=path, source_root=source, destination_root=archive)

    def _read_zip_export(self, path: Path) -> pl.DataFrame:
        """
        Read all CSV/TXT members from an AVO ZIP export and concatenate them.

        Args:
            path: ZIP archive path.

        Returns:
            Concatenated raw dataframe.
        """
        frames: list[pl.DataFrame] = []

        with zipfile.ZipFile(path, "r") as archive:
            member_names = [
                name for name in archive.namelist()
                if not name.endswith("/") and Path(name).suffix.lower() in {".csv", ".txt"}
            ]

            if not member_names:
                raise ValueError("ZIP archive does not contain a readable CSV/TXT member.")

            for member_name in member_names:
                with archive.open(member_name) as handle:
                    frames.append(self._read_csv_export(handle.read(), origin=f"{path.name}:{member_name}"))

        return self._combine_frames(frames)

    def _read_csv_export(self, raw: bytes, origin: str) -> pl.DataFrame:
        """
        Read an AVO CSV/TXT export from bytes.

        Args:
            raw: File content.
            origin: Origin label for error reporting.

        Returns:
            Raw dataframe before normalization.
        """
        try:
            return pl.read_csv(
                BytesIO(raw),
                null_values=self._NULL_VALUES,
                infer_schema_length=5000,
                ignore_errors=False,
                try_parse_dates=False,
            )
        except Exception as err:
            raise ValueError(f"Could not parse AVO CSV/TXT export from {origin}: {err}") from err

    def _normalize_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Harmonize dataframe schema across raw exports and pre-compiled parquet.

        Args:
            df: Raw dataframe.

        Returns:
            Normalized dataframe.
        """
        rename_map = {col: str(col).strip().lstrip("\ufeff") for col in df.columns}
        df = df.rename(rename_map)

        empty_columns = [col for col in df.columns if not str(col).strip()]
        if empty_columns:
            df = df.drop(empty_columns)

        non_null_columns = [
            col for col in df.columns
            if df.select(pl.col(col).is_not_null().sum()).item() > 0
        ]
        df = df.select(non_null_columns)

        drop_columns = [
            col for col in df.columns
            if col in self._DROP_COLUMNS or col.lower().startswith("slot.")
        ]
        if drop_columns:
            df = df.drop(drop_columns)

        df = df.rename({col: self._canonical_name(col) for col in df.columns})

        if "pnc" in df.columns:
            df = df.with_columns((pl.col("pnc").cast(pl.Float64, strict=False) / 1000.0).alias("pnc"))

        dtm_col = getattr(self, "dtm", "dtm")
        if dtm_col not in df.columns:
            if "ts" in df.columns:
                df = df.with_columns(self._parse_timestamp_expr("ts").alias(dtm_col))
            elif "Datetime_start(UTC)" in df.columns:
                df = df.with_columns(self._parse_timestamp_expr("Datetime_start(UTC)").alias(dtm_col))
            else:
                raise ValueError(
                    f"Missing timestamp column. Available columns: {', '.join(map(str, df.columns))}"
                )
        else:
            df = df.with_columns(self._parse_timestamp_expr(dtm_col).alias(dtm_col))

        if "ts" not in df.columns:
            df = df.with_columns(
                pl.col(dtm_col).dt.strftime("%Y-%m-%dT%H:%M:%S%.3fZ").alias("ts")
            )
        else:
            df = df.with_columns(pl.col("ts").cast(pl.Utf8, strict=False).alias("ts"))

        exprs: list[pl.Expr] = []
        if "source" in df.columns:
            exprs.append(pl.col("source").cast(pl.Utf8, strict=False).alias("source"))

        for column in self._NUMERIC_COLUMNS:
            if column in df.columns:
                exprs.append(pl.col(column).cast(pl.Float64, strict=False).alias(column))

        if exprs:
            df = df.with_columns(exprs)

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
            dtm_col,
        ]
        selected = [column for column in preferred_order if column in df.columns]
        return df.select(selected).sort(dtm_col)

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
        Build a robust parser for AVO timestamps.

        Args:
            column: Name of the source timestamp column.

        Returns:
            Expression yielding ``pl.Datetime('us', 'UTC')``.
        """
        source = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
        return (
            pl.coalesce(
                [
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
                        format="%Y-%m-%dT%H:%M:%S",
                        strict=False,
                    ).dt.replace_time_zone("UTC"),
                    source.str.strptime(
                        pl.Datetime,
                        format="%Y-%m-%d %H:%M:%S",
                        strict=False,
                    ).dt.replace_time_zone("UTC"),
                    source.str.strptime(
                        pl.Datetime,
                        format="%m/%d/%Y %H:%M",
                        strict=False,
                    ).dt.replace_time_zone("UTC"),
                ]
            )
            .dt.with_time_unit("us")
        )

    def _infer_product_kind(self, path: Path) -> str:
        """
        Infer the aggregation product from the input file name.

        Args:
            path: Input file path.

        Returns:
            Product label such as ``instant``, ``hourly``, or ``daily``.
            Falls back to ``raw`` when no aggregation token is found.
        """
        stem = path.stem.lower()
        match = self._PRODUCT_PATTERN.search(stem)
        if match:
            token = match.group(1).lower()
            return self._PRODUCT_ALIASES.get(token, token)

        for token in re.split(r"[_\-.]+", stem):
            mapped = self._PRODUCT_ALIASES.get(token.lower())
            if mapped:
                return mapped

        return "raw"

    def _product_filename(self, product: str) -> str:
        """
        Build the compiled parquet filename for a product.

        Args:
            product: Aggregation product label.

        Returns:
            Output filename.
        """
        if product == "raw":
            return f"{self.name}.parquet"
        return f"{self.name}-{product}.parquet"

    def _normalize_split(self, split: bool | str | Iterable[str]) -> list[str]:
        """
        Normalize the split configuration used by other processors.

        Args:
            split: Split configuration.

        Returns:
            List of partition parts from ``year``, ``month``, and ``day``.
        """
        if split is False or split is None:
            return []
        if split is True:
            return ["year", "month"]
        if isinstance(split, str):
            value = split.strip().lower()
            if not value or value in {"none", "false", "no"}:
                return []
            if value == "year":
                return ["year"]
            if value == "month":
                return ["year", "month"]
            if value == "day":
                return ["year", "month", "day"]
            if value in {"year,month", "year/month"}:
                return ["year", "month"]
            if value in {"year,month,day", "year/month/day"}:
                return ["year", "month", "day"]
            raise ValueError(f"Unsupported split value '{split}' for AVO.")

        parts: list[str] = []
        for item in split:
            key = str(item).strip().lower()
            if key in {"year", "month", "day"} and key not in parts:
                parts.append(key)
        return parts

    def _combine_frames(self, frames: list[pl.DataFrame]) -> pl.DataFrame:
        """
        Combine multiple dataframes with tolerant schema alignment.

        Args:
            frames: Dataframes to combine.

        Returns:
            Combined dataframe.
        """
        valid_frames = [frame for frame in frames if frame is not None and not frame.is_empty()]
        if not valid_frames:
            return pl.DataFrame()
        if len(valid_frames) == 1:
            return valid_frames[0]
        return pl.concat(valid_frames, how="diagonal_relaxed")

    def _output_basename(self, product: str) -> str:
        """
        Resolve the output filename for one product.

        Args:
            product: Product label.

        Returns:
            Compiled parquet filename.
        """
        return self._product_filename(product)

    def _write_product_partitions(
        self,
        df: pl.DataFrame,
        product: str,
        target_root: Path,
        split_parts: list[str],
    ) -> None:
        """
        Write a product dataframe to one or more parquet partitions.

        Args:
            df: Combined dataframe for one product.
            product: Aggregation product.
            target_root: Output root passed by the caller.
            split_parts: Normalized split specification.
        """
        basename = self._output_basename(product)

        if "dtm" not in df.columns:
            raise ValueError("AVO dataframe is missing required 'dtm' column.")

        work = df.with_columns(
            [
                pl.col("dtm").dt.year().alias("_year"),
                pl.col("dtm").dt.month().alias("_month"),
                pl.col("dtm").dt.day().alias("_day"),
            ]
        )

        if not split_parts:
            out_dir = target_root
            payload = work.drop(["_year", "_month", "_day"], strict=False)
            self._append_or_write_parquet(payload=payload, out_path=out_dir / basename)
            return

        group_columns = [f"_{part}" for part in split_parts]
        for key, part_df in work.partition_by(group_columns, as_dict=True, maintain_order=True).items():
            if not isinstance(key, tuple):
                key = (key,)
            out_dir = target_root
            mapping = dict(zip(split_parts, key))
            if "year" in mapping:
                out_dir = out_dir / f"{int(mapping['year']):04d}"
            if "month" in mapping:
                out_dir = out_dir / f"{int(mapping['month']):02d}"
            if "day" in mapping:
                out_dir = out_dir / f"{int(mapping['day']):02d}"

            payload = part_df.drop(["_year", "_month", "_day"], strict=False)
            self._append_or_write_parquet(payload=payload, out_path=out_dir / basename)

    def _append_or_write_parquet(self, payload: pl.DataFrame, out_path: Path) -> None:
        """
        Append to an existing parquet or create a new one.

        Args:
            payload: Data to write.
            out_path: Target parquet path.
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = pl_simplify_dtypes(payload)

        if out_path.exists():
            existing = pl.read_parquet(out_path)
            combined = pl.concat([existing, payload], how="diagonal_relaxed")
            sort_columns = [column for column in ["dtm", "source"] if column in combined.columns]
            if sort_columns:
                combined = combined.sort(sort_columns)
            payload = combined.unique(maintain_order=True)

        payload.write_parquet(out_path)
        self.logger.info("Wrote %s", out_path)

    def _move_processed_file(
        self,
        path: Path,
        source_root: Path,
        destination_root: Path,
    ) -> None:
        """
        Move a processed file while preserving its relative subdirectory.

        Args:
            path: Original file path.
            source_root: Root source directory.
            destination_root: Archive or issues directory.
        """
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            relative = Path(path.name)

        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            destination = self._deduplicated_destination(destination)

        shutil.move(str(path), str(destination))

    def _deduplicated_destination(self, destination: Path) -> Path:
        """
        Generate a non-conflicting destination path.

        Args:
            destination: Proposed destination path.

        Returns:
            Non-existing destination path.
        """
        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent

        counter = 1
        candidate = destination
        while candidate.exists():
            candidate = parent / f"{stem}.{counter}{suffix}"
            counter += 1
        return candidate
