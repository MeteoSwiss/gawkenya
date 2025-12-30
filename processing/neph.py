from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import polars as pl
from charset_normalizer import from_bytes, from_path

from processing.instrument import Instrument, pl_simplify_dtypes

_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True)
class _NephReadPlan:
    has_header: bool
    skip_rows: int
    rename_first_col_to_dtm: bool
    header_override: list[str] | None  # for the "37,..." case


class Neph(Instrument):
    def __init__(self, name: str = "neph", log_file: str=str()) -> None:
        super().__init__(name=name, log_file=log_file)
        self.name = name

    def extract_to_dataframe(
        self,
        path: Path,
        dtm: str = "dtm",
        *,
        delete_if_empty: bool = True,
    ) -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a NEPH file (.dat or .zip containing .dat/.csv/.txt) to a Polars DataFrame.

        Supported formats:
        - acoem_no_header             : first column is "YYYY-mm-dd HH:MM:SS"
        - aurora3000_no_header        : first column is "YYYY-mm-ddTHH:MM:SS"
        - acoem_with_header-v1        : header row starts with "dtm,..."
        - acoem_with_header (legacy)  : first row starts with "37,..."
        - aurora3000_with_header      : header first column is "Date & Time"
        """
        df = pl.DataFrame()

        try:
            raw, inner_name = self._read_raw_bytes(path, delete_if_empty=delete_if_empty)
            text = self._decode_text(raw, path_for_fallback=path)

            lines = [ln for ln in text.splitlines() if ln.strip()]
            if not lines:
                if delete_if_empty:
                    path.unlink(missing_ok=True)
                raise ValueError("File is empty")

            first_row = [c.strip() for c in lines[0].split(",")]
            if not first_row or not first_row[0]:
                raise ValueError("First row is empty or malformed")

            plan = self._detect_plan(first_row, dtm)

            # Read using utf-8 bytes (Polars reads bytes; we control decoding above)
            buf = BytesIO("\n".join(lines).encode("utf-8", errors="strict"))
            df = pl.read_csv(
                buf,
                separator=",",
                has_header=plan.has_header,
                skip_rows=plan.skip_rows,
                try_parse_dates=True,
            )

            if df.height == 0:
                raise ValueError("No data rows found")

            # If we read without a header but want to apply a header from first_row / override
            if not plan.has_header:
                header = plan.header_override or first_row
                # Map Polars' auto column names to our header labels
                mappings = dict(zip(df.columns, header, strict=False))
                df = df.rename(mappings)

            # Rename dtm column if needed
            if plan.rename_first_col_to_dtm:
                df = df.rename({df.columns[0]: dtm})

            # Parse dtm robustly (handles both " " and "T")
            df = self._ensure_dtm_utc(df, dtm)

            df = pl_simplify_dtypes(df)

            if "4035" in df.columns:
                df = df.with_columns(pl.col("4035").cast(pl.Int32),)
            if "2002" in df.columns:
                df = df.with_columns(pl.col("2002").cast(pl.Int32),)

            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return df, str(err)


    @staticmethod
    def _read_raw_bytes(path: Path, *, delete_if_empty: bool) -> tuple[bytes, str | None]:
        """
        Return (raw_bytes, inner_filename_if_zip).
        """
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as z:
                data_files = [n for n in z.namelist() if n.lower().endswith((".dat", ".csv", ".txt"))]
                if not data_files:
                    if delete_if_empty:
                        path.unlink(missing_ok=True)
                    raise ValueError("No data files found in the zip archive.")
                if len(data_files) > 1:
                    raise ValueError(f"More than 1 file found in the zip archive: {data_files}")
                name = data_files[0]
                raw = z.read(name)
                if not raw:
                    if delete_if_empty:
                        path.unlink(missing_ok=True)
                    raise ValueError("Inner data file in zip is empty")
                return raw, name

        if path.suffix.lower() in {".dat", ".csv", ".txt"}:
            raw = path.read_bytes()
            if not raw:
                if delete_if_empty:
                    path.unlink(missing_ok=True)
                raise ValueError("File is empty")
            return raw, None

        raise ValueError(f"File type not recognized: {path.suffix}")

    @staticmethod
    def _decode_text(raw: bytes, *, path_for_fallback: Path) -> str:
        """
        Detect encoding from the actual content bytes (important for zip members),
        fallback to charset_normalizer.from_path for regular files, then utf-8.
        """
        best = from_bytes(raw).best()
        if best and best.encoding:
            return raw.decode(best.encoding, errors="strict")

        # fallback (sometimes from_bytes can't decide well on tiny samples)
        best2 = from_path(path_for_fallback).best()
        enc = best2.encoding if best2 and best2.encoding else "utf-8"
        return raw.decode(enc, errors="replace")

    @staticmethod
    def _detect_plan(first_row: list[str], dtm: str) -> _NephReadPlan:
        first_cell = first_row[0]

        # acoem_with_header-v1
        if first_cell == "dtm":
            return _NephReadPlan(
                has_header=True,
                skip_rows=0,
                rename_first_col_to_dtm=False,  # already "dtm"
                header_override=None,
            )

        # legacy acoem_with_header: first row begins with "37"
        if first_cell == "37":
            header = first_row.copy()
            header[0] = dtm
            header += ["operation", "period"]  # keep your legacy behavior
            return _NephReadPlan(
                has_header=False,
                skip_rows=1,
                rename_first_col_to_dtm=False,  # we set it above
                header_override=header,
            )

        # aurora3000_with_header
        if first_cell == "Date & Time":
            return _NephReadPlan(
                has_header=True,
                skip_rows=0,
                rename_first_col_to_dtm=True,  # "Date & Time" -> dtm
                header_override=None,
            )

        # no-header variants (first cell looks like datetime)
        if _DT_RE.match(first_cell):
            return _NephReadPlan(
                has_header=False,
                skip_rows=0,
                rename_first_col_to_dtm=True,
                header_override=None,
            )

        raise ValueError("Unrecognized file format")

    @staticmethod
    def _ensure_dtm_utc(df: pl.DataFrame, dtm: str) -> pl.DataFrame:
        if dtm not in df.columns:
            raise ValueError(f"Missing datetime column '{dtm}'")

        # If already parsed as Datetime, just enforce timezone + unit
        if df.schema[dtm] == pl.Datetime:
            return df.with_columns(pl.col(dtm).dt.replace_time_zone("UTC").cast(pl.Datetime("us", "UTC")))

        # If Utf8 (common), parse both patterns; coalesce picks the first successful parse
        if df.schema[dtm] == pl.Utf8:
            parsed = pl.coalesce(
                [
                    pl.col(dtm).str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False),
                    pl.col(dtm).str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S", strict=False),
                ]
            )
            return df.with_columns(parsed.alias(dtm).dt.replace_time_zone("UTC").cast(pl.Datetime("us", "UTC")))

        # Last resort: try a cast then enforce UTC (covers some odd inferred types)
        return df.with_columns(pl.col(dtm).cast(pl.Datetime).dt.replace_time_zone("UTC").cast(pl.Datetime("us", "UTC")))


    # def extract_to_dataframe(self, path: Path, dtm: str = "dtm") -> tuple[pl.DataFrame, str | None]:
    #     """
    #     Extract data from a NEPH file (.dat, .csv, .txt, or .zip) to a Polars DataFrame.

    #     Args:
    #         path (Path): Full path to data file.
    #         dtm (str): Name of datetime column.

    #     Returns:
    #         tuple: (DataFrame, error string if any)
    #     """
    #     df = pl.DataFrame()

    #     try:
    #         # Extract raw content
    #         if path.suffix == ".zip":
    #             with zipfile.ZipFile(path, "r") as z:
    #                 data_files = [f for f in z.namelist() if f.endswith(('.dat', '.csv', '.txt'))]
    #                 if not data_files:
    #                     # remove empty file and rais error
    #                     path.unlink()
    #                     raise ValueError("No data files found in the zip archive.")
    #                 if len(data_files) > 1:
    #                     raise ValueError("More than 1 file found in the zip archive.")
    #                 name = data_files[0]
    #                 raw = z.read(name)
    #         elif path.suffix == ".dat":
    #             raw = path.read_bytes()
    #         else:
    #             raise ValueError("File type not recognized.")
            
    #         # Detect encoding and decode
    #         res = from_path(path).best()
    #         encoding = res.encoding if res else "utf-8"
            
    #         text = raw.decode(encoding)

    #         # Check if file is empty or only contains blanks or whitespace, remove empty lines
    #         lines = [line for line in text.splitlines() if line.strip()]
    #         if not lines:
    #             # remove empty file and raise error
    #             path.unlink()
    #             raise ValueError("File is empty")

    #         first_row = lines[0].strip().split(",")

    #         try:
    #             _ = datetime.strptime(first_row[0], "%Y-%m-%d %H:%M:%S")
    #             # file_type = "acoem_no_header"
    #             df = pl.read_csv(
    #                 BytesIO(text.encode("utf-8")),
    #                 separator=",",
    #                 has_header=False,
    #                 try_parse_dates=True
    #             )
    #             df = df.rename({df.columns[0]: dtm})
    #             df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
    #             df = pl_simplify_dtypes(df)
    #             return df, None
    #         except:
    #             pass

    #         try:
    #             _ = datetime.strptime(first_row[0], "%Y-%m-%dT%H:%M:%S")
    #             # file_type = "aurora3000_no_header"
    #             df = pl.read_csv(
    #                 BytesIO(text.encode("utf-8")),
    #                 separator=",",
    #                 has_header=False,
    #                 try_parse_dates=True
    #             )
    #             df = df.rename({df.columns[0]: dtm})
    #             df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
    #             df = pl_simplify_dtypes(df)
    #             return df, None
    #         except:
    #             pass

    #         if first_row[0] == "dtm":
    #             # file_type = "acoem_with_header-v1"
    #             df = pl.read_csv(
    #                 BytesIO(text.encode("utf-8")),
    #                 separator=",",
    #                 has_header=False,
    #                 skip_rows=1,
    #                 try_parse_dates=True
    #             )
    #             if len(df) > 1:
    #                 mappings = dict(zip(df.columns, first_row))
    #                 df = df.rename(mappings)
    #             else:
    #                 df = pl.DataFrame()
    #                 raise ValueError("File contains only header")

    #         elif first_row[0] == "37":
    #             # file_type = "acoem_with_header"
    #             first_row[0] = dtm
    #             first_row += ['operation', 'period']
    #             df = pl.read_csv(
    #                 BytesIO(text.encode("utf-8")),
    #                 separator=",",
    #                 has_header=False,
    #                 skip_rows=1,
    #                 try_parse_dates=True
    #             )
    #             if len(df) > 1:
    #                 mappings = dict(zip(df.columns, first_row))
    #                 df = df.rename(mappings)
    #             else:
    #                 df = pl.DataFrame()
    #                 raise ValueError("File contains only header")

    #         elif first_row[0] == "Date & Time":
    #             # file_type = "aurora3000_with_header"
    #             df = pl.read_csv(
    #                 BytesIO(text.encode("utf-8")),
    #                 separator=",",
    #                 has_header=True,
    #                 try_parse_dates=True
    #             )
    #             df = df.rename({df.columns[0]: dtm})
    #         else:                
    #             raise ValueError("Unrecognized file format")

    #         df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
    #         df = pl_simplify_dtypes(df)
    #         return df, None

    #     except Exception as err:
    #         self.logger.error(f"Failed to extract {path.name}: {err}")
    #         return df, str(err)

        
    def apply_zero_span_flags(
        self,
        df: pl.DataFrame,
        dtm: str = "dtm",
        primary: str = "5002",
        diff_quantile: float = 0.995,
        smooth_window: int = 3,
    ) -> pl.DataFrame:
        """
        Detect ZERO/SPAN checks as step changes and add/update per-variable flag columns.

        Rules (NE-300 specific):
          - Positive step  -> SPAN check  (flag 4)
          - Negative step  -> ZERO check  (flag 3)
        Output:
          - For each target column X, adds/updates `f_X` with 0 outside checks,
            3 during ZERO, 4 during SPAN.

        Heuristics:
          - Uses a short rolling median (default 3 samples) to suppress noise.
          - Threshold = abs(diff) quantile at `diff_quantile` (default 99.5th),
            with a robust MAD-based floor so normal diurnal swings don't trigger.
          - The last detected event persists until the next event (piecewise-constant state).

        Parameters
        ----------
        df : pl.DataFrame
            Input table; must contain `dtm` and one or more numeric-variable columns.
        dtm : str
            Datetime column name.
        primary : str
            Always include this column (default "5002").
        diff_quantile : float
            Quantile of |diff| used as step threshold (default 0.995).
        smooth_window : int
            Rolling-median window (samples) before differencing (default 3).

        Returns
        -------
        pl.DataFrame
            Data with added `f_<col>` columns for flags.
        """
        if dtm not in df.columns:
            raise ValueError(f"'{dtm}' column not found")

        # Sort by time for consistent differencing
        df = df.sort(dtm)

        # Select 5002 + all columns whose names are numeric and > 1_000_000
        def _is_big_numeric_name(c: str) -> bool:
            return c.isdigit() and int(c) > 1_000_000

        targets = []
        if primary in df.columns:
            targets.append(primary)
        targets.extend([c for c in df.columns if _is_big_numeric_name(c)])

        if not targets:
            # Nothing to do
            return df

        for col in targets:
            # Work in float for numeric stability
            s = pl.col(col).cast(pl.Float64)

            # Light smoothing to reduce false triggers from noise
            sm = s.rolling_median(window_size=smooth_window, min_samples=1)

            # First difference and absolute magnitude
            diff = (sm - sm.shift(1))
            adiff = diff.abs()

            # Compute robust threshold (scalar)
            thr_q = df.select(adiff.quantile(diff_quantile, interpolation="nearest")).item()
            mad = df.select((adiff - adiff.median()).abs().median()).item()
            thr = max(thr_q or 0.0, (mad or 0.0) * 6.0, 1e-12)

            # Event: +step -> 4 (SPAN), -step -> 3 (ZERO), else 0
            evt = (
                pl.when(adiff > thr)
                  .then(pl.when(diff > 0).then(pl.lit(4)).otherwise(pl.lit(3)))
                  .otherwise(pl.lit(0))
                  .alias(f"_evt_{col}")
            )

            df = df.with_columns(evt)

            # Propagate last non-zero event forward → piecewise-constant state
            # 0→None→forward_fill→0 to keep pre-first-event at 0
            state = (
                pl.when(pl.col(f"_evt_{col}") == 0).then(None).otherwise(pl.col(f"_evt_{col}"))
                  .forward_fill()
                  .fill_null(0)
                  .cast(pl.Int8)
                  .alias(f"f_{col}")
            )
            df = df.with_columns(state).drop(f"_evt_{col}")

        return df
            