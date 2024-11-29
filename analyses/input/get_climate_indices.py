import pandas as pd

def load_enso(lag_months=0):
    """
    Downloads the ENSO from https://www.esrl.noaa.gov/psd/enso/mei/data/meiv2.data

    Function from https://usask-arg.github.io/lotus-regression/_modules/LOTUS_regression/predictors/download.html#load_enso

    Parameters
    ----------
    lag_months : int, Optional. Default 0
        The numbers of months of lag to introduce to the ENSO signal
    """
    data = pd.read_table(
        "https://www.esrl.noaa.gov/psd/enso/mei/data/meiv2.data",
        skiprows=1,
        skipfooter=4,
        sep=r"\s+",
        index_col=0,
        engine="python",
        header=None,
        parse_dates=True
)
    assert data.index[0] == pd.Timestamp('1979-01-01 00:00:00')
    data = data.to_numpy().flatten()
    data = data[data > -998]

    data = pd.DataFrame(
        data, index=pd.date_range(start="1979", periods=len(data), freq="M").to_period().to_timestamp() # first transform to period (months) and then to timestamp (first of month)
    )
    
    data.rename(columns={0: "MEI"}, inplace=True)
    data.index.rename("time", inplace=True)

    return data

def load_iod():
    """
    Downloads the Dipole Mode Index (DMI), indicating positive or negative Indian Ocean Dipole (IOD) 
    from https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data


    Parameters
    ----------
    """
    data = pd.read_table(
        "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data",
        skiprows=1,
        skipfooter=7,
        sep=r"\s+",
        index_col=0,
        engine="python",
        header=None,
        parse_dates=True
)
    assert data.index[0] == pd.Timestamp('1870-01-01 00:00:00')
    data = data.to_numpy().flatten()
    data = data[data > -998]

    data = pd.DataFrame(
        data, index=pd.date_range(start="1870", periods=len(data), freq="M").to_period().to_timestamp()
    )
    
    data.rename(columns={0: "DMI"}, inplace=True)
    data.rename(columns={0: "DMI"}, inplace=True)

    return data