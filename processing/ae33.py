from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional

import polars as pl

from toolbox.utils import pl_simplify_dtypes
from processing.instrument import Instrument


class AE33(Instrument):
    """
    Processor for AE33 aethalometer data files.

    Input:
      - .zip containing a single pipe-delimited .dat (optionally with comment lines starting with '#')
      - or a raw .dat file

    Output contract (consistent with Instrument):
      - returns (df, None) on success
      - returns (empty_df, "error message") on failure

    Notes:
      - Uses schema_overrides (mapping) instead of positional dtypes to satisfy Pylance.
      - Parses the dtm column as Datetime[us, UTC].
    """

    _COLS_TEMPLATE: tuple[str, ...] = (
        "Inst_SN", "row_id", "DateTime_1", "{dtm}", "unclear", "DateTime_2",
        "RefCh1", "Sen1Ch1", "Sen2Ch1", "RefCh2", "Sen1Ch2", "Sen2Ch2",
        "RefCh3", "Sen1Ch3", "Sen2Ch3", "RefCh4", "Sen1Ch4", "Sen2Ch4",
        "RefCh5", "Sen1Ch5", "Sen2Ch5", "RefCh6", "Sen1Ch6", "Sen2Ch6",
        "RefCh7", "Sen1Ch7", "Sen2Ch7",
        "BC11", "BC12", "BC1", "BC21", "BC22", "BC2", "BC31", "BC32", "BC3",
        "BC41", "BC42", "BC4", "BC51", "BC52", "BC5", "BC61", "BC62", "BC6",
        "BC71", "BC72", "BC7",
        "K1", "K2", "K3", "K4", "K5", "K6", "K7", "unclear_2", "Pres", "Temp",
        "Flow1", "Flow2", "FlowC", "Temp_1", "Temp_2", "Temp_3",
        "Stat_1", "Stat_2", "Stat_3", "Stat_4", "Stat_5",
        "TapeAdvCount", "unclear_3", "unclear_4", "unclear_5", "unclear_6",
    )

    # Length must match _COLS_TEMPLATE after formatting.
    _DTYPES: list[pl.DataType] = (
        [pl.Utf8, pl.Int64, pl.Utf8, pl.Utf8, pl.Int32, pl.Utf8]
        + [pl.Int64] * 42
        + [pl.Float64] * 10
        + [pl.Int64] * 3
        + [pl.Float64] * 3
        + [pl.Int64] * 10
    )

    _DTM_FORMAT: str = "%m/%d/%Y %I:%M:%S %p"

    def __init__(self, log_file: Optional[str] = None) -> None:
        super().__init__(name="ae33", log_file=log_file)

    @staticmethod
    def _read_bytes_zip_or_file(path: Path) -> tuple[bytes, Optional[str]]:
        """
        Read bytes from `path`, supporting .zip.

        For zip files:
          - prefer a .dat member if present
          - otherwise fall back to the first non-directory member

        Returns:
            (raw_bytes, member_name_if_zip)
        """
        if path.suffix.lower() != ".zip":
            return path.read_bytes(), None

        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n]
            if not members:
                raise ValueError(f"No files found inside zip: {path}")

            dats = [n for n in members if n.lower().endswith(".dat")]
            if len(dats) == 1:
                member = dats[0]
            elif len(dats) > 1:
                # prefer a matching stem (zip stem or parent stem)
                stem = path.stem.lower()
                matches = [n for n in dats if Path(n).stem.lower() == stem]
                member = matches[0] if matches else dats[0]
            else:
                member = members[0]

            return zf.read(member), member

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        df = pl.DataFrame()
        dtm = self.dtm

        try:
            cols = [c.format(dtm=dtm) for c in self._COLS_TEMPLATE]

            if len(cols) != len(self._DTYPES):
                raise ValueError(f"AE33 schema mismatch: cols={len(cols)} dtypes={len(self._DTYPES)}")

            schema_overrides = dict(zip(cols, self._DTYPES, strict=True))

            raw, member = self._read_bytes_zip_or_file(path)

            df = pl.read_csv(
                source=io.BytesIO(raw),      # Pylance-friendly
                has_header=False,
                separator="|",
                comment_prefix="#",
                new_columns=cols,
                schema_overrides=schema_overrides,
                ignore_errors=True,
            )

            # Parse dtm and standardize to Datetime[us, UTC]
            df = df.with_columns(
                pl.col(dtm)
                .cast(pl.Utf8)
                .str.strptime(pl.Datetime, self._DTM_FORMAT, strict=False)
                .dt.cast_time_unit("us")
                .dt.replace_time_zone("UTC")
                .alias(dtm)
            )

            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            src = f"{path}{'::' + member if member else ''}"
            msg = f"{type(err).__name__}: {err}"
            self.logger.error(f"Failed to extract {src}: {msg}")
            return df, msg
