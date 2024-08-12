""" 
Read the aerosol data from Mt. Kenya station

Author: Leonie Bernet
Version: 1.0
Created on: 2024-07
Modifications: date -> modified
"""

# import
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import pyplot
import os
import matplotlib.ticker as ticker
import numpy as np
import xarray as xr
import sys
from utils.utilities import (
    find_best_grid_point,
    get_station_coords,
    form_xdate,
    get_anomalies,
)
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import datetime as dt
from os import PathLike
from pathlib import Path
import zipfile
import re

from plotting import tol_colors  # color schemes from https://personal.sron.nl/~pault/
from utils import process_data

# add the parent directory to syspath to allow importing modules from the parent directory
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if not parent_dir in sys.path:
    sys.path.append(parent_dir)

##
# aerosol_data_dir = Path("..\data\level2\L2_AEROSOL_data_bachelorthesis Mike Baumann")


def aerosol_data_to_dataset(
    aerosol_data_dir="../../data/level2/L2_AEROSOL_data_bachelorthesis Mike Baumann",
):
    """
    Read in aerosol data from aethalometer and nephelometer.
    Output them as datasets
    """
    aerosol_data_dir = Path(aerosol_data_dir)
    ##--------------- extract from zip file ---------------##
    if not aerosol_data_dir.is_dir():
        # Check if the directory exists already
        # If not, unzip the zip file (if the zip file exists)
        aerosol_data_file = aerosol_data_dir.parent / (aerosol_data_dir.name + ".zip")
        if aerosol_data_file.is_file():  # if the file exists
            if not aerosol_data_dir.is_dir():
                print(f"Extracting aerosol data from {aerosol_data_file}")
                with zipfile.ZipFile(aerosol_data_file, "r") as zip_ref:
                    aerosol_data_dir.mkdir(exist_ok=True)
                    zip_ref.extractall(aerosol_data_dir)
        else:
            raise FileNotFoundError(f"Directory {aerosol_data_dir} does not exist")

    # Read in the aerosol csv files
    custom_date_parser = lambda x: pd.to_datetime(x, format="%Y-%m-%d %H:%M:%S")

    ##--------------- read in csv file ---------------##
    if aerosol_data_dir.is_dir():
        df_ae = pd.read_csv(
            aerosol_data_dir / "2019_03_01_5y_MKN_AE31_1hr_cleaned0523.csv",
            header=[0, 1],  # 2 header lines
            parse_dates=[1],  # {'time':[1]},
            date_parser=custom_date_parser,
            # date_format = "%Y-%m-%d %H:%M:%S", # should be used instead date_parser, but then still requires to apply to_datetime() somehow
            # index_col= 0, #set index later because of the 2 header lines
            # skiprows
        )
        df_neph = pd.read_csv(
            aerosol_data_dir / "2019_03_01_5y_MKN_neph_1hr_cleaned0523.csv",
            header=[0, 1],
            parse_dates=[1],
            date_parser=custom_date_parser,
        )
    else:
        raise FileNotFoundError(f"Directory {aerosol_data_dir} is not a directory.")

    ##--------------- prepare the aerosol data dataframe to an easier readable format ---------------##
    ## adapt the dataframe structure
    description_ae = df_ae.columns.get_level_values(
        1
    )  # second header line contains descriptions
    description_ae = description_ae.delete(
        loc=1
    )  # remove the time in the time description in the description/previous header
    df_ae = df_ae.droplevel(1, axis=1)  # remove second header line
    df_ae = df_ae.set_index("DateTimeUTC")  # set the time as index

    df_ae.index.rename("time", inplace=True)  # rename the index to 'time'
    ds_ae = df_ae.to_xarray()

    description_neph = df_neph.columns.get_level_values(1)
    description_neph = description_neph.delete(
        loc=1
    )  # remove the time in the time description in the description/previous header
    df_neph = df_neph.droplevel(1, axis=1)  # remove second header line
    df_neph = df_neph.set_index("DateTimeUTC")  # set the time as index
    df_neph.index.rename("time", inplace=True)  # rename the index to 'time'
    ds_neph = df_neph.to_xarray()

    # align both instrument-datasets to have same time dimensions
    ds_ae, ds_neph = xr.align(ds_ae, ds_neph)

    ## save description and units as attributes in the dataframes
    for ds_instr, descr in zip([ds_ae, ds_neph], [description_ae, description_neph]):
        for i, (var_name, ds) in enumerate(ds_instr.data_vars.items()):
            # save station description:
            ds_instr[var_name].attrs["description"] = descr[i]
            # save units:
            pattern = r"\((.*?)\)"
            match = re.search(pattern, descr[i])
            if match:
                unit = match.group(1)
            else:
                unit = ""
            ds_instr[var_name].attrs["units"] = unit

    return ds_ae, ds_neph


def aerosols_to_full_dataset(ds_ae, ds_neph):
    """
    Calculate aerosol properites (SAE, SSA, AAE) and save everything in a suitable format.

    # Some variable explanations:
    # Absorption, measured by the Aethalometer (ds_ae)
    # Ba10_A11 or BaG0_A11
    #   - B = not sure, but all the coefficients have B. X is used for black carbon equivalent
    #   - a = absorption
    #   - 1 = number of the 7 channels 370, 470, 521, 590, 660, 880, 950nm
    #   or G = Green channel (blue=470nm, green = 521nm, red = 660nm)
    #   - 0 = PM10 (not sure what this means in this context. 1 would be PM1)
    #   - _A11 = same for all
    # X6c0_A11
    #   - X = black carbon
    #   - 6 = 6th channel
    #   - c = concentration
    #
    # Scattering, measured by the Nephalometer
    # BsG0_S11
    # Same principle as above
    #   - s = scattering
    #   - G = Green channel (blue=450nm, green = 525nm, red = 635nm)
    #   - _S11 = same for all
    Make wavelenghts as an additional data dimension to have a better overview.
    """
    ##--------------- calculate aerosol properties ---------------##
    # Absorption Angstrom exponent: gives indication about composition/chemistry
    # Wavelength dependence of aerosol absorption
    # Black carbon: AAE ~=1
    # Dust: AAE >=2
    # Requires 2 wavelenghts, Mike used 470 and 880
    c_abs1 = ds_ae["Ba20_A11"]  # abs. coeff. at 470nm (PM10)
    c_abs2 = ds_ae["Ba60_A11"]  # abs. coeff. at 880nm
    AAE = -np.log(c_abs1 / c_abs2) / np.log(
        470 / 880
    )  # np.log is the natuarl logarithm ln()

    # Scattering Angstrom exponent:
    # Describes wavelenght dependence of scattered light
    # Small values (close to zero) indicate large particles, often indicating that we are close to sources (more coagulation)
    c_scat1 = ds_neph["BsB0_S11"]  # scattering coeff. at blue (450nm)
    c_scat2 = ds_neph["BsR0_S11"]  # scattering coeff. at red (635nm)
    SAE = -np.log(c_scat1 / c_scat2) / np.log(450 / 635)

    # single scattering albedo
    # Contribution of scattering and absorption to total extinction
    # Purely scattering: SSA = 1
    # Strong absorption: SSA <= 0.3
    #
    # Mike is doing the following, not sure why:
    c_abs3 = ds_ae["Ba40_A11"]  # abs. at 590nm
    abs_525 = c_abs3 * (525 / 590) ** (
        -AAE
    )  # why 525?? The AAE used 479/880, and c_abs3 is at 590nm ??
    c_scat = ds_neph["BsG0_S11"]  # scattering at green light (525nm)
    SSA = c_scat / (abs_525 + c_scat)

    ##--------------- Create a new dataset ---------------##
    # # merge the variables of interest along a new wavelength-dimension
    lambda_neph = [450, 525, 635]  # blue, green, red
    lambda_ae = [370, 470, 521, 590, 660, 880, 950]

    # merge the absorption coefficients along the wavelenght dimension
    vars_to_concat = [f"Ba{i}0_A11" for i in range(1, len(lambda_ae) + 1)]

    abs = xr.concat(
        [da for varname, da in ds_ae[vars_to_concat].data_vars.items()],
        dim="lambda_abs",
    ).assign_coords(lambda_abs=lambda_ae)
    abs.attrs["description"] = (
        " ".join(abs.attrs["description"].split()[0:3])
        + " "
        + abs.attrs["description"].split()[-1]
    )  # adapt attribute

    # merge the scattering coefficients along the wavelenght dimension
    vars_to_concat = [
        "BsB0_S11",
        "BsG0_S11",
        "BsR0_S11",
    ]  # correct wavelength order: blue, green, red
    scat = xr.concat(
        [da for varname, da in ds_neph[vars_to_concat].data_vars.items()],
        dim="lambda_scat",
    ).assign_coords(lambda_scat=lambda_neph)
    scat.attrs["description"] = (
        " ".join(scat.attrs["description"].split()[0:3])
        + " "
        + scat.attrs["description"].split()[-1]
    )  # adapt attribute

    # merge the equivalent black carbon along the wavelenght dimension
    vars_to_concat = [f"X{i}c0_A11" for i in range(1, len(lambda_ae) + 1)]
    bc = xr.concat(
        [da for varname, da in ds_ae[vars_to_concat].data_vars.items()],
        dim="lambda_abs",
    ).assign_coords(lambda_abs=lambda_ae)
    bc.attrs["description"] = (
        " ".join(bc.attrs["description"].split()[0:4])
        + " "
        + bc.attrs["description"].split()[-1]
    )  # adapt attribute

    ##--------------- Add the calculated variables (SAE, AAE, SSA) ---------------##
    aerosol_exponents = xr.Dataset(
        data_vars=dict(
            AAE=(
                ["time"],
                AAE.values,
                dict(description="Absorption Angstrom exponent", units=""),
            ),  # AAE
            SAE=(
                ["time"],
                SAE.values,
                dict(description="Scattering Angstrom exponent", units=""),
            ),  # AAE
            SSA=(
                ["time"],
                AAE.values,
                dict(description="Single scattering albedo", units=""),
            ),  # AAE
        ),
        coords=dict(time=ds_ae["time"].values),
        attrs=dict(),
    )
    # merge all three datasets:
    ds_aerosols = xr.merge([abs, scat, bc, aerosol_exponents])
    ds_aerosols.attrs = {"description": "Aerosol measurements at MKN"}

    # rename the variables
    ds_aerosols = ds_aerosols.rename(
        dict(Ba10_A11="abs_coeff", BsB0_S11="scat_coeff", X1c0_A11="black_carbon")
    )
    return ds_aerosols


## Figure example
## Absorption and scattering timeseries

# fig, axs = plt.subplots(3,1,sharex=True)
# # Total absorption coefficient at 521nm
# ds_sel = ds_ae["Ba30_A11"]
# ax = axs[0]
# ds_sel.plot(
#     label=ds_sel.attrs["description"],
#     ax=ax
# )
# ax.set_ylabel(f"{ds_sel.name} ({ds_sel.attrs["units"]})")
# ax.set_title('Total absorption coefficient at 521nm ',loc='left')
# ax.set_xlabel('')

# # Total Scattering coefficient at 525nm (green)
# ds_sel = ds_neph["BsG0_S11"]
# ax = axs[1]
# ds_sel.plot(
#     label=ds_sel.attrs["description"],
#     ax=ax
# )
# ax.set_ylabel(f"{ds_sel.name} ({ds_sel.attrs["units"]})")
# ax.set_title('Total scattering coefficient at 525nm',loc='left')

# # # Equivalent black carbon
# ds_sel = ds_ae["X6c0_A11"]
# ax = axs[2]
# ds_sel.plot(
#     label=ds_sel.attrs["description"],
#     ax=ax
# )
# ax.set_ylabel(f"{ds_sel.name} ({ds_sel.attrs["units"]})") # I think the unit should be microgramm/m3
# ax.set_title('Total equivalent black carbon',loc='left')

# plt.show()
