# from asyncio.log import logger
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import pandas as pd
import polars as pl
import glob
import json
import re
import shutil
import time
import zipfile
import matplotlib.pyplot as plt
from matplotlib import cm

class Meteo:

    def __init__(self, log: str="meteo.log"):
        try:
            if log != "meteo.log":
                os.makedirs(os.path.dirname(log), exist_ok=True)
            # logging.basicConfig(filename=log, filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            self.logger = logging.getLogger(__name__)
            log_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            log_handler = logging.FileHandler(filename=log, mode="a", encoding="utf8")
            log_handler.setLevel(logging.INFO)
            log_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_handler)
            self.logger.info("Class 'Meteo' initialized successfully.")

            self.mappings = {'VRXA00': {
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
                    # 'itosurr0': 'Surface ozone (ppb, 5-min average)'
                }
            }

            self.dtypes = {'VRXA00': [pl.Utf8]*2 + [pl.Float64]*16,}

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.exception("Error initializing class 'Meteo'.", err)


    def extract_vrxa00_to_dataframe(self, file: str, log=True) -> tuple([pl.DataFrame, str]):
        """
        Open a file, determine its type from the file name, then extract content into a Polars dataframe.

        Args:
            file (str): full path to file.
            log (bln): Should activities be logged to 'meteo.log'? Defaults to True.

        Returns:
            pl.DataFrame: DataFrame with DateTime and source columns added to data
            str: Errors encountered
        """
        if bool(re.search(f'VRXA00', file)):
            if log:
                self.logger.info(f"Extracting file {file}.")

            try:
                if bool(re.search('.zip', file)):
                    zf = zipfile.ZipFile(file)
                    df = pl.read_csv(source=zf.open(zf.namelist()[0]).read(), has_header=True, separator=" ", skip_rows=3, null_values='/', dtypes=self.dtypes['VRXA00'])
                else:
                    df = pl.read_csv(source=file, has_header=True, separator=" ", skip_rows=3, null_values='/', dtypes=self.dtypes['VRXA00'])

                df = df.with_columns(pl.lit(file).alias('source'),
                                    pl.col('zzzztttt').str.to_datetime(format='%Y%m%d%H%M').alias('dtm'))
                return df, None

            except Exception as err:
                self.logger.error(err)
                return pl.DataFrame(), str(err)


    def compile_vrxa00_to_parquet(self, source: str, target: str, year: str=None, archive: str=None, issues: str=None, append_parquet: bool=True, verbose: bool=True, log: bool=True) -> None:
        """Extract and compile VRXA00 bulletins found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

        Args:
            source (str): Root path to directory to process. <year> will be appended to path. Sub-directories will also be considered.
            target (str): Root path to directory where .parquet files will be stored.  <year> will be appended to path.
            year (str): Relative path that will be appended to <source> before this path will be processed using os.walk().
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            append_parquet (bool, optional): If True, append new data to an existing .parquet file. Defaults to True.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
            log (bool, optional): Should activities be logged? Defaults to True.
        Returns:
            Nothing
        """
        source = os.path.join(source, year)
        target = os.path.join(target, year)
        os.makedirs(target, exist_ok=True)
        archive = os.path.join(archive, year)
        os.makedirs(archive, exist_ok=True)

        result = pl.DataFrame()
        errors = dict()
        
        try:
            # process files
            if verbose:
                print(f"Processing source {source} ...")
            for root, dirs, files in os.walk(source):
                n = (len(source) - len(root) + 1)
                relative_path = root[n:] if n < 0 else ""
                for file in files:
                    if verbose:
                        print(f"Processing {file} ...")
                    src = os.path.join(root, file)
                    tmp, err = self.extract_vrxa00_to_dataframe(src, log=log)
                    if err:
                        errors.update({file: err})
                        if issues:
                            dst = os.path.join(issues, relative_path)
                            os.makedirs(dst, exist_ok=True)
                            shutil.move(src=src, dst=os.path.join(dst, file))
                            print(f"issue: {src} > {dst}")
                    elif archive:
                        dst = os.path.join(archive, relative_path)
                        os.makedirs(dst, exist_ok=True)
                        shutil.move(src=src, dst=os.path.join(dst, file))
                        # print(f"archive: {src} > {dst}")
                    result = pl.concat([result, tmp], how='diagonal')

            if not result.is_empty:
                # if append_parquet==True, check if parquet already exists and append
                if append_parquet:
                    parquet = os.path.join(target, 'vrxa00.parquet')
                    if os.path.exists(parquet):
                        df = pl.read_parquet(parquet)
                        result = pl.concat([result, df], how='diagonal')
                    
                # remove duplicates, sort data
                result = result.unique()
                result = result.sort("dtm")

                # store result as parquet file
                result.write_parquet(parquet)

            # write errors to json file
            with open(os.path.join(target, 'vrxa00.errors.json'), "w") as fh:
                json.dump(errors, fh)

            # return result, errors
            return None

        except Exception as err:
            self.logger.error(err)
            print(err)


    def remove_extremes(self, df: pl.DataFrame, variable: str, q=0.001) -> tuple([pl.DataFrame, dict]):
        """Remove extreme values from polars DataFrame. Extremes are defined using quantiles.

        Args:
            df (pl.DataFrame): Meteo data
            q (float, optional): Quantile defining extreme values, i.e., values outside [>=q, <=(1-q)]. Defaults to 0.00001.

        Returns:
            pl.DataFrame: polars DataFrame of data that are retained
            dict: cutoffs giving the lower and upper boundaries

        [TODO] Instead of removing the extremes from the dataframe, it would be better to flag them
        """
        cutoffs = dict()
        try:
            lower = df[variable].quantile(q)
            upper = df[variable].quantile(1-q)
            df = df.filter((pl.col(variable) >= lower) & (pl.col(variable) <= upper))
            cutoffs[variable] = {'lower': lower, 'upper': upper}
            return df, cutoffs

        except Exception as err:
            print(err)


    def plot_data(self, df: pl.DataFrame, dtm: str="dtm", variable: str="tre200s0", start:str=None, end:str=None, title:str="Meteo Data", ylim=None) -> None:
        """Plot a polars DataFrame containing meteo data. Variable names according to MeteoSwiss DWH.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            dtm (str, optional): name of dateTime variable
            variable (str): ...
            start (str): ...
            end (str): ...
            title (str): Title of plot. Defaults to "Meteo Data"
        """
        try:
            df = df.sort(dtm)

            if start:
                df = df.filter(pl.col(dtm) >= pl.lit(start).str.strptime(pl.Date))
            if end:
                df = df.filter(pl.col(dtm) <= pl.lit(end).str.strptime(pl.Date))

            plt.figure(figsize=(12, 6))
            plt.scatter(df[dtm], df[variable], c='blue', marker="o", s=2)

            if ylim:
                plt.ylim(ylim)
            # plt.legend(legend)
            plt.suptitle(title)
            # plt.title(subtitle)
            plt.xlabel("DateTime")
            plt.ylabel(variable)
            plt.show()
        except Exception as err:
            print(err)


    # def vrxa00_to_parquet(self, source: str, target: str, archive: str=None, verbose: bool=True, log: bool=True) -> None:
    #     """Extract and compile VRXA00 bulletins found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

    #     Args:
    #         source (str): Root path to directory to process. Sub-directories will also be considered.
    #         target (str): Root path to directory where monthly .parquet files will be stored.
    #         archive (str): Root path to directory where files will be archived. Sub-folders will be created corresponding to source.
    #         verbose (bool, optional): Should information on process be written to console? Defaults to True.
    #     Returns:
    #         Nothing
    #         # pl.DataFrame: DataFrame with DateTime and source columns added to data
    #         # dict: name of files that could not be processed as well as errors encountered.
    #     """
    #     result = pl.DataFrame()
    #     errors = dict()
    #     try:
    #         # process files
    #         if verbose:
    #             print(f"Processing source {source} ...")
    #         for root, dirs, files in os.walk(source):
    #             for file in files:
    #                 if verbose:
    #                     print(f"Processing {file} ...")
    #                 tmp, err = self.extract_vrxa00_to_dataframe(os.path.join(root, file), log=log)
    #                 if err:
    #                     errors.update({file: err})
    #                 elif archive:
    #                     dst = os.path.join(archive, root[-(len(root)-len(source)-1):])
    #                     os.makedirs(dst, exist_ok=True)
    #                     # shutil.move(src=os.path.join(root, file), dst=os.path.join(dst, file))
    #                     print(f"{os.path.join(root, file)} > {os.path.join(dst, file)}")
    #                 result = pl.concat([result, tmp], how='diagonal')

    #         # create target directoriy if it doesn't yet exist
    #         os.makedirs(target, exist_ok=True)

    #         # remove duplicates, sort data
    #         result = result.unique()
    #         # result = result.sort("DateTime")

    #         # store result as parquet file
    #         result.write_parquet(os.path.join(target, 'vrxa00.parquet'))

    #         # write errors to json file
    #         with open(os.path.join(target, 'vrxa00.errors.json'), "w") as fh:
    #             json.dump(errors, fh)

    #         # return result, errors
    #         return None

    #     except Exception as err:
    #         print(err)

    # def extract_bulletin(self, file: str, pattern: str, log=True) -> pd.DataFrame:
    #     """
    #     Open a file, determine its type from the file name, then extract content into a Pandas dataframe.

    #     Args:
    #         file (str): full path to file.
    #         pattern (str): should be one of "VMSW43" or "VRXA00"
    #         log (bln): Should activities be logged to 'meteo.log'? Defaults to True.
    #     """
    #     try:
    #         msg = f"Extracting file {file}."
    #         if log:
    #             logger.info(msg)
    
    #         df = pd.DataFrame()

    #         if bool(re.search(f'{pattern}', file)):
    #             if bool(re.search('.zip', file)):
    #                 zf = zipfile.ZipFile(file)
    #                 df = pd.read_csv(zf.open(zf.namelist()[0]), skiprows=1, header=1, sep=' ', na_values='/')
    #             else:
    #                 df = pd.read_csv(file, skiprows=1, header=1, sep=' ', na_values='/')
    #         df["dtm"] = pd.to_datetime(df['zzzztttt'], format='%Y%m%d%H%M')
    #         df['source'] = file
    #         df.set_index("dtm", inplace=True)

    #         if not df.empty:
    #             for column in df:
    #                 if df[column].dtype == 'float64':
    #                     df[column] = pd.to_numeric(df[column], downcast='float')
    #                 if df[column].dtype == 'int64':
    #                     df[column] = pd.to_numeric(df[column], downcast='integer')
    #         return df

    #     except Exception as err:
    #         logger.error(err)
    #         return pd.DataFrame()

    
#     def extract_bulletins(self, path: str, pattern=["VMSW43", "VRXA00"], recursive=False, archive=None, remove_duplicates=True, save=None, log=True) -> pd.DataFrame:
#         """
#         Scan a directory and combine file content into a Pandas dataframe.

#         Args:
#             path (str): path to directory.
#             recursive (bln): Should sub-directories be considered? Defaults to False.
#             pattern (list): Pattern for recognition of bulletin files. Defaults to ["VSMW43", "VRXA00"]
#             archive (str): If specified, files are moved to <path>/<archive>. Defaults to None.
#             remove_duplicates (bln): Remove duplicates found in resulting data frame? Defaults to True.
#             save (str): If one of ["csv", "json", "pkl"], resulting data frame is persisted to file. Defaults to None.
#             log (bln): Should activities be logged to 'meteo.log'? Defaults to True.
#         """
#         try:
#             msg = f"Extracting files found at '{path}' with pattern '{pattern}' ..."
#             if log:
#                 logger.info(msg)
    
#             df = pd.DataFrame()

#             for p in pattern:
#                 files = glob.glob(os.path.join(path, f"{p}*"), recursive=recursive)
#                 msg = f"Found {len(files)} files to extract and combine."
#                 if log:
#                     logger.info(msg)

#                 for file in files:
#                     df = pd.concat([df, self.extract_bulletin(file=file, pattern=p, log=log)])
#                     if archive:
#                         dstdir = os.path.join(os.path.dirname(file), archive)
#                         os.makedirs(dstdir, exist_ok=True)
#                         shutil.move(src=file, dst=os.path.join(dstdir, os.path.basename(file)))

#             if remove_duplicates:
#                 logger.info("Duplicate bulletins were found. Unique values were retained.")
#                 df.drop_duplicates(subset=df.columns[df.columns != "source"], inplace=True)

#             if save:
#                 dst = os.path.join(path, f"meteo-{time.strftime('%Y%m%d%H%M%S')}.{save}")
#                 if save=="csv":
#                     df.to_csv(dst)
#                 elif save=="json":
#                     df.to_json(dst)
#                 elif save=="pickle":
#                     df.to_pickle(dst)
#                 else: 
#                     raise ValueError("'save' must be one of ['csv', 'json', 'pickle'].")
#                 if log:
#                     logger.info(f"Results saved in '{dst}'.")

#             return df

#         except Exception as err:
#             logger.error(err)
#             return pd.DataFrame()


#     # def mappings2json(self, path: str, log=True) -> str:
#         try:
#             file = os.path.join(path, "mappings.json")
#             with open(file=file, mode="wt") as fh:
#                 fh.write(json.dumps(self.mappings))
#             if log:
#                 logger.info(f"Mappings saved in '{file}'.")
#             return file
            
#         except Exception as err:
#             logger.error(err)


#     # def plot_coverage(self, df, figure="meteodata_coverage.png", data="meteodata_coverage.csv", add_period=True, verbose=True):
#         """
#         Plot the number of days per week with observations as a function of time
    
#         Plot the number of days per week with observations as a function of time        
    
#         Parameters
#         ----------
#         df : object
#             Pandas dataframe, expected to have an index 'dtm'
    
#         figure : str
#             Name of image file with file extension
    
#         data : str
#             Name of data file with file extension. At present, only .csv is supported.
    
#         add_period : bln
#             Append period covered to filename? Defaults to True
            
#         verbose : str
#             should function return info? default=True
    
#         Returns
#         _______
#         nothing
#         """
#         try:
#             cols = df.columns[df.columns.str.contains('P')]            
# #            cols = ['P-1', 'P-2']
#             x = df.reset_index()['dtm'].tolist()

#             y = df[cols]
#             ymin = df[cols].min().min()
#             ymax = df[cols].max().max()

#             # set up plot
#             fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True)
    
#             # configure ax1
#             ax1.set_ylim(ymin, ymax)
#             ax1.set_title('Meteo Data Coverage at %s GAW Station' % self.config['name'])
#             ax1.set_ylabel("Coverage (days per week)")
    
            
#             for col in cols:           
#                 colors = cm.Greens(y[col]/ymax)        
#                 ax1.bar(x, y[col], width=-1, align='edge', color = colors, edgecolor = colors, label=col)
# #            ax1.plot(df.loc[:, cols], label=cols, marker=".", linewidth=0.3)
#             ax1.xaxis_date()
#             ax1.legend(cols, prop={'size':6}, loc='best')
    
#             plt.gcf().autofmt_xdate()
#             plt.tight_layout()
            
#             path = os.path.join(os.path.expanduser(self.config['results']), 
#                                 self.config['wsi'], 'meteo')
#             os.makedirs(path, exist_ok=True)
            
#             period = ""            
#             if add_period:
#                 period = "%s-%s" % (min(x).strftime("%Y%m%d"), max(x).strftime("%Y%m%d"))
            
#             figure = "%s_%s%s" % (os.path.splitext(figure)[0], period, os.path.splitext(figure)[1])
#             plt.savefig(os.path.join(path, figure), dpi=300)
    
#             if ".csv" in data.lower():
#                 data = "%s_%s%s" % (os.path.splitext(data)[0], period, os.path.splitext(data)[1])
#                 df.to_csv(os.path.join(path, data))
    
#         except Exception as err:
#             print(err)


if __name__ == "__main__":
    pass