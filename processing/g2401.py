from pathlib import Path
import polars as pl
from charset_normalizer import from_path
# import pandas as pd
import re
import io
import zipfile
from toolbox.utils import pl_simplify_dtypes
from processing.instrument import Instrument


class G2401(Instrument):
    """
    Processor for Picarro G2401 data files.
    Attempts to auto-detect encoding and extract datetime.
    """

    def __init__(self, log_file: str = str()):
        super().__init__(name="g2401", log_file=log_file)
        self.dtypes = {
            'DataLog_User_Sync': [pl.Utf8]*2 + [pl.Float64]*4 + [pl.Int64]*2 + [pl.Float64]*14,
        }

    def auto_flag_g2401_data(
        self,
        df: pl.DataFrame,
        *,
        key_valve: str = "solenoid_valves",
        dtm: str = "dtm",
        flag_col_prefix: str = "f_",
        overwrite: bool = False,
    ) -> pl.DataFrame:
        """Flag numeric Picarro data from the solenoid valve state.

        solenoid_valves = 0 -> 0 (valid); = 1 -> 4 (span);
        > 1 -> 2 (uncertain). Missing, negative or unparseable states
        remain unclassified (null). Timing/source metadata and the valve
        state itself are not measurement variables.

        Existing non-null flags (including manual QC flags) are preserved
        unless overwrite=True.
        """
        if key_valve not in df.columns:
            return df

        valve = pl.col(key_valve).cast(pl.Float64, strict=False)
        suggested = (
            pl.when(valve == 0).then(pl.lit(0, dtype=pl.Int8))
            .when(valve == 1).then(pl.lit(4, dtype=pl.Int8))
            .when(valve > 1).then(pl.lit(2, dtype=pl.Int8))
            .otherwise(pl.lit(None, dtype=pl.Int8))
        )

        excluded = {
            dtm, "source", key_valve, "DATE", "TIME",
            "FRAC_DAYS_SINCE_JAN1", "FRAC_HRS_SINCE_JAN1",
            "JULIAN_DAYS", "EPOCH_TIME",
        }
        updates: list[pl.Expr] = []
        for name, dtype in df.schema.items():
            if (name in excluded or name.startswith(flag_col_prefix)
                    or not dtype.is_numeric()):
                continue
            flag_name = f"{flag_col_prefix}{name}"
            existing = (
                pl.col(flag_name).cast(pl.Int8, strict=False)
                if flag_name in df.columns
                else pl.lit(None, dtype=pl.Int8)
            )
            updated = (
                pl.when(suggested.is_not_null()).then(suggested).otherwise(existing)
                if overwrite
                else pl.when(existing.is_null()).then(suggested).otherwise(existing)
            )
            updates.append(updated.alias(flag_name))
        return df.with_columns(updates) if updates else df

    def extract_to_dataframe(self, path: Path, dtm="dtm") -> tuple[pl.DataFrame, str | None]:
        """
        Extract a Picarro G2401 DataLog_User_Sync file into a Polars dataframe.

        NB: Polars doesn't support fwf at this point. Workaround: Read file, replace multiple spaces with comma, and then read as byte stream.

        Args:
            path (Path): Path to the input text file.
            dtm (str): Name for dateTime column to be generated.

        Returns:
            tuple: (DataFrame, error string or None)
        """
        if bool(re.search("DataLog_User_Sync", str(path))):
            # self.logger.info(f"Extracting file {path}.")

            try:
                # if bool(re.search('.zip', str(path))):
                if path.suffix == '.zip':
                    zf = zipfile.ZipFile(path)
                    source = re.sub(" +", ",", zf.open(zf.namelist()[0]).read().decode('utf-8'))
                else:
                    source = re.sub(" +", ",", open(path, "rb").read().decode('utf-8'))

                source = re.sub(",\r\n", "\n", source)
                source = re.sub("\x00", "", source)
                if len(source) > 0:
                    df = pl.read_csv(io.StringIO(source), has_header=True, separator=",", schema_overrides=self.dtypes["DataLog_User_Sync"])
                    df = df.with_columns(
                        pl.lit(str(path)).alias('source'),
                        pl.format("{} {}", "DATE", "TIME").str.to_datetime(time_unit="us", time_zone="UTC").alias(dtm)
                    )
                    if "solenoid_valves" not in df.columns:
                        self.logger.warning(
                            "G2401 file %s has no solenoid_valves column; "
                            "automatic QC flags were not assigned.", path
                        )
                    df = self.auto_flag_g2401_data(df, dtm=dtm)
                    return df, None
                else:
                    return pl.DataFrame(), str(ValueError(f"File is empty."))

            except Exception as err:
                self.logger.error(err)
                return pl.DataFrame(), str(err)
        else:
            return pl.DataFrame(), f"{path}: File type unknown."
