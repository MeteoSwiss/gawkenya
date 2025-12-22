from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

import polars as pl

from processing.instrument import Instrument


# ----------------------------
# AE31 schema
# ----------------------------

AE31_COLS: list[str] = [
    "id", "date", "time",
    "UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950",
    "flow",
]
AE31_COLS += ["_370", "sens_zero_370", "sens_beam_370", "ref_zero_370", "ref_beam_370", "att_370"]
AE31_COLS += ["_470", "sens_zero_470", "sens_beam_470", "ref_zero_470", "ref_beam_470", "att_470"]
AE31_COLS += ["_520", "sens_zero_520", "sens_beam_520", "ref_zero_520", "ref_beam_520", "att_520"]
AE31_COLS += ["_590", "sens_zero_590", "sens_beam_590", "ref_zero_590", "ref_beam_590", "att_590"]
AE31_COLS += ["_660", "sens_zero_660", "sens_beam_660", "ref_zero_660", "ref_beam_660", "att_660"]
AE31_COLS += ["_880", "sens_zero_880", "sens_beam_880", "ref_zero_880", "ref_beam_880", "att_880"]
AE31_COLS += ["_950", "sens_zero_950", "sens_beam_950", "ref_zero_950", "ref_beam_950", "att_950"]

# Header tokens we consider strong evidence for a header row
_AE31_HEADER_TOKENS: set[str] = {"dtm", *AE31_COLS}

# Regexes used for heuristics / parsing
_ISO_DTM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_DATE_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$")  # e.g. 20-oct-24


class AE31(Instrument):
    """
    Magee AE31 aethalometer raw-file parser.

    Supports (at least) these variants:
      - header row present (some files only include dtm column)
      - header row present but data rows missing the 'id' value (shifted columns)
      - no header row; first field may be dtm OR id
      - timestamp missing -> dtm is deduced from date + time

    Returns:
      (df, err) where err is None on success.
    """

    def __init__(self, name: str = "ae31", log_file: str = str()) -> None:
        super().__init__(name=name, log_file=log_file)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, Optional[str]]:
        """
        Extract AE31 data into a Polars DataFrame.

        Contract (per Instrument.extract_to_dataframe):
            return (df, None) on success
            return (empty_df, "error message") on failure
        """
        try:
            lines, has_header, err = self._preprocess_data_file(path, known_header_tokens=_AE31_HEADER_TOKENS)
            if err:
                return pl.DataFrame(), err
            if not lines:
                return pl.DataFrame(), "Empty file"

            # Iterate CSV records from the decoded lines (zip-aware via Instrument)
            rows_iter = self._iter_csv_rows(lines)
            first = next(rows_iter, None)
            if first is None:
                return pl.DataFrame(), "No CSV records found"

            if has_header:
                header = [h.strip().lstrip("\ufeff") for h in first]
                # drop trailing empty header fields
                while header and header[-1] == "":
                    header.pop()
                schema = header
            else:
                schema = ["dtm"] + AE31_COLS
                # first is actually a data record; put it back into the stream
                rows_iter = self._chain_first(first, rows_iter)

            df = self._build_dataframe_from_rows(rows_iter, schema=schema, has_header=has_header)

            # Ensure dtm exists and is Datetime[us, UTC]
            df = self._ensure_dtm_us_utc(df)

            # Cast remaining columns (tolerant)
            df = self._cast_columns(df)

            return df, None

        except Exception as e:
            # keep message short; logger has full context
            self.logger.error(f"extract_to_dataframe failed for {path}: {e}")
            return pl.DataFrame(), str(e)

    # ----------------------------
    # Helpers
    # ----------------------------

    @staticmethod
    def _iter_csv_rows(lines: list[str]):
        """
        Yield raw CSV rows (list[str]) from decoded lines, skipping blank records.
        """
        for row in csv.reader(lines, skipinitialspace=True):
            if not row:
                continue
            # strip whitespace
            row = [c.strip() for c in row]
            # drop trailing empty fields (e.g. lines ending with a comma)
            while row and row[-1] == "":
                row.pop()
            if not row or all(c == "" for c in row):
                continue
            yield row

    @staticmethod
    def _chain_first(first_row: list[str], iterator):
        yield first_row
        yield from iterator

    @staticmethod
    def _looks_like_iso_dtm(value: Optional[str]) -> bool:
        return bool(value) and bool(_ISO_DTM_RE.match(value.strip()))

    def _build_dataframe_from_rows(
        self,
        rows_iter,
        *,
        schema: list[str],
        has_header: bool,
    ) -> pl.DataFrame:
        """
        Normalize rows to `schema` and return a DataFrame (all values as strings/None initially).
        """
        ncol = len(schema)
        if ncol == 0:
            return pl.DataFrame()

        # indices we use for heuristics / fixes
        id_idx: Optional[int] = None
        dtm_idx: Optional[int] = None
        lower = [c.lower() for c in schema]
        if "id" in lower:
            id_idx = lower.index("id")
        if "dtm" in lower:
            dtm_idx = lower.index("dtm")

        normalized: list[list[Optional[str]]] = []

        for raw in rows_iter:
            cleaned: list[Optional[str]] = [None if c == "" else c for c in raw]

            # No-header variant: if schema starts with dtm, row may start with id.
            if not has_header and dtm_idx == 0:
                first = cleaned[0] if cleaned else None
                if not self._looks_like_iso_dtm(first):
                    cleaned.insert(0, None)

            # Header variant: data row may be missing 'id' (shifted left)
            if has_header and id_idx is not None and len(cleaned) == ncol - 1:
                candidate = cleaned[id_idx] if id_idx < len(cleaned) else None
                if isinstance(candidate, str) and _DATE_RE.match(candidate):
                    cleaned.insert(id_idx, None)

            # Pad / trim
            if len(cleaned) < ncol:
                cleaned.extend([None] * (ncol - len(cleaned)))
            elif len(cleaned) > ncol:
                cleaned = cleaned[:ncol]

            normalized.append(cleaned)

        return pl.DataFrame(normalized, schema=schema, orient="row")

    def _ensure_dtm_us_utc(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Ensure a 'dtm' column exists and is Datetime[us, UTC].
        - If df already has 'dtm', it is parsed.
        - If missing, and date/time exist, dtm is computed from them.
        """
        if df.is_empty():
            # still ensure dtm exists to satisfy downstream compilation steps
            return df.with_columns(pl.lit(None).cast(pl.Datetime("us", "UTC")).alias("dtm")) if "dtm" not in df.columns else df

        has_dtm = "dtm" in df.columns
        has_date_time = "date" in df.columns and "time" in df.columns

        # parse existing dtm if present (ISO-ish)
        parsed_from_dtm = pl.lit(None, dtype=pl.Datetime)
        if has_dtm:
            dtm_str = pl.col("dtm").cast(pl.Utf8)
            parsed_from_dtm = pl.coalesce(
                dtm_str.str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%.f", strict=False),
                dtm_str.str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S", strict=False),
                dtm_str.str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S%.f", strict=False),
                dtm_str.str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False),
            )

        # parse from date+time if available (e.g. 20-oct-24 + 16:05)
        parsed_from_date_time = pl.lit(None, dtype=pl.Datetime)
        if has_date_time:
            date_fixed = pl.col("date").cast(pl.Utf8).str.to_titlecase()
            time_fixed = pl.col("time").cast(pl.Utf8)
            dt_str = pl.concat_str([date_fixed, time_fixed], separator=" ")
            parsed_from_date_time = pl.coalesce(
                dt_str.str.strptime(pl.Datetime, "%d-%b-%y %H:%M:%S", strict=False),
                dt_str.str.strptime(pl.Datetime, "%d-%b-%y %H:%M", strict=False),
                dt_str.str.strptime(pl.Datetime, "%d-%b-%Y %H:%M:%S", strict=False),
                dt_str.str.strptime(pl.Datetime, "%d-%b-%Y %H:%M", strict=False),
            )

        dtm_expr = (
            pl.coalesce(parsed_from_dtm, parsed_from_date_time)
            .dt.cast_time_unit("us")
            .dt.replace_time_zone("UTC")
            .alias("dtm")
        )

        return df.with_columns(dtm_expr)

    @staticmethod
    def _cast_columns(df: pl.DataFrame) -> pl.DataFrame:
        """
        Tolerant casting for known AE31 columns.
        """
        if df.is_empty():
            return df

        int_cols = {"UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950"}

        exprs: list[pl.Expr] = []

        # id/date/time as strings or ints
        if "id" in df.columns:
            exprs.append(pl.col("id").cast(pl.Utf8).alias("id"))
        if "date" in df.columns:
            exprs.append(pl.col("date").cast(pl.Utf8).alias("date"))
        if "time" in df.columns:
            exprs.append(pl.col("time").cast(pl.Utf8).alias("time"))

        # other columns
        for c in df.columns:
            if c in {"dtm", "id", "date", "time"}:
                continue
            if c in int_cols:
                exprs.append(pl.col(c).cast(pl.Int32, strict=False).alias(c))
            else:
                exprs.append(pl.col(c).cast(pl.Float32, strict=False).alias(c))

        return df.with_columns(exprs) if exprs else df


# from __future__ import annotations

# import csv
# import io
# import re
# import zipfile
# from contextlib import contextmanager
# from datetime import datetime
# from io import BytesIO
# from pathlib import Path
# from typing import IO, Optional, Iterator

# import polars as pl
# from charset_normalizer import from_path

# from processing.instrument import Instrument

# """AE-31 Manual
# Section 14.9.3 Expanded Data Format: 
# “date”, “time”, 
# UV [370 nm] result,Blue [470 nm] result, 
# Green [520 nm] result, 
# Yellow [590 nm]result, 
# Red [660 nm] result, 
# IR1 [880 nm, “standard BC”] result,
# IR2 [950 nm] result, 
# air flow (LPM), 
# bypass fraction,
# and then the following columns of data repeated for the seven
# measurement wavelengths:
# sensing zero signal, sensing beam signal, reference zero signal,
# reference beam signal, optical attenuation, air flow (LPM), bypass
# fraction.
# The ‘air flow’ and ‘bypass fraction’ columns are repeated to allow for
# easy visual identification of the separation between the seven sets of
# data columns.
# A typical line in the data file might look like:
# "24-jul-00","16:40", 610 , 604 , 605 , 612 , 617 , 611 , 641 , 3.131 ,-
# .9812 ,-.9814 , 1.1881 , 1.8384 , 1 , 6.4 , 2.704 ,-.9812 ,-.9814 , 4.2483
# , 2.7373 , 1 , 6.4 , 2.45 ,-.9812 ,-.9814 , 2.1716 , 1.9438 , 1 , 6.4 , 2.232
# ,-.9812 ,-.9814 , 2.854 , 3.5259 , 1 , 6.4 , 1.957 ,-.9812 ,-.9814 , 3.3428
# , 2.596 , 1 , 6.4 , 1.452 ,-.9812 ,-.9814 , 4.6719 , 3.3935 , 1 , 6.4 , 1.396
# ,-.9812 ,-.9814 , 2.705 , 2.438 , 1 , 6.4
# """


# # Your existing AE31_COLS (kept as you posted; no dtm here)
# AE31_COLS: list[str] = [
#     "id", "date", "time",
#     "UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950",
#     "flow",
# ]
# AE31_COLS += ["_370", "sens_zero_370", "sens_beam_370", "ref_zero_370", "ref_beam_370", "att_370"]
# AE31_COLS += ["_470", "sens_zero_470", "sens_beam_470", "ref_zero_470", "ref_beam_470", "att_470"]
# AE31_COLS += ["_520", "sens_zero_520", "sens_beam_520", "ref_zero_520", "ref_beam_520", "att_520"]
# AE31_COLS += ["_590", "sens_zero_590", "sens_beam_590", "ref_zero_590", "ref_beam_590", "att_590"]
# AE31_COLS += ["_660", "sens_zero_660", "sens_beam_660", "ref_zero_660", "ref_beam_660", "att_660"]
# AE31_COLS += ["_880", "sens_zero_880", "sens_beam_880", "ref_zero_880", "ref_beam_880", "att_880"]
# AE31_COLS += ["_950", "sens_zero_950", "sens_beam_950", "ref_zero_950", "ref_beam_950", "att_950"]


# _ISO_DTM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")

# """
# '1144,"20-oct-24","16:05",  2087,  2246,  2261,  2317,  2373,  2447,  2456,  3.8, 
# 0.0212, 1.1359, 0.0212, 3.5391,  .53, 65.961, 
# 0.0212,  .8765, 0.0212, 2.5901,  .53, 49.016, 
# 0.0212, 1.5084, 0.0212, 2.5596,  .53, 42.713, 
# 0.0212, 1.2244, 0.0212, 1.1925,  .53, 37.749, 
# 0.0212,  .9628, 0.0212, 1.7056,  .53, 33.773, 
# 0.0212,  .8833, 0.0212,  .9363,  .53, 24.800, 
# 0.0212, 1.6419, 0.0212, 2.0497,  .53, 22.892'
# """
# # AE31_DTYPES: dict[str, pl.DataType] = dict(zip(AE31_COLS,
# #                                                [pl.Utf8] + [pl.Utf8]*2 + [pl.Int32]*7 + [pl.Float32]*43))


# def is_datetime(string: str) -> bool:
#     try:
#         datetime.strptime(string.strip(), "%Y-%m-%dT%H:%M:%S")
#         return True
#     except ValueError:
#         return False

# _DATE_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$")  # e.g. 13-dec-25


# class AE31(Instrument):
#     def __init__(self, name: str = "ae31", log_file: str=str()) -> None:
#         super().__init__(name=name, log_file=log_file)

#     def extract_to_dataframe(self, file: Path) -> tuple[pl.DataFrame, str | None, str | None]:
#         """
#         Wrapper that dispatches to the appropriate extractor depending on whether the file
#         starts with a header row or data rows.

#         Heuristics:
#         - If the first non-empty CSV record contains known column names (e.g. 'dtm', 'UV370',
#           'sens_zero_370', ...), treat it as a header.
#         - Otherwise treat it as a no-header file (which may start with dtm or with id).
#         """
#         first_row: Optional[list[str]] = None

#         with self._open_text(file) as f:
#             reader = csv.reader(f, skipinitialspace=True)
#             for row in reader:
#                 row = [c.strip().lstrip("\ufeff") for c in row]
#                 while row and row[-1] == "":
#                     row.pop()
#                 if not row or all(c == "" for c in row):
#                     continue
#                 first_row = row
#                 break

#         if not first_row:
#             return (pl.DataFrame({name: [] for name in ["dtm"] + AE31_COLS}), None, None)

#         lowered = {c.lower() for c in first_row if c}
#         known = {"dtm"} | {c.lower() for c in AE31_COLS}

#         if lowered & known:
#             return self.extract_to_dataframe_with_header(file)

#         return self.extract_to_dataframe_without_header(file)
    

#     @staticmethod
#     @contextmanager
#     def _open_text(path: Path) -> Iterator[io.TextIOBase]:
#         """
#         Open either a plain text/CSV file, or a .zip containing a single CSV-like member,
#         and yield a text stream. Resources are always closed on exit.
#         """
#         if path.suffix.lower() == ".zip":
#             with zipfile.ZipFile(path) as zf:
#                 members = [n for n in zf.namelist() if not n.endswith("/")]
#                 if not members:
#                     raise ValueError(f"No files found inside zip: {path}")
#                 with zf.open(members[0], "r") as raw:
#                     with io.TextIOWrapper(
#                         raw, encoding="utf-8-sig", errors="replace", newline=""
#                     ) as txt:
#                         yield txt
#         else:
#             with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as txt:
#                 yield txt

#     def extract_to_dataframe_with_header(self, file: Path) -> tuple[pl.DataFrame, str | None, str | None]:
#         """
#         Read an AE31 CSV-like file that includes a header row.

#         Handles three variants:
#         1) Data rows with only dtm (e.g. '2025-12-07T09:05:00,')
#         2) Data rows missing the 'id' field while header includes 'id'
#         3) Fully populated data rows

#         Rules:
#         - Uses the header row for column names (whitespace stripped).
#         - Pads missing trailing fields with nulls.
#         - If exactly one field is missing AND it looks like 'id' is missing, inserts null at 'id'.
#         - Casts:
#             dtm -> Datetime
#             UV370..IR950 -> Int32 (strict=False)
#             everything else (except id/date/time) -> Float32 (strict=False)
#         """
#         with self._open_text(file) as f:
#             reader = csv.reader(f, skipinitialspace=True)

#             try:
#                 header = next(reader)
#             except StopIteration:
#                 raise ValueError(f"Empty file: {file}")

#             # strip whitespace; keep internal empties, but drop trailing empty header fields if any
#             header = [h.strip().lstrip("\ufeff") for h in header]
#             while header and header[-1] == "":
#                 header.pop()

#             ncol = len(header)
#             if ncol == 0:
#                 raise ValueError(f"Header row has no columns: {file}")

#             # find 'id' position if present
#             id_idx: Optional[int] = None
#             for i, name in enumerate(header):
#                 if name.lower() == "id":
#                     id_idx = i
#                     break

#             rows: list[list[Optional[str]]] = []

#             for fields in reader:
#                 if not fields:
#                     continue

#                 fields = [s.strip() for s in fields]

#                 # drop trailing empty fields (typical for lines ending with a comma)
#                 while fields and fields[-1] == "":
#                     fields.pop()

#                 # skip fully empty lines
#                 if not fields or all(s == "" for s in fields):
#                     continue

#                 # Convert empty strings to None (we do it early so later checks are clean)
#                 cleaned: list[Optional[str]] = [None if s == "" else s for s in fields]

#                 # Variant: header includes 'id' but data row is missing it (common in your sample)
#                 # We only do this when the row is exactly 1 field short AND the would-be id field
#                 # looks like a date (e.g. "13-dec-25"), which strongly indicates shifting.
#                 if id_idx is not None and len(cleaned) == ncol - 1:
#                     candidate = cleaned[id_idx] if id_idx < len(cleaned) else None
#                     if isinstance(candidate, str) and _DATE_RE.match(candidate):
#                         cleaned.insert(id_idx, None)

#                 # Pad/trim to header length
#                 if len(cleaned) < ncol:
#                     cleaned.extend([None] * (ncol - len(cleaned)))
#                 elif len(cleaned) > ncol:
#                     cleaned = cleaned[:ncol]

#                 rows.append(cleaned)

#         df = pl.DataFrame(rows, schema=header, orient="row")

#         # Type coercion (tolerant)
#         int_cols = {"UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950"}

#         exprs: list[pl.Expr] = []

#         if "dtm" in df.columns:
#             dtm_expr = pl.coalesce(
#                 pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%.f", strict=False),
#                 pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S", strict=False),
#                 pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S%.f", strict=False),
#                 pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False),
#             ).dt.cast_time_unit("us").dt.replace_time_zone("UTC").alias("dtm")
#             exprs.append(dtm_expr)


#         for c in ("id", "date", "time"):
#             if c in df.columns:
#                 exprs.append(pl.col(c).cast(pl.Utf8).alias(c))

#         for c in df.columns:
#             if c in ("dtm", "id", "date", "time"):
#                 continue
#             if c in int_cols:
#                 exprs.append(pl.col(c).cast(pl.Int32, strict=False).alias(c))
#             else:
#                 exprs.append(pl.col(c).cast(pl.Float32, strict=False).alias(c))

#         if exprs:
#             df = df.with_columns(exprs)

#         return (df, None, None)


#     def extract_to_dataframe_without_header(self, file: Path) -> tuple[pl.DataFrame, str | None, str | None]:
#         """
#         Read AE31 data files WITHOUT a header row.

#         Handles:
#         - rows starting with dtm:  dtm,id,date,time,...
#         - rows starting with id:   id,date,time,... (dtm missing)
#             -> dtm is computed from date + time

#         Output columns:
#         dtm + AE31_COLS

#         dtm is timezone-aware UTC with microsecond resolution.
#         """
#         cols = ["dtm"] + AE31_COLS
#         ncol = len(cols)

#         rows: list[list[Optional[str]]] = []

#         with self._open_text(file) as handle:
#             reader = csv.reader(handle, skipinitialspace=True)
#             for fields in reader:
#                 if not fields:
#                     continue

#                 fields = [s.strip() for s in fields]

#                 # drop trailing empty fields (lines ending with a comma)
#                 while fields and fields[-1] == "":
#                     fields.pop()

#                 if not fields or all(s == "" for s in fields):
#                     continue

#                 cleaned: list[Optional[str]] = [None if s == "" else s for s in fields]

#                 # Detect whether the row starts with dtm
#                 first = cleaned[0] if cleaned else None
#                 has_dtm_first = isinstance(first, str) and bool(_ISO_DTM_RE.match(first))

#                 if has_dtm_first:
#                     # Expect: dtm,id,date,time,...
#                     row = cleaned
#                 else:
#                     # Expect: id,date,time,...  -> insert dtm placeholder at position 0
#                     row = [None] + cleaned

#                 # Pad/trim to expected length
#                 if len(row) < ncol:
#                     row.extend([None] * (ncol - len(row)))
#                 elif len(row) > ncol:
#                     row = row[:ncol]

#                 rows.append(row)
#         df = pl.DataFrame(rows, schema=cols, orient="row")

#         int_cols = {"UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950"}

#         # Parse dtm from either:
#         #  - existing dtm string (ISO-ish)
#         #  - or date+time (e.g. 20-oct-24 + 16:05)
#         date_fixed = pl.col("date").cast(pl.Utf8).str.to_titlecase()  # "20-oct-24" -> "20-Oct-24"
#         time_fixed = pl.col("time").cast(pl.Utf8)

#         dtm_from_iso = pl.coalesce(
#             pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%.f", strict=False),
#             pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S", strict=False),
#             pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S%.f", strict=False),
#             pl.col("dtm").cast(pl.Utf8).str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False),
#         )

#         dtm_from_date_time = pl.coalesce(
#             pl.concat_str([date_fixed, time_fixed], separator=" ")
#             .str.strptime(pl.Datetime, "%d-%b-%y %H:%M:%S", strict=False),
#             pl.concat_str([date_fixed, time_fixed], separator=" ")
#             .str.strptime(pl.Datetime, "%d-%b-%y %H:%M", strict=False),
#         )

#         dtm_expr = (
#             pl.coalesce(dtm_from_iso, dtm_from_date_time)
#             .dt.cast_time_unit("us")
#             .dt.replace_time_zone("UTC")
#             .alias("dtm")
#         )

#         exprs: list[pl.Expr] = [dtm_expr]

#         # id as Int32 (null-safe); keep date/time as strings
#         exprs.append(pl.col("id").cast(pl.Utf8).alias("id"))
#         exprs.append(pl.col("date").cast(pl.Utf8).alias("date"))
#         exprs.append(pl.col("time").cast(pl.Utf8).alias("time"))

#         for c in df.columns:
#             if c in ("dtm", "id", "date", "time"):
#                 continue
#             if c in int_cols:
#                 exprs.append(pl.col(c).cast(pl.Int32, strict=False).alias(c))
#             else:
#                 exprs.append(pl.col(c).cast(pl.Float32, strict=False).alias(c))

#         return (df.with_columns(exprs), None, None)


# if __name__ == "__main__":
#     pass