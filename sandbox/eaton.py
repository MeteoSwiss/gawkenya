# -*- coding: utf-8 -*-
# Auhor: joerg.klausen@meteoswiss.ch

import os
import pandas as pd
import matplotlib.pyplot as plt
from pandas.plotting import register_matplotlib_converters
register_matplotlib_converters()

root = "C:/Users/jkl/Documents/MKN/data/eaton/"

def read_data(root, folder, verbose=True):
    #  read files, combine into single dataframe
    df = pd.DataFrame()
    for file in os.scandir(os.path.join(root, folder)):
        if verbose:
            print("Reading file: ", file)
        tmp = pd.read_csv(file, sep=',', header=0)
        df = df.append(tmp, sort=False)
    
    # sort rows, extract proper date/time stamp, remove duplicates
    df.drop_duplicates(inplace=True)
    df.index = pd.to_datetime(df.iloc[:, 0], format='%Y-%m-%dT%H:%M:%S.%f+00:00')
    df.sort_index(inplace=True)
    
    return df


def plot_measures(df, cols, name, ylab):
    # plot specified columns
    fig, ax = plt.subplots(nrows=1, ncols=1, sharex=True)
    ax.set_ylim(220, 250)
    for col in cols:
        ax.plot(df.iloc[:, col], label=df.columns[col])
    ax.legend()

    # plt.figure(figsize=(8, 5))
    ax.set_title('Eaton UPS Mt. Kenya GAW Station')
    ax.set_ylabel(ylab)
    plt.gcf().autofmt_xdate()
    plt.tight_layout()
    plt.show()
    plt.savefig(name)
    
    return None


def plot_alarms(df, name, priority='critical', verbose=True):
    """
    Plot time series of alarms
    
    Plot time series of alarms. For the selected priority, seperate series
    are plotted for each unique message. 
    
    Parameters
    ----------
    df : dataframe  
        index 'datetime'
        columns 'Priority', 'Application', 'Message', 'Code', 'Status'
    
    name : str
        path of figure on disk    
     
    priority : str
        one of 'critical|warning|info'
    
    verbose : str
        should function return info? default=True
    """
    labels = list(df[df.Priority==priority].Message.unique())
    # d = dict(zip(range(len(labels)), labels))
    # d.keys()
    # d.items()
    
    # create a dataframe with separate series for each message
    dummies = df[df.Priority==priority].Message.str.get_dummies()
    for k, v in zip(range(len(labels)), labels):
        # print(k, v)
        dummies.loc[:, v] = dummies.loc[:, v] * k
    plt.plot(dummies, ' *')
    plt.title('Alarms of type {}'.format(priority))
    plt.gcf().autofmt_xdate()
    plt.yticks(ticks=range(len(labels)), labels=labels)
    plt.tight_layout()
    plt.show()
    plt.savefig(name)

def main():
    verbose = True

    folder = "Alarms"
    df = read_data(root, folder)
    # df = df.iloc[:,[2, 3, 5, 6, 9]]
    plot_alarms(df, name='alarms.png')
    
    folder = "UPS"
    cols = [1, 3, 5]
    ylab = "Voltage (V)"
    name = 'measures.png'
    df = read_data(root, folder)
    plot_measures(df, cols, name, ylab)


if __name__ == "__main__":
    main()