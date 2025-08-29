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

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None, str]:
        """
        Extract data from a PALAS Fidas .csv file into a Polars DataFrame.

        Args:
            path (Path): Path to the .csv file.

        Returns:
            tuple: (DataFrame, error string or None, file type ['fidas'])
        """
        df = pl.DataFrame()
        file_type = "fidas"

        try:
            df = pl.read_parquet(source=path)
            df = pl_simplify_dtypes(df)
            return df, None, file_type

        except Exception as e:
            self.logger.error(f"Failed to extract {path.name}: {e}")
            return df, str(e), file_type