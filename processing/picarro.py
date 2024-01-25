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

# %%
class G2401:

    def __init__(self, log: str='g2401.log'):
        try:
            if log != "g2401.log":
                os.makedirs(os.path.dirname(log), exist_ok=True)
            logger = logging.getLogger(__name__)
            logging.basicConfig(filename=log, filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            logger.info("Class 'G2401' initialized successfully.")

            self.dtypes = {'DataLog_User_Sync': [pl.Utf8]*2 + [pl.Float64]*4 + [pl.Int64]*2 + [pl.Float64]*14,
                           }

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.error("Error initializing class 'G2401'.", err)


    def extract_g2401_to_dataframe(self, file: str, dtm="dtm", log=True) -> tuple([pl.DataFrame, str, str]):
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
            str: File type
        """
        file_type = "DataLog_User_Sync" if bool(re.search("DataLog_User_Sync", file)) else "unknown"

        if bool(re.search(file_type, file)):
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

                return df, None, file_type

            except Exception as err:
                logger.error(err)
                return pl.DataFrame(), str(err), None


    def compile_g2401_to_parquet(self, source: str, target: str, base: str=None, dtm="dtm", archive: str=None, issues: str=None, verbose: bool=True, log: bool=True) -> None:
        """Extract and compile G2401 DataLog_User_Sync files found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

        Args:
            source (str): Root path to directory to process. <base> will be appended to path. Sub-directories will also be considered.
            target (str): Root path to directory where .parquet files will be stored.  <base> will be appended to path.
            base (str): Relative path that will be appended to <source> before this path will be processed using os.walk().
            dtm (str): Name of dateTime column.
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
            log (bool, optional): Should activities be logged? Defaults to True.
        Returns:
            Nothing
        """
        source = os.path.join(source, base)
        target = os.path.join(target, base)
        os.makedirs(target, exist_ok=True)
        if archive:
            archive = os.path.join(archive, base)

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
                    tmp, err, file_type = self.extract_g2401_to_dataframe(src, log=log)
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

            # remove duplicates, sort data
            result = result.unique()
            result = result.sort(dtm)

            # store result as parquet file
            result.write_parquet(os.path.join(target, f"{file_type}.parquet"))

            # write errors to json file
            with open(os.path.join(target, f"{file_type}.errors.json"), "w") as fh:
                json.dump(errors, fh)

            # return result, errors
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


if __name__ == "__main__":
    pass
