# %%
import os
import logging
from asyncio.log import logger
import glob
import shutil
import time
import re
import zipfile
import pandas as pd
import sqlite3

# %%
class Thermo:

    def __init__(self, config=None):
        try:
            logger = logging.getLogger(__name__)
            logging.basicConfig(filename="thermo.log", filemode="a", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
            logger.info("Class 'Thermo' initialized successfully.")

            # assign variables
            self.config = config

        except Exception as err:
            logger = logging.getLogger(__name__)
            logger.error("Error initializing class 'Thermo'.", err)


    def extract_file(self, file: str, log=True) -> pd.DataFrame:
        """
        Open a file, determine its type from the file name, then extract content into a Pandas dataframe.

        Args:
            file (str): full path to file.
            log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
        """
        try:
            msg = f"Extracting file {file}."
            if log:
                logger.info(msg)
    
            # df = pd.DataFrame()

            if bool(re.search('.zip', file)):
                zf = zipfile.ZipFile(file)
                tmp = zf.open(zf.namelist()[0])
                df = pd.read_csv(tmp, sep="\s+")
            else:
                df = pd.read_csv(file, sep="\s+", engine='python')

            df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'], format="%Y-%m-%d %H:%M:%S")
            df['source'] = file
            if 'hio3' in df.columns:
                df.drop(columns='hio3', inplace=True)
            df.set_index('dtm', inplace=True)

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

    
    def extract_files(self, path: str, pattern=["tei49c", "tei49i"], recursive=False, archive=None, remove_duplicates=True, save=None, log=True) -> pd.DataFrame:
        """
        Scan a directory and combine file content into a Pandas dataframe.

        Args:
            path (str): path to directory.
            recursive (bln): Should sub-directories be considered? Defaults to False.
            pattern (list): Pattern for recognition of bulletin files. Defaults to ["tei49c", "tei49i"]
            archive (str): If specified, files are moved to <path>/<archive>. Defaults to None.
            remove_duplicates (bln): Remove duplicates found in resulting data frame? Defaults to True.
            save (str): If one of ["csv", "json", "pkl"], resulting data frame is persisted to file. Defaults to None.
            log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
        """
        try:
            msg = f"Extracting files found at '{path}' with pattern '{pattern}' ..."
            if log:
                logger.info(msg)
    
            df = pd.DataFrame()

            for p in pattern:
                if recursive:
                    pathname = os.path.join(path, f"**/{p}")
                else:
                    pathname = os.path.join(path, f"{p}")
                files = glob.glob(pathname=pathname, recursive=recursive) 
                msg = f"Found {len(files)} files to extract and combine."
                if log:
                    logger.info(msg)

                for file in files:
                    df = pd.concat([df, self.extract_file(file=file, log=log)])
                    if archive:
                        dst = file.replace("incoming", "archive")
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.move(src=file, dst=dst)

                if remove_duplicates:
                    numrows = len(df)
                    df.drop_duplicates(subset=df.columns[df.columns != "source"], inplace=True)
                    if len(df) < numrows:
                        logger.info(f"{numrows-len(df)} duplicate entries were found and removed.")

                if save:
                    dst = os.path.join(path, f"{p}-{time.strftime('%Y%m%d%H%M%S')}.{save}")
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

    def undo_archiving(self, path, archive="archive", recursive=True, log=True):
        try:
            pathname = os.path.join(path, "**", archive, "*")
            files = glob.glob(pathname=pathname, recursive=recursive) 
            msg = f"Found {len(files)} files to un-archive."
            if log:
                logger.info(msg)

            for file in files:
                dst = os.path.join(os.path.dirname(os.path.dirname(file)), os.path.basename(file))
                shutil.move(src=file, dst=dst)
        except Exception as err:
            logger.error(err)

           

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
