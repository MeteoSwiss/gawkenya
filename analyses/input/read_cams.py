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

import zipfile
import shutil

## Add parent directory to syspath
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if not parent_dir in sys.path:
    sys.path.append(parent_dir)
from utils import utilities
#%%
def cams_unzip(dir_path="/input/ECMWF/CAMS/EAC4_africa"):
    """
    Some cams products (e.g. EAC4) are given as zip-files, containing one netcdf per level (e.g. pressure, surface or model level)
    This function extracts the zip files, merges the containing netcdfs, and saves them as a new netcdf (with the same name as the initial zip-file)
    """

        
    file_list = [os.path.join(dir_path, file) for file in os.listdir(dir_path) if file.endswith(".zip")]

    # read data:
    # loop through all zip-files and extract them

    for file_name in file_list:
        zip_path = os.path.join(dir_path, file_name)
        zip_extract = os.path.join(dir_path, os.path.splitext(file_name)[0])
        new_file_name = zip_extract + ".nc"
        #skip if the merged nc file does already exist:
        if os.path.isfile(new_file_name):
            print(f"File {new_file_name} already exists. Skip.")
            continue
        print(f"unzip {file_name}")
        os.makedirs(zip_extract, exist_ok=True)

        # read and extract the zip file
        with zipfile.ZipFile(zip_path, "r") as zip_sel:
            zip_sel.extractall(zip_extract)

        extracted_files_list = os.listdir(zip_extract)
        # open the netcdfs in the extracted folder and merge them to one dataset
        cams_temps = []
        for nc_file in extracted_files_list:
            cams_temp = xr.open_dataset(os.path.join(zip_extract, nc_file))
            cams_temps.append(cams_temp)
        cams_combined = xr.merge(cams_temps)
        cams_combined = cams_combined.rename(
            {"valid_time": "time", "model_level": "level"}
        )
        cams_combined.to_netcdf(new_file_name)
        print(f"Merged file saved as {new_file_name}")



# %%
def read_cams_inv(
    dir_data,
    dir_out="../../data/cams",
    species="co2",
    yr1=2020,
    yr2=2023,
    month1=1,
    month2=12,
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
    yr1,yr2     Starting and ending year
    month1,month2   Starting month in yr1 and ending month in yr2, only needed if we should not read full data of a year
    """
    # get months as string with leading zero
    month1_str = "{:02d}".format(int(month1))
    month2_str = "{:02d}".format(int(month2))

    # get station coordinates
    lat, lon, alt = utilities.get_station_coords(station)

    dir_path = dir_data + "/invGG"
    # file_list = glob.glob(os.path.join(dir_path + rf'/cams73_latest_{species}_conc_*.nc'))

    # first, extract all zip files
    file_list = os.listdir(dir_path)
    for file_name in file_list:
        if file_name.endswith(".zip"):
            zip_path = os.path.join(dir_path, file_name)
            zip_extract = os.path.join(dir_path, os.path.splitext(file_name)[0])
            os.makedirs(zip_extract, exist_ok=True)

            # read and extract the zip file
            with zipfile.ZipFile(zip_path, "r") as zip_sel:
                zip_sel.extractall(zip_extract)
            # move the extracted files to the main directory
            extracted_files = os.listdir(zip_extract)
            for extracted_file in extracted_files:
                src_file = os.path.join(zip_extract, extracted_file)
                dst_file = os.path.join(dir_path, extracted_file)
                shutil.move(src_file, dst_file)
            # remove the empty directory and the zip file
            os.rmdir(zip_extract)
            os.remove(zip_path)

    # read data
    ds_combined = None
    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        data_files = glob.glob(dir_path + f"/cams73_latest_{species}_conc_*_{y}*.nc")
        for file in data_files:
            if y == yr1 and file[-5:-3] < month1_str:
                # skip months before given first month1 in yr1
                continue
            if y == yr2 and file[-5:-3] > month2_str:
                # skip months after given last month2 in yr2
                continue
            data_chunk = xr.open_dataset(file)
            data_chunk = data_chunk.sortby("latitude")
            ds_sel = data_chunk.sel(
                latitude=slice(lat - dy * fact_dxy, lat + dy * fact_dxy),
                longitude=slice(lon - dx * fact_dxy, lon + dx * fact_dxy),
            ).load()
            # Concatenate along the time dimension to create a single dataset
            if ds_combined is None:
                ds_combined = ds_sel
            else:
                ds_combined = xr.concat([ds_combined, ds_sel], dim="time")

    date_start = str(ds_combined.time[0].dt.year.values) + "{:02d}".format(int(ds_combined.time[0].dt.month.values))
    date_stop = str(ds_combined.time[-1].dt.year.values)  + "{:02d}".format(int(ds_combined.time[-1].dt.month.values))

    # unit conversion
    if species == "co2":
        ds_combined["CO2"] = ds_combined["CO2"] * 1e6  # CO2 in ppm
        ds_combined["CO2"].attrs["units"] = "ppm"
    if species == "ch4":
        ds_combined["CH4"].attrs["units"] = "ppb"

    # remove file if already existing
    fname = f"{dir_out}/cams_invGG_{species}_{date_start}_{date_stop}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)
    ds_combined.to_netcdf(fname, mode="w")


# %%
def read_cams_egg4(
    dir_data, dir_out="../../data/cams", yr1=2020, yr2=2020, station="MKN"
):
    """
    Read in the CAMS EGG4 data and save as new netcdf.

    """
    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        ds_temp = xr.open_mfdataset(dir_data + f"/EGG4/cams_egg4_{y}*_{station}.nc")

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

    fname = f"{dir_out}/cams_egg4_{yr1}_{yr2}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)

    ds_combined.to_netcdf(fname)


# %%
def read_cams_gfas(dir_data, dir_out="../../data/cams", yr1=2020, yr2=2024,save_combined_netcdf=False):
    """
    Read in all CAMS GFAS biomass burning data and save as new netcdf.

    """
    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        ds_temp = xr.open_mfdataset(dir_data + f"/cams_gfas_{y}*.nc")
        #ds_temp = xr.open_mfdataset(dir_data + f"/GFAS/cams_gfas_{y}*.nc")

        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_temp
        else:
            ds_combined = xr.concat([ds_combined, ds_temp], dim="valid_time")

    # Data from new Atmospheric Data Store (ADS) is now sorted by valid_time. Rename to time. 
    ds_combined = ds_combined.rename({'valid_time': 'time'})

    yr1 = ds_combined.time[0].dt.year.values
    yr2 = ds_combined.time[-2].dt.year.values # in the new data, the last time step of 31.12. is 01.01. 00:00 of the next year

    # rename variables:
    # ds_combined = ds_combined.rename({"co2": "CO2", "ch4": "CH4"})

    if save_combined_netcdf:
        fname = f"{dir_out}/cams_gfas_{yr1}_{yr2}.nc"
        if os.path.isfile(fname):
            os.remove(fname)

        ds_combined.to_netcdf(fname)

    return ds_combined


# %%
def read_cams_eac4(dir_data, dir_out="../../data/cams", station="MKN"):
    """
    Read in the full cams EAC4 data.
    Two seperate .nc files are saved as a zip file for each month. The files should already contain 9 grids around the MKN station (downloadedf with kadi_get_cams.py)

    Extract that zip-file, read in the files and merge to a netcdf.
    Save the merged data as new netcdf.

    """
    dir_path = dir_data + "/EAC4"
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
                f"{zip_extract}/levtype_pl.nc"
            )  # pressure level
            eac4_sfc_temp = xr.open_dataset(
                f"{zip_extract}/levtype_sfc.nc"
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

    fname = f"{dir_out}/cams_eac4_{yr1}_{yr2}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)
    ds_combined.to_netcdf(fname, mode="w")

def read_cams_eac4_aerosols(dir_data, yr1=2020,yr2=2023, dir_out="data/cams", station="MKN"):
    """
    Read in the cams EAC4 aerosol mxing ratio data (because that was downloaded seperately, not required if you download all EAC4 data at once).

    Read in the files and merge to a netcdf.
    Save the merged data as new netcdf.

    """
    dir_path = dir_data + f"/EAC4_aerosols"

    ds_combined = None
    # read data

    for y in np.arange(yr1, yr2 + 1):
        print(f"read year {y}")
        ds_temp = xr.open_mfdataset(dir_path + f"/cams_eac4_{y}*.nc")

        # Concatenate along the time dimension to create a single dataset
        if ds_combined is None:
            ds_combined = ds_temp
        else:
            ds_combined = xr.concat([ds_combined, ds_temp], dim="time")

    yr1 = ds_combined.time[0].dt.year.values
    yr2 = ds_combined.time[-1].dt.year.values


    fname = f"{dir_out}/cams_eac4_aerosols_{yr1}_{yr2}_{station}.nc"
    if os.path.isfile(fname):
        os.remove(fname)
    ds_combined.to_netcdf(fname, mode="w")


def get_best_cams(
    obs_all,
    dir_in="../../../Data/CAMS",
    dir_out="../../data/level3/cams",
    obs_datasets=["CO2", "CH4", "CO", "O3"],
    cams_datasets=[
        "co2_invgg",
        "co2_invgg2", #2nd period with higer resolution
        "co2_egg4",
        "ch4_invgg",
        "ch4_invgg2",#2nd period with higer resolution
        "ch4_egg4",
        "co_eac4",
        "o3_eac4",
    ],
    save_netcdf=True,
):
    """
    Get the best grid point for each observational dataset and save the corresponding CAMS data as netcdf.
    cams_datasets: list of CAMS datasets to consider
    obs_datasets: list of observational datasets to consider (finally not used)
    """
    # for now, only concentrate on data starting in 2020! (so no flask data)

    # if obs_datasets==[]:
    #   obs_datasets = obs_all.dataset #use all available datasets

    ## take 3h mean of observations
    print("take 3h mean of observations")
    obs_all_3h = obs_all.resample(time="3h").mean(keep_attrs=True)
    print("take 6h mean of observations")
    obs_all_6h = obs_all.resample(time="6h").mean(keep_attrs=True)

    # Read all cams datasets (Give the correct filenames!)
    dir_data_cams = "../data/level3/cams"
    cams_invgg_co2 = xr.open_dataset(
        dir_data_cams + "/cams_invGG_co2_202001_202306_MKN.nc"
    )
    cams_invgg_co2_2 = xr.open_dataset(
        dir_data_cams + "/cams_invGG_co2_202307_202309_MKN.nc"
    )
    cams_invgg_ch4 = xr.open_dataset(
        dir_data_cams + "/cams_invGG_ch4_202001_202112_MKN.nc"
    )
    cams_invgg_ch4_2 = xr.open_dataset(
        dir_data_cams + "/cams_invGG_ch4_202201_202312_MKN.nc"
    )
    cams_eac4 = xr.open_dataset(dir_data_cams + "/cams_eac4_2003_2023_MKN.nc")
    cams_egg4 = xr.open_dataset(dir_data_cams + "/cams_egg4_2003_2020_MKN.nc")

    # for each observational dataset, define the corresponding cams dataset and find the best cams-grid
    datasets = []
    attributes_dict = {}
    for i, ds_name in enumerate(cams_datasets):
        print(f"find best grid for {ds_name}")
        # CO2
        if ds_name == "co2_invgg":
            cams_sel = cams_invgg_co2["CO2"]
            obs_sel = obs_all_3h.sel(dataset="CO2")
        if ds_name == "co2_invgg2":#2nd period with higer resolution
            cams_sel = cams_invgg_co2_2["CO2"]
            obs_sel = obs_all_3h.sel(dataset="CO2")
        elif ds_name == "co2_egg4":
            cams_sel = cams_egg4["CO2"]
            obs_sel = obs_all_3h.sel(dataset="CO2")
        # CH4
        elif ds_name == "ch4_invgg":
            cams_sel = cams_invgg_ch4["CH4"]
            obs_sel = obs_all_6h.sel(dataset="CH4")  # methane only 6hourly
        elif ds_name == "ch4_invgg2":#2nd period with higer resolution
            cams_sel = cams_invgg_ch4_2["CH4"]
            obs_sel = obs_all_6h.sel(dataset="CH4")  # methane only 6hourly
        elif ds_name == "ch4_egg4":
            cams_sel = cams_egg4["CH4"]
            obs_sel = obs_all_3h.sel(dataset="CH4")
        # CO
        elif ds_name == "co_eac4":
            cams_sel = cams_eac4["CO"]
            obs_sel = obs_all_3h.sel(dataset="CO")
        # O3
        elif ds_name == "o3_eac4":
            cams_sel = cams_eac4["O3"]
            obs_sel = obs_all_3h.sel(dataset="O3")

        times_nonan_obs = obs_sel.where(obs_sel.value.notnull(), drop=True).time
        times_nonan_cams = cams_sel.where(cams_sel.notnull(), drop=True).time
        # get time period where both are available
        tend = np.min([times_nonan_obs[-1].values, times_nonan_cams[-1].values])
        tstart = np.max([times_nonan_obs[0].values, times_nonan_cams[0].values])
            
        # Function to select the best grid. Append the selection to datasets
        def get_best(tstart,tend,cams_sel,obs_sel,ds_name):
            cams = cams_sel.sel(time=slice(tstart, tend))
            obs = obs_sel.sel(time=slice(tstart, tend)).value.to_dataframe()["value"]
            # find the best grid point (best correlated for whole period)
            best_grid = utilities.find_best_grid_point(cams, obs)

            cams_best = cams.sel(
                latitude=best_grid[0], longitude=best_grid[1], level=best_grid[2]
            )
            # add dataset as a new dimension and use the dataset name as a coordinate
            cams_best = cams_best.expand_dims(dataset = [ds_name])
            #cams_best = cams_best.assign_coords(dataset=ds_name)
            cams_best = cams_best.rename(
                "value"
            )  # give the same name ("value") to all species
            #transform dataarray to dataset
            ds_cams_best = cams_best.to_dataset()
            #add dataset-dimension to all coordinates
            ds_cams_best = ds_cams_best.assign(
                latitude=("dataset", [cams_best.latitude.values]),
                longitude=("dataset", [cams_best.longitude.values]),
                level=("dataset", [cams_best.level.values]),
                unit=("dataset", [cams_best.attrs["units"]])
            )
            ds_cams_best["unit"] = cams_best.attrs["units"]

            datasets.append(ds_cams_best)  # append
            return cams_best
        cams_best = get_best(tstart,tend,cams_sel,obs_sel,ds_name)    
        
    cams_best_datasets = xr.concat(datasets, dim="dataset")

    ## merge
    if save_netcdf:
        fname = f"{dir_out}/cams_best_grid_MKN.nc"
        if os.path.isfile(fname):
            os.remove(fname)
        cams_best_datasets.to_netcdf(fname, mode="w")

    return cams_best_datasets


# %%
def main(dir_data="../../Data/CAMS", station="MKN"):
    # when debugging directly in the file: dir_data = "../../Data/CAMS"
    # read_cams_inv(
    #     dir_data,
    #     species="ch4",
    #     yr1=2020,
    #     yr2=2021,
    #     dx=3,
    #     dy=2,
    #     fact_dxy=2,
    #     station=station,
    # )  # ch4: coarser resolution
    # read_cams_inv(dir_data, species="co2", yr1=2020, yr2=2023, station=station)

    # read_cams_eac4(dir_data, station=station)
    # read_cams_egg4(dir_data, yr1=2003, yr2=2020, station=station)

    read_cams_eac4_aerosols(dir_data, station=station)



if __name__ == "__main__":
    main()
