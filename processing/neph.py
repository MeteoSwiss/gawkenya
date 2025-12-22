import logging
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import polars as pl
from charset_normalizer import from_path

from processing.instrument import Instrument, pl_simplify_dtypes

# MAPPINGS = pl.read_csv('cdp2_aurora_mappings.csv', has_header=True, schema_overrides=[pl.String]*4)


class Neph(Instrument):
    def __init__(self, name: str = "neph", log_file: str=str()) -> None:
        super().__init__(name=name, log_file=log_file)
        self.name = name

    def extract_to_dataframe(self, path: Path, dtm: str = "dtm") -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a NEPH file (.dat, .csv, .txt, or .zip) to a Polars DataFrame.

        Args:
            path (Path): Full path to data file.
            dtm (str): Name of datetime column.

        Returns:
            tuple: (DataFrame, error string if any)
        """
        df = pl.DataFrame()

        try:
            # Extract raw content
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as z:
                    data_files = [f for f in z.namelist() if f.endswith(('.dat', '.csv', '.txt'))]
                    if not data_files:
                        # remove empty file and rais error
                        path.unlink()
                        raise ValueError("No data files found in the zip archive.")
                    if len(data_files) > 1:
                        raise ValueError("More than 1 file found in the zip archive.")
                    name = data_files[0]
                    raw = z.read(name)
            elif path.suffix == ".dat":
                raw = path.read_bytes()
            else:
                raise ValueError("File type not recognized.")
            
            # Detect encoding and decode
            res = from_path(path).best()
            encoding = res.encoding if res else "utf-8"
            
            text = raw.decode(encoding)

            # Check if file is empty or only contains blanks or whitespace, remove empty lines
            lines = [line for line in text.splitlines() if line.strip()]
            if not lines:
                # remove empty file and raise error
                path.unlink()
                raise ValueError("File is empty")

            first_row = lines[0].strip().split(",")

            try:
                _ = datetime.strptime(first_row[0], "%Y-%m-%d %H:%M:%S")
                file_type = "acoem_no_header"
                df = pl.read_csv(
                    BytesIO(text.encode("utf-8")),
                    separator=",",
                    has_header=False,
                    try_parse_dates=True
                )
                df = df.rename({df.columns[0]: dtm})
                df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
                df = pl_simplify_dtypes(df)
                return df, None
            except:
                pass

            try:
                _ = datetime.strptime(first_row[0], "%Y-%m-%dT%H:%M:%S")
                file_type = "aurora3000_no_header"
                df = pl.read_csv(
                    BytesIO(text.encode("utf-8")),
                    separator=",",
                    has_header=False,
                    try_parse_dates=True
                )
                df = df.rename({df.columns[0]: dtm})
                df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
                df = pl_simplify_dtypes(df)
                return df, None
            except:
                pass

            if first_row[0] == "37":
                file_type = "acoem_with_header"
                first_row[0] = dtm
                first_row += ['operation', 'period']
                df = pl.read_csv(
                    BytesIO(text.encode("utf-8")),
                    separator=",",
                    has_header=False,
                    skip_rows=1,
                    try_parse_dates=True
                )
                if len(df) > 1:
                    mappings = dict(zip(df.columns, first_row))
                    df = df.rename(mappings)
                else:
                    df = pl.DataFrame()
                    raise ValueError("File contains only header")

            elif first_row[0] == "Date & Time":
                file_type = "aurora3000_with_header"
                df = pl.read_csv(
                    BytesIO(text.encode("utf-8")),
                    separator=",",
                    has_header=True,
                    try_parse_dates=True
                )
                df = df.rename({df.columns[0]: dtm})
            else:                
                raise ValueError("Unrecognized file format")

            df = df.with_columns(pl.col(dtm).cast(pl.Datetime("us", "UTC")))
            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return df, str(err)

        
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
            sm = s.rolling_median(window_size=smooth_window, min_periods=1)

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
            