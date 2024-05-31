import os
import logging
from asyncio.log import logger
import polars as pl
import matplotlib.pyplot as plt
# from io import BytesIO
import json
import shutil
import zipfile


class AE33:
    """Magee Scientific AE33 aethalometer data as produced by mkndaq

    Methods:
        extract_zipfile_to_dataframe(self, path: str, sep="|", round="min") -> (pl.DataFrame, str): Read AE33 data file into a polars dataframe
        zipfiles_to_parquet(self, source: str, target: str, plot: bool=True, verbose: bool=True, remove_early_data: bool=True) -> (pl.DataFrame, dict): Extract and compile AE33 zipfiles found in source and its sub-folders to polars DataFrame, save as parquet files in target. Optionally plot the data.
        plot_aethalometer_data(self, df: pl.DataFrame, variable: str="eBC", start:str=None, end:str=None, title:str="Magee Scientific AE33") -> None: Plot a polars DataFrame containing nephelometer data.
        remove_extremes(self, df: pl.DataFrame, q=0.01) -> pl.DataFrame: Remove extreme values from polars DataFrame. Extremes are defined using quantiles.
    """

    def __init__(self, log: str='ae33.log'):
        try:
            if log != "ae33.log":
                os.makedirs(os.path.dirname(log), exist_ok=True)
            logger = logging.getLogger(__name__)
            # logging.basicConfig(filename=log, filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            log_handler = logging.FileHandler(filename=log, mode="a", encoding="utf8")
            log_handler.setLevel(logging.DEBUG)
            log_handler.setFormatter("%(asctime)s %(levelname)s %(message)s")
            logger.addHandler(log_handler)
            logger.info("Class 'AE33' initialized successfully.")

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.error("Error initializing class 'AE33'.", err)


    def extract_zipfile_to_dataframe(self, path: str, dtm="dtm", sep="|") -> tuple([pl.DataFrame, str]):
        """Read AE33 data file into a polars dataframe

        Args:
            path (str): full path to file
            dtm (str, optional): Name of dateTime column. Defaults to 'dtm'
            sep (str, optional): field separator used in file. Defaults to "|".

        Returns:
            pl.DataFrame: DataFrame with DateTime and source columns added to data
            str: Errors encountered

        Usage:
        >>> path = "tests/data/ae33/ae33-202310190000.zip"
        >>> ae33 = AE33()
        >>> df = ae33.extract_zipfile_to_dataframe(path=path)
        >>> len(df)
        """
        df = pl.DataFrame()
        cols = ("Inst_SN", "row_id", "DateTime_1", f"{dtm}", "unclear", "DateTime_2", 
                "RefCh1", "Sen1Ch1", "Sen2Ch1", "RefCh2", "Sen1Ch2", "Sen2Ch2", "RefCh3", "Sen1Ch3", "Sen2Ch3", "RefCh4", "Sen1Ch4", "Sen2Ch4", "RefCh5", "Sen1Ch5", "Sen2Ch5", "RefCh6", "Sen1Ch6", "Sen2Ch6", "RefCh7", "Sen1Ch7", "Sen2Ch7", 
                "BC11", "BC12", "BC1", "BC21", "BC22", "BC2", "BC31", "BC32", "BC3", "BC41", "BC42", "BC4", "BC51", "BC52", "BC5", "BC61", "BC62", "BC6", "BC71", "BC72", "BC7", 
                "K1", "K2", "K3", "K4", "K5", "K6", "K7", "unclear_2", "Pres", "Temp", "Flow1", "Flow2", "FlowC", "Temp_1", "Temp_2","Temp_3",
                # "ContTemp", "SupplyTemp", "LedTemp",
                "Stat_1", "Stat_2", "Stat_3", "Stat_4", "Stat_5", 
                # "Status", "ContStatus", "DetectStatus", "LedStatus", "ValveStatus", 
                "TapeAdvCount", "unclear_3", "unclear_4", "unclear_5", "unclear_6"
                # "ID_com1", "ID_com2", "ID_com3", "fields_i"
        )
        dtypes = [pl.Utf8] + [pl.Int64] + [pl.Utf8]*4 + [pl.Int64]*42 + [pl.Float64]*10 + [pl.Int64]*3 + [pl.Float64]*3 + [pl.Int64]*10

        try:
            source = zipfile.ZipFile(path).read(os.path.basename(path).replace('.zip', '.dat'))
            # df = pl.read_csv(source=source, 
            #                 has_header=False, 
            #                 separator=chr(0),
            #                 comment_char="#",
            #                 ).select(tmp=pl.col('column_1')
            #                 .str.split(sep)
            #                 # .list.to_struct(
            #                 #     n_field_strategy='max_width',
            #                 #     fields=lambda x:f"column_{x+1}")
            #                 ).unnest('tmp').with_columns(
            #                     pl.col('column_4')
            #                     .str.to_datetime(format='%m/%d/%Y %I:%M:%S %p', time_zone='UTC'))
            df = pl.read_csv(source=source, 
                            has_header=False, 
                            separator=sep,
                            comment_char="#",
                            dtypes=dtypes
                            ).with_columns(
                                pl.col('column_4')
                                .str.to_datetime(format='%m/%d/%Y %I:%M:%S %p')
                                )
            df.columns = cols
            # df = df.with_columns(pl.col(pl.Utf8).exclude(f"^(I|D|{dtm}).*$").cast(pl.Float32))

            return df, None
        except Exception as err:
            logger.error(err)
            return df, str(err)


    def zipfiles_to_parquet(self, source: str, target: str, dtm: str="dtm", archive: str=None, issues: str=None, append_parquet: bool=True, plot: bool=True, verbose: bool=True) -> tuple([pl.DataFrame, dict]):
        """Extract and compile AE33 zipfiles found in source and its sub-folders to polars DataFrame, save as parquet files in target. Optionally plot the data.

        Args:
            source (str): Path to directory to process. Sub-directories will also be considered.
            target (str): Path to directory where .parquet files will be stored.
            dtm (str, optional): Name of dateTime column. Defaults to 'dtm'
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            append_parquet (bool, optional): If True, append new data to an existing .parquet file. Defaults to True.
            plot (bool, optional): Should the resulting DataFrames be visualized? Defaults to True.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
        Returns:
            dict: name of files that could not be processed as well as errors encountered.
        """
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
                    tmp, err = self.extract_zipfile_to_dataframe(os.path.join(root, file))
                    if err:
                        errors.update({file: err})
                        if issues:
                            os.makedirs(issues, exist_ok=True)
                            dst = os.path.join(issues, file)
                            shutil.move(src=src, dst=dst)
                            print(f"issue: {src} > {dst}")
                    elif archive:
                        dst = os.path.join(archive, relative_path)
                        os.makedirs(dst, exist_ok=True)
                        shutil.move(src=src, dst=os.path.join(dst, file))
                    result = pl.concat([result, tmp], how='diagonal')

            if not result.is_empty:
                # create target directory if it doesn't yet exist
                os.makedirs(target, exist_ok=True)

                # if append_parquet==True, check if parquet already exists and append
                if append_parquet:
                    file = os.path.join(target, "ae33.parquet")
                    if os.path.exists(file):
                        df = pl.read_parquet(source=file)
                        result = pl.concat([df, result], how='diagonal')

                    # remove duplicates, sort data
                    result = result.unique()
                    result = result.sort(dtm)
        
                    # store result as parquet file
                    result.write_parquet(file)

                # plot data
                if plot:
                    self.plot_aethalometer_data(df=result)

            if errors:
                # create target directoriy if it doesn't yet exist
                os.makedirs(target, exist_ok=True)
                # write errors to json file (append if it exists already)
                with open(os.path.join(target, "ae33.errors.json"), "a") as fh:
                    json.dump(errors, fh)

            return result, errors

        except Exception as err:
            logger.error(err)
            print(err)


    def plot_aethalometer_data(self, df: pl.DataFrame, variable: str="eBC", dtm: str="dtm", start:str=None, end:str=None, title:str="Magee Scientific AE33", ylim=None) -> None:
        """Plot a polars DataFrame containing nephelometer data.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            variable (str): ...
            dtm (str, optional): name of dateTime column. Defaults to 'dtm'.
            start (str): start dateTime, default format is '%Y-%m-%d %H:%M:%S', possibly simplified.
            end (str): end  dateTime, default format is '%Y-%m-%d %H:%M:%S', possibly simplified.
            title (str): Title of plot. Defaults to "Magee Scientific AE33"
        """
        try:
            df = df.sort(dtm)

            if start:
                df = df.filter(pl.col(dtm) >= pl.lit(start).str.strptime(pl.Date))
            if end:
                df = df.filter(pl.col(dtm) <= pl.lit(end).str.strptime(pl.Date))

            if variable=="eBC":
                variable = "BC"
                subtitle = "Equivalent Black Carbon Concentration"
                ylabel = "(ng/m3)"
                legend = ('370 nm', '470 nm', '521 nm', '590 nm', '660 nm', '880 nm', '950 nm')
                # __df = df
            else:
                raise ValueError(f"Type not recognized (source: plot_aethalometer_data)")
            
            c = ('purple', 'darkblue', 'blue', 'green', 'gold', 'orange', 'red')
            plt.figure(figsize=(12, 6))
            for i in range(1, 8):
                plt.scatter(df[dtm], df[f"{variable}{i}"], c=c[i-1], marker="o", s=2)

            # for i in range(1, 8):
            #     plt.scatter(df.filter(pl.col(f"flags_BC{i}")>0)[dtm], df.filter(pl.col(f"flags_BC{i}")>0)[f"flags_BC{i}"], c="black", marker="o", s=2)

            if ylim:
                plt.ylim(ylim)
            plt.legend(legend)
            plt.suptitle(title)
            plt.title(subtitle)
            plt.xlabel(dtm)
            plt.ylabel(ylabel)
            plt.show()
        except Exception as err:
            logger.error(err)
            print(err)


    def remove_extremes(self, df: pl.DataFrame, q=0.00001) -> tuple([pl.DataFrame, dict]):
        """Remove extreme BC values from polars DataFrame. Extremes are defined using quantiles.

        Args:
            df (pl.DataFrame): AE33 nephelometer data
            q (float, optional): Quantile defining extreme values, i.e., values outside [>=q, <=(1-q)]. Defaults to 0.00001.

        Returns:
            pl.DataFrame: polars DataFrame of data that are retained
            dict: cutoffs giving the lower and upper boundaries

        [TODO] Instead of removing the extremes from the dataframe, it would be better to flag them
        """
        cutoffs = dict()
        try:
            N = range(1, 8)
            for n in N:
                lower = df[f"BC{n}"].quantile(q)
                upper = df[f"BC{n}"].quantile(1-q)
                df = df.filter((pl.col(f"BC{n}") >= lower) & (pl.col(f"BC{n}") <= upper))
                cutoffs[f"BC{n}"] = {'lower': lower, 'upper': upper}
            return df, cutoffs

        except Exception as err:
            logger.error(err)
            print(err)


    def flag_spurious_data(self, df: pl.DataFrame, flag_col="flags", spurious_zero_wiggle=0.01, consecutive_threshold=2) -> pl.DataFrame:
        """
        Flag spurious zero BC data.

        Parameters:
        - df: polars DataFrame
        - value_threshold: threshold for considering values around zero (default: 0)
        - consecutive_threshold: threshold for consecutive occurrences (default: 2)

        Returns:
        - polars DataFrame with an additional 'spurious_flag' column
        """

        spurious_flags = []

        column_names = [f"BC{i}" for i in range(1, 8)]

        for column in column_names:
            # Identify spurious data based on the specified thresholds
            spurious_mask = (
                (df[column] <= spurious_zero_wiggle) & (df[column] >= -spurious_zero_wiggle)
                & (df[column].shift(-1) > spurious_zero_wiggle)
                & (df[column].shift(consecutive_threshold) > spurious_zero_wiggle) 
            # )
            ) | (
                (df[column] <= spurious_zero_wiggle) & (df[column] >= -spurious_zero_wiggle)
                & (df[column].shift(1) > spurious_zero_wiggle)
                & (df[column].shift(-consecutive_threshold) > spurious_zero_wiggle)
            )

            # spurious_flags.append(spurious_mask)

            # Create a new column 'spurious_flag' in the DataFrame
            df = df.hstack([pl.Series(f"{flag_col}_{column}", spurious_mask)])

        return df

# ae33 = AE33()
# path = "/home/zue/users/jkl/Public/git/gawkenya/data/ae33/ae33-202310190000.zip"
# df, err = ae33.extract_zipfile_to_dataframe(path)
# print(df.schema)

# years = ["2022", "2023"]
# for year in years:
#     source = os.path.join("/product_data/data/pay/Kenya/MKN/incoming/ae33/data", year)
#     target = os.path.join("results", "ae33", year)
#     df, err = ae33.zipfiles_to_parquet(source=source, target=target)
#     print(err)
# print("done")