import logging
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import polars as pl
from charset_normalizer import from_path

from processing.instrument import Instrument, pl_simplify_dtypes

MAPPINGS = pl.read_csv('cdp2_aurora_mappings.csv', has_header=True, dtypes=[pl.String]*4)


class Neph(Instrument):
    def __init__(self, name: str = "neph", log_file: str=str()) -> None:
        super().__init__(name=name, log_file=log_file)
        self.name = name

    def extract_to_dataframe(self, path: Path, dtm: str = "dtm") -> tuple[pl.DataFrame, str | None, str]:
        """
        Extract data from a NEPH file (.dat, .csv, .txt, or .zip) to a Polars DataFrame.

        Args:
            path (Path): Full path to data file.
            dtm (str): Name of datetime column.

        Returns:
            tuple: (DataFrame, error string if any, file type string)
        """
        df = pl.DataFrame()
        file_type = self.name

        try:
            # Extract raw content
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as z:
                    data_files = [f for f in z.namelist() if f.endswith(('.dat', '.csv', '.txt'))]
                    if not data_files:
                        raise ValueError("No data files found in the zip archive.")
                    if len(data_files) > 1:
                        raise ValueError("More than 1 file found in the zip archive.")
                    name = data_files[0]
                    raw = z.read(name)
            else:
                raw = path.read_bytes()

            # Detect encoding and decode
            res = from_path(path).best()
            encoding = res.encoding if res else "utf-8"
            
            text = raw.decode(encoding)

            # Check if file is empty or only contains blanks or whitespace
            lines = [line for line in text.splitlines() if line.strip()]
            if not lines:
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
                return df, None, file_type
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
                return df, None, file_type
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
            return df, None, file_type

        except Exception as e:
            self.logger.error(f"Failed to extract {path.name}: {e}")
            return df, str(e), file_type