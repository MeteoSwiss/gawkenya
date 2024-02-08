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
                        if line.strip() == "# VARIABLE ORDER":
                            break
                    data_sel = pd.read_csv(f, sep=" ", skiprows=2, na_values=['-999', '-9', '-99.9', '-999.999'], header=None)
                    data_sel.index += 1

                data_sel.columns = ["site_gaw_id", "year", "month", "day", "hour", "minute", "second", "year1", "month1", "day1", "hour1", "minute1", "second1", "value", "value_unc", "nvalue", "latitude", "longitude", "altitude", "elevation", "intake_height", "flask_no", "ORG_QCflag", "QCflag", "instrument", "measurement_method", "scale"]
                df = pd.DataFrame(data_sel)                

                datetime = (pd.to_datetime(df[['year', 'month', 'day','hour','minute','second']]))
                df["time"] = datetime
                df.set_index('time',inplace=True)#replace index by dates 


        return df
    
    except Exception as err:
        print(err)


                          

def ebas_aerosol_file_to_dataframe(data_path: str) -> pd.DataFrame:
    """read EBAS data file and put into data frame

    Args:
        data_path (str): Path to file

    Returns:
        pd.DataFrame: Pandas DataFrame with O3 data in ppbv
    """
    try:
        fh = nappy.openNAFile(data_path)
        fh.readData()

        X = fh.X
        V = fh.V
        na_values = fh.VMISS
        for row in range(len(na_values)):
            V[row] = [None if x == na_values[row] else x for x in V[row]]

        X = pd.DataFrame(X)
        X.columns = fh.XNAME
        V = pd.DataFrame(V).T
        V.columns = fh.VNAME

        df_aerosol = X.merge(V, left_index=True, right_index=True)

        long_names = list2df(list(df_aerosol.columns))
        long_names.rename(columns={0: 'long_name', 1: "unit"}, inplace=True)

        # assign short but unique column names
        df_aerosol.columns = fh.getNADict()['NCOM'][-1].split()
        inc = itertools.count().__next__
        dups = df_aerosol.columns[df_aerosol.columns.duplicated()]
        df_aerosol.rename(columns=lambda x: f"{x}_{inc()}" if x in dups else x, inplace=True)
        short_names = pd.DataFrame(df_aerosol.columns)
        short_names.rename(columns={0: 'short_name'}, inplace=True)
        mappings = pd.concat([short_names, long_names], axis=1)

        # convert times to datetime
        epoch = datetime.strptime("%s-%s-%s" % tuple(fh.DATE), "%Y-%m-%d")
        df_aerosol['dtm'] = epoch + pd.to_timedelta(round(df_aerosol['starttime'] / fh.DX[0]), unit='H')
        df_aerosol.set_index('dtm')

        return df_aerosol
    
    except Exception as err:
        print(err)

