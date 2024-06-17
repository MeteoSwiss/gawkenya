# %%
import os
import io
import logging
# from asyncio.log import logger
import glob
import json
import matplotlib as plt
import polars as pl
import re
import shutil
import zipfile

# %%
class Thermo:

    def __init__(self, log: str='thermo.log'):
        try:
            if log != "thermo.log":
                os.makedirs(os.path.dirname(log), exist_ok=True)
            self.logger = logging.getLogger(__name__)
            # logging.basicConfig(filename=log, filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            log_handler = logging.FileHandler(filename=log, mode="a", encoding="utf8")
            log_handler.setLevel(logging.DEBUG)
            log_handler.setFormatter("%(asctime)s %(levelname)s %(message)s")
            self.logger.addHandler(log_handler)

            self.dtypes = {'tei49c': [pl.Utf8]*4 + [pl.Float64]*1 + [pl.Utf8]*1 + [pl.Int64]*2 + [pl.Float64]*6,
                           'tei49i': [pl.Utf8]*5 + [pl.Float64]*2 + [pl.Int64]*2 + [pl.Float64]*6,}
            self.logger.info("Class 'Thermo' initialized successfully.")

        except Exception as err:
            self.logger = logging.getLogger(__name__)
            self.logger.error("Error initializing class 'Thermo'.", err)


    def extract_thermo_to_dataframe(self, file: str, dtm="dtm", log=True) -> tuple([pl.DataFrame, str, str]):
        """
        Extract a Thermo file into a Polars dataframe.

        Args:
            file (str): full path to file.
            dtm (str): Name for dateTime column to be generated.
            log (bln): Should activities be logged to 'thermo.log'? Defaults to True.

        Returns:
            pl.DataFrame: DataFrame with DateTime and source columns added to data
            str: Errors encountered
            str: File (=instrument) type
        """
        file_type = "tei49c" if bool(re.search("tei49c", file)) else "tei49i" if bool(re.search("tei49i", file)) else "unknown"

        if bool(re.search(file_type, file)):
            if log:
                self.logger.info(f"Extracting file {file}.")

            try:
                if bool(re.search('.zip', file)):
                    with zipfile.ZipFile(file, 'r') as zf:
                        with zf.open(zf.namelist()[0]) as fh:
                            content = fh.read().decode('utf-8')
                    # df = pl.read_csv(source=zf.open(zf.namelist()[0]).read(), has_header=True, separator=" ", skip_rows=0, null_values='/', dtypes=self.dtypes[file_type])
                else:
                    with open(file, 'r') as fh:
                        content = fh.read()
                    # df = pl.read_csv(source=file, has_header=True, separator=" ", skip_rows=0, null_values='/', dtypes=self.dtypes[file_type])

                # Split the content into lines
                lines = content.splitlines()
                
                # Process the header, replace multiple spaces with a single space
                header = lines[0].replace('  ', ' ')
                
                # Join the processed header with the rest of the lines
                corrected_content = '\n'.join([header] + lines[1:])
                
                # Read the corrected content into a Polars DataFrame
                df = pl.read_csv(source=io.StringIO(corrected_content), has_header=True, separator=" ", skip_rows=0, null_values='/', dtypes=self.dtypes[file_type])

            except:
                df = pl.DataFrame()
                pass

            try:
                if "hio3" in df.columns:
                    df = df.drop("hio3")
                
                df = df.with_columns(pl.lit(file).alias('source'),
                                     pl.format("{} {}", "pcdate", "pctime").str.to_datetime(time_zone="UTC").dt.round("1m").alias(dtm))

                return df, None, file_type

            except Exception as err:
                self.logger.error(err)
                return pl.DataFrame(), str(err), None


    def compile_thermo_to_parquet(self, source: str, target: str, dtm="dtm", archive: str=None, issues: str=None, append_parquet: bool=True, verbose: bool=True, log: bool=True) -> None:
        """Extract and compile Thermo bulletins found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

        Args:
            source (str): Root path to directory to process. <base> will be appended to path. Sub-directories will also be considered.
            target (str): Root path to directory where .parquet files will be stored.  <base> will be appended to path.
            dtm (str): Name of dateTime column.
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
            log (bool, optional): Should activities be logged? Defaults to True.
        Returns:
            Nothing
        """
        # source = os.path.join(source, base)
        # target = os.path.join(target, base)
        os.makedirs(target, exist_ok=True)
        if archive:
            archive = os.path.join(archive)

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
                        print(f"> Processing {file} ...")
                    src = os.path.join(root, file)
                    tmp, err, file_type = self.extract_thermo_to_dataframe(src, log=log)
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

                # clean up iffolder is empty
                if not os.listdir(root):
                    os.rmdir(root)

            if not result.is_empty():
                parquet = os.path.join(target, f"{file_type}.parquet")
                if append_parquet:                    
                    # avoid over-writing an existing parquet file
                    if os.path.exists(parquet):
                        df = pl.read_parquet(source=parquet)
                        result = pl.concat([df, result], how='diagonal')
                
                # remove duplicates, sort data
                result = result.unique()
                result = result.sort(dtm)

                # store result as parquet file
                result.write_parquet(parquet)

            # write errors to json file
            if errors:
                with open(os.path.join(target, f"{file_type}.errors.json"), "w") as fh:
                    json.dump(errors, fh)

            # return result, errors
            return None

        except Exception as err:
            self.logger.error(err)
            print(err)


    def remove_extremes(self, df: pl.DataFrame, variable: str, q=0.001) -> tuple([pl.DataFrame, dict]):
        """Remove extreme values from polars DataFrame. Extremes are defined using quantiles.

        Args:
            df (pl.DataFrame): Thermo data
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


    def plot_data(self, df: pl.DataFrame, dtm: str="dtm", variable: str="o3", start:str=None, end:str=None, title:str="Thermo Data", ylim=None) -> None:
        """Plot a polars DataFrame containing Thermo data.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            dtm (str, optional): name of dateTime variable
            variable (str): ...
            start (str): ...
            end (str): ...
            title (str): Title of plot. Defaults to "Thermo Data"
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


    # def extract_file(self, file: str, log=True) -> pd.DataFrame:
    #     """
    #     Open a file, determine its type from the file name, then extract content into a Pandas dataframe.

    #     Args:
    #         file (str): full path to file.
    #         log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
    #     """
    #     try:
    #         msg = f"Extracting file {file}."
    #         if log:
    #             logger.info(msg)
    
    #         # df = pd.DataFrame()

    #         if bool(re.search('.zip', file)):
    #             zf = zipfile.ZipFile(file)
    #             tmp = zf.open(zf.namelist()[0])
    #             df = pd.read_csv(tmp, sep="\s+")
    #         else:
    #             df = pd.read_csv(file, sep="\s+", engine='python')

    #         df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'], format="%Y-%m-%d %H:%M:%S")
    #         df['source'] = file
    #         if 'hio3' in df.columns:
    #             df.drop(columns='hio3', inplace=True)
    #         df.set_index('dtm', inplace=True)

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

    
    # def extract_files(self, path: str, pattern=["tei49c", "tei49i"], recursive=False, archive=None, remove_duplicates=True, save=None, log=True) -> pd.DataFrame:
    #     """
    #     Scan a directory and combine file content into a Pandas dataframe.

    #     Args:
    #         path (str): path to directory.
    #         recursive (bln): Should sub-directories be considered? Defaults to False.
    #         pattern (list): Pattern for recognition of bulletin files. Defaults to ["tei49c", "tei49i"]
    #         archive (str): If specified, files are moved to <path>/<archive>. Defaults to None.
    #         remove_duplicates (bln): Remove duplicates found in resulting data frame? Defaults to True.
    #         save (str): If one of ["csv", "json", "pkl"], resulting data frame is persisted to file. Defaults to None.
    #         log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
    #     """
    #     try:
    #         msg = f"Extracting files found at '{path}' with pattern '{pattern}' ..."
    #         if log:
    #             logger.info(msg)
    
    #         df = pd.DataFrame()

    #         for p in pattern:
    #             if recursive:
    #                 pathname = os.path.join(path, f"**/{p}")
    #             else:
    #                 pathname = os.path.join(path, f"{p}")
    #             files = glob.glob(pathname=pathname, recursive=recursive) 
    #             msg = f"Found {len(files)} files to extract and combine."
    #             if log:
    #                 logger.info(msg)

    #             for file in files:
    #                 df = pd.concat([df, self.extract_file(file=file, log=log)])
    #                 if archive:
    #                     dst = file.replace("incoming", "archive")
    #                     os.makedirs(os.path.dirname(dst), exist_ok=True)
    #                     shutil.move(src=file, dst=dst)

    #             if remove_duplicates:
    #                 numrows = len(df)
    #                 df.drop_duplicates(subset=df.columns[df.columns != "source"], inplace=True)
    #                 if len(df) < numrows:
    #                     logger.info(f"{numrows-len(df)} duplicate entries were found and removed.")

    #             if save:
    #                 dst = os.path.join(path, f"{p}-{time.strftime('%Y%m%d%H%M%S')}.{save}")
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

    #         return df

    #     except Exception as err:
    #         logger.error(err)
    #         return pd.DataFrame()


    def undo_archiving(self, path, archive="archive", recursive=True, log=True):
        try:
            pathname = os.path.join(path, "**", archive, "*")
            files = glob.glob(pathname=pathname, recursive=recursive) 
            msg = f"Found {len(files)} files to un-archive."
            if log:
                self.logger.info(msg)

            for file in files:
                dst = os.path.join(os.path.dirname(os.path.dirname(file)), os.path.basename(file))
                shutil.move(src=file, dst=dst)
        except Exception as err:
            self.logger.error(err)

           

if __name__ == "__main__":
    pass


#         res = df2sqlite.df2sqlite(df, db, tbl)

#     except Exception as err:
#         print(err)

# # %%
# def thermo2sqlite2(source, db: str, tbl: str):
#     try:
#         if "http" in source:
#             obj = mchfilebrowser.download_url(source)
#             df = pd.read_csv(obj, sep="\s+", engine='python')
#         else:
#             df = pd.read_csv(source, sep="\s+", engine='python')
#             df.reset_index(inplace=True)
#         if "level_0" in df.columns:
#             df.rename(columns={'level_0': 'pcdate', 'level_1': 'pctime'}, inplace=True)
#         if "pcdate" in df.columns:
#             df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'])
#         else:
#             df['dtm'] = pd.to_datetime(df['date'] + ' ' + df['time'])
#         df['source'] = source
#         if 'hio3' in df.columns:
#             df.drop(columns='hio3', inplace=True)
#         if 'o3lt' in df.columns:
#             df.drop(columns='o3lt', inplace=True)
#         df.set_index('dtm', inplace=True)
#         if 'index' in df.columns:
#             df.drop(columns='index', inplace=True)
#         res = df2sqlite.df2sqlite(df, db, tbl)

#     except Exception as err:
#         print(err)


# # %%
# def zip2sqlite(file: str, db: str, tbl: str, year=None):
#     try:
#         if "tei49c" in tbl:
#             if year is None:
#                 raise ValueError("'year' must be specified.")
#             else:
#                 year = year + "-"
#         with zipfile.ZipFile(file=file, mode="r") as zf:
#             for file in zf.namelist():
#                 if tbl in file:
#                     print(f"Processing {file} ...")
#                     with zf.open(file, mode="r") as obj:
#                         df = pd.read_csv(obj, sep="\s+", engine='python')
#                         df.reset_index(inplace=True)
#                         if "level_0" in df.columns:
#                             df.rename(columns={'level_0': 'pcdate', 'level_1': 'pctime'}, inplace=True)
#                         if "pcdate" in df.columns:
#                             df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'])
#                         else:
#                             if "tei49c" in tbl:
#                                 df['dtm'] = pd.to_datetime(year + df['date'] + ' ' + df['time'])
#                             else:
#                                 df['dtm'] = pd.to_datetime(df['date'] + ' ' + df['time'])
#                         df['source'] = os.path.join(archive, file)
#                         if 'hio3' in df.columns:
#                             df.drop(columns='hio3', inplace=True)
#                         if 'o3lt' in df.columns:
#                             df.drop(columns='o3lt', inplace=True)
#                         df.set_index('dtm', inplace=True)
#                         if 'index' in df.columns:
#                             df.drop(columns='index', inplace=True)
#                         res = df2sqlite.df2sqlite(df, db, tbl)
#     except Exception as err:
#         print(err)

# # %% download and process files from pay-data
# base_url = "https://hub.meteoswiss.ch/filebrowser/pay-data/data/pay/Kenya/MKN/incoming//tei49c/"
# file_urls = mchfilebrowser.get_urls_from_filebrowser(url=base_url, pattern="tei49c.+zip")
# target = "C:/Users/localadmin/Documents/git/gawkenya/data/thermo/tei49c"
# root = "C:/Users/localadmin/Documents/"
# db = os.path.join(root, "data/mkn.sqlite")
# tbl = "tei49c"

# for file_url in file_urls:
#     print(f"Downloading {file_url}")
#     obj = mchfilebrowser.download_url(file_url)
#     df = pd.read_csv(obj, sep="\s+", engine="python")
#     df.drop('o3lt', axis=1, inplace=True)
#     df2sqlite.df2sqlite(df=df, db=db, tbl=tbl)

# # %% process files copied directly from minix
# root = "C:/Users/localadmin/Documents/"
# db = os.path.join(root, "data/mkn.sqlite")

# # %% tei49c
# tbl = "tei49c"
# folder = os.path.join(root, "data/minix/thermo/", tbl)
# # archive = os.path.join(folder, "2021.zip")
# # zip2sqlite(file=archive, db=db, tbl=tbl, year="2021")

# # archive = os.path.join(folder, "2022.zip")
# # zip2sqlite(file=archive, db=db, tbl=tbl, year="2022")

# archive = os.path.join(folder, "tei49c-20221123.zip")
# zip2sqlite(file=archive, db=db, tbl=tbl, year="2022")

# # %% tei49i
# tbl = "tei49i"
# folder = os.path.join(root, "data/minix/thermo/", tbl)

# # archive = os.path.join(folder "tei49i_all_lrec-20220719102005.zip")
# archive = os.path.join(folder, "tei49i-20221123.zip")
# zip2sqlite(archive, db, tbl)

# # %% tei49i_2
# tbl = "tei49i_2"
# folder = os.path.join(root, "data/minix/thermo/", tbl)

# archive = os.path.join(folder, "tei49i_2-20221123.zip")
# zip2sqlite(archive, db, tbl)


#   # %% don't run
# import os
# import re

# def remove_echo(file: str, echo=r"lrec\s\n"):
#     try:
#         with open(file, "rt") as fh:
#             content = fh.read()
#             if re.search(echo, content):
#                 print(file)
#                 content = re.sub(echo, "", content)
#                 fh.close()
#                 with open(file, "wt") as fh:
#                     fh.write(content)
#         fh.close()

#     except Exception as err:
#         print(err)

# path = "C:/Users/localadmin/Documents/data/minix/thermo/tei49c/11/"
# files = os.listdir(path)
# for file in files:
#     remove_echo(f"{path}/{file}")
# # %%
