import polars as pl
from pathlib import Path
from processing.instrument import pl_simplify_dtypes

def aggregate_data(
    source: Path,
    target: Path,
    instrument_name: str,
    dtm = "dtm",
    freq: str = "hourly",
    extract_cols: list[str] = ["UV370", "B470", "G520", "Y590", "R660", "IR880", "IR950"],
    statistics: str = "mean",  # or "median"
) -> tuple[pl.DataFrame, str]:
    """
    Recursively read Parquet files under source, aggregate instrument data,
    and save result to a uniquely named Parquet file under target.

    Args:
        source (Path): Path to input Parquet file.
        target (Path): Directory to save the output Parquet file.
        instrument_name (str): Name of the instrument (used in output filename).
        freq (str): Aggregation frequency, "hourly" or "daily".
        extract_cols (list[str]): Columns to extract and aggregate.
        statistics (str): "mean" or "median" for aggregation method.
    
    Returns:
        tuple[pl.DataFrame, str]: aggregated pl.DataFrame, file path
    """
    # Gather all matching parquet files under source recursively
    parquet_files = sorted(f for f in source.rglob("*.parquet") if instrument_name in f.name)
    if not parquet_files:
        print(f"⚠️ No .parquet files found in {source}")
        return

    # Concatenate all files
    dataframes = []
    for file in parquet_files:
        try:
            print(f"Processing {file} ..")
            df = pl.read_parquet(file)
            if "dtm" not in df.columns:
                continue  # skip if no datetime column
            cols_present = ["dtm"] + [c for c in extract_cols if c in df.columns]
            flag_cols = [f"f_{c}" for c in extract_cols if f"f_{c}" in df.columns]
            df = df.select([*cols_present, *flag_cols])
            for col in extract_cols:
                flag_col = f"f_{col}"
                if flag_col in df.columns:
                    df = df.filter((pl.col(flag_col) == 0) | (pl.col(flag_col).is_nan()) | (pl.col(flag_col).is_null()))
            dataframes.append(df)
        except Exception as e:
            print(f"⚠️ Skipping {file.name}: {e}")

    if not dataframes:
        print("⚠️ No valid data to process.")
        return

    df = pl.concat(dataframes, how="diagonal_relaxed")
    df = pl_simplify_dtypes(df)

    # Time bucketing
    if freq == "hourly":
        df = df.with_columns(pl.col(dtm).dt.truncate("1h").alias("bucket"))
    elif freq == "daily":
        df = df.with_columns(pl.col(dtm).dt.date().alias("bucket"))
    else:
        raise ValueError("freq must be 'hourly' or 'daily'")

    # Select aggregation function
    if statistics == "mean":
        agg_fn = lambda col: pl.col(col).mean().alias(col)
    elif statistics == "median":
        agg_fn = lambda col: pl.col(col).median().alias(col)
    else:
        raise ValueError("statistics must be 'mean' or 'median'")

    # Group and aggregate
    grouped = df.group_by("bucket").agg([agg_fn(col) for col in extract_cols if col in df.columns])
    grouped = grouped.rename({'bucket': dtm}).sort(dtm)

    # apply some sanity checks
    grouped = grouped.filter(pl.col(dtm) >= pl.datetime(2000, 1, 1, time_unit='us', time_zone='UTC'))
    grouped = grouped.with_columns([
        pl.when(pl.col(col) < 0)
        .then(None)
        .otherwise(pl.col(col))
        .alias(col)
        for col in extract_cols
    ])
    grouped = grouped.sort(by=dtm)

    # Output file path
    out_file = f"{instrument_name}-{freq}-{statistics}.parquet"
    out_path = target / out_file
    
    return grouped, out_path


