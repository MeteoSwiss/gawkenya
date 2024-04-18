import numpy as np
import matplotlib.pyplot as plt
import xarray as xr



def rem_out(ds, vars=["value"], std_fac=10, z_threshold=4):
    """
    Remove outliers: remove data with high standard deviation.
    Also, remove when they exceed a certain value, based on statistics of the whole time series.
    As a criteria we use the zscore, which is a standardized deviation.
    Idea from: https://towardsdatascience.com/ways-to-detect-and-remove-the-outliers-404d16608dba

    stat (str)          Station name
    vars (str)           Variable name(s)
    std_fac (int)       Factor of the uncertainty used as threshold to exclude data. The factor is multiplied with the mean uncertainty. of the whole period.
    z_threshold (int) :   outliers defined as soon as >= z_threshold * zscore
    """

    ds_init = ds.copy(deep=True)

    ## workaround to avoid that time dimension is added to non-time variables (e.g. the station):
    ds_withtime = ds.drop([var for var in ds.variables if not "time" in ds[var].dims])
    ds_timeless = ds.drop([var for var in ds.variables if "time" in ds[var].dims])

    # for each desired variable,remove values with high uncertainty
    for var in vars:
        stdmean = ds_withtime[var + "_unc"].mean(keep_attrs=True).values
        ## set outliers to nan
        # problem: sometimes, the Stdev is nan, but it does not mean that I don't want to use the data
        ds_temp = ds_withtime.copy(deep=True)
        nan_times = ds_withtime.where(
            np.isnan(ds_withtime[var + "_unc"]), drop=True
        ).time
        ds_temp[var + "_unc"].loc[dict(time=nan_times)] = (
            0  # set all nans in stdev to zero, to not exclude them
        )
        ds_withtime = ds_withtime.where(
            ds_temp[var + "_unc"] <= stdmean * std_fac
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
        ds_withtime = ds_withtime.drop("zscore")

        ## to check outliers:
        # f, axs = plt.subplots(2, 1, sharex=True)
        # plt.suptitle("Removed outliers")
        # ds_init[var].plot(ls="", marker="o", ax=axs[0])
        # ds_init[var + "_unc"].plot(ls="", marker="o", ax=axs[1])
        # # new data:
        # ds_withtime[var].plot(ls="", marker=".", ax=axs[0])
        # ds_withtime[var + "_unc"].plot(ls="", marker=".", ax=axs[1])
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

    return ds_workaround
