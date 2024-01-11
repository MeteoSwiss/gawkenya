# -*- coding: utf-8 -*-

"""
@author: joerg.klausen@meteoswiss.ch
"""

import os
import time
import logging
import pandas as pd

class DataProcessor:
    """
    Functions to operate on data frames
    
    Available methods include
    - data_coverage(df, base="1D", aggregate="1W", key="dtm", verbose=True)
    - 
    """

    @classmethod    
    def __init__(self, config, ver='v0.1'):
        """
        constructor

        Parameters
        ----------
        config : dict
            configuration
        """
        try:
            self.logger = logging.getLogger(__name__)
            self.logger.info("DataProcessor initialized successfully.")

            # assign variables
            self.config = config

        except Exception as err:
            self.logger.error('Error initializing DataProcessor', err)


    @classmethod    
    def data_coverage(self, df, base="1D", bins="1W", key="dtm", verbose=True):
        """
        Compute temporal coverage of dataframe
        
        Data are first aggregated according to base, then counted for each bin.
        
        Parameters
        ----------
        df : dataframe
            Pandas dataframe to characterize
            
        base : str
            Base time period to use. Acceptable values can be found at https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#offset-aliases

        bins : str
            Bin size for the aggregation. Acceptable values are same as for base.

        Returns
        -------
        Pandas dataframe with counts (of base) per bin
        """
        try:
            df.set_index(key, inplace=True)
            
            base_df = df.resample(rule=base, how='mean')            
            coverage = base_df.resample(rule=bins, how='count')            
    
            return(coverage)
            
        except Exception as err:
            msg = "'Error in .data_coverage'"
            self.logger.error(msg, err)


    @classmethod    
    def data_coverage_kpi(self, df, variable, ref_date=None, base="1D", deltas=("7D", "30D", "180D", "365D", "1095D"), key="dtm", verbose=True):
        """
        Report temporal coverage as a KPI (% availability for different periods)
        
        Data are first aggregated according to base, then counted for each bin. 
        The most recent value for each bin is expressed as a percentage, thus 
        characterizing the availability for a certain time period from present.
        
        Parameters
        ----------
        df : dataframe
            Pandas dataframe to characterize
            
        variable : str
            Name of variable to use
            
        ref_date : str
            Reference date from which to look back. Defaults to None, which will use the current date
            
        base : str
            Base time period to use. Acceptable values can be found at https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#offset-aliases

        bins : str
            Bin size for the aggregation. Acceptable values are same as for base.

        Returns
        -------
        Pandas dataframe with percentages per bin
        """
        try:
            df.set_index(key, inplace=True)
            cols = df.columns[df.columns.str.contains(variable)]            
            
            base_df = df.resample(rule=base, how='mean')            
            df.reset_index(inplace=True)            
            
            if not ref_date:
                ref_date = pd.Timestamp('today')
#            begin_dates = [ref_date - pd.to_timedelta(12, unit='h')
            
            kpi = []
            for rule in deltas:            
                coverage_max = int(rule[0:len(rule)-1])
                start = ref_date - pd.to_timedelta(int(rule[0:len(rule)-1]), unit=rule[-1])
#                coverage = base_df.resample(rule=rule, origin=start, how='count')
                coverage = base_df.resample(rule=rule, how='count')
                coverage = coverage.iloc[len(coverage)-1, :]
                kpi.append(coverage[cols] / coverage_max)
            
            kpi = dict(zip(deltas, kpi))
    
            return(kpi)
            
        except Exception as err:
            msg = "'Error in .data_coverage_kpi'"
            self.logger.error(msg, err)
            

if __name__ == '__main__':
    pass            