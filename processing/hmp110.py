from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

import polars as pl

from processing.instrument import Instrument


_HMP110_DEFAULT_COLS: list[str] = ["dtm", "T", "RH", "Td"]
_HMP110_HEADER_TOKENS: set[str] = {c.lower() for c in _HMP110_DEFAULT_COLS}


class HMP110(Instrument):
    """
    Extractor for Vaisala HMP110 data files.

    Expected file content (usually with header):
        dtm,T,RH,Td
        2025-12-17 17:59:01,26.58,35.37,10.04
        ...

    Notes:
      - Supports plain files and .zip files (first non-directory member) via Instrument helpers.
      - `dtm` is parsed as timezone-aware Datetime[us, UTC].
      - Missing/short rows are padded with nulls (won't crash).
    """

    def __init__(self, name: str = "hmp110", dtm: str = "dtm", log_file: Optional[str] = None) -> None:
        super().__init__(name=name, dtm=dtm, log_file=log_file)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, Optional[str]]:
        """
        Contract (per Instrument.extract_to_dataframe):
            return (df, None) on success
            return (empty_df, "error message") on failure
        """
        try:
            lines, has_header, err = self._preprocess_data_file(path, known_header_tokens=_HMP110_HEADER_TOKENS)
            if err:
                return pl.DataFrame(), err
            if not lines:
                return pl.DataFrame(), "Empty file"

            text = "\n".join(lines)
            reader = csv.reader(io.StringIO(text), skipinitialspace=True)

            # Determine header
            header: list[str]
            first_record: Optional[list[str]] = None
            for rec in reader:
                if rec and any((c or "").strip() for c in rec):
                    first_record = [c.strip().lstrip("\ufeff") for c in rec]
                    break

            if first_record is None:
                return pl.DataFrame(), "No CSV records found"

            rows: list[list[Optional[str]]] = []

            if has_header:
                header = [h.strip() for h in first_record if h.strip() != ""]
            else:
                header = _HMP110_DEFAULT_COLS
                # treat the first record as data
                rows.append([None if (c.strip() == "") else c.strip() for c in first_record])

            # Normalize header
            header = [h.lstrip("\ufeff") for h in header]
            if not header:
                header = _HMP110_DEFAULT_COLS

            ncol = len(header)

            # Read remaining rows
            for rec in reader:
                if not rec:
                    continue
                rec = [c.strip() for c in rec]
                # drop trailing empty fields
                while rec and rec[-1] == "":
                    rec.pop()
                if not rec or all(c == "" for c in rec):
                    continue

                cleaned: list[Optional[str]] = [None if c == "" else c for c in rec]

                # pad/trim
                if len(cleaned) < ncol:
                    cleaned.extend([None] * (ncol - len(cleaned)))
                elif len(cleaned) > ncol:
                    cleaned = cleaned[:ncol]

                rows.append(cleaned)

            df = pl.DataFrame(rows, schema=header, orient="row")

            # Ensure required columns exist
            if "dtm" not in df.columns:
                return pl.DataFrame(), "Missing required column 'dtm'"

            # dtm parsing: support "YYYY-MM-DD HH:MM:SS[.fff]" and a few fallbacks
            dtm_expr = (
                pl.coalesce(
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S%.f", strict=False),
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False),
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M", strict=False),
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d", strict=False),
                    # also tolerate ISO-like with T
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%.f", strict=False),
                    pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S", strict=False),
                )
                .dt.cast_time_unit("us")
                .dt.replace_time_zone("UTC")
                .alias("dtm")
            )

            exprs: list[pl.Expr] = [dtm_expr]

            # Cast known numeric columns if present
            for c in df.columns:
                if c == "dtm":
                    continue
                # T/RH/Td and any additional columns are numeric floats
                exprs.append(pl.col(c).cast(pl.Float32, strict=False).alias(c))

            df = df.with_columns(exprs)

            return df, None

        except Exception as e:
            return pl.DataFrame(), str(e)
