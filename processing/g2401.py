# %%
import os
import logging
from asyncio.log import logger
import io
import json
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl
import re
import shutil
import zipfile

from housekeeping import organize_files


# %%
class G2401:

    def __init__(self, log: str='g2401.log'):
        try:
            if log != "g2401.log":
                os.makedirs(os.path.dirname(log), exist_ok=True)
            logger = logging.getLogger(__name__)
            # logging.basicConfig(filename=log, filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            log_handler = logging.FileHandler(filename=log, mode="a", encoding="utf8")
            log_handler.setLevel(logging.DEBUG)
            log_handler.setFormatter("%(asctime)s %(levelname)s %(message)s")
            logger.addHandler(log_handler)

            self.dtypes = {'DataLog_User_Sync': [pl.Utf8]*2 + [pl.Float64]*4 + [pl.Int64]*2 + [pl.Float64]*14,
                           }
            logger.info("Class 'G2401' initialized successfully.")

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.error("Error initializing class 'G2401'.", err)


    def extract_g2401_to_dataframe(self, file: str, dtm="dtm", log=True) -> tuple([pl.DataFrame, str]):
        """
        Extract a Picarro G2401 DataLog_User_Sync file into a Polars dataframe.

        NB: Polars doesn't support fwf at this point. Workaround: Read file, replace multiple spaces with comma, and then read as byte stream.

        Args:
            file (str): full path to file.
            dtm (str): Name for dateTime column to be generated.
            log (bln): Should activities be logged? Defaults to True.

        Returns:
            pl.DataFrame: DataFrame with DateTime and source columns added to data
            str: Errors encountered
        """
        if bool(re.search("DataLog_User_Sync", file)):
            if log:
                logger.info(f"Extracting file {file}.")

            try:
                if bool(re.search('.zip', file)):
                    zf = zipfile.ZipFile(file)
                    source = re.sub(" +", ",", zf.open(zf.namelist()[0]).read().decode('utf-8'))
                else:
                    source = re.sub(" +", ",", open(file, "rb").read().decode('utf-8'))

                source = re.sub(",\r\n", "\n", source)
                df = pl.read_csv(io.StringIO(source), has_header=True, separator=",", dtypes=self.dtypes["DataLog_User_Sync"])
                df = df.with_columns(pl.lit(file).alias('source'),
                                     pl.format("{} {}", "DATE", "TIME").str.to_datetime(time_zone="UTC").alias(dtm))
                return df, None

            except Exception as err:
                logger.error(err)
                return pl.DataFrame(), str(err)
        else:
            return pl.DataFrame(), f"{file}: File type unknown."
        

    def compile_g2401_to_parquet(self, source: str, target: str, year: str=None, by_month: bool=True, dtm="dtm", archive: str=None, issues: str=None, append_parquet: bool=True, verbose: bool=True, log: bool=True) -> None:
        """Extract and compile G2401 DataLog_User_Sync files found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

        Args:
            source (str): Root path to directory to process. <year> will be appended to path. Sub-directories will also be considered.
            target (str): Root path to directory where .parquet files will be stored.  <year> will be appended to path.
            year (str): Relative path that will be appended to <source> before this path will be processed using os.walk().
            by_month (bool, optional): Should .parquet files be generated per month? Defaults to True. NB: Yearly files risk to become too large for normal git!
            dtm (str): Name of dateTime column.
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            append_parquet (bool, optional): If True, append new data to an existing .parquet file. Defaults to True.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
            log (bool, optional): Should activities be logged? Defaults to True.
        Returns:
            Nothing
        """
        def __process_tree(source, target, archive, issues, month):
            result = pl.DataFrame()
            errors = dict()
            base = os.path.join(source, month)
            if os.path.exists(base):
                for root, dirs, files in os.walk(base):
                    for file in files:
                        if verbose:
                            print(f"Processing {file} ...")
                        src = os.path.join(root, file)
                        df, err = self.extract_g2401_to_dataframe(src, log=log)
                        if err:
                            errors.update({file: err})
                            if issues:
                                dst = os.path.join(issues, month)
                                os.makedirs(dst, exist_ok=True)
                                shutil.move(src=src, dst=os.path.join(dst, file))
                        else:
                            try:
                                result = pl.concat([result, df], how='diagonal')
                                if archive:
                                    dst = os.path.join(archive, month)
                                    os.makedirs(dst, exist_ok=True)
                                    shutil.move(src=src, dst=os.path.join(dst, file))
                                    # print(f"archive: {src} > {dst}")
                            except Exception as err:
                                errors.update({file: err})
                                pass

                # store result as parquet file
                # if append_parquet==True, check if parquet already exists and append
                dst = os.path.join(target, month)
                os.makedirs(dst, exist_ok=True)
                parquet = os.path.join(dst, "g2401.parquet")
                if not result.is_empty():
                    if append_parquet:
                        if os.path.exists(parquet):
                            df = pl.read_parquet(source=parquet)
                            result = pl.concat([result, df], how='diagonal')

                    # remove duplicates, sort data
                    result = result.unique()
                    result = result.sort(dtm)

                    # store result as parquet file
                    result.write_parquet(parquet)

                # write errors to json file (append if it exists already)
                with open(os.path.join(dst, "g2401.errors.json"), "a") as fh:
                    json.dump(errors, fh)

            return None
        
        source = os.path.join(source, year)
        target = os.path.join(target, year)
        if issues:
            issues = os.path.join(issues, year)
        if archive:
            archive = os.path.join(archive, year)
        
        try:
            # process files
            if verbose:
                print(f"Processing source {source} ...")
            if by_month:
                months = ["{:02d}".format(mm) for mm in range(1, 13, 1)]
                for month in months:
                    __process_tree(source, target, archive, issues, month)                    
            else:
                __process_tree(source, target, archive, issues, month=None)
            return None

        except Exception as err:
            print(err)


    def remove_extremes(self, df: pl.DataFrame, variable: str, q=0.001) -> tuple([pl.DataFrame, dict]):
        """Remove extreme values from polars DataFrame. Extremes are defined using quantiles.

        Args:
            df (pl.DataFrame): Picarro data
            q (float, optional): Quantile defining extreme values, i.e., values outside [>=q, <=(1-q)]. Defaults to 0.00001.

        Returns:
            pl.DataFrame: polars DataFrame of data that are retained
            dict: cutoffs giving the lower and upper boundaries

        [TODO] Instead of removing the extremes from the dataframe, it would be better to flag them. Also, use flags to filter first.
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
            return pl.DataFrame, dict()


    def plot_data(self, df: pl.DataFrame, dtm: str="dtm", variable: str="CO2_dry_sync", start:str=None, end:str=None, title:str="G2401 Data", ylim=None) -> None:
        """Plot a polars DataFrame containing Picarro data.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            dtm (str, optional): name of dateTime variable
            variable (str): ...
            start (str): ...
            end (str): ...
            title (str): Title of plot. Defaults to "G2401 Data"
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


    def unarchive_files(self):
        """Helper function to unarchive files"""
        instr = "g2401"
        source = f"/product_data/data/pay/Kenya/MKN/incoming/{instr}"
        archive = f"/product_data/data/pay/Kenya/MKN/archive/{instr}"
        for year in ["2020", "2021", "2022", "2023", "2024"]:
            if os.path.exists(os.path.join(archive, year)):
                n = organize_files.move_files(source=os.path.join(archive, year), target=source, pattern="CFKADS2320-\d{8}-\d{6}Z-DataLog_User_Sync.zip")


if __name__ == "__main__":
    pass
