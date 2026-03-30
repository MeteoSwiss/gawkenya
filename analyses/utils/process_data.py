import numpy as np
import matplotlib.pyplot as plt
import xarray as xr
import pandas as pd



def rem_out(ds, vars=["value"], use_unc=True, std_fac=10, z_threshold=4, plot_timeseries = True):
    """
    Remove outliers: remove data with high uncertainty (if uncertainty is given). 
    Also, remove when they exceed a certain value, based on statistics of the whole time series.
    As a criteria we use the zscore, which is a standardized deviation.
    Idea from: https://towardsdatascience.com/ways-to-detect-and-remove-the-outliers-404d16608dba

    stat (str)          Station name
    vars (str)           Variable name(s)
    std_fac (int)       Factor of the uncertainty used as threshold to exclude data. The factor is multiplied with the mean uncertainty of the whole period.
    z_threshold (int) :   outliers defined as soon as >= z_threshold * zscore
    use_unc (bool):     Use the given uncertainty to exclude data (uncertainty * std_fac). Requires to be saved as {var_name}_sd!
    plot_timeseries (bool): plot the time_series or not
    """

    ds_init = ds.copy(deep=True)

    ## workaround to avoid that time dimension is added to non-time variables (e.g. the station):
    ds_withtime = ds.drop([var for var in ds.variables if not "time" in ds[var].dims])
    ds_timeless = ds.drop([var for var in ds.variables if "time" in ds[var].dims])

    # for each desired variable,remove values with high uncertainty
    for var in vars:
        if use_unc:
            stdmean = ds_withtime[var + "_sd"].mean(keep_attrs=True).values
            ## set outliers to nan
            # problem: sometimes, the Stdev is nan, but it does not mean that I don't want to use the data
            ds_temp = ds_withtime.copy(deep=True)
            nan_times = ds_withtime.where(
                np.isnan(ds_withtime[var + "_sd"]), drop=True
            ).time
            ds_temp[var + "_sd"].loc[dict(time=nan_times)] = (
                0  # set all nans in stdev to zero, to not exclude them
            )
            ds_withtime = ds_withtime.where(
                ds_temp[var + "_sd"] <= stdmean * std_fac
            )  # exclude values with hihg uncertainty (but do not exlude data when stdev is nan!)

        # if method == 'zscore':
        ds_withtime["zscore"] = abs(
            (
                (ds_withtime[var] - ds_withtime[var].mean(dim="time", keep_attrs=True))
                / ds_withtime[var].std(dim="time", keep_attrs=True)
            )
        )
        # same as: from scipy import stats; np.abs(stats.zscore(ds_withtime[var]))
        ds_withtime = ds_withtime.where(ds_withtime.zscore < z_threshold)
        mask_no_outliers = ds_withtime.where(ds_withtime.zscore < z_threshold)['zscore'].isnull().values == False
        ds_withtime = ds_withtime.drop("zscore")

        # ## to check outliers:
        if plot_timeseries: 
            f, axs = plt.subplots(2, 1, sharex=True)
            plt.suptitle("Removed outliers")
            ds_init[var].plot(ls="", marker="o", ax=axs[0])
            if use_unc: 
                ds_init[var + "_sd"].plot(ls="", marker="o", ax=axs[1])
            # new data:
            ds_withtime[var].plot(ls="", marker=".", ax=axs[0])
            if use_unc: 
                ds_withtime[var + "_sd"].plot(ls="", marker=".", ax=axs[1])
            # ## If values with high stdev are present, plot them:
            # if len(ds.where(ds.o3_stdev>stdmean*std_fac,drop=True).time) > 0:
            #     ds.where(ds.o3_stdev>stdmean*std_fac,drop=True).o3.plot(ls='',marker='x',ax=axs[0])
            #     ds.where(ds.o3_stdev>stdmean*std_fac,drop=True).o3_stdev.plot(ls='',marker='x',ax=axs[1])

            plt.show()

    # merge new ds with the time-less variables:
    ds_workaround = xr.merge([ds_timeless, ds_withtime], combine_attrs="identical")

    # ## keep attributes
    # for varname, da in ds.data_vars.items():
    #     if varname in ds_workaround.data_vars:
    #         ds_workaround[varname].attrs = da.attrs
    #     if varname in ds_workaround.dims:
    #         #add attrs for dimensions if available
    #         ds_workaround[varname].attrs = da.attrs

    return ds_workaround, mask_no_outliers



## transform flexpart data with numpoint dimension to 3-hourly time series
def flexpart_to_3hourly(ds):
    """
    Transform a dataset with dimensions (time, numpoint) to a dataset with a single time dimension
    by expanding the time dimension to 3-hourly intervals based on the numpoint values.

    Parameters:
    ds (xarray.Dataset): Input dataset with dimensions (time, numpoint).

    Returns:
    xarray.Dataset: Transformed dataset with a single time dimension.
    """
    # Step 1: build the 3-hourly time index
    daily_time = ds.time.values  # daily timestamps at 00:00
    numpoints = ds.sizes["numpoint"]  # should be 8

    # Create 3-hour offsets: [0, 3, 6, ..., 21]
    offsets = np.arange(numpoints) * 3

    # Expand daily_time → full 3-hourly time
    new_time = (
        pd.DatetimeIndex(daily_time)
        .repeat(numpoints)  # repeat each day 8 times
        + pd.to_timedelta(np.tile(offsets, len(daily_time)), unit="h")
    )

    # Step 2: reshape dataset so (time, numpoint) → (new_time,)
    ds_new = (
        ds.rename({"time": "day"})  # keep original as 'day'
        .stack(help_dim=("day", "numpoint"))  # combine
        .assign_coords(time=("help_dim", new_time))  # assign new time coord
        .swap_dims({"help_dim": "time"})               # replace helper with time
        .drop_vars("help_dim")                         # drop helper
        #.reset_coords(drop=True)  # drop old stacked coords
    )


    # Step 3: ensure order is correct
    ds_new = ds_new.set_coords("time").sortby("time")
    return ds_new