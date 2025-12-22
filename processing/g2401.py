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
                    return df, None
                else:
                    return pl.DataFrame(), str(ValueError(f"File is empty."))

            except Exception as err:
                self.logger.error(err)
                return pl.DataFrame(), str(err)
        else:
            return pl.DataFrame(), f"{path}: File type unknown."
