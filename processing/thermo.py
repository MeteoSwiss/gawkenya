from pathlib import Path
import zipfile
import polars as pl
from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Thermo(Instrument):
    """
    Processor for Thermo ozone analyzer data files (49c and 49i).
    Automatically detects and parses files, supports .dat and .zip.
    """

    def __init__(self, name: str = "thermo", log_file: str = str()) -> None:
        super().__init__(name="thermo", log_file=log_file)
        self.name = name
        self.headers = {
            "tei49c": [
                "pcdate", "pctime", "time", "date", "o3", "flags",
                "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ],
            "tei49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ],
            "49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ]
        }
        self.dtypes = {
            'tei49c': [pl.Utf8]*4 + [pl.Float32]*1 + [pl.Utf8]*1 + [pl.Int32]*2 + [pl.Float32]*6,
            'tei49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
            '49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
        }

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a Thermo 49c or 49i .dat/.zip file into a Polars DataFrame.

        Fix: Some integer columns sometimes appear as integral floats in text (e.g. "123.000").
             These are coerced to integers before casting.

        Args:
            path: Path to the input data file.

        Returns:
            (DataFrame, error_message_or_None)
        """
        df = pl.DataFrame()
        file_type = "49i" if "49i-" in path.name.lower() else "tei49c"
        expected_fields = len(self.headers[file_type])
        dtm = self.dtm

        try:
            # Read raw lines from file
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as archive:
                    name = archive.namelist()[0]
                    with archive.open(name) as f:
                        lines = f.read().decode("utf-8").splitlines()
            else:
                lines = path.read_text(encoding="utf-8").splitlines()

            # Find start of data and extract rows
            data_lines: list[list[str]] = []
            for line in lines:
                if line.lower().startswith("pcdate"):
                    continue  # skip header
                parts = line.strip().split()
                if len(parts) == expected_fields:
                    data_lines.append(parts)
                else:
                    self.logger.warning(f"{path.name} invalid row: {line.strip()}")

            if not data_lines:
                raise ValueError("No valid data records found.")

            # Build as strings first
            df = pl.DataFrame(data_lines, schema=self.headers[file_type])

            # Target dtypes
            dtype_map = dict(zip(self.headers[file_type], self.dtypes[file_type]))

            # Coerce columns that should be integers but may appear as "123.000"
            int_types = {
                pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
            }
            int_cols = [c for c, dt in dtype_map.items() if dt in int_types]

            if int_cols:
                exprs = []
                for c in int_cols:
                    target = dtype_map[c]

                    # 1) Fast path: strip trailing .0/.000 etc (and a trailing dot)
                    s = pl.col(c).cast(pl.Utf8, strict=False)
                    s_clean = (
                        s.str.strip_chars()
                         .str.replace_all(r"\.$", "")
                         .str.replace_all(r"\.0+$", "")
                    )
                    direct_int = s_clean.cast(target, strict=False)

                    # 2) Fallback: parse as float and accept only values that are effectively integral
                    f = s.cast(pl.Float64, strict=False)
                    f_int = (
                        pl.when(
                            f.is_not_null()
                            & ((f - f.floor()).abs() < 1e-6)
                        )
                        .then(f.floor())
                        .otherwise(None)
                        .cast(target, strict=False)
                    )

                    exprs.append(pl.coalesce([direct_int, f_int]).alias(c))

                df = df.with_columns(exprs)

            # Convert columns to correct types (non-strict to avoid hard failures on odd values)
            df = df.with_columns(
                [pl.col(c).cast(dt, strict=False).alias(c) for c, dt in dtype_map.items()]
            )

            # Optional: warn if any integer columns still contain nulls after coercion
            for c in int_cols:
                nnull = df[c].null_count()
                if nnull:
                    self.logger.warning(f"{path.name}: column '{c}' has {nnull} null(s) after int coercion/cast")

            # drop optional hio3 column if empty
            if "hio3" in df.columns and df["hio3"].null_count() == len(df):
                df = df.drop("hio3")

            df = df.with_columns([
                pl.lit(str(path)).alias("source"),
                pl.format("{} {}", "pcdate", "pctime")
                  .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
                  .dt.replace_time_zone("UTC")
                  .dt.with_time_unit("us")
                  .alias(dtm)
            ])
            df = pl_simplify_dtypes(df)

            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return pl.DataFrame(), str(err)


# from pathlib import Path
# import zipfile
# import polars as pl
# from processing.instrument import Instrument
# from toolbox.utils import pl_simplify_dtypes


# class Thermo(Instrument):
#     """
#     Processor for Thermo ozone analyzer data files (49c and 49i).
#     Automatically detects and parses files, supports .dat and .zip.
#     """

#     def __init__(self, name: str = "thermo", log_file: str=str()) -> None:
#         super().__init__(name="thermo", log_file=log_file)
#         self.name = name
#         self.headers = {
#             "tei49c": [
#                 "pcdate", "pctime", "time", "date", "o3", "flags",
#                 "cellai", "cellbi", "bncht", "lmpt", "o3lt",
#                 "flowa", "flowb", "pres"
#             ],
#             "tei49i": [
#                 "pcdate", "pctime", "time", "date", "flags", "o3",
#                 "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
#                 "flowa", "flowb", "pres"
#             ],
#             "49i": [
#                 "pcdate", "pctime", "time", "date", "flags", "o3",
#                 "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
#                 "flowa", "flowb", "pres"
#             ]
#         }
#         self.dtypes = {
#             'tei49c': [pl.Utf8]*4 + [pl.Float32]*1 + [pl.Utf8]*1 + [pl.Int32]*2 + [pl.Float32]*6,
#             'tei49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
#             '49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
#         }


#     def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
#         """
#         Extracts data from a Thermo 49c or 49i .dat/.zip file into a Polars DataFrame.

#         Args:
#             path (Path): Path to the input data file.

#         Returns:
#             tuple: (DataFrame, error message or None, file type ['tei49c' | 'tei49i'])
#         """
#         df = pl.DataFrame()
#         file_type = "49i" if "49i-" in path.name.lower() else "tei49c"
#         expected_fields = len(self.headers[file_type])
#         dtm = self.dtm

#         try:
#             # Read raw lines from file
#             if path.suffix == ".zip":
#                 with zipfile.ZipFile(path, "r") as archive:
#                     name = archive.namelist()[0]
#                     with archive.open(name) as f:
#                         lines = f.read().decode("utf-8").splitlines()
#             else:
#                 lines = path.read_text(encoding="utf-8").splitlines()

#             # Find start of data and extract rows
#             data_lines = []
#             for line in lines:
#                 if line.lower().startswith("pcdate"):
#                     continue  # skip header
#                 parts = line.strip().split()
#                 if len(parts) == expected_fields:
#                     data_lines.append(parts)
#                 else:
#                     self.logger.warning(f"{path.name} invalid row: {line.strip()}")

#             if not data_lines:
#                 raise ValueError("No valid data records found.")

#             df = pl.DataFrame(data_lines, schema=self.headers[file_type])

#             # Convert columns to correct types
#             df = df.cast(dict(zip(self.headers[file_type], self.dtypes[file_type])))

#             # drop optional hio3 column if empty
#             if "hio3" in df.columns and df["hio3"].null_count() == len(df):
#                 df = df.drop("hio3")

#             df = df.with_columns([
#                 pl.lit(str(path)).alias("source"),
#                 pl.format("{} {}", "pcdate", "pctime")
#                   .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
#                   .dt.replace_time_zone("UTC")
#                   .dt.with_time_unit("us")
#                   .alias(dtm)
#             ])
#             df = pl_simplify_dtypes(df)

#             return df, None

#         except Exception as err:
#             self.logger.error(f"Failed to extract {path.name}: {err}")
#             return pl.DataFrame(), str(err)
