from __future__ import annotations

import argparse
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes

WIND_PAIRS: list[tuple[str, str]] = [
    ("fa1010z0", "da1010z0"),
    ("fkl010z0", "dkl010z0"),
]

EXCLUDE_FROM_OUTPUT = {"source", "zzzztttt"}
EXCLUDE_FROM_MEAN = {"source", "zzzztttt", "iii"}
CUMULATIVE_SUM_COLS = {"rre150z0", "ra1150z0"}

class Meteo(Instrument):
    """
    Processor for VRXA00 meteorological bulletin files.
    Parses fixed-width formatted records and constructs datetime.
    """

    def __init__(self, name: str="vrxa00", log_file: str=str()):
        super().__init__(name=name, log_file=log_file)

        self.mappings = {'VRXA00': {
                'iii': 'MeteoSwiss internal station identifier; MKN=187; NRB=',
                'zzzztttt': 'dateTime as %Y%m%d%H%M%S',
                'tre200s0': 'Temperature (°C, 10-min average) at 2m above ground (Lufft)',
                'uor200s0': 'Humidity (%, 10-min average) at 2m above ground (Lufft)',
                'prestas0': 'Pressure (hPa, 10-min average) at 2m above ground (Lufft)',
                'fa1010z0': 'Wind speed (m/s, , 10-min average) at 2m above ground (Lufft)',
                'da1010z0': 'Wind direction (°, 10-min average) at 2m above ground (Lufft)',
                'rre150z0': 'Precipitation (mm, 10-min sum) at 2m above ground (Lufft, radar)',
                'ta1200s0': 'Temperature (°C, 10-min average) at 10m above ground (Lufft)',
                'ua1200s0': 'Humidity (%, 10-min average) at 10m above ground (Lufft)',
                'pa1stas0': 'Pressure (hPa, 10-min average) at 10m above ground (Lufft)',
                'fkl010z0': 'Wind speed (m/s, 10-min average) at 10m above ground (Lufft)',
                'dkl010z0': 'Wind direction (°, 10-min average) at 10m above ground (Lufft)',
                'ra1150z0': 'Precipitation (mm, 10-min sum) at 10m above ground (Lufft, radar)',
                'fkl010z1': 'Wind speed (m/s, 10-min maximum) at 10m above ground (Lufft)',
                'gor000z0': 'Global solar radiation (W, 10-min average) at 2m above ground (Lufft)',
                'ta2200s0': 'Temperature (°C, 10-min average) at 2m above ground, parallel measurement (Rotronic)',
                'ua2200s0': 'Pressure (hPa, 10-min average) at 2m above ground, parallel measurement (Rotronic)',
                # 'itosurr0': 'Surface ozone (ppb, 5-min average)' --- will be needed for Nairobi
            }
        }

        self.schema_overrides = {
            "VRXA00": {
                "iii": pl.Int32,
                "zzzztttt": pl.Utf8,
                "tre200s0": pl.Float64,
                "uor200s0": pl.Float64,
                "prestas0": pl.Float64,
                "fa1010z0": pl.Float64,
                "da1010z0": pl.Float64,
                "rre150z0": pl.Float64,
                "ta1200s0": pl.Float64,
                "ua1200s0": pl.Float64,
                "pa1stas0": pl.Float64,
                "fkl010z0": pl.Float64,
                "dkl010z0": pl.Float64,
                "ra1150z0": pl.Float64,
                "fkl010z1": pl.Float64,
                "gor000z0": pl.Float64,
                "ta2200s0": pl.Float64,
                "ua2200s0": pl.Float64,
            }
        }

        # self.logger.info("Class 'Meteo' initialized successfully.")


    def extract_to_dataframe(self, path: Path, dtm: str = "dtm") -> tuple[pl.DataFrame, str | None]:
        """
        Extract data from a METEO file (.txt or .zip) to a Polars DataFrame.

        Args:
            path (Path): Full path to data file.
            dtm (str): Name of datetime column.

        Returns:
            tuple: (DataFrame, error string if any, file type string)
        """
        file_type = "vrxa00"

        try:
            if ".zip" in path.name:
                with zipfile.ZipFile(path, "r") as z:
                    data_files = [f for f in z.namelist() if f.endswith(".txt") or f.startswith("VRXA")]
                    if not data_files:
                        raise ValueError("No valid data file found in ZIP archive.")
                    if len(data_files) > 1:
                        raise ValueError("Multiple data files found in ZIP archive.")
                    content = z.read(data_files[0])
                    df = pl.read_csv(
                        source=content,
                        has_header=True,
                        separator=" ",
                        skip_rows=3,
                        null_values="/",
                        schema_overrides=self.schema_overrides["VRXA00"]
                    )
            else:
                df = pl.read_csv(
                    source=path,
                    has_header=True,
                    separator=" ",
                    skip_rows=3,
                    null_values="/",
                    schema_overrides=self.schema_overrides["VRXA00"]
                )

            df = df.with_columns([
                pl.col("zzzztttt").str.to_datetime("%Y%m%d%H%M", time_unit="us", time_zone="UTC").alias(dtm),
                pl.lit(str(path)).alias("source"),
            ])

            return df, None

        except Exception as err:
            self.logger.error(f"Failed to extract {path.name}: {err}")
            return pl.DataFrame(), str(err)


    def find_vrxa00_files(self, root: Path) -> list[Path]:
        return sorted(p for p in root.rglob("vrxa00.parquet") if p.is_file())


    def ensure_datetime(self, df: pl.DataFrame, dtm_col: str = "dtm") -> pl.DataFrame:
        if dtm_col not in df.columns:
            raise ValueError(f"Missing datetime column: {dtm_col}")

        dtype = df.schema[dtm_col]

        if hasattr(dtype, "base_type") and dtype.base_type() == pl.Datetime:
            return df

        if dtype == pl.Utf8:
            return df.with_columns(
                pl.col(dtm_col).str.to_datetime(strict=False, time_zone="UTC")
            )

        if dtype == pl.Date:
            return df.with_columns(pl.col(dtm_col).cast(pl.Datetime("us")))

        return df.with_columns(pl.col(dtm_col).cast(pl.Datetime("us"), strict=False))


    def deduplicate_file(self, path: Path, dtm_col: str = "dtm") -> pl.DataFrame:
        df = pl.read_parquet(path)
        df = self.ensure_datetime(df, dtm_col)

        before = df.height
        df = df.unique(maintain_order=True).sort(dtm_col)
        removed = before - df.height

        if removed:
            df.write_parquet(path)
            print(f"Deduplicated {path}: removed {removed} rows")
        else:
            print(f"No duplicates in {path}")

        return df


    def flagged_mean_expr(self, col_name: str) -> pl.Expr:
        """
        Mean of a column using only rows where its corresponding flag is 0.
        If no matching flag column exists, use the plain mean.
        """
        flag_col = f"f_{col_name}"

        value = pl.col(col_name)
        valid = value.is_not_null()

        expr = (
            pl.when((pl.col(flag_col) == 0) & valid)
            .then(value)
            .otherwise(None)
            .mean()
            .alias(col_name)
        )

        return expr


    def flagged_sum_expr(self, col_name: str) -> pl.Expr:
        """
        Sum of a column using only rows where its corresponding flag is 0.
        If no matching flag column exists, use the plain sum.
        """
        flag_col = f"f_{col_name}"

        value = pl.col(col_name)
        valid = value.is_not_null()

        expr = (
            pl.when((pl.col(flag_col) == 0) & valid)
            .then(value)
            .otherwise(None)
            .sum()
            .alias(col_name)
        )

        return expr


    def _build_wind_component_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add temporary u/v columns for wind pairs, masked so that only rows with:
        - non-null speed
        - non-null direction
        - speed flag == 0 (if present)
        - direction flag == 0 (if present)
        contribute to the vector mean.
        """
        exprs: list[pl.Expr] = []

        for speed_col, dir_col in WIND_PAIRS:
            if speed_col not in df.columns or dir_col not in df.columns:
                continue

            speed_flag = f"f_{speed_col}"
            dir_flag = f"f_{dir_col}"

            valid = pl.col(speed_col).is_not_null() & pl.col(dir_col).is_not_null()

            if speed_flag in df.columns:
                valid = valid & (pl.col(speed_flag) == 0)
            if dir_flag in df.columns:
                valid = valid & (pl.col(dir_flag) == 0)

            rad = pl.col(dir_col).radians()

            exprs.extend(
                [
                    pl.when(valid)
                    .then(-pl.col(speed_col) * rad.sin())
                    .otherwise(None)
                    .alias(f"__u_{speed_col}"),
                    pl.when(valid)
                    .then(-pl.col(speed_col) * rad.cos())
                    .otherwise(None)
                    .alias(f"__v_{speed_col}"),
                ]
            )

        return df.with_columns(exprs) if exprs else df


    def _rename_s0_z0_to_h0(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Rename columns that end with 's0' or 'z0' to end with 'h0'.

        Examples:
            ta1200s0 -> ta1200h0
            fa1010z0 -> fa1010h0

        Other columns are left unchanged.
        """
        mapping = {}
        for col in df.columns:
            if col.endswith("s0") or col.endswith("z0"):
                mapping[col] = f"{col[:-2]}h0"

        return df.rename(mapping) if mapping else df


    def aggregate_one_frame_hourly(self, df: pl.DataFrame, dtm_col: str = "dtm") -> pl.DataFrame:
        df = self.ensure_datetime(df, dtm_col)
        df = self._build_wind_component_columns(df)

        df = df.with_columns(pl.col(dtm_col).dt.truncate("1h").alias("hour"))

        wind_speed_cols = {s for s, _ in WIND_PAIRS}
        wind_dir_cols = {d for _, d in WIND_PAIRS}
        wind_cols = wind_speed_cols | wind_dir_cols

        numeric_mean_cols: list[str] = []
        numeric_sum_cols: list[str] = []

        for name, dtype in df.schema.items():
            if name in {dtm_col, "hour"}:
                continue
            if name in EXCLUDE_FROM_MEAN:
                continue
            if name in wind_cols:
                continue
            if name.startswith("__u_") or name.startswith("__v_"):
                continue
            if name.startswith("f_"):
                continue
            if not dtype.is_numeric():
                continue

            if name in CUMULATIVE_SUM_COLS:
                numeric_sum_cols.append(name)
            else:
                numeric_mean_cols.append(name)

        agg_exprs: list[pl.Expr] = []

        # Ordinary numeric columns -> hourly mean, using only rows with flag == 0 if present
        for c in numeric_mean_cols:
            if f"f_{c}" in df.columns:
                agg_exprs.append(self.flagged_mean_expr(c))
            else:
                agg_exprs.append(pl.col(c).mean().alias(c))

        # Cumulative columns -> hourly sum, using only rows with flag == 0 if present
        for c in numeric_sum_cols:
            if f"f_{c}" in df.columns:
                agg_exprs.append(self.flagged_sum_expr(c))
            else:
                agg_exprs.append(pl.col(c).sum().alias(c))

        # iii -> first non-null
        if "iii" in df.columns:
            agg_exprs.append(pl.col("iii").drop_nulls().first().alias("iii"))

        # Wind u/v means from already-masked temporary columns
        for speed_col, _dir_col in WIND_PAIRS:
            u_col = f"__u_{speed_col}"
            v_col = f"__v_{speed_col}"
            if u_col in df.columns and v_col in df.columns:
                agg_exprs.extend(
                    [
                        pl.col(u_col).mean().alias(u_col),
                        pl.col(v_col).mean().alias(v_col),
                    ]
                )

        out = df.group_by("hour").agg(agg_exprs).sort("hour")

        post_exprs: list[pl.Expr] = [pl.col("hour").alias("dtm")]

        for c in numeric_mean_cols:
            if c in out.columns:
                post_exprs.append(pl.col(c))

        for c in numeric_sum_cols:
            if c in out.columns:
                post_exprs.append(pl.col(c))

        if "iii" in out.columns:
            post_exprs.append(pl.col("iii"))

        for speed_col, dir_col in WIND_PAIRS:
            u_col = f"__u_{speed_col}"
            v_col = f"__v_{speed_col}"
            if u_col in out.columns and v_col in out.columns:
                mean_u = pl.col(u_col)
                mean_v = pl.col(v_col)

                post_exprs.extend(
                    [
                        ((mean_u.pow(2) + mean_v.pow(2)).sqrt()).alias(speed_col),
                        ((pl.lit(180.0) + pl.arctan2(mean_u, mean_v).degrees()) % 360.0).alias(dir_col),
                    ]
                )

        out = out.select(post_exprs).sort("dtm")

        if "iii" in out.columns:
            out = out.with_columns(pl.col("iii").cast(pl.Int64, strict=False))

        keep_cols = [
            c for c in out.columns
            if out.select(pl.col(c).is_not_null().any()).item()
        ]

        return self._rename_s0_z0_to_h0(out.select(keep_cols))


    def combine_hourly_frames(self, frames: list[pl.DataFrame], dtm_col: str = "dtm") -> pl.DataFrame:
        if not frames:
            return pl.DataFrame()

        combined = pl.concat(frames, how="diagonal_relaxed")
        return self.aggregate_one_frame_hourly(combined, dtm_col=dtm_col)


    def write_yearly_level2_parquet(self, df: pl.DataFrame, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)

        if df.is_empty():
            print("No hourly data to write.")
            return

        df = df.with_columns(pl.col("dtm").dt.year().alias("year"))
        years = df.get_column("year").unique().sort().to_list()

        for year in years:
            out = (
                df.filter(pl.col("year") == year)
                .drop("year")
                .sort("dtm")
            )

            # Keep calculations in Float64, simplify only final stored output
            out = pl_simplify_dtypes(out, simplify_float=True, simplify_int=False)

            out_path = target / f"vrxa00_hourly_{year}.parquet"
            out.write_parquet(out_path)
            print(f"Wrote {out_path}")


    def process_level1_to_level2_hourly(self, source: Path, target: Path, dtm_col: str = "dtm") -> pl.DataFrame:
        """
        Deduplicate and aggregate VRXA00 Parquet files with Polars.

        What it does
        ------------
        1. Walk a source folder recursively and find all files named `vrxa00.parquet`.
        2. Open each file, remove exact duplicate rows, and write the cleaned file back in place.
        3. Aggregate all cleaned data to hourly values.
        4. Aggregate wind correctly by vector averaging for:
        - fa1010z0 + da1010z0
        - fkl010z0 + dkl010z0
        5. Combine the hourly results into yearly parquet files.

        Rules used
        ----------
        - ordinary numeric data columns: hourly mean
        - wind speed/direction pairs: vector mean
        - flag columns f_*: hourly max
        - iii: first non-null value in the hour
        - zzzztttt: rebuilt as YYYYmmddHHMM from the hourly timestamp
        - source: dropped from hourly output
        """
        files = self.find_vrxa00_files(source)
        if not files:
            raise FileNotFoundError(f"No vrxa00.parquet files found under {source}")

        hourly_parts: list[pl.DataFrame] = []

        for path in files:
            cleaned = self.deduplicate_file(path, dtm_col=dtm_col)
            hourly = self.aggregate_one_frame_hourly(cleaned, dtm_col=dtm_col)
            hourly_parts.append(hourly)

        combined = self.combine_hourly_frames(hourly_parts, dtm_col=dtm_col)
        self.write_yearly_level2_parquet(combined, target)

        return combined


    def export_to_wdcgg_format(self, df: pl.DataFrame, target: Path) -> Path:
        """
        Export one yearly hourly meteo DataFrame to a WDCGG-style space-separated
        .dat file.

        Expected input
        --------------
        The input DataFrame must represent one full or partial year of hourly data,
        typically read from one yearly hourly Parquet file produced by this class,
        e.g. `vrxa00_hourly_2024.parquet`.

        The DataFrame is expected to contain at least:
            - dtm       : hourly datetime column
            - iii       : station identifier
            - tre200h0  : air_temperature
            - uor200h0  : relative_humidity
            - prestah0  : air_pressure
            - gor000h0  : global_solar_radiation
            - rre150h0  : precipitation_amount
            - fkl010h0  : wind_speed
            - dkl010h0  : wind_direction

        Output
        ------
        A space-separated text file with columns:

            site_gaw_id year month day hour minute second
            wind_direction wind_speed relative_humidity air_pressure
            air_temperature precipitation_amount global_solar_radiation
            latitude longitude altitude elevation

        File naming
        -----------
        The output file name is derived from the station id and year:

            <site>_meteo_<year>.dat

        For example, if iii == 187, the site_gaw_id is "MKN" and the file name is:
            mkn_meteo_2024.dat

        Missing values
        --------------
        Missing floating-point meteorological values are written as -99.9.

        Notes
        -----
        - This function currently maps:
            187 -> "MKN"
        Additional mappings such as NRB can be added later.
        - The `target` argument is interpreted as a target directory if it is an
        existing directory or has no suffix. Otherwise, it is interpreted as a
        full file path and its parent directory is used, while the final file
        name is still enforced.
        """
        from pathlib import Path
        import polars as pl

        target = Path(target)

        required = [
            "dtm",
            "iii",
            "tre200h0",
            "uor200h0",
            "prestah0",
            "gor000h0",
            "rre150h0",
            "fkl010h0",
            "dkl010h0",
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required column(s): {missing}")

        # Determine station code from iii
        iii_values = (
            df.select(pl.col("iii").drop_nulls().unique().sort())
            .get_column("iii")
            .to_list()
        )
        if not iii_values:
            raise ValueError("Column 'iii' contains no non-null values.")

        if len(iii_values) != 1:
            raise ValueError(
                f"Expected a yearly hourly parquet for one station only, "
                f"but found multiple iii values: {iii_values}"
            )

        iii_value = iii_values[0]

        station_map = {
            187: "MKN",
            # Add NRB here once confirmed, e.g.:
            # 123: "NRB",
        }

        if iii_value not in station_map:
            raise ValueError(
                f"No station mapping defined for iii={iii_value}. "
                f"Update station_map in export_to_wdcgg_format()."
            )

        site_gaw_id = station_map[iii_value]
        site_prefix = site_gaw_id.lower()

        # Determine year
        years = (
            df.select(pl.col("dtm").dt.year().drop_nulls().unique().sort())
            .get_column("dtm")
            .to_list()
        )
        if not years:
            raise ValueError("Column 'dtm' contains no valid datetimes.")

        if len(years) != 1:
            raise ValueError(
                f"Expected one yearly hourly parquet, but found multiple years: {years}"
            )

        year = int(years[0])

        # Build final output path
        filename = f"{site_prefix}_meteo_{year}.dat"
        if target.exists() and target.is_dir():
            out_path = target / filename
        elif target.suffix:
            out_path = target.parent / filename
        else:
            out_path = target / filename

        out_path.parent.mkdir(parents=True, exist_ok=True)

        out = (
            df.with_columns(
                [
                    pl.lit(site_gaw_id).alias("site_gaw_id"),
                    pl.col("dtm").dt.year().alias("year"),
                    pl.col("dtm").dt.month().alias("month"),
                    pl.col("dtm").dt.day().alias("day"),
                    pl.col("dtm").dt.hour().alias("hour"),
                    pl.col("dtm").dt.minute().alias("minute"),
                    pl.col("dtm").dt.second().alias("second"),
                    pl.col("dkl010h0").cast(pl.Float64, strict=False).alias("wind_direction"),
                    pl.col("fkl010h0").cast(pl.Float64, strict=False).alias("wind_speed"),
                    pl.col("uor200h0").cast(pl.Float64, strict=False).alias("relative_humidity"),
                    pl.col("prestah0").cast(pl.Float64, strict=False).alias("air_pressure"),
                    pl.col("tre200h0").cast(pl.Float64, strict=False).alias("air_temperature"),
                    pl.col("rre150h0").cast(pl.Float64, strict=False).alias("precipitation_amount"),
                    pl.col("gor000h0").cast(pl.Float64, strict=False).alias("global_solar_radiation"),
                    pl.lit(-0.0621999986).alias("latitude"),
                    pl.lit(37.2971992493).alias("longitude"),
                    pl.lit(3688).alias("altitude"),
                    pl.lit(3678).alias("elevation"),
                ]
            )
            .select(
                [
                    "site_gaw_id",
                    "year",
                    "month",
                    "day",
                    "hour",
                    "minute",
                    "second",
                    "wind_direction",
                    "wind_speed",
                    "relative_humidity",
                    "air_pressure",
                    "air_temperature",
                    "precipitation_amount",
                    "global_solar_radiation",
                    "latitude",
                    "longitude",
                    "altitude",
                    "elevation",
                ]
            )
            .sort(["year", "month", "day", "hour", "minute", "second"])
        )

        float_cols = [
            "wind_direction",
            "wind_speed",
            "relative_humidity",
            "air_pressure",
            "air_temperature",
            "precipitation_amount",
            "global_solar_radiation",
            "latitude",
            "longitude",
        ]
        out = out.with_columns([pl.col(c).fill_null(-99.9) for c in float_cols])

        header = " ".join(out.columns)
        lines = [header]

        for row in out.iter_rows(named=True):
            lines.append(
                " ".join(
                    [
                        str(row["site_gaw_id"]),
                        str(int(row["year"])),
                        str(int(row["month"])),
                        str(int(row["day"])),
                        str(int(row["hour"])),
                        str(int(row["minute"])),
                        str(int(row["second"])),
                        f"{float(row['wind_direction']):g}",
                        f"{float(row['wind_speed']):g}",
                        f"{float(row['relative_humidity']):g}",
                        f"{float(row['air_pressure']):g}",
                        f"{float(row['air_temperature']):g}",
                        f"{float(row['precipitation_amount']):g}",
                        f"{float(row['global_solar_radiation']):g}",
                        f"{float(row['latitude']):.10f}",
                        f"{float(row['longitude']):.10f}",
                        str(int(row["altitude"])),
                        str(int(row["elevation"])),
                    ]
                )
            )

        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out_path


if __name__ == "__main__":
    pass