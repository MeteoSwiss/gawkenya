import logging
import os
import sys
from pathlib import Path

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
    logger_name: str,
    log_file: str = str(),
    level_file: str = "WARNING",
    level_console: str = "INFO"
) -> logging.Logger:
    """
    Set up a logger that optionally logs to both console and file.

    Args:
        name (str): logger name
        log_file (str, optional): Path to log file 
        level_file (str, optional): File log level (e.g., 'DEBUG', 'INFO', etc.). Defaults to 'WARNING'.
        level_console (str, optional): Console log level. Defaults to 'INFO'.

    Returns:
        logging.Logger
    """   
    if Path(log_file).suffix:  # Has .log, .txt, etc.
        file = Path(log_file)
        file_path = file.parent
        file_path.mkdir(parents=True, exist_ok=True)
    else:
        file = None

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
        if name.lower() == "termin":
            continue
        if hasattr(dtype, "base_type") and dtype.base_type() == pl.Datetime:
            continue  # preserve datetime precision
        if simplify_float and dtype == pl.Float64:
            ops.append(pl.col(name).cast(pl.Float32))
        elif simplify_int and dtype == pl.Int64:
            ops.append(pl.col(name).cast(pl.Int32))

    return df.with_columns(ops) if ops else df


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
