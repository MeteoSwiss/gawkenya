# import configparser
import logging
import os

import chardet
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


def setup_logging(file: str) -> logging:
    """Setup the main logging device

    Args:
        file (str): full path to log file

    Returns:
        logging: a logger object
    """
    file_path = os.path.dirname(file)
    main_logger = os.path.basename(file).split('.')[0]
    logger = logging.getLogger(main_logger)
    try:
        os.makedirs(file_path, exist_ok=True)

        logger.setLevel(logging.DEBUG)

        # create file handler which logs warning and above messages
        fh = logging.FileHandler(file)
        fh.setLevel(logging.WARNING)

        # create console handler which logs even debugging information
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        
        # create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s, %(levelname)s, %(name)s, %(message)s', datefmt="%Y-%m-%dT%H:%M:%S")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        # add the handlers to the logger
        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger
    except Exception as err:
        print(err)
        return logger


def pl_simplify_dtypes(df: pl.DataFrame, digits: int=2) -> pl.DataFrame:
    """Simplify dtypes of polars Dataframe

    Args:
        df (pl.DataFrame): polars Dataframe

    Returns:
        pl.DataFrame: polars Dataframe with most simple dtypes
    """
    for column in df.columns:
        dtype = df[column].dtype
        if dtype == pl.Datetime:
            continue  # Keep datetime columns as is
        elif dtype == pl.Float64 or dtype == pl.Float32:
            df = df.with_columns(pl.col(column).cast(pl.Float32))  # Convert floats to Float32 for efficiency
        elif dtype == pl.Int64 or dtype == pl.Int32:
            df = df.with_columns(pl.col(column).cast(pl.Int32))  # Convert integers to Int32 for efficiency
        elif dtype == pl.Utf8:
            try:
                # Try converting to Int32
                df = df.with_columns(df[column].cast(pl.Int32))
            except pl.ComputeError:
                try:
                    # If that fails, try Float32
                    df = df.with_columns(df[column].cast(pl.Float32).round(digits))
                except pl.ComputeError:
                    pass  # Keep as string if neither works


        elif dtype == pl.Binary:
            # Optionally, cast binary columns to a simpler form, such as Integers or leave as Binary
            df = df.with_columns(pl.col(column).cast(pl.Int32))  # Example: cast binary to Int32 (adjust as needed)
        else:
            # Handle any other unsupported dtypes
            df = df.with_columns(pl.col(column).cast(pl.Utf8))  # For example, cast others to string
    return df


def convert_file_to_utf8(file: str) -> None:
    """Open a file, determine the encoding of a file, and convert to utf-8.

    Args:
        file (str): full path to file.
    """
    try:
        with open(file, 'rb') as f:
            raw_data = f.read()
            encoding = chardet.detect(raw_data)['encoding']
            # print(encoding['encoding'])

        if encoding != 'utf-8':
            with open(file, 'r', encoding=encoding) as f:
                data = f.read()

            with open(file, 'w', encoding='utf-8') as f:
                f.write(data)

    except Exception as err:
        print(f"{file} could not be encoded in utf-8.")
