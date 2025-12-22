from pathlib import Path

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Fidas(Instrument):
    """
    Processor for PALAS Fidas particle counter data files.
    Automatically handles different encodings and extracts consistent datetime columns.
    """

    def __init__(self, log_file: str=str()):
        super().__init__(name="fidas", log_file=log_file)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a PALAS Fidas .csv file into a Polars DataFrame.

        Args:
            path (Path): Path to the .csv file.

        Returns:
            tuple: (DataFrame, error string or None)
        """
        df = pl.DataFrame()

        try:
            df = pl.read_parquet(source=path)
            df = pl_simplify_dtypes(df)
            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return df, str(err)