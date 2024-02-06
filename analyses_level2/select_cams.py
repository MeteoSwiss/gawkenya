""" 
Select all CAMS data for the Mt. Kenya region and save as netcdfs. 

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""
#%%
import numpy as np
import os,sys
import xarray as xr
import pandas as pd
import glob


import utilities
import zipfile


#%%
def read_cams_inv(dir_data,species='co2',yr1=2020,yr2=2023,dx=2.5, dy=1.3, fact_dxy=2, station='MKN'):
    '''
    Read in the full cams inversion data and select data around the station (station). 
    Save the selected data as new netcdf.
    species     'co2' or 'ch4'
    dx          longitude grid width
    dy          latitude grid width
    fact_dxy    number of grids to select in each direction around the station
    '''
    # get station coordinates
    lat,lon,alt= utilities.get_station_coords(station) 

    dir_path = dir_data+ rf"\invGG"
    #file_list = glob.glob(os.path.join(dir_path + rf'\cams73_latest_{species}_conc_*.nc'))

    ds_combined = None
    #read data

    for y in np.arange(yr1,yr2+1):
        print(f'read year {y}')
        data_chunk = xr.open_mfdataset(dir_path+ rf'\cams73_latest_{species}_conc_*_{y}*.nc')
        data_chunk = data_chunk.sortby('latitude') # co2 data and ch4 data are not the same (starting with 90 or -90)!
        ds_sel = data_chunk.sel(latitude=slice(lat-dy*fact_dxy,lat+dy*fact_dxy),
                              longitude=slice(lon-dx*fact_dxy,lon+dx*fact_dxy)
                              ).load()
        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_sel
        else:
            ds_combined = xr.concat([ds_combined, ds_sel], dim='time')

    yr_start = ds_combined.time[0].dt.year.values
    yr_stop = ds_combined.time[-1].dt.year.values

    ds_combined.to_netcdf(rf'..\data\cams\cams_invGG_{species}_{yr_start}_{yr_stop}_{station}.nc')

#%%
def read_cams_egg4(dir_data,yr1=2003,yr2=2020, station='MKN'):
    '''
    Read in the CAMS EGG4 data and save as new netcdf.

    '''
    ds_combined = None
    #read data

    for y in np.arange(yr1,yr2+1):
        print(f'read year {y}')
        ds_temp = xr.open_mfdataset(dir_data+ rf'\EGG4\cams_egg4_{y}*_{station}.nc')

        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_temp
        else:
            ds_combined = xr.concat([ds_combined, ds_temp], dim='time')
    
    yr1 = ds_combined.time[0].dt.year.values
    yr2 = ds_combined.time[-1].dt.year.values

    ds_combined.to_netcdf(rf'..\data\cams\cams_egg4_{yr1}_{yr2}_{station}.nc')


#%%
def read_cams_eac4(dir_data, station='MKN'):
    '''
    Read in the full cams EAC4 data. 
    Two seperate .nc files are saved as a zip file for each month. The files should already contain 9 grids around the MKN station (downloadedf with kadi_get_cams.py)

    Extract that zip-file, read in the files and merge to a netcdf. 
    Save the merged data as new netcdf.

    '''
    dir_path = dir_data+ rf"\EAC4"
    file_list = os.listdir(dir_path)

    ds_combined = None

    #read data: 
    # loop through all zip-files and extract them

    for file_name in file_list: 
        if file_name.endswith('_MKN.zip'):
            zip_path = os.path.join(dir_path,file_name)
            zip_extract = os.path.join(dir_path, os.path.splitext(file_name)[0])
            os.makedirs(zip_extract, exist_ok=True)

            # read and extract the zip file
            with zipfile.ZipFile(zip_path, 'r') as zip_sel: 
                zip_sel.extractall(zip_extract)

            # open the 2 netcdfs in the extracted folder and merge them to one dataset
            eac4_pl_temp  = xr.open_dataset(rf'{zip_extract}\levtype_pl.nc') #pressure level
            eac4_sfc_temp = xr.open_dataset(rf'{zip_extract}\levtype_sfc.nc') #single level

            eac4_merged_temp = xr.merge([eac4_pl_temp,eac4_sfc_temp])

            # Concatenate along the time dimension to create a single dataset
            if ds_combined is None:
                ds_combined = eac4_merged_temp
            else:
                ds_combined = xr.concat([ds_combined, eac4_merged_temp], dim='time')

            yr1 = ds_combined.time[0].dt.year.values
            yr2 = ds_combined.time[-1].dt.year.values

    ds_combined.to_netcdf(rf'..\data\cams\cams_eac4_{yr1}_{yr2}_{station}.nc')


#%%
def main(dir_data = r"..\Data\CAMS",station='MKN'):
    # when debugging directly in the file: dir_data = r"..\..\Data"
    read_cams_inv(dir_data,species='ch4',yr1=2020,yr2=2021,dx=3,dy=2,fact_dxy=2,station=station) #ch4: coarser resolution
    read_cams_inv(dir_data,species='co2',yr1=2020,yr2=2023,station=station)

    read_cams_eac4(dir_data,station=station)
    read_cams_egg4(dir_data,yr1=2003,yr2=2020,station=station)

if __name__ == '__main__':
    main()