# -*- coding: utf-8 -*-
#  Author: joerg.klausen@meteoswiss.ch

# %%
import os
import datetime
import json
import pandas as pd
import matplotlib.pyplot as plt
import re
import requests


def download_kplc_smartmeter_load_profile(usr: str, pwd: str, from_date: str, to_date: str, \
                                          base_url: str="http://41.203.223.137:9090/eup/", \
                                          target: str=None, file: str="load_profile.csv", verbose: bool=True) -> pd.DataFrame:
    """
    Download KPLC smartmeter data from their website, fix time stamps, optionally save to file.
    
    Scrape KPLC website: login and execute query for load profile data. These
    include voltages and currents for 3 all phases.
    
    Parameters
    ----------
    usr : str
        Account number
    pwd : str
        pwd
    from_date : str
        Beginning of data period, to_date be specified as yyyy-mm-dd
    to_date_date : str
        End of data period, to_date be specified as yyyy-mm-dd
    base_url : str
        base url of the KPLC smartmeter website
    target : str
        path to folder on disk. Defaults to None (= do not save)
    file : str
        Name of image file with file extension
    verbose : bool
        Should progrees be reported? Defaults to True.    
    
    Returns
    -------
    Pandas DataFrame
    """
    try:
        with requests.session() as session:
            # call login page with credentials in payload
            url = f"{base_url}login!init.do"
            data = {
                "czyId": usr, 
                "pwd": pwd, 
                "lang": "en_US"
            }
            result = session.post(url, data = data)   

            if result.ok:
                if verbose:
                    print("Login successful!")
                # retrieve session cookies
                url = f"{base_url}login!loginSuccess.do"   
                result = session.get(url, verify=False)                
                if result.status_code == 200: 
                    # execute query
                    url = f"{base_url}eup/fhqx/fhqx!query.do?"    
                    data = {
                        "start": "0",
                        "limit": "100000",
                        "hh": usr,
                        "czy": usr,
                        "opp": "0",
                        "cdid": "9",
                        "ksrq": from_date,
                        "jsrq": to_date
                    }
                    result = session.post(url, data = data, headers = dict(referer = url))
                
            if result.status_code == 200: 
                # convert byte object to json
                result = json.loads(result.content.decode())
                if verbose:
                    print("{} rows successfully downloaded.".format(result["rows"]))

                result = pd.read_json(json.dumps(result['result']))

                # rename columns to match XLS download feature
                # download mappings of column header names
                url = f"{base_url}js/locale/eupModule/fhqx/fhqx_en_US.js"                    
                column_headers = session.get(url)
                column_headers = column_headers.content.decode()
                column_headers = re.sub("fhqx_title_|'|\r\n", "", column_headers)
                column_headers = re.split("=|;", column_headers)
                column_headers.pop()                
                column_headers = dict(zip(column_headers[::2], column_headers[1::2]))
                column_headers = {k.upper(): v for k, v in column_headers.items()}

                result.rename(columns=column_headers, inplace=True)

                result = __fix_time_stamps(result)

                if target:
                    file = f"{file.split('.')[0]}-{datetime.datetime.strftime('%Y%m%d')}.{file.split('.')[1]}"
                    result.to_csv(file)

            else:
                print("Download not succesful!!")
                result = pd.DataFrame()
                                
            return(result)
                    
    except Exception as err:
        print(err)


def __fix_time_stamps(df: pd.DataFrame) -> pd.DataFrame:
    try:
        # sort data by 'Total cumulative energy(T1+T2)(kWh)'
        df['row'] = range(len(df))
        df.sort_values(by='row', ascending=False, inplace=True)

        # assign Time to new column dtm and convert to proper datetime and
        df['dtm'] = df['Time']
        df['dtm'] = pd.to_datetime(df['dtm'], format='%Y-%m-%d %H:%M:%S')

        # fix erroneous timestamps in data (afternoon times all of by 12 hrs)
        # cf. https://pandas.pydata.org/pandas-docs/stable/user_guide/indexing.html#returning-a-view-versus-a-copy
        # subtract 12 hrs if timestamp jumps 25 hrs from the previous timestamp
        df.loc[df['dtm'].diff(1) == pd.to_timedelta(25, unit='h'), 'dtm'] -= pd.to_timedelta(12, unit='h')
        # add 12 h to duplicated time stamps
        df.loc[df['dtm'].duplicated(), 'dtm'] += pd.to_timedelta(12, unit='h')
        # fix the first timestamps
        df.loc[df['dtm'] < pd.datetime(2020,6,18), 'dtm'] += pd.to_timedelta(12, unit='h')

        # Breaks in the time series may lead to 'missing duplicates' for the afternoon timestamps.
        # This can lead to a negative 1st difference. Fix this iteratively
        while(any(df['dtm'].diff(1) < pd.to_timedelta(0, unit='h'))):
            df.loc[df['dtm'].diff(1) < pd.to_timedelta(0, unit='h'), 'dtm'] += -df['dtm'].diff(1) + pd.to_timedelta(1, unit='h')

        df.set_index(df['dtm'], inplace=True)
        df.drop(labels=['row'], axis=1, inplace=True)

        return(df)

    except Exception as err:
        print(err)


# def read_kplc_smartmeter_load_profile(file: str, fix: bool=True, save: bool=True) -> pd.DataFrame:
#     """
#     Read KPLC smart meter 'load profile' data and fix time stamps

#     Parameters
#     ----------
#     file : str
#         Path to CSV file on disk
        
#     fix : bln
#         Try to fix erroneous time stamps? Defaults to True

#     save_csv : bln
#         Should file be saved as a CSV file? default=True
        
#     verbose : bln
#         Should function return info? default=True

#     Returns
#     -------
#     df: Pandas dataframe
#     """
#     try:
#         df = pd.read_csv(file)
            
#         if fix:
#             # sort data by 'Total cumulative energy(T1+T2)(kWh)'
#             df['row'] = range(len(df))
#             df.sort_values(by='row', ascending=False, inplace=True)

#             # assign Time to new column dtm and convert to proper datetime and
#             df['dtm'] = df['Time']
#             df['dtm'] = pd.to_datetime(df['dtm'], format='%Y-%m-%d %H:%M:%S')

#             # fix erroneous timestamps in data (afternoon times all of by 12 hrs)
#             # cf. https://pandas.pydata.org/pandas-docs/stable/user_guide/indexing.html#returning-a-view-versus-a-copy
#             # subtract 12 hrs if timestamp jumps 25 hrs from the previous timestamp
#             df.loc[df['dtm'].diff(1) == pd.to_timedelta(25, unit='h'), 'dtm'] -= pd.to_timedelta(12, unit='h')
#             # add 12 h to duplicated time stamps
#             df.loc[df['dtm'].duplicated(), 'dtm'] += pd.to_timedelta(12, unit='h')
#             # fix the first timestamps
#             df.loc[df['dtm'] < pd.datetime(2020,6,18), 'dtm'] += pd.to_timedelta(12, unit='h')

#             # Breaks in the time series may lead to 'missing duplicates' for the afternoon timestamps.
#             # This can lead to a negative 1st difference. Fix this iteratively
#             while(any(df['dtm'].diff(1) < pd.to_timedelta(0, unit='h'))):
#                 df.loc[df['dtm'].diff(1) < pd.to_timedelta(0, unit='h'), 'dtm'] += -df['dtm'].diff(1) + pd.to_timedelta(1, unit='h')

#             df.set_index(df['dtm'], inplace=True)
#             df.drop(labels=['row'], axis=1, inplace=True)

#         if verbose:
#             print(df.describe())

#         return(df)

#     except Exception as err:
#         print(err)


def plot_kplc_smartmeter_load_profile(df: pd.DataFrame, target: str=None, figure: str="load_profile.png") -> None:
    """
    Plot KPLC smart meter 'load profile' data, optionally save to file.

    Parameters
    ----------
    df : object
        Pandas dataframe

    target : str
        path to folder on disk. Defaults to None (= do not save)

    figure : str
        Name of image file with file extension

    Returns
    _______
    nothing
    """
    try:
        # set up 2 plots, ax1, ax2 for voltages, ax3 for currents
        fig, (ax1, ax2, ax3) = plt.subplots(nrows=3, ncols=1, sharex=True)

        # configure ax1
        ax1.set_title('KPLC Powerline Mt. Kenya GAW Station')
        ax1.set_ylabel("Voltage (V)")
        cols = ['A phase voltage(V)', 'B phase voltage(V)', 'C phase voltage(V)']
        ax1.set_ylim(210, 280)
        ax1.plot(df.loc[:, cols], label=cols, marker=".", linewidth=0.3)
        ax1.legend(cols, prop={'size':6}, loc='best')

        # configure ax2
        ax2.set_ylabel("Voltage (V)")
        cols = ['A phase voltage(V)', 'B phase voltage(V)', 'C phase voltage(V)']
        ax2.set_ylim(0, 50)
        ax2.plot(df.loc[:, cols], label=cols, marker=".", linewidth=0.3)
        ax2.legend(cols, prop={'size':6}, loc='upper left')

        # configure ax3
        ax3.set_ylabel("Current (A)")
        cols = ['A phase current(A)', 'B phase current(A)', 'C phase current(A)']
        ax3.set_ylim(0, 15)
        ax3.plot(df.loc[:, cols], label=cols, marker=".", linewidth=0.3)
        ax3.legend(cols, prop={'size':6}, loc='best')

        plt.gcf().autofmt_xdate()
        plt.tight_layout()
        
        if target:
            figure = f"{figure.split('.')[0]}-{datetime.datetime.strftime('%Y%m%d')}.{figure.split('.')[1]}"
            os.makedirs(target, exist_ok=True)   
            plt.savefig(os.path.join(target, figure), dpi=300)

        plt.show()

    except Exception as err:
        print(err)


if __name__ == "__main__":
    pass