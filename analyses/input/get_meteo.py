import json
import xarray as xr
import pandas as pd
import re
import polars as pl


def get_meteo_timeseries_new(data_path= "../../data/",yr_start=2022,yr_end=2024):

    ## Get temperature data (after 2023):
    #read json file:
    meta_data = json.load(open(f"{data_path}/level2/mkn/{yr_end}/mkn_meteo_1h.json"))
    list_meteo = []
    for year in range(yr_start,yr_end+1):
        meteo = pl.read_parquet(data_path + f'/level2/mkn/{year}/mkn_meteo_1h.parquet')
        df_meteo = meteo.to_pandas()
        df_meteo.set_index('dtm', inplace=True)
        df_meteo.index = pd.to_datetime(df_meteo.index)
        df_meteo.index = df_meteo.index.tz_localize(None)
        # append years
        list_meteo.append(df_meteo)
    df_meteo_all = pd.concat(list_meteo)

    ds_meteo = df_meteo_all.to_xarray()
    ds_meteo = ds_meteo.rename({'dtm':'time'})

    # rename variables and add attributes
    for var in ds_meteo.data_vars:
        ds_meteo[var].attrs['description'] = meta_data[var]
        # unit: select last parantheses of string
        ds_meteo[var].attrs['unit'] = re.findall(r'\((.*?)\)',meta_data[var])[-1]
        ds_meteo[var].attrs['varname'] = var

    ds_meteo = ds_meteo.rename_vars({'ta2200h0': 'temperature', #2m temperature
                            'prestah0': 'pressure', #station pressure
                            'ua2200h0': 'rh', #2m relative humidity
                            'fkl010h0': 'windspeed', #10m windspeed
                            'dkl010h0': 'winddirection', #10m wind direction
                            'rre150h0': 'precipitation', #rain
                            'gre000h0': 'radiation', #global radiation
    })
    return ds_meteo

def get_meteo_timeseries_old(data_path= "../../data/"):
    ##---- data before 2023 (not very regular data)
    meteo_old = pl.read_parquet(data_path + "level1/mkn/dwh_mkn_meteo_1h_20170101000000-20240101000000.parquet")
    #meteo = pl.read_parquet(data_path + "level1/mkn/dwh_mkn_meteo_raw.parquet")
    metadata_old = {
        'prestah0': '2m pressure (QFE), Lufft (hPa)',
        'ta2200h0': '2m temperature, Rotronic (°C)',
        'ua2200h0': '2m relative humidity, Rotronic (%)',
        'fkl010h0': '10m horizontal wind speed (m/s)',
        'dkl010h0': '10m horizontal wind direction (deg)',
        'rre150h0': '2m precipitation, Lufft (mm/h)',
        'gre000h0': '2m global radiation, Lufft (W/m2)',
        'tre200h0': '2m temperature, Lufft (up until 19 Oct 2023 09 UTC)',
        'ure200h0': '2m relative humidity, Lufft (%) (up until 19 Oct 2023 09 UTC)',
    }


    df_meteo_old = meteo_old.to_pandas()
    df_meteo_old.set_index('dtm', inplace=True)
    df_meteo_old.index = pd.to_datetime(df_meteo_old.index)
    df_meteo_old.index = df_meteo_old.index.tz_localize(None)

    ds_meteo_old = df_meteo_old.to_xarray()
    ds_meteo_old = ds_meteo_old.rename({'dtm':'time'})

    # rename variables and add attributes
    for var in ds_meteo_old.data_vars:
        #if the variable is in metadata, add the description
        if var in metadata_old.keys():
            ds_meteo_old[var].attrs['description'] = metadata_old[var]
            # unit: select last parantheses of string
            ds_meteo_old[var].attrs['unit'] = re.findall(r'\((.*?)\)',metadata_old[var])[-1]
            ds_meteo_old[var].attrs['varname'] = var

    new_names = {
            'prestah0': 'pressure',
            'fkl010h0': 'windspeed',
            'dkl010h0': 'winddirection',
            'rre150h0': 'precipitation',
            'gre000h0': '2radiation',
            'tre200h0': 'temperature', #2m temperature (up until 19 Oct 2023 09 UTC)
            'ure200h0': 'rh', #(up until 19 Oct 2023 09 UTC)
    }
    # drop variables that are not in new_names
    ds_meteo_old = ds_meteo_old.drop_vars([var for var in ds_meteo_old.data_vars if var not in new_names.keys()])
    # rename variables:
    ds_meteo_old = ds_meteo_old.rename_vars(new_names)
    #
    #restrict to data before 2023
    ds_meteo_old = ds_meteo_old.sel(time=slice(None,'2022-12-31 23:00:00'))
    #temperature = ds_meteo['tre200h0'] # '2m temperature, Lufft (up until 19 Oct 2023 09 UTC)
    return ds_meteo_old