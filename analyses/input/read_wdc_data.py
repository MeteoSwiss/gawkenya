""" 
Provide classes and methods to read in the the gawkenya level2 data (data from world data centers WDCGG and ebas)

Author: Leonie Bernet
Version: 1.0
Created on: 2024-02
Modifications: date -> modified
"""
from abc import ABC, abstractmethod
import xarray as xr
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import sys
from dataclasses import dataclass

# add the parent directory to syspath to allow importing modules from the parent directory
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if not parent_dir in sys.path:
    sys.path.append(parent_dir)


from processing import ebas
from processing import wdc


# Define an abstract base class to read our data
class BaseDataReader(ABC):
    '''
    Basic class
    data_path   should be the folder that contains all data-subfolders (e.g. ./data)
    '''
    def __init__(self, data_path, dataset, species, **kwargs):
        self.data_path = data_path
        self.dataset = dataset
        self.species = species
        self.kwargs = kwargs

    @abstractmethod
    def read_data(self) -> pd.DataFrame:
        pass
    
    @abstractmethod
    def process_data(self, data,**kwargs):
        pass

# dataclass to define different datasets
@dataclass
class WhichData:
    dataset: str
    species: str
    database: str


class wdcGHGReader(BaseDataReader):
    """
    This is a class to read GHG data from wdc. 
    It is a subclass of BaseInstrumentReader
    """
    # initialize class-specific attributes
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs) #include the initialization of the base class (attributes)
        self.data_path = os.path.join(self.data_path, f'wdc/wdcgg/{self.species}')


    def read_data(self):
        df = wdc.compile_wdcgg_into_dataframe(self.data_path,sampling='hourly')
        return df
    
    # Perform additional processing if needed    
    def process_data(self,df,**kwargs):
        df.rename_axis('time',inplace=True) # rename time index 

        return df


class wdcFlaskReader(BaseDataReader):
    """
    This is a class to read GHG flask (event) data from wdc. 
    It is a subclass of BaseInstrumentReader
    """
    # initialize class-specific attributes
    def __init__(self, *args, **kwargs):
        super().__init__( *args, **kwargs) #include the initialization of the base class (attributes)
        self.data_path = os.path.join(self.data_path, f'wdc/wdcgg/{self.species}')


    def read_data(self):
        df = wdc.compile_wdcgg_into_dataframe(self.data_path,sampling='event')

        return df
    
    def process_data(self,df,**kwargs):
        ## Check for duplicate dates:
        ## events have always twice the same time -> take mean of values with same time (parallel flask measurements)
        duplicates = df.index.duplicated(keep='first')
        if duplicates.any():
            numeric_columns = df.select_dtypes(include=['number']).columns # cannot take the mean of non-numeric columns
            df_numeric_mean = df.groupby(df.index)[numeric_columns].mean() # groupby time (same timestep) and the mean for each
            df_non_numeric = df.drop(columns=numeric_columns)
            df = pd.concat([df_numeric_mean, df_non_numeric.groupby(df.index).first()], axis=1)

        df.rename_axis('time',inplace=True) # rename time index 

        ## Exclude flagged data
        if 'FLASK_FLAG_CORR' in self.kwargs:
            if self.kwargs['FLASK_FLAG_CORR']:
                df.loc[df['QCflag']==3] = np.nan

        return df

class ebasReader(BaseDataReader):
    """
    This is a class to read data from ebas. 
    It is a subclass of BaseInstrumentReader
    """
    # initialize class-specific attributes
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs) #include the initialization of the base class (attributes)
        self.data_path = os.path.join(self.data_path, f'wdc/ebas/')

        if self.species in ['O3','CO','other_gases']:
            self.data_path = os.path.join(self.data_path, f'air/')
        elif self.species == 'aerosols':
            self.data_path = os.path.join(self.data_path, f'aerosols/')
        elif self.species == 'meteo':
            self.data_path = os.path.join(self.data_path, f'met/')
        else:
            raise NotImplementedError(
            f"Please add to the code the folder where the data of ebas {self.species} is stored.")

    def read_data(self):
        if self.species == 'O3':
            read_unc = True # get all available ozone data, which means not only the mean but also uncertainties (and values in ppb and mug/m3)
            df = ebas.compile_ebas_ozone_data_into_dataframe(self.data_path,read_unc=read_unc)
            if read_unc:
                df.rename(columns={'O3':'value','O3_unc':'value_sd','flag':'QCflag'},inplace=True)
            else: 
                df.rename(columns={'O3_0':'value','flag':'QCflag'},inplace=True)

        elif self.species == 'aerosols':
            # get aerosol file (for ozone that was done in ebas.py, but I do it now here)
            df = pd.DataFrame()
            for file in os.listdir(self.data_path):
                if "aerosol" in str(file):
                    file_path = self.data_path+file
                    data_file = ebas.ebas_aerosol_file_to_dataframe(file_path)
                df = pd.concat([df, data_file])

            df.rename(columns={'flag':'QCflag'},inplace=True)

        else:
            df = None
            raise NotImplementedError(
            f"The ebas reading for {self.species} has not been ipmlemented yet, please add it to the code.")
        
        return df
    
       
    # Perform additional processing if needed    
    def process_data(self, df,**kwargs):
        df.rename_axis('time',inplace=True) # rename time index 

        #replace flag-nan (so far it is set to 0.999)
        #df['QCflag'].replace(0.999, np.nan,inplace=True)
        df['QCflag'] = df['QCflag'].replace(0.999, np.nan)

        # check for duplicat dates. Sometimes we have multiple files for the same years. 
        #Usually, the new file just adds dates where the old file had nan. 
        # Therefore, we can just take the mean of all duplicated dates. 
        # Caution: this would be wrong if the new file would REPLACE old values!
        duplicates = df.index.duplicated(keep='first')
        if duplicates.any():
            numeric_columns = df.select_dtypes(include=['number']).columns # cannot take the mean of non-numeric columns
            df_numeric_mean = df.groupby(df.index)[numeric_columns].mean() # groupby time (same timestep) and the mean for each
            df_non_numeric = df.drop(columns=numeric_columns)
            df = pd.concat([df_numeric_mean, df_non_numeric.groupby(df.index).first()], axis=1)

        return df
    

# Dictionary with all the possible data
# Defines which species needs which data-reader    
    
AvailableData = {
    "CO2": WhichData(
        dataset = 'CO2',
        species ='CO2',
        database ='wdcgg'
    ),
    "CO2_flask": WhichData(
        dataset = 'CO2_flask',
        species ='CO2',
        database ='wdcgg_flask'
    ),
    "CO": WhichData(
        dataset = 'CO',
        species='CO',
        database='wdcgg'
    ),
    "CO_flask": WhichData(
        dataset = 'CO_flask',
        species ='CO',
        database ='wdcgg_flask'
    ),
    "CO_2002-2006": WhichData(
        dataset = 'CO_2002-2006',
        species='CO',
        database='ebas'
    ),
    "CH4": WhichData(
        dataset = 'CH4',
        species='CH4',
        database='wdcgg'
    ),
    "CH4_flask": WhichData(
        dataset = 'CH4_flask',
        species='CH4',
        database='wdcgg_flask'
    ),
    "O3": WhichData(
        dataset = 'O3',
        species ='O3',
        database ='ebas'
    ),
    "aerosols_2015": WhichData(
        dataset = 'aerosols_2015',
        species ='aerosols',
        database ='ebas'
    ),
    "aerosols": WhichData(
        dataset = 'aerosols',
        species = 'aerosols',
        database = 'psi' #??
    ),
    "other_gases_ebas": WhichData(
        dataset = 'other_gases_ebas', 
        species = 'glass_flask',  #not done yet
        database = 'ebas'
    ),
    "other_gases_wdc": WhichData( 
        dataset = 'other_gases_wdc',
        species = 'glass_flask',
        database = 'wdc' #not done yet
    ),
    "meteo": WhichData( 
        dataset = 'meteo',
        species = 'meteo',
        database = 'ebas' #not done yet
    ),


}
    
def create_data_reader(data_path: str, dataset: str,**kwargs) -> BaseDataReader:
    database = AvailableData[dataset].database
    species = AvailableData[dataset].species
    dataset = AvailableData[dataset].dataset
    
    if database == 'wdcgg':
        return wdcGHGReader(data_path=data_path, dataset=dataset, species=species,**kwargs) #return an instance of the wdcGHGReader class
    elif database == 'wdcgg_flask':
        return wdcFlaskReader(data_path=data_path, dataset=dataset, species=species,**kwargs)
    elif database == 'ebas':
        return  ebasReader(data_path=data_path, dataset=dataset, species=species,**kwargs)
    else:
        raise ValueError(f"Unsupported database: {database}")
    
