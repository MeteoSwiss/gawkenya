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


# Fixed Aurora3000 schema for "no-header" CSVs (identified via filename)
_AURORA3000_HEADER: list[str] = [
    "dtm",
    "ssp1",
    "ssp2",
    "ssp3",
    "sbsp1",
    "sbsp2",
    "sbsp3",
    "sample_temp",
    "enclosure_temp",
    "RH",
    "pressure",
    "major_state",
    "DIO_state",
]
CALIBRATION_GAS_CONSTANTS_CO2: dict[str, float] = {"450": 71.67, "525": 38.68, "635": 18.07}

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

            # Use filename (zip member name if present) as a key for format detection
            file_key = (inner_name or path.name).lower()

            plan = self._detect_plan(first_row, dtm, file_key=file_key)

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

            # Apply header override ONLY when we actually have one.
            # (For true no-header formats without a known schema, keep Polars' default column names.)
            if plan.header_override is not None:
                if len(plan.header_override) != len(df.columns):
                    raise ValueError(
                        f"Header override length mismatch: "
                        f"{len(plan.header_override)} != {len(df.columns)}"
                    )
                mappings = dict(zip(df.columns, plan.header_override, strict=True))
                df = df.rename(mappings)

            # Rename dtm column if needed (avoid no-op renames)
            if plan.rename_first_col_to_dtm and df.columns and df.columns[0] != dtm:
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
    def _detect_plan(first_row: list[str], dtm: str, *, file_key: str = "") -> _NephReadPlan:
        first_cell = first_row[0]
        key = file_key.lower()
        is_aurora3000 = "aurora3000" in key

        # acoem_with_header-v1 (also matches aurora3000 header variant where first col is "dtm")
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

        # aurora3000_with_header (older exports)
        if first_cell == "Date & Time":
            return _NephReadPlan(
                has_header=True,
                skip_rows=0,
                rename_first_col_to_dtm=True,  # "Date & Time" -> dtm
                header_override=None,
            )

        # no-header variants (first cell looks like datetime)
        if _DT_RE.match(first_cell):
            # Aurora3000 no-header CSVs: schema is fixed; identify by filename
            if is_aurora3000:
                return _NephReadPlan(
                    has_header=False,
                    skip_rows=0,
                    rename_first_col_to_dtm=False,  # header override already sets "dtm"
                    header_override=_AURORA3000_HEADER.copy(),
                )

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
    

    def auto_flag_ne300_data(
        self,
        df: pl.DataFrame,
        *,
        dtm: str = "dtm",
        key_4035: str = "4035",
        minutes_after_transition: int = 10,
        low: int = 1_000_000,
        high: int = 8_000_000,
        flag_col_prefix: str = "f_",
        overwrite: bool = False,
        assume_null_is_normal: bool = True,
    ) -> pl.DataFrame:
        """Auto-flag NE300 measurement channels based on the 4035 state column.

        Mapping (requested)
        -------------------
        4035 -> key
            0 -> 0 (valid)
            1 -> 3 (zero)
            2 -> 4 (span)

        Transition rule
        ---------------
        The first `minutes_after_transition` minutes after any transition *from* or *to*
        {0,1,2} in 4035 are flagged as 2 (uncertain).

        Flag columns
        ------------
        For each numeric channel column with `low <= nnn <= high`, create or update
        `f_<nnn>` additively (fill only NULLs) unless `overwrite=True`.
        """
        if dtm not in df.columns or key_4035 not in df.columns:
            return df

        df = df.sort(dtm)

        k = pl.col(key_4035)
        if assume_null_is_normal:
            k = pl.coalesce(k, pl.lit(0))
        k = k.cast(pl.Int64)
        k_prev = k.shift(1)

        # Transition when 4035 changes and either side is in {0,1,2}
        m_transition = (
            k_prev.is_not_null()
            & (k != k_prev)
            & (k.is_in([0, 1, 2]) | k_prev.is_in([0, 1, 2]))
        )

        transition_time = pl.when(m_transition).then(pl.col(dtm)).otherwise(None)
        last_transition_time = transition_time.forward_fill()

        window = pl.duration(minutes=minutes_after_transition)
        m_uncertain = (
            last_transition_time.is_not_null()
            & (pl.col(dtm) >= last_transition_time)
            & ((pl.col(dtm) - last_transition_time) <= window)
        )

        base_flag = (
            pl.when(k == 0)
            .then(0)
            .when(k == 1)
            .then(3)
            .when(k == 2)
            .then(4)
            .otherwise(None)
        )

        auto_flag = pl.when(m_uncertain).then(2).otherwise(base_flag).cast(pl.Int8)

        updates: list[pl.Expr] = []
        for c in df.columns:
            if c.isdigit():
                n = int(c)
                if low <= n <= high:
                    fcol = f"{flag_col_prefix}{c}"
                    cur = (
                        pl.col(fcol).cast(pl.Int8)
                        if fcol in df.columns
                        else pl.lit(None, dtype=pl.Int8)
                    )

                    if overwrite:
                        expr = pl.when(auto_flag.is_not_null()).then(auto_flag).otherwise(cur).alias(fcol)
                    else:
                        expr = pl.when(cur.is_null()).then(auto_flag).otherwise(cur).alias(fcol)

                    updates.append(expr)

        return df.with_columns(updates) if updates else df


    def auto_flag_aurora3000_data(
        self,
        df: pl.DataFrame,
        *,
        dtm: str = "dtm",
        key_major_state: str = "major_state",
        minutes_after_transition: int = 10,
        flag_col_prefix: str = "f_",
        overwrite: bool = False,
        assume_null_is_normal: bool = True,
    ) -> pl.DataFrame:
        """Auto-flag Aurora 3000 channels based on the major_state column.

        Mapping (requested)
        -------------------
        major_state -> f_flag
            0        -> 0 (valid)
            1, 3     -> 4 (span)
            2, 5     -> 3 (zero)

        Transition rule
        ---------------
        The first `minutes_after_transition` minutes after any change in major_state
        are flagged as 2 (uncertain), overriding the base mapping for that window.

        Flag columns
        ------------
        Adds/updates `f_<col>` for all *data* columns (everything except dtm,
        major_state, DIO_state, and existing f_* columns). Updates additively unless
        overwrite=True.
        """
        if dtm not in df.columns or key_major_state not in df.columns:
            return df

        df = df.sort(dtm)

        # Aurora major_state often arrives as float-like values (e.g., "0.000").
        # Use rounding to robustly map to 0..7.
        k_raw = pl.col(key_major_state)
        if assume_null_is_normal:
            k_raw = pl.coalesce(k_raw, pl.lit(0))

        k = k_raw.cast(pl.Float64).round(0).cast(pl.Int64)
        k_prev = k.shift(1)

        # Transition whenever major_state changes (first row excluded)
        m_transition = k_prev.is_not_null() & (k != k_prev)

        transition_time = pl.when(m_transition).then(pl.col(dtm)).otherwise(None)
        last_transition_time = transition_time.forward_fill()

        window = pl.duration(minutes=minutes_after_transition)
        m_uncertain = (
            last_transition_time.is_not_null()
            & (pl.col(dtm) >= last_transition_time)
            & ((pl.col(dtm) - last_transition_time) <= window)
        )

        base_flag = (
            pl.when(k == 0)
            .then(0)
            .when(k.is_in([1, 3]))
            .then(4)
            .when(k.is_in([2, 5]))
            .then(3)
            .otherwise(None)
        )

        auto_flag = pl.when(m_uncertain).then(2).otherwise(base_flag).cast(pl.Int8)

        # Target columns: all non-helper columns
        exclude = {dtm, key_major_state, "DIO_state"}
        updates: list[pl.Expr] = []

        for c in df.columns:
            if c in exclude or c.startswith(flag_col_prefix):
                continue

            fcol = f"{flag_col_prefix}{c}"
            cur = pl.col(fcol).cast(pl.Int8) if fcol in df.columns else pl.lit(None, dtype=pl.Int8)

            if overwrite:
                expr = pl.when(auto_flag.is_not_null()).then(auto_flag).otherwise(cur).alias(fcol)
            else:
                expr = pl.when(cur.is_null()).then(auto_flag).otherwise(cur).alias(fcol)

            updates.append(expr)

        return df.with_columns(updates) if updates else df


    def propagate_zero_span_flags_from_5002(
        self,
        df: pl.DataFrame,
        *,
        dtm: str = "dtm",
        source_flag_col: str | None = None,
        low: int = 1_000_000,
        high: int = 8_000_000,
        flag_col_prefix: str = "f_",
        overwrite: bool = False,
    ) -> pl.DataFrame:
        """Propagate ZERO/SPAN/UNCERTAIN flags (2/3/4) from 5002 to NE300 channels.

        This is intended for your ezFlag workflow, where you manually flag variable "5002"
        and want to copy those flags to the full-parameter range.

        - Creates `f_<nnn>` columns if missing.
        - Copies only codes {2,3,4} from `source_flag_col` at matching rows.
        - Preserves existing manual flags by default:
            overwrite=False (default): fill only where `f_<nnn>` is NULL.
            overwrite=True : set 2/3/4 wherever the source has 2/3/4.

        Parameters
        ----------
        df:
            Input table; should contain the source flag column and NE300 parameter columns.
        source_flag_col:
            Defaults to `f_5002` if present, otherwise must be provided.
        """
        src = source_flag_col
        if src is None:
            if "f_5002" in df.columns:
                src = "f_5002"
            else:
                return df

        if src not in df.columns:
            return df

        m_234 = pl.col(src).is_in([2, 3, 4])

        updates: list[pl.Expr] = []
        for c in df.columns:
            if c.isdigit():
                n = int(c)
                if low <= n <= high:
                    fcol = f"{flag_col_prefix}{c}"
                    cur = pl.col(fcol).cast(pl.Int8) if fcol in df.columns else pl.lit(None, dtype=pl.Int8)

                    if overwrite:
                        expr = pl.when(m_234).then(pl.col(src).cast(pl.Int8)).otherwise(cur).alias(fcol)
                    else:
                        expr = pl.when(cur.is_null() & m_234).then(pl.col(src).cast(pl.Int8)).otherwise(cur).alias(fcol)

                    updates.append(expr)

        return df.with_columns(updates) if updates else df


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
