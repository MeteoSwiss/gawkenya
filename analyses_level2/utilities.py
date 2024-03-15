""" 
Utilities for the data analyses.

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""

from scipy.stats import spearmanr
import numpy as np

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
                print(f'check corr. for {la.values}, {lo.values}, {le.values}')
                tmp = rean.sel(latitude=la, longitude=lo, level=le)
                r = spearmanr(obs.values, np.array(tmp.values).squeeze(), nan_policy='omit').statistic # initially it was: np.array(tmp.to_array())
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
