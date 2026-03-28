from __future__ import annotations

from io import BytesIO
from pathlib import Path

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Fidas(Instrument):
    """
    Processor for PALAS Fidas particle counter data files.

    Supported input formats:
      - legacy ``.parquet`` files
      - current ``.zip`` files containing a single ``.csv`` member
      - plain ``.csv`` files

    The extractor normalizes the timestamp column to ``dtm`` with datatype
    ``pl.Datetime('us', 'UTC')`` and attempts to coerce all measurement columns
    to floating point values while keeping ``id`` and ``checksum`` as strings
    when present.
    """

    _TEXT_SUFFIXES = {".csv", ".zip"}
    _HEADER_TOKENS = {"dtm"}
    _STRING_COLUMNS = {"id", "checksum"}

    def __init__(self, log_file: str = str()):
        super().__init__(name="fidas", log_file=log_file)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a PALAS Fidas file into a Polars DataFrame.

        Args:
            path (Path): Path to a ``.parquet``, ``.csv``, or ``.zip`` file.

        Returns:
            tuple[pl.DataFrame, str | None]: Extracted dataframe and an optional
            error string.
        """
        df = pl.DataFrame()

        try:
            suffix = path.suffix.lower()

            if suffix == ".parquet":
                df = pl.read_parquet(source=path)
            elif suffix in self._TEXT_SUFFIXES:
                df = self._read_csv_or_zip(path)
            else:
                raise ValueError(
                    f"Unsupported Fidas file format '{path.suffix}'. "
                    "Expected .parquet, .csv, or .zip."
                )

            if df.is_empty():
                return df, None

            df = self._normalize_dataframe(df)
            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return df, str(err)

    def _read_csv_or_zip(self, path: Path) -> pl.DataFrame:
        """
        Read a current-format Fidas CSV or ZIP-wrapped CSV file.

        Args:
            path (Path): Path to ``.csv`` or ``.zip`` input.

        Returns:
            pl.DataFrame: Raw dataframe before normalization.
        """
        _lines, has_header, err = self._preprocess_data_file(
            path,
            known_header_tokens=self._HEADER_TOKENS,
        )
        if err:
            raise ValueError(f"Could not inspect CSV header in {path.name}: {err}")

        raw, member_name = self._read_bytes_maybe_zip(path)
        if path.suffix.lower() == ".zip" and member_name and not member_name.lower().endswith(".csv"):
            self.logger.warning(
                f"ZIP member {member_name!r} does not end with .csv; attempting to parse it anyway."
            )

        df = pl.read_csv(
            BytesIO(raw),
            has_header=has_header,
            null_values=["", "nan", "NaN", "NAN"],
            infer_schema_length=5000,
            ignore_errors=False,
            try_parse_dates=False,
        )

        if not has_header:
            raise ValueError(
                f"Fidas text file {path.name} does not expose a recognised header. "
                "Expected first header token to be 'dtm'."
            )

        return df

    def _normalize_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Harmonize dataframe schema across legacy and current Fidas file formats.

        Args:
            df (pl.DataFrame): Raw dataframe.

        Returns:
            pl.DataFrame: Normalized dataframe.
        """
        rename_map = {col: str(col).strip().lstrip("\ufeff") for col in df.columns}
        df = df.rename(rename_map)

        empty_columns = [col for col in df.columns if not str(col).strip()]
        if empty_columns:
            df = df.drop(empty_columns)

        if self.dtm not in df.columns:
            raise ValueError(
                f"Missing '{self.dtm}' column. Available columns: {', '.join(map(str, df.columns[:10]))}"
            )

        exprs: list[pl.Expr] = [self._parse_dtm_expr()]
        for column in df.columns:
            if column == self.dtm:
                continue
            if column in self._STRING_COLUMNS:
                exprs.append(pl.col(column).cast(pl.Utf8, strict=False))
            else:
                exprs.append(pl.col(column).cast(pl.Float64, strict=False))

        df = df.with_columns(exprs)
        return df.sort(self.dtm)

    def _parse_dtm_expr(self) -> pl.Expr:
        """
        Build a robust expression to parse legacy and current Fidas timestamps.

        Returns:
            pl.Expr: Expression yielding ``dtm`` as UTC timestamps.
        """
        source = pl.col(self.dtm).cast(pl.Utf8, strict=False).str.strip_chars()
        return (
            pl.coalesce(
                [
                    source.str.strptime(
                        pl.Datetime(time_zone="UTC"),
                        format="%Y-%m-%d %H:%M:%S%.f%#z",
                        strict=False,
                    ),
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
                ]
            )
            .alias(self.dtm)
        )
