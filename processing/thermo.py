from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Thermo(Instrument):
    """
    Processor for Thermo ozone analyzer data files (49c and 49i).

    The parser auto-detects both legacy Thermo text files, whose first header
    field is ``pcdate``, and the newer long-term format produced by the current
    code, whose first header field is ``dtm``. Input may be provided as plain
    text files or as ``.zip`` archives containing a single data member.
    """

    def __init__(self, name: str = "thermo", log_file: str = str()) -> None:
        super().__init__(name="thermo", log_file=log_file)
        self.name = name

        self.headers = {
            "tei49c": [
                "pcdate", "pctime", "time", "date", "o3", "flags",
                "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres",
            ],
            "tei49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres",
            ],
            "49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres",
            ],
        }

        self.modern_headers = {
            "tei49i": [
                "dtm", "time", "date", "o3", "flags", "hio3",
                "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres",
            ],
            "49i": [
                "dtm", "time", "date", "o3", "flags", "hio3",
                "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres",
            ],
        }

        self.dtypes = {
            "tei49c": [pl.Utf8] * 4 + [pl.Float32] * 1 + [pl.Utf8] * 1 + [pl.Int32] * 2 + [pl.Float32] * 6,
            "tei49i": [pl.Utf8] * 5 + [pl.Float32] * 2 + [pl.Int32] * 2 + [pl.Float32] * 6,
            "49i": [pl.Utf8] * 5 + [pl.Float32] * 2 + [pl.Int32] * 2 + [pl.Float32] * 6,
        }

        self.modern_dtypes = {
            "tei49i": [pl.Utf8] * 3 + [pl.Float32] * 1 + [pl.Utf8] * 1 + [pl.Float32] * 1 + [pl.Int32] * 2 + [pl.Float32] * 6,
            "49i": [pl.Utf8] * 3 + [pl.Float32] * 1 + [pl.Utf8] * 1 + [pl.Float32] * 1 + [pl.Int32] * 2 + [pl.Float32] * 6,
        }

    def _read_lines(self, path: Path) -> list[str]:
        """
        Read text lines from a Thermo source file.

        For ``.zip`` inputs, the first non-directory archive member is read.
        For plain files, the content is read directly.

        Args:
            path: Input file path.

        Returns:
            Decoded text lines.
        """
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as archive:
                member_names = [name for name in archive.namelist() if not name.endswith("/")]
                if not member_names:
                    raise ValueError("ZIP archive does not contain a readable file.")
                member_name = member_names[0]
                with archive.open(member_name) as handle:
                    return handle.read().decode("utf-8-sig", errors="replace").splitlines()

        return path.read_text(encoding="utf-8-sig").splitlines()

    def _detect_layout(self, lines: list[str]) -> tuple[str, list[str]]:
        """
        Detect the Thermo file layout from the first non-empty header line.

        Args:
            lines: Raw text lines.

        Returns:
            Tuple of ``(layout, header_fields)`` where layout is one of
            ``"legacy"`` or ``"modern"``.
        """
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            comma_header = [field.strip() for field in stripped.split(",")]
            if comma_header and comma_header[0].lower() == "dtm":
                return "modern", comma_header

            whitespace_header = stripped.split()
            if whitespace_header and whitespace_header[0].lower() == "pcdate":
                return "legacy", whitespace_header

            break

        raise ValueError("Unsupported Thermo file header. Expected 'pcdate' or 'dtm' as first field.")

    def _extract_legacy_rows(
        self,
        lines: list[str],
        schema: list[str],
        path: Path,
    ) -> list[list[str]]:
        """
        Extract whitespace-delimited legacy Thermo rows.

        Args:
            lines: Raw file lines.
            schema: Expected column names.
            path: Input path for logging context.

        Returns:
            Parsed row values as strings.
        """
        expected_fields = len(schema)
        rows: list[list[str]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("pcdate"):
                continue

            parts = stripped.split()
            if len(parts) == expected_fields:
                rows.append(parts)
            else:
                self.logger.warning("%s invalid legacy row: %s", path.name, stripped)

        return rows

    def _extract_modern_rows(
        self,
        lines: list[str],
        schema: list[str],
        path: Path,
    ) -> list[list[str]]:
        """
        Extract comma-delimited modern Thermo rows.

        Args:
            lines: Raw file lines.
            schema: Expected column names.
            path: Input path for logging context.

        Returns:
            Parsed row values as strings.
        """
        expected_fields = len(schema)
        rows: list[list[str]] = []

        reader = csv.reader(io.StringIO("\n".join(lines)))
        header_skipped = False

        for raw_parts in reader:
            parts = [part.strip() for part in raw_parts]
            if not parts or not any(parts):
                continue

            if not header_skipped and parts[0].lower() == "dtm":
                header_skipped = True
                continue

            if len(parts) == expected_fields:
                rows.append(parts)
            else:
                self.logger.warning("%s invalid modern row: %s", path.name, ",".join(parts))

        return rows

    def _coerce_numeric_columns(
        self,
        df: pl.DataFrame,
        dtype_map: dict[str, pl.DataType],
        path: Path,
    ) -> pl.DataFrame:
        """
        Coerce numeric Thermo columns with tolerance for integer-like floats.

        Integer columns sometimes occur in text as values such as ``123.000``.
        These are normalized before casting.

        Args:
            df: Raw DataFrame containing string columns.
            dtype_map: Target dtype mapping by column.
            path: Input path for logging context.

        Returns:
            DataFrame with numeric columns coerced as far as possible.
        """
        int_types = {
            pl.Int8, pl.Int16, pl.Int32, pl.Int64,
            pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
        }
        int_cols = [column for column, dtype in dtype_map.items() if dtype in int_types]

        if int_cols:
            exprs: list[pl.Expr] = []
            for column in int_cols:
                target = dtype_map[column]
                s = pl.col(column).cast(pl.Utf8, strict=False)
                s_clean = (
                    s.str.strip_chars()
                    .str.replace_all(r"\.$", "")
                    .str.replace_all(r"\.0+$", "")
                )
                direct_int = s_clean.cast(target, strict=False)

                f = s.cast(pl.Float64, strict=False)
                f_int = (
                    pl.when(
                        f.is_not_null()
                        & ((f - f.floor()).abs() < 1e-6)
                    )
                    .then(f.floor())
                    .otherwise(None)
                    .cast(target, strict=False)
                )

                exprs.append(pl.coalesce([direct_int, f_int]).alias(column))

            df = df.with_columns(exprs)

        df = df.with_columns(
            [pl.col(column).cast(dtype, strict=False).alias(column) for column, dtype in dtype_map.items()]
        )

        for column in int_cols:
            null_count = df[column].null_count()
            if null_count:
                self.logger.warning(
                    "%s: column '%s' has %s null(s) after int coercion/cast",
                    path.name,
                    column,
                    null_count,
                )

        return df

    def _finalize_legacy_dataframe(self, df: pl.DataFrame, path: Path) -> pl.DataFrame:
        """
        Finalize a legacy Thermo DataFrame by parsing ``pcdate`` + ``pctime``.

        Args:
            df: Parsed legacy data.
            path: Input path for logging context.

        Returns:
            Finalized DataFrame with parsed timestamp and source.
        """
        dtm_column = self.dtm

        df = df.with_columns([
            pl.lit(str(path)).alias("source"),
            pl.format("{} {}", "pcdate", "pctime")
            .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
            .dt.replace_time_zone("UTC")
            .dt.with_time_unit("us")
            .alias(dtm_column),
        ])

        return df

    def _finalize_modern_dataframe(self, df: pl.DataFrame, path: Path) -> pl.DataFrame:
        """
        Finalize a modern Thermo DataFrame by parsing the input ``dtm`` column.

        For backward compatibility, ``pcdate`` and ``pctime`` are derived from
        ``dtm`` so downstream code can continue to work with either style.

        Args:
            df: Parsed modern data.
            path: Input path for logging context.

        Returns:
            Finalized DataFrame with parsed timestamp and source.
        """
        parsed_name = "__parsed_dtm"
        dtm_column = self.dtm

        df = df.with_columns([
            pl.col("dtm")
            .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
            .dt.replace_time_zone("UTC")
            .dt.with_time_unit("us")
            .alias(parsed_name),
        ])

        df = df.with_columns([
            pl.lit(str(path)).alias("source"),
            pl.col(parsed_name).dt.strftime("%Y-%m-%d").alias("pcdate"),
            pl.col(parsed_name).dt.strftime("%H:%M:%S").alias("pctime"),
            pl.col(parsed_name).alias(dtm_column),
        ])

        if dtm_column != "dtm":
            df = df.drop("dtm")

        return df.drop(parsed_name)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a Thermo 49c or 49i text file into a Polars DataFrame.

        Supported layouts:
        - legacy whitespace-delimited files starting with ``pcdate``
        - modern comma-delimited files starting with ``dtm``

        Supported containers:
        - plain text files such as ``.dat`` or ``.csv``
        - ``.zip`` archives containing one text member

        Args:
            path: Path to the input data file.

        Returns:
            Tuple of ``(dataframe, error_message_or_none)``.
        """
        file_type = "49i" if "49i-" in path.name.lower() else self.name
        if file_type not in self.headers:
            file_type = "tei49c"

        try:
            lines = self._read_lines(path)
            layout, _ = self._detect_layout(lines)

            if layout == "modern":
                if file_type not in self.modern_headers:
                    raise ValueError(
                        f"Modern 'dtm' layout is not configured for Thermo type '{file_type}'."
                    )
                schema = self.modern_headers[file_type]
                dtype_map = dict(zip(schema, self.modern_dtypes[file_type]))
                rows = self._extract_modern_rows(lines, schema=schema, path=path)
                if not rows:
                    raise ValueError("No valid modern Thermo data records found.")
                df = pl.DataFrame(rows, schema=schema)
                df = self._coerce_numeric_columns(df, dtype_map=dtype_map, path=path)
                df = self._finalize_modern_dataframe(df, path=path)
            else:
                schema = self.headers[file_type]
                dtype_map = dict(zip(schema, self.dtypes[file_type]))
                rows = self._extract_legacy_rows(lines, schema=schema, path=path)
                if not rows:
                    raise ValueError("No valid legacy Thermo data records found.")
                df = pl.DataFrame(rows, schema=schema)
                df = self._coerce_numeric_columns(df, dtype_map=dtype_map, path=path)
                df = self._finalize_legacy_dataframe(df, path=path)

            if "hio3" in df.columns and df["hio3"].null_count() == len(df):
                df = df.drop("hio3")

            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            self.logger.error("Failed to extract %s: %s", path.name, err)
            return pl.DataFrame(), str(err)
