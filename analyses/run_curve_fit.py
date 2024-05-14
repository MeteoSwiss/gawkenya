import numpy as np
import pandas as pd
from utils.ccg_filter import ccg_filter as ccgfilt
from utils.ccg_filter import ccg_dates

## function to select correct data and create the fit/filter object
def run_ccgfilter(
    ds,
    dataset_str,
    t1,
    t2,
    **fit_properties
    # shortterm=80,
    # longterm=667,
    # numpolyterms=2,
    # sampleinterval=1 / 24,  #if not given, determine from the data
    # numharmonics=4,
):

    ## prepare data
    ds_sel = ds.sel(time=slice(t1, t2))
    ds_nonan = ds_sel.where(np.isnan(ds_sel) == False, drop=True)

    xp = ds_nonan.time.values
    yp = ds_nonan.values

    ## Initialize df_interp with a default value
    df_interp = None
    if len(xp)>0 and len(yp)>0: #if we have data
        # get time as decimal date
        xp_dec = [ccg_dates.decimalDateFromDatetime(d) for d in pd.to_datetime(xp)]

        # create the ccgfilt object
        # Note:  For less than 3 years of data it is best
        # to use a linear term for the polynomial part of the function (k=2)
        print(f"Run filter for {dataset_str}")
        filt = ccgfilt.ccgFilter(
            xp_dec,
            yp,  #
            shortterm=fit_properties['shortterm'],
            longterm=fit_properties['longterm'],
            numpolyterms=fit_properties['numpolyterms'],
            sampleinterval=fit_properties['sampleinterval'],
            numharmonics=fit_properties['numharmonics'],
            # debug=True
        )

        ## save required data
        x0 = filt.xinterp
        datetimes = [ccg_dates.datetimeFromDecimalDate(np.round(d,12)) for d in x0] # round to avoid floating point errors
        df_interp = pd.DataFrame(
            {
                "time": datetimes,
                "smooth": filt.smooth,
                "trend": filt.trend,
                "smoothed_vals": filt.getSmoothValue(x0),
                "trend_vals": filt.getTrendValue(x0),
                "harmonic_vals": filt.getHarmonicValue(x0),
                "seasonal_detrend": filt.getHarmonicValue(x0) + filt.smooth - filt.trend,
            }
        )
        df_interp.set_index("time", inplace=True)
        ds_interp = df_interp.to_xarray()
        ds_interp = ds_interp.assign_coords(dataset=dataset_str)
    else:
        filt = None
    return filt, df_interp, ds_interp