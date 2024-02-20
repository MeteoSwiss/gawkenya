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

# %%
def list2df(illformed_list, sep=',', expected_number_of_items=10) -> pd.DataFrame:
    """To turn list into data frame [TODO] expand documentation

    Args:
        illformed_list (_type_): _description_
        sep (str, optional): _description_. Defaults to ','.
        expected_number_of_items (int, optional): _description_. Defaults to 10.

    Returns:
        pd.DataFrame: _description_
    """
    expanded_list = []
    for i, x in enumerate(illformed_list):
        try:
            expanded_list.append(x.split(sep)[0:expected_number_of_items])
        except:
            x = x + sep * expected_number_of_items
            expanded_list.append(x.split(sep)[0:expected_number_of_items])

    df = pd.DataFrame(expanded_list)
    df.rename(columns={0: 'variable', 1: 'unit'}, inplace=True)
    df.dropna(how='all', axis=1)
    return df


def compile_ebas_ozone_data_into_dataframe(data_path: str, o3_conversion_factor: float=1.99534, read_unc: bool=False) -> pd.DataFrame:
    """read O3 data files and put into data frame

    Args:
        data_path (str): Path to folder containing data
        o3_conversion_factor (float): Conversion factor to convert from µg/m3 to ppbv

    Returns:
        pd.DataFrame: Pandas DataFrame with O3 data in ppbv
    """
    try:
        data_O3_all = pd.DataFrame()

        for file in os.listdir(data_path):
            if "ozone" in str(file):
                data_path_O3 = data_path+file
                fh = nappy.openNAFile(data_path_O3)
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
                df_O3 = X.merge(V, left_index=True, right_index=True)
                long_names = list2df(list(df_O3.columns))
                long_names.rename(columns={0: 'long_name', 1: "unit"}, inplace=True)
                col_names = fh.getNADict()['NCOM'][-1].split()
                df_O3.columns = col_names

                if read_unc == False: #default: keep all ozone columns and rename
                    inc = itertools.count().__next__
                    dups = df_O3.columns[df_O3.columns.duplicated()]
                    df_O3.rename(columns=lambda x: f"{x}_{inc()}" if x in dups else x, inplace=True)
                    short_names = pd.DataFrame(df_O3.columns)
                    short_names.rename(columns={0: 'short_name'}, inplace=True)
                    mappings = pd.concat([short_names, long_names], axis=1)

                else:
                    'To read the uncertainties. Read all available ozone values and make a combined variablename'
                    for i in range(len(long_names['variable'])):
                        v = long_names['variable'][i]
                        if v=='ozone':
                            unit = long_names['unit'][i].replace(' ','')
                            stats = long_names[2][i].split('=')[-1].replace(' ','')
                            #assume arithmeticmean as standard ozone value
                            stats = [f'_{stats}' if stats!='arithmeticmean' else ''][0]
                            vnew = f'{v}_{unit}{stats}'
                            col_names[i] = vnew
                    df_O3.columns = col_names

                epoch = datetime.strptime("%s-%s-%s" % tuple(fh.DATE), "%Y-%m-%d")
                #df_O3['dtm'] = epoch + pd.to_timedelta(round(df_O3['starttime']), unit='D') #this gives only days, no hours
                df_O3['dtm'] = epoch + pd.to_timedelta(df_O3['starttime']*24*3600, unit='s').round('s') #includes hours (first transforming to seconds)
                df_O3.set_index('dtm',inplace=True)

                data_O3_all = pd.concat([data_O3_all, df_O3])

        # in ppb
        if read_unc == False:
            data_O3_all["O3_0"] = data_O3_all["O3_0"] / o3_conversion_factor 
        else:
            #use the ug/m3 value and convert to ppb (the nmol/mol is not given in all files)
            # do the same for uncertainties. Remove all other ozone values
            data_O3_all['O3'] = data_O3_all['ozone_ug/m3']/o3_conversion_factor 
            data_O3_all['O3_unc'] = data_O3_all['ozone_ug/m3_stddev']/o3_conversion_factor 
            # only keep O3 and O3_unc
            data_O3_all=data_O3_all[['endtime','O3','O3_unc','flag']]

        return data_O3_all
    
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
        df_aerosol.set_index('dtm',inplace=True)

        return df_aerosol
    
    except Exception as err:
        print(err)

