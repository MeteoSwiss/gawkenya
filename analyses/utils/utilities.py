""" 
Utilities for the data analyses.

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""

from scipy.stats import spearmanr
import numpy as np
import xarray as xr
import matplotlib.colors as mc
import colorsys 

#for tick format:
from matplotlib.ticker import FormatStrFormatter,AutoMinorLocator, \
MultipleLocator, LinearLocator, LogLocator
from matplotlib import ticker
import matplotlib.dates as mdates #to change tick dates
from matplotlib.dates import DateFormatter

def get_station_coords(stat):
    '''
    Get station coordinates
    '''
    if stat == 'MKN':
        lat = -0.062
        lon = 37.297
        alt = 3678
    elif stat == 'NAIROBI':
        lat = -1.27
        lon = 36.8
        alt = 1795
    elif stat == 'KAPITI':
        lat = -1.61 
        lon = 37.1327
        alt = np.nan # which altitude?
    elif stat == 'TAITA':
        lat = -3.47 
        lon = 38.20
        alt = np.nan # which altitude?
    else:
        print('Please define the coordinates for the station ' + stat)
    return lat,lon, alt




def find_best_grid_point(rean, obs):
    """
    Script from Yuri Brugnara (Empa). 
    Select the grid point that best fits the measurements (highest Spearman's r)
    rean: xarray dataset with one variable
    obs: pandas dataframe with one column (df[[col]])
    """ 
    best_r = -1
    best = []
    for la in rean.latitude:
        for lo in rean.longitude:
            for le in rean.level:
                tmp = rean.sel(latitude=la, longitude=lo, level=le)
                r = spearmanr(obs.values, np.array(tmp.values).squeeze(), nan_policy='omit').statistic # initially it was: np.array(tmp.to_array())
                print(f'corr. for {la.values}lat, {lo.values}lon, level {le.values}: {r}')
                if r > best_r:
                    best_r = r
                    best = [la.values, lo.values, le.values]
    return best



def form_xdate(ax,Yrfmt,tickMaj, tickMin):
    ''' make date format for axis
        Yrfmt can be y for 99 or Y for 1999
        tickMaj : (int) major ticks
        tickMin : (int) minor ticks
        Empty value (tickMin='') when all months should be plot
        Example: Major tick for every 2nd year, minor tick every year:
            form_xdate(ax,'Y',2,1)
        '''
    ax.xaxis.set_major_formatter(DateFormatter('%'+ Yrfmt))
    #ax.xaxis.set_minor_formatter(DateFormatter('%'+ Mthfmt))
    ax.xaxis.set_major_locator(mdates.YearLocator(tickMaj))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(tickMin))

def get_anomalies(ds_m,var,yr1='',yr2=''):
        ## Calculate anomalies of monthly means for the variable var
        # If no specific time period is given (yr1 and yr2 = ''), use full time period as reference for anomalies
        if yr1=='':
            yr1=ds_m.time.dt.year[0].values
        if yr2=='':
            yr2=ds_m.time.dt.year[-1].values
        climatology_mean = ds_m[var].sel(time=slice('01-01-'+str(yr1),'31-12-'+str(yr2))).groupby("time.month").mean("time")
        climatology_std = ds_m[var].sel(time=slice('01-01-'+str(yr1),'31-12-'+str(yr2))).groupby("time.month").std("time")
        ds_m[var + '_anom'] = ds_m[var].groupby("time.month") - climatology_mean

        ds_m[var + '_anom_per'] = xr.apply_ufunc(lambda x, m, s: (x - m) / s *100,
            ds_m[var].groupby("time.month"),
            climatology_mean,
            climatology_mean,
        )
        ds_m[var + '_anom_stdz'] = xr.apply_ufunc(lambda x, m, s: (x - m) / s,
            ds_m[var].groupby("time.month"),
            climatology_mean,
            climatology_std,
        )
        ds_m[var + '_anom_per'].attrs['Description'] = 'Monthly anomalies in percent (divided by overall monthly mean of each month of the year)'
        ds_m[var + '_anom_stdz'].attrs['Description'] = 'Standardized monthly anomalies (divided by overall monthly standard deviation of each month of the year)'
        return ds_m

# adjust the lightness of a color
def adjust_lightness(color, amount=0.5):
    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, amount * c[1])), c[2])