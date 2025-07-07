from io import BytesIO
from pathlib import Path
from typing import Tuple
from zipfile import ZipFile

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

def extract_detailed_data_zip_to_polars_dfs(zip_path: Path) -> dict[str, pl.DataFrame]:
    """
    Extract AVO CSV files from a ZIP archive in memory and return a dictionary of cleaned Polars DataFrames,
    one per unique 'Source' value. Each DataFrame contains a 'dtm' column with UTC timezone and microsecond precision.
    """
    result: dict[str, pl.DataFrame] = {}

    with ZipFile(zip_path, "r") as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue

            with archive.open(name) as file:
                csv_bytes = BytesIO(file.read())

                df = pl.read_csv(csv_bytes, infer_schema_length=5000)

                # Ensure required columns
                if "Datetime_start(UTC)" not in df.columns or "Source" not in df.columns:
                    continue

                # Create dtm column with microsecond resolution and UTC timezone
                dtm = (
                    pl.col("Datetime_start(UTC)")
                    .str.strptime(pl.Datetime, "%m/%d/%Y %H:%M")
                    .cast(pl.Datetime("us"))
                    .dt.replace_time_zone("UTC")
                    .alias("dtm")
                )
                df = df.with_columns(dtm)

                # Drop columns where all values are null
                df = df.select([col for col in df.columns if df.select(pl.col(col).is_not_null().sum()).item() > 0])

                # Drop unwanted columns
                df = df.drop([col for col in ["Device timezone", 
                                              "Datetime_start(UTC)", 
                                              "Datetime_end(UTC)", 
                                              "AQI US","AQI CN", 
                                              "Temperature (Fahrenheit)", 
                                              "slot.2.co",
                                              ] if col in df.columns])

                # Convert pressure from Pa to hPa
                if "Pressure (pascal)" in df.columns:
                    df = df.with_columns(
                        (pl.col("Pressure (pascal)") / 100).alias("P [hPa]")
                    ).drop("Pressure (pascal)")

                # Convert Particle Count from 1/L to 1/cm3
                if "Particle Count" in df.columns:
                    df = df.with_columns(
                        (pl.col("Particle Count") / 1000).alias("PNC [1/cm3]")
                    ).drop("Particle Count")

                # Rename columns and correct wrong assignments
                df = df.rename({"Temperature (Celsius)": "T [°C]", 
                                "Humidity (%)": "RH [%]",
                                "PM1 (ug/m3)": "PM1 [ug/m3]",
                                "PM2.5 (ug/m3)": "PM2.5 [ug/m3]",
                                "PM10 (ug/m3)": "PM10 [ug/m3]",
                                # "Particle Count": "PNC [1/cm3]",
                                # "slot.2.pm25": "Cn_1",
                                # "slot.4.pm1": "Cn_2",
                                # "slot.2.pm1": "pm10_1",
                                # "slot.3.no2": "pm10_2",
                                # "slot.2.pm10": "pm25_1",
                                # "slot.4.co2": "pm25_2",
                                # "slot.2.co2": "pm1_1",
                                # "slot.3.co": "pm1_2",
                                })


                # Split by Source
                for source in df.select("Source").unique().to_series().to_list():
                    source_df = df.filter(pl.col("Source") == source).drop("Source")
                    source_df = source_df.sort("dtm")
                    result[source] = source_df

    return result

# Example usage:
# from pathlib import Path
# dfs = extract_avo_zip_to_polars_dfs(Path("/path/to/IQAir_Export_validated_devices_29Jun24-29Jun25_hourly.zip"))

import polars as pl


def correct_pnc_using_dynamic_cutoff(df: pl.DataFrame, pnc_february_level: int=20, factor: int=1) -> pl.DataFrame:
    """
    Find the last date in February 2025 where 'PNC [1/cm3]' < pnc_february_level,
    and multiply 'PNC [1/cm3]' by factor for all earlier rows.

    Args:
        df (pl.DataFrame): Input DataFrame with 'dtm' and 'PNC [1/cm3]' columns.

    Returns:
        pl.DataFrame: Corrected DataFrame.
    """
    # Ensure datetime is naive or in UTC
    df = df.with_columns(pl.col("dtm").dt.replace_time_zone(None))

    # Filter for February 2025 values where 'PNC [1/cm3]' < 30
    february_filter = (
        (pl.col("dtm").dt.year() == 2025) &
        (pl.col("dtm").dt.month() == 2) &
        (pl.col("PNC [1/cm3]") < pnc_february_level)
    )

    february_dates = df.filter(february_filter).select("dtm")

    if february_dates.is_empty():
        print("No qualifying February 2025 values found. No correction applied.")
        return df

    cutoff = february_dates.max().item()

    print(f"Applying correction before: {cutoff}")

    # Apply correction for dates before the cutoff
    df = df.with_columns(
        pl.when(pl.col("dtm") < cutoff)
        .then(pl.col("PNC [1/cm3]") * factor)
        .otherwise(pl.col("PNC [1/cm3]"))
        .alias("PNC [1/cm3]")
    )

    return df


def correlate_pnc_pm10(df: pl.DataFrame) -> Tuple[dict, dict]:
    """
    Compute correlation and linear regression between 'PNC [1/cm3]' and 'PM10 [ug/m3]'
    before and after the dynamic cutoff date. Visualize results with regression lines.

    Returns:
        Tuple[dict, dict]: stats_before and stats_after
    """
    # Ensure datetime is naive
    df = df.with_columns(pl.col("dtm").dt.replace_time_zone(None))

    # Find cutoff date
    feb_filter = (
        (pl.col("dtm").dt.year() == 2025) &
        (pl.col("dtm").dt.month() == 2) &
        (pl.col("PNC [1/cm3]") < 30)
    )
    feb_dates = df.filter(feb_filter).select("dtm")

    if feb_dates.is_empty():
        raise ValueError("No qualifying February 2025 values found.")

    cutoff = feb_dates.max().item()

    # Prepare subsets
    before = df.filter(pl.col("dtm") < cutoff).select(["PNC [1/cm3]", "PM10 [ug/m3]"]).drop_nulls()
    after = df.filter(pl.col("dtm") >= cutoff).select(["PNC [1/cm3]", "PM10 [ug/m3]"]).drop_nulls()

    def compute_stats(subdf: pl.DataFrame) -> dict:
        x = subdf["PNC [1/cm3]"].to_numpy()
        y = subdf["PM10 [ug/m3]"].to_numpy()
        if len(x) < 2:
            return {"correlation": float("nan"), "slope": float("nan"), "intercept": float("nan"), "x": x, "y": y}
        corr = np.corrcoef(x, y)[0, 1]
        slope, intercept = np.polyfit(x, y, deg=1)
        return {"correlation": corr, "slope": slope, "intercept": intercept, "x": x, "y": y}

    stats_before = compute_stats(before)
    stats_after = compute_stats(after)

    # Plotting
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), sharex=True, sharey=True)

    # --- Before Cutoff ---
    x, y = stats_before["x"], stats_before["y"]
    ax1.scatter(x, y, alpha=0.6, label="Data")
    x_fit = np.linspace(x.min(), x.max(), 100)
    y_fit = stats_before["slope"] * x_fit + stats_before["intercept"]
    ax1.plot(x_fit, y_fit, color="black", lw=2, label="Regression")
    ax1.set_title("Before cutoff")
    ax1.set_xlabel("PNC [1/cm3]")
    ax1.set_ylabel("PM10 [ug/m3]")
    ax1.text(0.05, 0.95,
             f"$r$ = {stats_before['correlation']:.3f}\n"
             f"$y = {stats_before['slope']:.3f}x + {stats_before['intercept']:.2f}$",
             transform=ax1.transAxes,
             fontsize=10, va='top', ha='left', bbox=dict(facecolor='white', alpha=0.7))
    ax1.legend()

    # --- After Cutoff ---
    x, y = stats_after["x"], stats_after["y"]
    ax2.scatter(x, y, alpha=0.6, color='orange', label="Data")
    x_fit = np.linspace(x.min(), x.max(), 100)
    y_fit = stats_after["slope"] * x_fit + stats_after["intercept"]
    ax2.plot(x_fit, y_fit, color="black", lw=2, label="Regression")
    ax2.set_title("After cutoff")
    ax2.set_xlabel("PNC [1/cm3]")
    ax2.text(0.05, 0.95,
             f"$r$ = {stats_after['correlation']:.3f}\n"
             f"$y = {stats_after['slope']:.3f}x + {stats_after['intercept']:.2f}$",
             transform=ax2.transAxes,
             fontsize=10, va='top', ha='left', bbox=dict(facecolor='white', alpha=0.7))
    ax2.legend()

    fig.suptitle(f"PNC vs PM10 before and after cutoff ({cutoff:%Y-%m-%d %H:%M})", fontsize=14)
    plt.tight_layout()
    plt.show()

    # Clean return
    for s in (stats_before, stats_after):
        s.pop("x")
        s.pop("y")

    return stats_before, stats_after
