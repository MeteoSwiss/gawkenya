# import configparser
import logging
import os
import sys
from pathlib import Path

# import chardet
import polars as pl
import yaml


def load_config(config_file: str) -> dict:
    """
    Load configuration from config file.

    :param config_file: Path to the configuration file.
    :return: ConfigParser object with the loaded configuration.
    """
    config = dict()
    try:
        extension = os.path.basename(config_file).split(".")[1].lower()

        if extension in ['yaml', 'yml', 'cfg']:
            with open(config_file, 'r') as fh:
                config = yaml.safe_load(fh)
        else:
            print("Extension of config file not recognized!)")
        return config
    except Exception as err:
        print(err)
        return config


def setup_logging(
    file_or_name: str,
    level_file: str = "WARNING",
    level_console: str = "INFO"
) -> logging.Logger:
    """
    Set up a logger that optionally logs to both console and file.

    Args:
        file_or_name (str): Either full path to log file or just logger name
        level_file (str): File log level (e.g., 'DEBUG', 'INFO', etc.)
        level_console (str): Console log level

    Returns:
        logging.Logger
    """
    # Determine if argument is a path to a file
    if Path(file_or_name).suffix:  # Has .log, .txt, etc.
        file = Path(file_or_name)
        file_path = file.parent
        file_path.mkdir(parents=True, exist_ok=True)
        logger_name = file.stem
    else:
        file = None
        logger_name = file_or_name

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    # Logging level parsing
    level_file = getattr(logging, level_file.upper(), logging.WARNING)
    level_console = getattr(logging, level_console.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s, %(levelname)s, %(name)s, %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level_console)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File handler if file logging is desired
    if file:
        fh = logging.FileHandler(file)
        fh.setLevel(level_file)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def pl_simplify_dtypes(
    df: pl.DataFrame,
    simplify_float: bool = True,
    simplify_int: bool = True
) -> pl.DataFrame:
    """
    Downcasts numeric data types in a Polars DataFrame to reduce memory usage,
    while preserving datetime columns.

    - Float64 → Float32
    - Int64   → Int32
    - Skips any column of type pl.Datetime

    Args:
        df (pl.DataFrame): The input DataFrame to simplify.
        simplify_float (bool): Whether to downcast Float64 to Float32.
        simplify_int (bool): Whether to downcast Int64 to Int32.

    Returns:
        pl.DataFrame: A new DataFrame with simplified data types.
    """
    ops = []

    for name, dtype in df.schema.items():
        if dtype == pl.Datetime:
            continue  # preserve datetime precision
        if simplify_float and dtype == pl.Float64:
            ops.append(pl.col(name).cast(pl.Float32))
        elif simplify_int and dtype == pl.Int64:
            ops.append(pl.col(name).cast(pl.Int32))

    return df.with_columns(ops) if ops else df
# def pl_simplify_dtypes(df: pl.DataFrame, digits: int=2, exclude: list=list()) -> pl.DataFrame:
#     """Simplify dtypes of polars Dataframe

#     Args:
#         df (pl.DataFrame): polars Dataframe

#     Returns:
#         pl.DataFrame: polars Dataframe with most simple dtypes
#     """
#     # for column in df.columns:
#     for column in [x for x in df.columns if x not in set(exclude)]:
#         dtype = df[column].dtype
#         if dtype == pl.Datetime:
#             df = df.with_columns(pl.col(column).cast(pl.Datetime('us', 'UTC')))
#             # continue  # Keep datetime columns as is
#         elif dtype == pl.Float64 or dtype == pl.Float32:
#             df = df.with_columns(pl.col(column).cast(pl.Float32))  # Convert floats to Float32 for efficiency
#         elif dtype == pl.Int64 or dtype == pl.Int32:
#             df = df.with_columns(pl.col(column).cast(pl.Int32))  # Convert integers to Int32 for efficiency
#         elif dtype == pl.Utf8:
#             try:
#                 # Try converting to Int32
#                 df = df.with_columns(df[column].cast(pl.Int32))
#             except pl.ComputeError:
#                 try:
#                     # If that fails, try Float32
#                     df = df.with_columns(df[column].cast(pl.Float32))#.round(digits))
#                 except pl.ComputeError:
#                     pass  # Keep as string if neither works

#         elif dtype == pl.Binary:
#             # Optionally, cast binary columns to a simpler form, such as Integers or leave as Binary
#             df = df.with_columns(pl.col(column).cast(pl.Int32))  # Example: cast binary to Int32 (adjust as needed)
#         else:
#             # Handle any other unsupported dtypes
#             df = df.with_columns(pl.col(column).cast(pl.Utf8))  # For example, cast others to string
#     return df


# def convert_file_to_utf8(file: str) -> None:
#     """Open a file, determine the encoding of a file, and convert to utf-8.

#     Args:
#         file (str): full path to file.
#     """
#     try:
#         with open(file, 'rb') as f:
#             raw_data = f.read()
#             encoding = chardet.detect(raw_data)['encoding']
#             # print(encoding['encoding'])

#         if encoding != 'utf-8':
#             with open(file, 'r', encoding=encoding) as f:
#                 data = f.read()

#             with open(file, 'w', encoding='utf-8') as f:
#                 f.write(data)

#     except Exception as err:
#         print(f"{file} could not be encoded in utf-8.")


def aggregate_data(df: pl.DataFrame, dtm: str="dtm", interval: str='1h', how: str='median') -> pl.DataFrame:
    """
    Aggregates numeric columns in a Polars DataFrame to specified intervals.

    Args:
        df (pl.DataFrame): The input DataFrame.
        dtm (str, optional): Name of the datetime column for grouping. Defaults to dtm.
        interval (str): Time interval for grouping (default is '1h').
        how (str, optional): Aggregation operation ('median', 'mean', 'sum'). Defaults to median.

    Returns:
        pl.DataFrame: A DataFrame with aggregated numeric columns.
    """
    try:
        # Remove nulls in dtm
        df = df.filter(pl.col("dtm").is_not_null())
        
        # Ensure the datetime column is of Datetime type
        df = df.with_columns(pl.col(dtm).cast(pl.Datetime))
        
        # # Fill nulls in numeric columns (forward fill by default, can be customized)
        # df = df.with_columns(
        #     [
        #         pl.col(dtm).fill_null(strategy="forward"),
        #         pl.col(pl.Float32, pl.Float64, pl.Int32, pl.Int64).fill_null(strategy="forward")
        #     ]
        # )
        
        df = df.sort(by=dtm)

        # Map the operation to the corresponding Polars method
        how_map = {
            "median": lambda col: col.median(),
            "mean": lambda col: col.mean(),
            "sum": lambda col: col.sum()
        }
        
        # Validate the operation
        if how not in how_map:
            raise ValueError(f"Invalid operation: {how}. how must be one of 'median', 'mean', or 'sum'.")
        
        # Perform the aggregation
        aggregated_df = (
            df
            .groupby_dynamic(dtm, every=interval, truncate=True)
            .agg([
                how_map[how](pl.col(pl.Float32, pl.Float64, pl.Int32, pl.Int64)).keep_name()
            ])
        )
        
        return aggregated_df

    except Exception as err:
        print(err)
