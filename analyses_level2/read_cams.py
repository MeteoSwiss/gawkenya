""" 
Select all CAMS data for the Mt. Kenya region and save as netcdfs. 

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""

# %%
import numpy as np
import os, sys
import xarray as xr
import pandas as pd
import glob

from molmass import Formula
from molmass import ELEMENTS, Element


import utilities
import zipfile


# %%
def read_cams_inv(
    dir_data,
    species="co2",
    yr1=2020,
    yr2=2023,
    dx=2.5,
    dy=1.3,
    fact_dxy=2,
    station="MKN",
):
    """
    Read in the full cams inversion data and select data around the station (station).
    Save the selected data as new netcdf.
    species     'co2' or 'ch4'
    dx          longitude grid width
    dy          latitude grid width
    fact_dxy    number of grids to select in each direction around the station
    """
    # get station coordinates
    lat, lon, alt = utilities.get_station_coords(station)

    dir_path = dir_data + rf"\invGG"
    # file_list = glob.glob(os.path.join(dir_path + rf'\cams73_latest_{species}_conc_*.nc'))

    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        data_chunk = xr.open_mfdataset(
            dir_path + rf"\cams73_latest_{species}_conc_*_{y}*.nc"
        )
        data_chunk = data_chunk.sortby(
            "latitude"
        )  # co2 data and ch4 data are not the same (starting with 90 or -90)!
        ds_sel = data_chunk.sel(
            latitude=slice(lat - dy * fact_dxy, lat + dy * fact_dxy),
            longitude=slice(lon - dx * fact_dxy, lon + dx * fact_dxy),
        ).load()
        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_sel
        else:
            ds_combined = xr.concat([ds_combined, ds_sel], dim="time")

    yr_start = ds_combined.time[0].dt.year.values
    yr_stop = ds_combined.time[-1].dt.year.values

    # unit conversion
    if species == "co2":
        ds_combined["CO2"] = ds_combined["CO2"] * 1e6  # CO2 in ppm
        ds_combined["CO2"].attrs["units"] = "ppm"
    if species == "ch4":
        ds_combined["CH4"].attrs["units"] = "ppb"

    # remove file if already existing
    fname = rf"..\data\cams\cams_invGG_{species}_{yr_start}_{yr_stop}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)
    ds_combined.to_netcdf(fname, mode="w")


# %%
def read_cams_egg4(dir_data, yr1=2020, yr2=2020, station="MKN"):
    """
    Read in the CAMS EGG4 data and save as new netcdf.

    """
    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        ds_temp = xr.open_mfdataset(dir_data + rf"\EGG4\cams_egg4_{y}*_{station}.nc")

        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_temp
        else:
            ds_combined = xr.concat([ds_combined, ds_temp], dim="time")

    yr1 = ds_combined.time[0].dt.year.values
    yr2 = ds_combined.time[-1].dt.year.values

    # rename variables:
    ds_combined = ds_combined.rename({"co2": "CO2", "ch4": "CH4"})

    # unit conversion (mass mixing ratio to volume mixing ratio)
    M_air = 28.9647  # molar weight of dry air (g/mol)
    selected_variables = ds_combined.filter_by_attrs(units="kg kg**-1")
    for var_name, value in selected_variables.data_vars.items():
        if var_name == "CO2":
            pp = 1e6  # ppm
            unit = "ppm"
        elif var_name == "CH4":
            pp = 1e9  # ppb
            unit = "ppb"
        M_gas = Formula(var_name).mass
        ds_combined[var_name] = (
            ds_combined[var_name] * (M_air / M_gas) * pp
        )  # in ppm or ppb
        ds_combined[var_name] = ds_combined[var_name].assign_attrs(units=unit)

    fname = rf"..\data\cams\cams_egg4_{yr1}_{yr2}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)

    ds_combined.to_netcdf(fname)
    
# %%
def read_cams_gfas(dir_data, yr1=2020, yr2=2023):
    """
    Read in all CAMS GFAS biomass burning data and save as new netcdf.

    """
    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        ds_temp = xr.open_mfdataset(dir_data + rf"\GFAS\cams_gfas_{y}*.nc")

        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_temp
        else:
            ds_combined = xr.concat([ds_combined, ds_temp], dim="time")

    yr1 = ds_combined.time[0].dt.year.values
    yr2 = ds_combined.time[-1].dt.year.values

    # rename variables:
    #ds_combined = ds_combined.rename({"co2": "CO2", "ch4": "CH4"})

    fname = rf"..\data\cams\cams_gfas_{yr1}_{yr2}.nc"
    if os.path.isfile(fname):
        os.remove(fname)

    ds_combined.to_netcdf(fname)

# %%
def read_cams_eac4(dir_data, station="MKN"):
    """
    Read in the full cams EAC4 data.
    Two seperate .nc files are saved as a zip file for each month. The files should already contain 9 grids around the MKN station (downloadedf with kadi_get_cams.py)

    Extract that zip-file, read in the files and merge to a netcdf.
    Save the merged data as new netcdf.

    """
    dir_path = dir_data + rf"\EAC4"
    file_list = os.listdir(dir_path)

    ds_combined = None

    # read data:
    # loop through all zip-files and extract them

    for file_name in file_list:
        if file_name.endswith("_MKN.zip"):
            zip_path = os.path.join(dir_path, file_name)
            zip_extract = os.path.join(dir_path, os.path.splitext(file_name)[0])
            os.makedirs(zip_extract, exist_ok=True)

            # read and extract the zip file
            with zipfile.ZipFile(zip_path, "r") as zip_sel:
                zip_sel.extractall(zip_extract)

            # open the 2 netcdfs in the extracted folder and merge them to one dataset
            eac4_pl_temp = xr.open_dataset(
                rf"{zip_extract}\levtype_pl.nc"
            )  # pressure level
            eac4_sfc_temp = xr.open_dataset(
                rf"{zip_extract}\levtype_sfc.nc"
            )  # single level

            eac4_merged_temp = xr.merge([eac4_pl_temp, eac4_sfc_temp])

            # Concatenate along the time dimension to create a single dataset
            if ds_combined is None:
                ds_combined = eac4_merged_temp
            else:
                ds_combined = xr.concat([ds_combined, eac4_merged_temp], dim="time")

            yr1 = ds_combined.time[0].dt.year.values
            yr2 = ds_combined.time[-1].dt.year.values

    # Rename variables
    ds_combined = ds_combined.rename({"go3": "O3", "co": "CO"})

    # unit conversion (O3 and CO are given in mass mixing ratio, convert to volume mixing ratio)
    M_air = 28.9647  # molar weight of dry air (g/mol)
    for var_name in ["CO", "O3"]:
        if var_name == "CO":
            M_gas = 16 + 12
        elif var_name == "O3":
            M_gas = 3 * 16
        my_attrs = ds_combined[
            var_name
        ].attrs  # workaround to preserve attributes after multiplication
        ds_combined[var_name] = ds_combined[var_name] * (M_air / M_gas) * 1e9  # in ppb
        ds_combined[var_name].attrs.update(
            my_attrs
        )  # reassign attributes (not working??)
        ds_combined[var_name] = ds_combined[var_name].assign_attrs(units="ppb")

    fname = rf"..\data\cams\cams_eac4_{yr1}_{yr2}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)
    ds_combined.to_netcdf(fname, mode="w")


def get_best_cams(obs_all, obs_datasets=["CO2", "CH4", "CO", "O3"], 
                  cams_datasets = ["co2_invgg","co2_egg4","ch4_invgg","ch4_egg4","co_eac4","o3_eac4"],
                  save_netcdf=True):
    # for now, only concentrate on data starting in 2020! (so no flask data)

    # if obs_datasets==[]:
    #   obs_datasets = obs_all.dataset #use all available datasets

    ## take 3h mean of observations
    print("take 3h mean of observations")
    obs_all_3h = obs_all.resample(time="3h").mean(keep_attrs=True)
    print("take 6h mean of observations")
    obs_all_6h = obs_all.resample(time="6h").mean(keep_attrs=True)

    # Read all cams datasets
    dir_data_cams = r"../data/cams"
    cams_invgg_co2 = xr.open_dataset(
        dir_data_cams + r"/cams_invGG_co2_2020_2023_MKN.nc"
    )
    cams_invgg_ch4 = xr.open_dataset(
        dir_data_cams + r"/cams_invGG_ch4_2020_2021_MKN.nc"
    )
    cams_eac4 = xr.open_dataset(dir_data_cams + r"/cams_eac4_2003_2022_MKN.nc")
    cams_egg4 = xr.open_dataset(dir_data_cams + r"/cams_egg4_2003_2020_MKN.nc")

    # for each observational dataset, define the corresponding cams dataset and find the best cams-grid
    datasets = []
    attributes_dict = {}
    for i, ds_name in enumerate(cams_datasets):
        print(f"find best grid for {ds_name}")
        #CO2
        if ds_name == "co2_invgg":
            cams_sel = cams_invgg_co2["CO2"]
            obs_sel = obs_all_3h.sel(dataset="CO2")
        elif ds_name == "co2_egg4":
            cams_sel = cams_egg4["CO2"]
            obs_sel = obs_all_3h.sel(dataset="CO2") 
        #CH4
        elif ds_name == "ch4_invgg":
            cams_sel = cams_invgg_ch4["CH4"]
            obs_sel = obs_all_6h.sel(dataset="CH4")  # methane only 6hourly
        elif ds_name == "ch4_egg4":
            cams_sel = cams_egg4["CH4"] 
            obs_sel = obs_all_3h.sel(dataset="CH4") 
        #CO
        elif ds_name == "co_eac4":
            cams_sel = cams_eac4["CO"]
            obs_sel = obs_all_3h.sel(dataset="CO")
        #O3
        elif ds_name == "o3_eac4":
            cams_sel = cams_eac4["O3"]
            obs_sel = obs_all_3h.sel(dataset="O3")

        times_nonan_obs = obs_sel.where(obs_sel.value.notnull(), drop=True).time
        times_nonan_cams = cams_sel.where(cams_sel.notnull(), drop=True).time
        # get time period where both are available
        tend = np.min([times_nonan_obs[-1].values, times_nonan_cams[-1].values])
        tstart = np.max([times_nonan_obs[0].values, times_nonan_cams[0].values])
        cams = cams_sel.sel(time=slice(tstart, tend))
        obs = obs_sel.sel(time=slice(tstart, tend)).value.to_dataframe()["value"]
        # find the best grid point (best correlated for whole period)
        best_grid = utilities.find_best_grid_point(cams, obs)

        cams_best = cams.sel(
            latitude=best_grid[0], longitude=best_grid[1], level=best_grid[2]
        )
        cams_best = cams_best.assign_coords(dataset=ds_name)
        cams_best = cams_best.rename(
            "value"
        )  # give the same name ("value") to all species
        cams_best["unit"] = cams_best.attrs["units"]
        datasets.append(cams_best.to_dataset())  # append

    cams_best_datasets = xr.concat(datasets, dim="dataset")

    ## merge
    if save_netcdf:
        fname = rf"..\data\cams\cams_best_grid_MKN.nc"
        if os.path.isfile(fname):
            os.remove(fname)
        cams_best_datasets.to_netcdf(fname, mode="w")

    return cams_best_datasets


# %%
def main(dir_data=r"..\Data\CAMS", station="MKN"):
    # when debugging directly in the file: dir_data = r"..\..\Data"
    read_cams_inv(
        dir_data,
        species="ch4",
        yr1=2020,
        yr2=2021,
        dx=3,
        dy=2,
        fact_dxy=2,
        station=station,
    )  # ch4: coarser resolution
    read_cams_inv(dir_data, species="co2", yr1=2020, yr2=2023, station=station)

    read_cams_eac4(dir_data, station=station)
    read_cams_egg4(dir_data, yr1=2003, yr2=2020, station=station)


if __name__ == "__main__":
    main()
