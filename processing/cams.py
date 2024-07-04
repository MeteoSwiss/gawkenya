import xarray as xr
import pandas as pd
import polars as pl
import cdsapi

cams_eac4_source = 'https://ads.atmosphere.copernicus.eu/cdsapp#!/dataset/cams-global-reanalysis-eac4'
cams_eac4_reference = 'Inness et al. (2019), http://www.atmos-chem-phys.net/19/3515/2019/'
cams_attribution = 'Contains modified Copernicus Atmosphere Monitoring Service information [2003-2023]'

def download_cams_monthly_ozone_data(product: str='cams-global-reanalysis-eac4-monthly',
                       target: str='data/level3/copernicus/cams/eac4',
                       years: range=range(2003, 2024),
                       convert: bool=True) -> None:

    c = cdsapi.Client()

    for year in years:
        filepath = f'{target}/{product}_{year}'
        print(f"Downloading data from CDS and saving to {filepath}.nc ...")
        c.retrieve(
            product,
            {
                'format': 'netcdf',
                'variable': ['ozone', 'temperature'],
                'pressure_level': [
                    '1', '2', '3',
                    '5', '7', '10',
                    '20', '30', '50',
                    '70',
                ],
                'year': [str(year)],
                'month': [
                    '01', '02', '03',
                    '04', '05', '06',
                    '07', '08', '09',
                    '10', '11', '12',
                ],
                'product_type': 'monthly_mean',
                'area': [
                    -1.3017, 36.7592, -1.3017, 36.7592,
                ],
            },
            f'{filepath}.nc',
            )
        
        if convert:
            convert_cams_nc_to_parquet(filepath)
    return


def convert_cams_nc_to_parquet(filepath: str):
    # Constants
    M_air = 28.97  # Molar mass of air in g/mol
    M_ozone = 48  # Molar mass of ozone in g/mol

    print(f"Converting {filepath}.nc to {filepath}.parquet")
    try:
        df_pd = xr.open_dataset(f'{filepath}.nc').to_dataframe().reset_index()
        df_pl = pl.from_pandas(df_pd)
        df_pl = df_pl.with_columns(pl.col('time').dt.date().alias('dte'))
        df_pl = df_pl.drop(['longitude', 'latitude', 'time'])

        # Convert the Ozone mass mixing ratio to partial pressure (Pa) for each pressure level
        # [go3] = kg/kg; [level] = hPa = 100 Pa
        df_pl = df_pl.with_columns((pl.col('go3') * (M_air / M_ozone) * pl.col('level') * 1e5).alias('O3_mPa'))
        df_pl.write_parquet(f'{filepath}.parquet')
        return
    except Exception as err:
        print(err)


def residual_ozone_cams(df: pl.DataFrame, start_level: int) -> float:
    try:
        print('todo')
    except Exception as err:
        print(err)




