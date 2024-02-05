""" 
Utilities for the data analyses.

Author: Leonie Bernet
Version: 1.0
Created on: 2024-01
Modifications: date -> modified
"""

from scipy.stats import spearmanr

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
                tmp = rean.sel(latitude=la, longitude=lo, level=le)
                r = spearmanr(obs.values, np.array(tmp.to_array()).squeeze(), nan_policy='omit').statistic
                if r > best_r:
                    best_r = r
                    best = [la, lo, le]
    return best