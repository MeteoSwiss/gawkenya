""" 
Get CAMS data for the Mt. Kenya region

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""

# %%
import cdsapi  # to install: see https://cds.climate.copernicus.eu/api-how-to
import numpy as np
import os, sys
import xarray as xr
import pandas as pd
import zipfile

## Add parent directory to syspath
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if not parent_dir in sys.path:
    sys.path.append(parent_dir)
from utils import utilities


# %%
def get_cams_eac4(dir_data, year, month, days_mon, stat, lat, lon, dxy=0.75):
    """
    Download CAMS reanalyses (EAC4) data
    lat, lon    Station latitude and longitude
    dxy         Model resolution. It selcts grids +-dxy around the station.
    """
    print("Get data for: {}-{}".format(year, month))

    c = cdsapi.Client()

    c.retrieve(
        "cams-global-reanalysis-eac4",
        {
            "format": "netcdf",
            "variable": [
                "10m_u_component_of_wind",
                "10m_v_component_of_wind",
                "2m_temperature",
                "black_carbon_aerosol_optical_depth_550nm",
                "dust_aerosol_optical_depth_550nm",
                "organic_matter_aerosol_optical_depth_550nm",
                "particulate_matter_10um",
                "particulate_matter_1um",
                "particulate_matter_2.5um",
                "surface_pressure",
                "total_aerosol_optical_depth_1240nm",
                "total_aerosol_optical_depth_469nm",
                "total_aerosol_optical_depth_550nm",
                "total_aerosol_optical_depth_670nm",
                "total_aerosol_optical_depth_865nm",
                "ozone",
                "carbon_monoxide",
                "temperature",
                "total_column_carbon_monoxide",
                "total_column_methane",
                "total_column_ozone",
                "total_column_water_vapour",
                'dust_aerosol_0.03-0.55um_mixing_ratio', 
                'dust_aerosol_0.55-0.9um_mixing_ratio', 
                'dust_aerosol_0.9-20um_mixing_ratio',
                'hydrophilic_black_carbon_aerosol_mixing_ratio', 
                'hydrophobic_black_carbon_aerosol_mixing_ratio', 
                'sulphate_aerosol_mixing_ratio',
            ],
            "time": [
                "00:00",
                "03:00",
                "06:00",
                "09:00",
                "12:00",
                "15:00",
                "18:00",
                "21:00",
            ],
            "pressure_level": [
                "600",
                "700",
                "800",
                "850",
                "900",
                "925",
                "950",
                "1000",
            ],
            "area": "{}/{}/{}/{}".format(lat + dxy, lon - dxy, lat - dxy, lon + dxy),
            "date": "{y}-{m}-{d1}/{y}-{m}-{d2}".format(
                y=year, m=month, d1="01", d2=days_mon
            ),  ##Normally it should ignore non-existing days (e.g. 31.February), so that I can just put 31, but for unknown reason it saves then the first days of the following month!!??
        },
        #f"{dir_data}\EAC4\cams_eac4_{year}_{month}_{stat}.zip",
        f"{dir_data}\EAC4\cams_eac4_{year}_{month}_{stat}.zip",
    )  # contains 2 files, one with plevels, one single-level file

def get_cams_eac4_aerosols(dir_data, year, month, days_mon, stat, lat, lon, dxy=0.75):
    """
    Download CAMS reanalyses (EAC4) data. Same as above, but here we only download aerosol multilevel data.
    Normally, this can be done together with the other data, with get_cams_eac4(). 
    lat, lon    Station latitude and longitude
    dxy         Model resolution. It selcts grids +-dxy around the station.
    """
    print("Get data for: {}-{}".format(year, month))

    c = cdsapi.Client()

    c.retrieve(
        "cams-global-reanalysis-eac4",
        {
            "format": "netcdf",
            "variable": [
                'dust_aerosol_0.03-0.55um_mixing_ratio', 
                'dust_aerosol_0.55-0.9um_mixing_ratio', 
                'dust_aerosol_0.9-20um_mixing_ratio',
                'hydrophilic_black_carbon_aerosol_mixing_ratio', 
                'hydrophobic_black_carbon_aerosol_mixing_ratio', 
                'sulphate_aerosol_mixing_ratio',
            ],
            "time": [
                "00:00",
                "03:00",
                "06:00",
                "09:00",
                "12:00",
                "15:00",
                "18:00",
                "21:00",
            ],
            "pressure_level": [
                "600",
                "700",
                "800",
                "850",
                "900",
                "925",
                "950",
                "1000",
            ],
            "area": "{}/{}/{}/{}".format(lat + dxy, lon - dxy, lat - dxy, lon + dxy),
            "date": "{y}-{m}-{d1}/{y}-{m}-{d2}".format(
                y=year, m=month, d1="01", d2=days_mon
            ),  ##Normally it should ignore non-existing days (e.g. 31.February), so that I can just put 31, but for unknown reason it saves then the first days of the following month!!??
        },
        #f"{dir_data}\EAC4\cams_eac4_{year}_{month}_{stat}.zip",
        f"{dir_data}\EAC4_aerosols\cams_eac4_{year}_{month}_{stat}.zip",
    )  # contains 2 files, one with plevels, one single-level file


def get_cams_inv_co2(dir_data, year, month, days_mon, stat, lat, lon, dx=4, dy=2):
    """
    Get CAMS global inversion-optimised greenhouse gas fluxes and concentrations (Not tried yet, so far: run in online form)

    dx,dy   longitude and latitude grids (or other way around??)

    =>finally I was running it in the online form!
    """

    print("Get data for: {}".format(year))
    c = cdsapi.Client()

    c.retrieve(
        "cams-global-greenhouse-gas-inversion",
        {
            "version": "latest",
            "format": "zip",
            "input_observations": "satellite",
            "variable": "carbon_dioxide",
            "quantity": "concentration",
            "year": year,
            # [
            #  '2020', '2021', '2022',
            # '2023',            ],
            "month": month,
            #'area':  '{}/{}/{}/{}'.format(lat+dy,lon-dx,lat-dy,lon+dx),  #not sure if it works here?
            "time_aggregation": "instantaneous",
        },
        f"{dir_data}\invGG\cams_inv_co2_{year}_{month}.zip",
    )


def get_cams_inv_ch4_all(dir_data, year, month, stat, lat, lon, dx=4, dy=2):
    """
    Get CAMS global inversion-optimised greenhouse gas fluxes and concentrations (Not tried yet, so far: run in online form)
    = >finally I was running it in the online form!

    dx,dy   longitude and latitude grids (or other way around??)
    """

    print("Get data for: {}".format(year))
    c = cdsapi.Client()

    c.retrieve(
        "cams-global-greenhouse-gas-inversion",
        {
            "version": "latest",
            "format": "zip",
            "input_observations": "surface_satellite",
            "variable": "methane",
            "quantity": "concentration",
            "year": year,
            # [
            #  '2020', '2021', '2022',
            # '2023',            ],
            "month": month,
            #'area':  '{}/{}/{}/{}'.format(lat+dy,lon-dx,lat-dy,lon+dx),  #not working?
            "time_aggregation": "instantaneous",
        },
        f"{dir_data}\invGG\cams_inv_ch4_{year}_{stat}.zip",
    )


def get_cams_egg4(dir_data, year, month, days_mon, stat, lat, lon, dxy=0.75):
    """
    Get CAMS EGG4 data for a specific station.

    dxy     model resolution. It selcts grids +-dxy around the station.

    """
    print("Get data for: {}".format(year))

    c = cdsapi.Client()

    c.retrieve(
        "cams-global-ghg-reanalysis-egg4",
        {
            "format": "netcdf",
            "variable": [
                "carbon_dioxide",
                "methane",
            ],
            "step": [
                "0",
                "3",
                "6",
                "9",
                "12",
                "15",
                "18",
                "21",
            ],
            "area": "{}/{}/{}/{}".format(lat + dxy, lon - dxy, lat - dxy, lon + dxy),
            "pressure_level": [
                "600",
                "700",
                "800",
                "850",
                "900",
                "925",
                "950",
                "1000",
            ],
            #'model_level': ['60',  ],
            "date": "{y}-{m}-{d1}/{y}-{m}-{d2}".format(
                y=year, m=month, d1="01", d2=days_mon
            ),  ##Normally it should ignore non-existing days (e.g. 31.February), so that I can just put 31, but for unknown reason it saves then the first days of the following month!!??
        },
        f"{dir_data}\EGG4\cams_egg4_{year}_{month}_{stat}.nc",
    )


def get_cams_gfas(dir_data, year, month, days_mon, stat, lat, lon):
    """
    Get CAMS GFAS data for a specific station.
    CAUTION: hard-coded area selected!

    dxy     model resolution. It selcts grids +-dxy around the station. (not used, could be  dxy=2 * 0.1)

    """
    print("Get CAMS GFAS data for: {}".format(year))

    c = cdsapi.Client()

    c.retrieve(
        "cams-global-fire-emissions-gfas",
        {
            "date": "{y}-{m}-{d1}/{y}-{m}-{d2}".format(
                y=year, m=month, d1="01", d2=days_mon
            ),  ##Normally it should ignore non-existing days (e.g. 31.February), so that I can just put 31, but for unknown reason it saves then the first days of the following month!!??
            "format": "netcdf",
            #"area": "{}/{}/{}/{}".format(lat + 20, lon - 20, lat - 10, lon + 10), #saved in GFAS_17_10SW_47_20NE
            #"area": "{}/{}/{}/{}".format(lat + 20, lon - 30, lat - 20, lon + 15), #saved in GFAS_7_20SW_52_20NE
            "area": "{}/{}/{}/{}".format(20, 0, -35, 60), #saved in GFAS
            "variable": [
                "wildfire_flux_of_carbon_dioxide",
                "wildfire_flux_of_carbon_monoxide",
                "wildfire_flux_of_methane",
                "wildfire_flux_of_black_carbon",
                "wildfire_flux_of_particulate_matter_d_2_5_µm",
                "wildfire_flux_of_total_particulate_matter",
                "wildfire_radiative_power"
            ],
        },
        f"{dir_data}\GFAS\cams_gfas_{year}_{month}_{stat}.nc",
    )


def days_in_month(month, year):
    """
    check number of days in the month.
    from https://confluence.ecmwf.int/pages/viewpage.action?pageId=143050283
    """
    if (
        month == 1
        or month == 3
        or month == 5
        or month == 7
        or month == 8
        or month == 10
        or month == 12
    ):

        return 31

    elif month == 2:

        if is_leap_year(year):

            return 29

        else:

            return 28

    else:

        return 30


def is_leap_year(year):
    return (year % 4 == 0) and (year % 100 != 0) or (year % 400 == 0)


# %%
def main(
    dir_data=r"..\..\Data\CAMS", #local path to save the data
    yr1=2020,
    yr2=2023,
    which="cams_eac4",
    station=["MKN"],
):
    """
    Please adapt dir_data to a local folder to save the CAMS data.
    """
    years = np.arange(yr1, yr2 + 1)
    months = np.arange(1, 13)

    for y in years:
        year = "{:04d}".format(int(y))
        for m in months:
            month = "{:02d}".format(int(m))  # get formated string (with leading zero)
            days_mon = days_in_month(m, y)  # get number of days in this month
            for s in station:
                lat, lon, alt = utilities.get_station_coords(s)

                if which == "cams_egg4":
                    get_cams_egg4(dir_data, year, month, str(days_mon), s, lat, lon)

                if which == "cams_inv_co2":
                    get_cams_inv_co2(dir_data, year, month, str(days_mon), s, lat, lon)

                if which == "cams_inv_ch4":
                    get_cams_inv_ch4_all(dir_data, year, month, s, lat, lon)

                if which == "cams_eac4":
                    get_cams_eac4(dir_data, year, month, str(days_mon), s, lat, lon)
                
                if which == "cams_eac4_aerosols":
                    get_cams_eac4_aerosols(dir_data, year, month, str(days_mon), s, lat, lon)

                if which == "cams_gfas": 
                    get_cams_gfas(dir_data, year, month, str(days_mon), s, lat, lon)

                else:
                    print("please indicate the cams product. ")


if __name__ == "__main__":
    main()
