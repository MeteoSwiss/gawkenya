from asyncio.log import logger
import os
import logging
import pandas as pd
import glob
import json
import re
import shutil
import time
import zipfile
import matplotlib.pyplot as plt
from matplotlib import cm

class Meteo:

    def __init__(self, config=None):
        try:
            logger = logging.getLogger(__name__)
            logging.basicConfig(filename="meteo.log", filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            logger.info("Class 'Meteo' initialized successfully.")

            # assign variables
            self.config = config

            self.mappings = {
                'iii': 'MeteoSwiss internal station identifier; MKN=187; NRB=',
                'zzzztttt': 'dateTime as %Y%m%d%H%M%S',
                'tre200s0': 'Temperature (°C, 10-min average) at 2m above ground (Lufft)',
                'uor200s0': 'Humidity (%, 10-min average) at 2m above ground (Lufft)',
                'prestas0': 'Pressure (hPa, 10-min average) at 2m above ground (Lufft)',
                'fa1010z0': 'Wind speed (m/s, , 10-min average) at 2m above ground (Lufft)',
                'da1010z0': 'Wind direction (°, 10-min average) at 2m above ground (Lufft)',
                'rre150z0': 'Precipitation (mm, 10-min sum) at 2m above ground (Lufft, radar)',
                'ta1200s0': 'Temperature (°C, 10-min average) at 10m above ground (Lufft)',
                'ua1200s0': 'Humidity (%, 10-min average) at 10m above ground (Lufft)',
                'pa1stas0': 'Pressure (hPa, 10-min average) at 10m above ground (Lufft)',
                'fkl010z0': 'Wind speed (m/s, 10-min average) at 10m above ground (Lufft)',
                'dkl010z0': 'Wind direction (°, 10-min average) at 10m above ground (Lufft)',
                'ra1150z0': 'Precipitation (mm, 10-min sum) at 10m above ground (Lufft, radar)',
                'fkl010z1': 'Wind speed (m/s, 10-min maximum) at 10m above ground (Lufft)',
                'gor000z0': 'Global solar radiation (W, 10-min average) at 2m above ground (Lufft)',
                'ta2200s0': 'Temperature (°C, 10-min average) at 2m above ground, parallel measurement (Rotronic)',
                'ua2200s0': 'Pressure (hPa, 10-min average) at 2m above ground, parallel measurement (Rotronic)',
                'itosurr0': 'Surface ozone (ppb, 5-min average)'
            }

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.error("Error initializing class 'Meteo'.", err)


    def extract_bulletin(self, file: str, pattern: str, log=True) -> pd.DataFrame:
        """
        Open a file, determine its type from the file name, then extract content into a Pandas dataframe.

        Args:
            file (str): full path to file.
            pattern (str): should be one of "VMSW43" or "VRXA00"
            log (bln): Should activities be logged to 'meteo.log'? Defaults to True.
        """
        try:
            msg = f"Extracting file {file}."
            if log:
                logger.info(msg)
    
            df = pd.DataFrame()

            if bool(re.search(f'{pattern}', file)):
                if bool(re.search('.zip', file)):
                    zf = zipfile.ZipFile(file)
                    df = pd.read_csv(zf.open(zf.namelist()[0]), skiprows=1, header=1, sep=' ', na_values='/')
                else:
                    df = pd.read_csv(file, skiprows=1, header=1, sep=' ', na_values='/')
            df["dtm"] = pd.to_datetime(df['zzzztttt'], format='%Y%m%d%H%M')
            df['source'] = file
            df.set_index("dtm", inplace=True)

            if not df.empty:
                for column in df:
                    if df[column].dtype == 'float64':
                        df[column] = pd.to_numeric(df[column], downcast='float')
                    if df[column].dtype == 'int64':
                        df[column] = pd.to_numeric(df[column], downcast='integer')
            return df

        except Exception as err:
            logger.error(err)
            return pd.DataFrame()

    
    def extract_bulletins(self, path: str, pattern=["VMSW43", "VRXA00"], recursive=False, archive=None, remove_duplicates=True, save=None, log=True) -> pd.DataFrame:
        """
        Scan a directory and combine file content into a Pandas dataframe.

        Args:
            path (str): path to directory.
            recursive (bln): Should sub-directories be considered? Defaults to False.
            pattern (list): Pattern for recognition of bulletin files. Defaults to ["VSMW43", "VRXA00"]
            archive (str): If specified, files are moved to <path>/<archive>. Defaults to None.
            remove_duplicates (bln): Remove duplicates found in resulting data frame? Defaults to True.
            save (str): If one of ["csv", "json", "pkl"], resulting data frame is persisted to file. Defaults to None.
            log (bln): Should activities be logged to 'meteo.log'? Defaults to True.
        """
        try:
            msg = f"Extracting files found at '{path}' with pattern '{pattern}' ..."
            if log:
                logger.info(msg)
    
            df = pd.DataFrame()

            for p in pattern:
                files = glob.glob(os.path.join(path, f"{p}*"), recursive=recursive)
                msg = f"Found {len(files)} files to extract and combine."
                if log:
                    logger.info(msg)

                for file in files:
                    df = pd.concat([df, self.extract_bulletin(file=file, pattern=p, log=log)])
                    if archive:
                        dstdir = os.path.join(os.path.dirname(file), archive)
                        os.makedirs(dstdir, exist_ok=True)
                        shutil.move(src=file, dst=os.path.join(dstdir, os.path.basename(file)))

            if remove_duplicates:
                logger.info("Duplicate bulletins were found. Unique values were retained.")
                df.drop_duplicates(subset=df.columns[df.columns != "source"], inplace=True)

            if save:
                dst = os.path.join(path, f"meteo-{time.strftime('%Y%m%d%H%M%S')}.{save}")
                if save=="csv":
                    df.to_csv(dst)
                elif save=="json":
                    df.to_json(dst)
                elif save=="pickle":
                    df.to_pickle(dst)
                else: 
                    raise ValueError("'save' must be one of ['csv', 'json', 'pickle'].")
                if log:
                    logger.info(f"Results saved in '{dst}'.")

            return df

        except Exception as err:
            logger.error(err)
            return pd.DataFrame()


    def mappings2json(self, path: str, log=True) -> str:
        try:
            file = os.path.join(path, "mappings.json")
            with open(file=file, mode="wt") as fh:
                fh.write(json.dumps(self.mappings))
            if log:
                logger.info(f"Mappings saved in '{file}'.")
            return file
            
        except Exception as err:
            logger.error(err)


    def plot_coverage(self, df, figure="meteodata_coverage.png", data="meteodata_coverage.csv", add_period=True, verbose=True):
        """
        Plot the number of days per week with observations as a function of time
    
        Plot the number of days per week with observations as a function of time        
    
        Parameters
        ----------
        df : object
            Pandas dataframe, expected to have an index 'dtm'
    
        figure : str
            Name of image file with file extension
    
        data : str
            Name of data file with file extension. At present, only .csv is supported.
    
        add_period : bln
            Append period covered to filename? Defaults to True
            
        verbose : str
            should function return info? default=True
    
        Returns
        _______
        nothing
        """
        try:
            cols = df.columns[df.columns.str.contains('P')]            
#            cols = ['P-1', 'P-2']
            x = df.reset_index()['dtm'].tolist()

            y = df[cols]
            ymin = df[cols].min().min()
            ymax = df[cols].max().max()

            # set up plot
            fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True)
    
            # configure ax1
            ax1.set_ylim(ymin, ymax)
            ax1.set_title('Meteo Data Coverage at %s GAW Station' % self.config['name'])
            ax1.set_ylabel("Coverage (days per week)")
    
            
            for col in cols:           
                colors = cm.Greens(y[col]/ymax)        
                ax1.bar(x, y[col], width=-1, align='edge', color = colors, edgecolor = colors, label=col)
#            ax1.plot(df.loc[:, cols], label=cols, marker=".", linewidth=0.3)
            ax1.xaxis_date()
            ax1.legend(cols, prop={'size':6}, loc='best')
    
            plt.gcf().autofmt_xdate()
            plt.tight_layout()
            
            path = os.path.join(os.path.expanduser(self.config['results']), 
                                self.config['wsi'], 'meteo')
            os.makedirs(path, exist_ok=True)
            
            period = ""            
            if add_period:
                period = "%s-%s" % (min(x).strftime("%Y%m%d"), max(x).strftime("%Y%m%d"))
            
            figure = "%s_%s%s" % (os.path.splitext(figure)[0], period, os.path.splitext(figure)[1])
            plt.savefig(os.path.join(path, figure), dpi=300)
    
            if ".csv" in data.lower():
                data = "%s_%s%s" % (os.path.splitext(data)[0], period, os.path.splitext(data)[1])
                df.to_csv(os.path.join(path, data))
    
        except Exception as err:
            print(err)


if __name__ == "__main__":
    pass