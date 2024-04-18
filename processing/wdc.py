# %%
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import pyplot
import os
import matplotlib.ticker as ticker
import numpy as np
import nappy
from datetime import datetime
import itertools




def compile_wdcgg_into_dataframe(data_path: str, sampling: str) -> pd.DataFrame:
    """read WDC GHG data and put into data frame

    Args:
        data_path (str):    Path to folder containing data
        species (str):      Name of species (e.g. 'CO2', 'CO',...)
        sampling (str):     'hourly' or 'event' (for flask data) 

    Returns:
        pd.DataFrame: Pandas DataFrame with O3 data in ppbv
    """
    try:

        tar = os.listdir(data_path)
        if os.path.basename(data_path + tar[0]).endswith('tar'):
            data_path = os.path.join(data_path, tar[0])
        files = os.listdir(data_path)

        for file in files:
            if os.path.basename(file).endswith(f'{sampling}.txt'):
                file_sel = os.path.join(data_path, file)

                #open file
                with open(file_sel) as f:
                    while line := f.readline():
                        split_line = line.strip().split()
                        if len(split_line) > 1:
                            if line.strip().split()[1] == 'value:units':
                                unit = line.strip().split()[3]
                            
                        if line.strip() == "# VARIABLE ORDER":
                            break
                    data_sel = pd.read_csv(f, 
                                           sep=" ", 
                                           skiprows=2, na_values=['-999', '-9', '-99.9', '-999.999'], 
                                           header= None )
                    data_sel.index += 1

                data_sel.columns = ["site_gaw_id", "year", "month", "day", "hour", "minute", "second", "year1", "month1", "day1", "hour1", "minute1", "second1", "value", "value_unc", "nvalue", "latitude", "longitude", "altitude", "elevation", "intake_height", "flask_no", "ORG_QCflag", "QCflag", "instrument", "measurement_method", "scale"]
                df = pd.DataFrame(data_sel)                

                # assemble all date columns together
                date_columns_start = ['year', 'month', 'day','hour','minute','second']
                date_columns_end = ['year1', 'month1', 'day1','hour1','minute1','second1']
                starttime = pd.to_datetime(df[date_columns_start])
                df["starttime"] = starttime
                df = df.drop(date_columns_start, axis=1)

                #rename now the endtime columns
                df.rename(columns=dict(zip(date_columns_end, date_columns_start)),inplace=True)
                #endtime = (pd.to_datetime(df[date_columns_end].astype(str).agg('-'.join, axis=1),errors='coerce'))
                endtime = pd.to_datetime(df[date_columns_start])
                df["endtime"] = endtime
                df = df.drop(date_columns_start, axis=1)

                df.set_index('starttime',inplace=True)#replace index by dates 
                df['unit'] = unit


        return df
    
    except Exception as err:
        print(err)



