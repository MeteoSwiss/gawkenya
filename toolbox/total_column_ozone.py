import polars as pl
import numpy as np

def total_column_ozone_from_pressure_profile(df: pl.DataFrame, pressure_col: str, ozone_col: str, other_cols: list=['O3_DU']) -> pl.DataFrame:
    """
    Calculate total column ozone from ozone partial pressure data in a Polars DataFrame.
    
    Parameters:
        df (pl.DataFrame): Polars DataFrame containing the data.
        pressure_col (str): Column name for pressure levels in hectopascals (hPa).
        ozone_col (str): Column name for ozone partial pressures in millipascals (mPa).

    Returns:
        pl.DataFrame: Polars DataFrame with cumulative ozone column 'O3_DU_calc' in Dobson Units (DU). Additionally, columns pressure_col, ozone_col and other_col are returned.
    """
    # Constants
    N_A = 6.02214076E+23  # Avogadro's number, 1/mol
    M = 0.0289652  # Molar mass of dry air in kg/mol
    g = 9.80665  # Acceleration due to gravity in m/s^2
    DU = 2.69e20  # Conversion factor for Dobson Units, molecules/m^2

    f_DU = N_A / M / g / DU  # Conversion factor for Dobson Units, Pa/molecule

    # Sort the dataframe by pressure in descending order
    df_sorted = df.sort(by=pressure_col, descending=True)

    # Extract relevant columns, eliminate Null values
    df_sorted = df_sorted.select([pressure_col, ozone_col] + other_cols)#.drop_nulls()

    # Interpolate missing values
    df_sorted = df_sorted.with_columns(
        df_sorted[ozone_col].interpolate(method='linear')
    )

    # Convert columns to numpy arrays for processing
    p_atm = df_sorted[pressure_col].to_numpy() * 100  # convert hPa to Pa
    p_o3 = df_sorted[ozone_col].to_numpy() * 1e-3  # convert mPa to Pa

    # Calculate the cumulative integrated number density of ozone using the trapezoidal rule
    o3_du_calc = np.array([
        np.trapz(p_o3[:i+1] / p_atm[:i+1], p_atm[:i+1]) * (-1) * f_DU
        for i in range(len(p_atm))
    ])

    # Create a new DataFrame with the cumulative ozone column added
    df_result = df_sorted.with_columns(
        pl.Series("O3_DU_calc", o3_du_calc),
    )
    
    return df_result