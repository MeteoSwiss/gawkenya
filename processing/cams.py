import xarray as xr
import pandas as pd
import polars as pl
import cdsapi
import zipfile

cams_eac4_source = 'https://ads.atmosphere.copernicus.eu/cdsapp#!/dataset/cams-global-reanalysis-eac4-monthly'
cams_eac4_reference = 'Inness et al. (2019), http://www.atmos-chem-phys.net/19/3515/2019/'
cams_attribution = 'Contains modified Copernicus Atmosphere Monitoring Service information [2003-2023]'

def download_cams_monthly_ozone_data(product: str='cams-global-reanalysis-eac4-monthly',
                       target: str='data/level3/copernicus/cams/eac4',
                       years: range=range(2003, 2025)) -> str:
    """Download data from ECMWF for MKN coordinates and selected pressure levels. Files are zipped netCDF files.
    Consult https://ads.atmosphere.copernicus.eu/how-to-api for details on API use.

    Args:
        product (str, optional): _description_. Defaults to 'cams-global-reanalysis-eac4-monthly'.
        target (str, optional): _description_. Defaults to 'data/level3/copernicus/cams/eac4'.
        years (range, optional): _description_. Defaults to range(2003, 2024).
    Returns:
        str: relative filepath of product retrieved
    """

    c = cdsapi.Client()

    filepath = f'{target}/{product}.nc.zip'
    request = {
        'variable': ['ozone', 'temperature'],
        'pressure_level': [
            '1', '2', '3', '5', '7', '10', '20', '30', '50', '70',
            ],
        'year': [f"{y}" for y in years],
        'month': [f"{i:02}" for i in range(1, 13)],
        'product_type': ['monthly_mean'],
        'data_format': 'netcdf_zip',
        'area': [-1.3017, 36.7592, -1.3017, 36.7592,],
        }
    
    print(f"Downloading data from Copernicus ADS and saving to {filepath} ...")
    c.retrieve(product, request).download(f"{filepath}")
    return filepath


def convert_cams_nc_to_parquet(source: str) -> str:
    """Convert CAMS data retrieved from Atmospheric Data Store to a .parquet file. Ozone mass fractions are converted to ozon partial pressure in mPa.

    Args:
        source (str): relative (or absolute) path to source file

    Returns:
        str: relative (or absolute) path to target fle
    """
    # Constants
    M_air = 28.97  # Molar mass of air in g/mol
    M_ozone = 48  # Molar mass of ozone in g/mol
    
    target = source.replace('.nc.zip', '.parquet')
    print(f"Converting {source} to {target}")
    try:
        with zipfile.ZipFile(file=source, mode='r').open(name='data_allhours_plev.nc', mode='r') as zf:
            df_pd = xr.open_dataset(filename_or_obj=zf).to_dataframe().reset_index()
        
        df_pl = pl.from_pandas(df_pd)
        df_pl = df_pl.with_columns(pl.col('valid_time').dt.date().alias('dte'))
        df_pl = df_pl.drop(['longitude', 'latitude', 'valid_time'])

        # Convert the Ozone mass mixing ratio to partial pressure (Pa) for each pressure level
        # [go3] = kg/kg; [pressure_level] = hPa = 100 Pa
        df_pl = df_pl.with_columns((pl.col('go3') * (M_air / M_ozone) * pl.col('pressure_level') * 1e5).alias('O3_mPa'))
        df_pl.write_parquet(target)
        return
    except Exception as err:
        print(err)


def residual_ozone_cams(df: pl.DataFrame, start_level: int) -> float:
    try:
        print('todo')
    except Exception as err:
        print(err)
