from pathlib import Path
import zipfile
import polars as pl
from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Thermo(Instrument):
    """
    Processor for Thermo ozone analyzer data files (49c and 49i).
    Automatically detects and parses files, supports .dat and .zip.
    """

    def __init__(self, name: str = "thermo"):
        super().__init__(name="thermo")
        self.name = name
        self.headers = {
            "tei49c": [
                "pcdate", "pctime", "time", "date", "o3", "flags",
                "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ],
            "tei49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ],
            "49i": [
                "pcdate", "pctime", "time", "date", "flags", "o3",
                "hio3", "cellai", "cellbi", "bncht", "lmpt", "o3lt",
                "flowa", "flowb", "pres"
            ]
        }
        self.dtypes = {
            'tei49c': [pl.Utf8]*4 + [pl.Float32]*1 + [pl.Utf8]*1 + [pl.Int32]*2 + [pl.Float32]*6,
            'tei49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
            '49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,
        }


    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None, str]:
        """
        Extracts data from a Thermo 49c or 49i .dat/.zip file into a Polars DataFrame.

        Args:
            path (Path): Path to the input data file.

        Returns:
            tuple: (DataFrame, error message or None, file type ['tei49c' | 'tei49i'])
        """
        df = pl.DataFrame()
        file_type = "49i" if "49i-" in path.name.lower() else "tei49c"
        expected_fields = len(self.headers[file_type])
        dtm = self.dtm

        try:
            # Read raw lines from file
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as archive:
                    name = archive.namelist()[0]
                    with archive.open(name) as f:
                        lines = f.read().decode("utf-8").splitlines()
            else:
                lines = path.read_text(encoding="utf-8").splitlines()

            # Find start of data and extract rows
            data_lines = []
            for line in lines:
                if line.lower().startswith("pcdate"):
                    continue  # skip header
                parts = line.strip().split()
                if len(parts) == expected_fields:
                    data_lines.append(parts)
                else:
                    self.logger.warning(f"{path.name} invalid row: {line.strip()}")

            if not data_lines:
                raise ValueError("No valid data records found.")

            df = pl.DataFrame(data_lines, schema=self.headers[file_type])

            # Convert columns to correct types
            df = df.cast(dict(zip(self.headers[file_type], self.dtypes[file_type])))

            # drop optional hio3 column if empty
            if "hio3" in df.columns and df["hio3"].null_count() == len(df):
                df = df.drop("hio3")

            df = df.with_columns([
                pl.lit(str(path)).alias("source"),
                pl.format("{} {}", "pcdate", "pctime")
                  .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
                  .dt.replace_time_zone("UTC")
                  .dt.with_time_unit("us")
                  .alias(dtm)
            ])
            df = pl_simplify_dtypes(df)

            return df, None, file_type

        except Exception as e:
            self.logger.error(f"Failed to extract {path.name}: {e}")
            return pl.DataFrame(), str(e), file_type

# import glob
# import io
# import json
# import logging
# import os
# import re
# import shutil
# import zipfile

# import matplotlib as plt
# import polars as pl

# from toolbox.utils import pl_simplify_dtypes


# class Thermo:
#     """
#     Class defining Thermo instruments as configured by a dictionary config. 
#     Presently, 'tei49c' (ozone) and 'tei49i' (ozone) are supported.
#     """
#     def __init__(self, config: dict=dict()):
#         try:
#             if config==dict():
#                 self.logger = logging.getLogger(__name__)
#                 self.headers = {'tei49c': 'pcdate pctime time date o3 flags cellai cellbi bncht lmpt o3lt flowa flowb pres'.split('.')[0],
#                                 'tei49i': 'pcdate pctime time date flags o3 hio3 cellai cellbi bncht lmpt o3lt flowa flowb pres'.split('.')[0],}
#             else:
#                 _logger = f"{config['logging']}".split('.')[0]
#                 self.logger = logging.getLogger(f"{_logger}.{__name__}")

#                 self.headers = {'tei49c': config['tei49c']['header'].split(),
#                                 'tei49i': config['tei49i']['header'].split(),}
#             self.dtypes = {'tei49c': [pl.Utf8]*4 + [pl.Float32]*1 + [pl.Utf8]*1 + [pl.Int32]*2 + [pl.Float32]*6,
#                         'tei49i': [pl.Utf8]*5 + [pl.Float32]*2 + [pl.Int32]*2 + [pl.Float32]*6,}
#             self.logger.info("Class 'Thermo' initialized successfully.")

#         except Exception as err:
#             self.logger = logging.getLogger(__name__)
#             self.logger.error("Error initializing class 'Thermo'.", err)


#     def extract_thermo_to_dataframe(self, file: str, dtm="dtm", log=True) -> tuple([pl.DataFrame, str, str]):
#         """
#         Extract a Thermo file into a Polars dataframe.

#         Args:
#             file (str): full path to file.
#             dtm (str): Name for dateTime column to be generated.
#             log (bln): Should activities be logged to 'thermo.log'? Defaults to True.

#         Returns:
#             pl.DataFrame: DataFrame with DateTime and source columns added to data
#             str: Errors encountered
#             str: File (=instrument) type
#         """
#         if not os.path.exists(file):
#             raise ValueError('File not found.')
        
#         file_type = 'tei49c' if 'tei49c' in file else 'tei49i' if 'tei49i' in file else 'unknown'
#         header = self.headers['tei49c'] if 'tei49c' in file else self.headers['tei49i'] if 'tei49i' in file else None
#         expected_number_of_items = None if file_type=='unknown' else len(header)

#         if file_type in file:
#             if log:
#                 self.logger.info(f"Extracting file {file}.")

#             try:
#                 if '.zip' in file:
#                     with zipfile.ZipFile(file, 'r') as zf:
#                         with zf.open(zf.namelist()[0]) as fh:
#                             lines = fh.read().decode('utf-8')
#                     lines = lines.splitlines()

#                 else:
#                     with open(file, 'r') as fh:
#                         lines = fh.readlines()

#                 # # Split the content into lines
#                 # lines = content.splitlines()
                
#                 # # Process the header, replace multiple spaces with a single space
#                 # header = lines[0].replace('  ', ' ')
                
#                 # # Join the processed header with the rest of the lines
#                 # corrected_content = '\n'.join([header] + lines[1:])
                
#                 # # Read the corrected content into a Polars DataFrame
#                 # df = pl.read_csv(source=io.StringIO(corrected_content), has_header=True, separator=" ", skip_rows=0, null_values='/', dtypes=self.dtypes[file_type])

#                 # # Read the file into a list of lines
#                 # with open(input_file, 'r') as f:
#                 #     lines = f.readlines()
                
#                 # Check for the header and split lines into columns
#                 for i, line in enumerate(lines):
#                     if line.strip().startswith("pcdate"):
#                         # header = line.strip().split()
#                         data_lines = lines[i+1:]
#                         break
                
#                 # if not header:
#                 #     raise ValueError("Header starting with 'pcdate' not found in the file.")
                
#                 # Separate valid and invalid records
#                 valid_records = []
#                 for line in data_lines:
#                     fields = line.strip().split()
#                     if len(fields) == expected_number_of_items and (expected_number_of_items is not None):
#                         valid_records.append(fields)
#                     else:
#                         self.logger.warning(f"{file} contains invalid record: {line.strip()}")
                               
#                 # Process valid records into a DataFrame
#                 if valid_records and (expected_number_of_items is not None):
#                     df = pl.DataFrame(valid_records, schema=header)
#                 elif valid_records:
#                     df = pl.DataFrame(valid_records)
#                 else:
#                     return df, None, file_type

#                 # # Combine pcdate and pctime into a single datetime column
#                 # df = df.with_columns(
#                 #     pl.concat_str([pl.col("pcdate"), pl.col("pctime")], separator=" ")
#                 #     .str.strptime(pl.Datetime, fmt="%Y-%m-%d %H:%M:%S")
#                 #     .alias("dtm")
#                 # )
                
#                 # # Convert numerical columns
#                 # for col in header:
#                 #     if col not in {"pcdate", "pctime"}:
#                 #         df = df.with_columns(
#                 #             pl.col(col)
#                 #             .cast(pl.Float32, strict=False)
#                 #             .cast(pl.Int32, strict=False)  # If cast fails, keep as float
#                 #         )
                
#                 # return df

#             except:
#                 df = pl.DataFrame()
#                 self.logger.warning(f"{file} could not be extracted.")
#                 pass

#             try:
#                 # drop hio3 if included in the dataframe
#                 if "hio3" in df.columns:
#                     df = df.drop("hio3")
                
#                 # create a proper dtm datetime stamp 
#                 df = df.with_columns(pl.lit(file).alias('source'),
#                                      pl.format("{} {}", "pcdate", "pctime").str.to_datetime(time_zone="UTC").dt.round("1m").alias(dtm))

#                 # simplify all dtypes
#                 df = pl_simplify_dtypes(df, digits=1)

#                 # # round data to 2 decimals
#                 # if 'o3' in df.columns:
#                 #     df = df.with_columns(pl.col('o3').round(2))

#                 return df, None, file_type

#             except Exception as err:
#                 self.logger.error(err)
#                 return pl.DataFrame(), str(err), None


#     def compile_thermo_to_parquet(self, source: str, target: str, dtm="dtm", archive: str=None, issues: str=None, append_parquet: bool=True, verbose: bool=True, log: bool=True) -> None:
#         """Extract and compile Thermo bulletins found in source and its sub-folders to monthly polars DataFrames, save as parquet files in target.

#         Args:
#             source (str): Root path to directory to process. <base> will be appended to path. Sub-directories will also be considered.
#             target (str): Root path to directory where .parquet files will be stored.  <base> will be appended to path.
#             dtm (str): Name of dateTime column.
#             archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
#             issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
#             verbose (bool, optional): Should information on process be written to console? Defaults to True.
#             log (bool, optional): Should activities be logged? Defaults to True.
#         Returns:
#             Nothing
#         """
#         result = pl.DataFrame()
#         errors = dict()      
#         try:
#             # process files
#             self.logger.info(f"processing source {source} ...")
#             for root, dirs, files in os.walk(source):
#                 n = (len(source) - len(root) + 1)
#                 relative_path = root[n:] if n < 0 else ""
#                 for file in files:
#                     self.logger.info(f"processing {file} ...")
#                     src = os.path.join(root, file)
#                     tmp, err, file_type = self.extract_thermo_to_dataframe(src, log=log)
#                     if err:
#                         errors.update({file: err})
#                         if issues:
#                             dst = os.path.join(issues, relative_path)
#                             os.makedirs(dst, exist_ok=True)
#                             shutil.move(src=src, dst=os.path.join(dst, file))
#                             self.logger.warning(f"issue: {src} > {dst}")
#                     elif archive:
#                         dst = os.path.join(archive, relative_path)
#                         os.makedirs(dst, exist_ok=True)
#                         shutil.move(src=src, dst=os.path.join(dst, file))
#                         self.logger.info(f"archive: {src} > {dst}")
#                     result = pl.concat([result, tmp], how='diagonal')

#                 # clean up if folder is empty
#                 if not os.listdir(root):
#                     os.rmdir(root)

#             if not result.is_empty():
#                 os.makedirs(target, exist_ok=True)
#                 parquet = os.path.join(target, f"{file_type}.parquet")
#                 if append_parquet:                    
#                     # avoid over-writing an existing parquet file
#                     if os.path.exists(parquet):
#                         df = pl.read_parquet(source=parquet)
#                         result = pl.concat([df, result], how='diagonal')
                
#                 # remove duplicates, sort data
#                 result = result.unique()
#                 result = result.sort(dtm)

#                 # store result as parquet file
#                 result.write_parquet(parquet)

#             # write errors to json file
#             if errors:
#                 with open(os.path.join(target, f"{file_type}.errors.json"), "w") as fh:
#                     json.dump(errors, fh)

#             # return result, errors
#             return None

#         except Exception as err:
#             self.logger.error(err)


#     def remove_extremes(self, df: pl.DataFrame, variable: str, q=0.001) -> tuple([pl.DataFrame, dict]):
#         """Remove extreme values from polars DataFrame. Extremes are defined using quantiles.

#         Args:
#             df (pl.DataFrame): Thermo data
#             q (float, optional): Quantile defining extreme values, i.e., values outside [>=q, <=(1-q)]. Defaults to 0.00001.

#         Returns:
#             pl.DataFrame: polars DataFrame of data that are retained
#             dict: cutoffs giving the lower and upper boundaries

#         [TODO] Instead of removing the extremes from the dataframe, it would be better to flag them. Also, use flags to filter first.
#         """
#         cutoffs = dict()
#         try:
#             lower = df[variable].quantile(q)
#             upper = df[variable].quantile(1-q)
#             df = df.filter((pl.col(variable) >= lower) & (pl.col(variable) <= upper))
#             cutoffs[variable] = {'lower': lower, 'upper': upper}
#             return df, cutoffs

#         except Exception as err:
#             print(err)


#     def plot_data(self, df: pl.DataFrame, dtm: str="dtm", variable: str="o3", start:str=None, end:str=None, title:str="Thermo Data", ylim=None) -> None:
#         """Plot a polars DataFrame containing Thermo data.

#         Args:
#             df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
#             dtm (str, optional): name of dateTime variable
#             variable (str): ...
#             start (str): ...
#             end (str): ...
#             title (str): Title of plot. Defaults to "Thermo Data"
#         """
#         try:
#             df = df.sort(dtm)

#             if start:
#                 df = df.filter(pl.col(dtm) >= pl.lit(start).str.strptime(pl.Date))
#             if end:
#                 df = df.filter(pl.col(dtm) <= pl.lit(end).str.strptime(pl.Date))

#             plt.figure(figsize=(12, 6))
#             plt.scatter(df[dtm], df[variable], c='blue', marker="o", s=2)

#             if ylim:
#                 plt.ylim(ylim)
#             # plt.legend(legend)
#             plt.suptitle(title)
#             # plt.title(subtitle)
#             plt.xlabel("DateTime")
#             plt.ylabel(variable)
#             plt.show()
#         except Exception as err:
#             print(err)


#     def compile_time_series(self, source: str, pattern: str="tei49c.parquet", dtm: str="dtm", simplify_dtypes: bool=True) -> pl.DataFrame:
#         try:
#             df = pl.DataFrame()
#             for root, dirs, files in os.walk(source):
#                 for file in files:
#                     if re.search(pattern=pattern, string=file):
#                         df_tmp = pl.read_parquet(os.path.join(root, file))
#                         if not df_tmp.is_empty():
#                             if simplify_dtypes:
#                                 df_tmp = pl_simplify_dtypes(df_tmp)
#                             df = pl.concat([df, df_tmp], how='diagonal')
#             df = df.sort(by=pl.col(dtm))
#             return df
#         except Exception as err:
#             print(err)


#     def extract_lrec_from_file(self, file_path: str) -> pl.DataFrame:
#         """
#         Reads the given data file and transforms it into a polars DataFrame.
        
#         - The first two columns (time and date) are retained.
#         - A 'dtm' column is created by combining time and date with UTC timezone.
#         - The 'hio3' column is dropped if present.
#         - Repeated column labels in data rows are removed.
#         - A new 'source' column is added with the file path.
#         - New columns 'pcdate' and 'pctime' are added with Null values.
        
#         :param file_path: Path to the data file.
#         :return: A polars DataFrame.
#         """
#         try:
#             # Read the raw lines
#             with open(file_path, 'r', encoding='utf-8') as f:
#                 lines = f.readlines()
            
#             # Extract column headers from the first data row (every second word after time/date)
#             first_row_parts = lines[0].strip().split()
#             headers = ['time', 'date'] + [first_row_parts[i] for i in range(2, len(first_row_parts), 2)]
            
#             # Read the file as a structured table
#             df = pl.read_csv(file_path, separator=" ", has_header=False)
            
#             # Drop columns containing header names
#             drop_cols = [f"column_{i}" for i in range(3, 24, 2)]
#             df = df.drop(drop_cols)

#             # # Ensure column count matches expectation
#             # expected_cols = 2 + len(headers)
#             # if df.width < expected_cols * 2:
#             #     raise ValueError("Unexpected column structure in the file.")
            
#             # # Keep only the first occurrence of each column (dropping repeated headers)
#             # df = df[:, :expected_cols]
                        
#             # Rename columns
#             df = df.rename(dict(zip(df.columns, headers)))
            
#             # Create 'dtm' column
#             df = df.with_columns(
#                 (pl.col("date") + " " + pl.col("time")).str.to_datetime("%m-%d-%y %H:%M", time_unit="us").alias("dtm")
#             )
            
#             # Drop the 'hio3' column if it exists
#             if "hio3" in df.columns:
#                 df = df.drop("hio3")
            
#             # Add 'source' column with the file path
#             df = df.with_columns(pl.lit(file_path).alias("source"))
            
#             # Add 'pcdate' and 'pctime' columns with Null values
#             df = df.with_columns(
#                 pl.lit('').cast(pl.Utf8).alias("pcdate"),
#                 pl.lit('').cast(pl.Utf8).alias("pctime")
#             )

#             # simplify all dtypes
#             df = pl_simplify_dtypes(df, digits=1)

#             return df

#         except Exception as err:
#             self.logger.error(err)
#             return pl.DataFrame()


#     # def extract_file(self, file: str, log=True) -> pd.DataFrame:
#     #     """
#     #     Open a file, determine its type from the file name, then extract content into a Pandas dataframe.

#     #     Args:
#     #         file (str): full path to file.
#     #         log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
#     #     """
#     #     try:
#     #         msg = f"Extracting file {file}."
#     #         if log:
#     #             logger.info(msg)
    
#     #         # df = pd.DataFrame()

#     #         if bool(re.search('.zip', file)):
#     #             zf = zipfile.ZipFile(file)
#     #             tmp = zf.open(zf.namelist()[0])
#     #             df = pd.read_csv(tmp, sep="\s+")
#     #         else:
#     #             df = pd.read_csv(file, sep="\s+", engine='python')

#     #         df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'], format="%Y-%m-%d %H:%M:%S")
#     #         df['source'] = file
#     #         if 'hio3' in df.columns:
#     #             df.drop(columns='hio3', inplace=True)
#     #         df.set_index('dtm', inplace=True)

#     #         if not df.empty:
#     #             for column in df:
#     #                 if df[column].dtype == 'float64':
#     #                     df[column] = pd.to_numeric(df[column], downcast='float')
#     #                 if df[column].dtype == 'int64':
#     #                     df[column] = pd.to_numeric(df[column], downcast='integer')
#     #         return df

#     #     except Exception as err:
#     #         logger.error(err)
#     #         return pd.DataFrame()

    
#     # def extract_files(self, path: str, pattern=["tei49c", "tei49i"], recursive=False, archive=None, remove_duplicates=True, save=None, log=True) -> pd.DataFrame:
#     #     """
#     #     Scan a directory and combine file content into a Pandas dataframe.

#     #     Args:
#     #         path (str): path to directory.
#     #         recursive (bln): Should sub-directories be considered? Defaults to False.
#     #         pattern (list): Pattern for recognition of bulletin files. Defaults to ["tei49c", "tei49i"]
#     #         archive (str): If specified, files are moved to <path>/<archive>. Defaults to None.
#     #         remove_duplicates (bln): Remove duplicates found in resulting data frame? Defaults to True.
#     #         save (str): If one of ["csv", "json", "pkl"], resulting data frame is persisted to file. Defaults to None.
#     #         log (bln): Should activities be logged to 'thermo.log'? Defaults to True.
#     #     """
#     #     try:
#     #         msg = f"Extracting files found at '{path}' with pattern '{pattern}' ..."
#     #         if log:
#     #             logger.info(msg)
    
#     #         df = pd.DataFrame()

#     #         for p in pattern:
#     #             if recursive:
#     #                 pathname = os.path.join(path, f"**/{p}")
#     #             else:
#     #                 pathname = os.path.join(path, f"{p}")
#     #             files = glob.glob(pathname=pathname, recursive=recursive) 
#     #             msg = f"Found {len(files)} files to extract and combine."
#     #             if log:
#     #                 logger.info(msg)

#     #             for file in files:
#     #                 df = pd.concat([df, self.extract_file(file=file, log=log)])
#     #                 if archive:
#     #                     dst = file.replace("incoming", "archive")
#     #                     os.makedirs(os.path.dirname(dst), exist_ok=True)
#     #                     shutil.move(src=file, dst=dst)

#     #             if remove_duplicates:
#     #                 numrows = len(df)
#     #                 df.drop_duplicates(subset=df.columns[df.columns != "source"], inplace=True)
#     #                 if len(df) < numrows:
#     #                     logger.info(f"{numrows-len(df)} duplicate entries were found and removed.")

#     #             if save:
#     #                 dst = os.path.join(path, f"{p}-{time.strftime('%Y%m%d%H%M%S')}.{save}")
#     #                 if save=="csv":
#     #                     df.to_csv(dst)
#     #                 elif save=="json":
#     #                     df.to_json(dst)
#     #                 elif save=="pickle":
#     #                     df.to_pickle(dst)
#     #                 else: 
#     #                     raise ValueError("'save' must be one of ['csv', 'json', 'pickle'].")
#     #                 if log:
#     #                     logger.info(f"Results saved in '{dst}'.")

#     #         return df

#     #     except Exception as err:
#     #         logger.error(err)
#     #         return pd.DataFrame()


#     def undo_archiving(self, path, archive="archive", recursive=True, log=True):
#         try:
#             pathname = os.path.join(path, "**", archive, "*")
#             files = glob.glob(pathname=pathname, recursive=recursive) 
#             msg = f"Found {len(files)} files to un-archive."
#             if log:
#                 self.logger.info(msg)

#             for file in files:
#                 dst = os.path.join(os.path.dirname(os.path.dirname(file)), os.path.basename(file))
#                 shutil.move(src=file, dst=dst)
#         except Exception as err:
#             self.logger.error(err)
   

# if __name__ == "__main__":
#     pass


# #         res = df2sqlite.df2sqlite(df, db, tbl)

# #     except Exception as err:
# #         print(err)

# # # %%
# # def thermo2sqlite2(source, db: str, tbl: str):
# #     try:
# #         if "http" in source:
# #             obj = mchfilebrowser.download_url(source)
# #             df = pd.read_csv(obj, sep="\s+", engine='python')
# #         else:
# #             df = pd.read_csv(source, sep="\s+", engine='python')
# #             df.reset_index(inplace=True)
# #         if "level_0" in df.columns:
# #             df.rename(columns={'level_0': 'pcdate', 'level_1': 'pctime'}, inplace=True)
# #         if "pcdate" in df.columns:
# #             df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'])
# #         else:
# #             df['dtm'] = pd.to_datetime(df['date'] + ' ' + df['time'])
# #         df['source'] = source
# #         if 'hio3' in df.columns:
# #             df.drop(columns='hio3', inplace=True)
# #         if 'o3lt' in df.columns:
# #             df.drop(columns='o3lt', inplace=True)
# #         df.set_index('dtm', inplace=True)
# #         if 'index' in df.columns:
# #             df.drop(columns='index', inplace=True)
# #         res = df2sqlite.df2sqlite(df, db, tbl)

# #     except Exception as err:
# #         print(err)


# # # %%
# # def zip2sqlite(file: str, db: str, tbl: str, year=None):
# #     try:
# #         if "tei49c" in tbl:
# #             if year is None:
# #                 raise ValueError("'year' must be specified.")
# #             else:
# #                 year = year + "-"
# #         with zipfile.ZipFile(file=file, mode="r") as zf:
# #             for file in zf.namelist():
# #                 if tbl in file:
# #                     print(f"Processing {file} ...")
# #                     with zf.open(file, mode="r") as obj:
# #                         df = pd.read_csv(obj, sep="\s+", engine='python')
# #                         df.reset_index(inplace=True)
# #                         if "level_0" in df.columns:
# #                             df.rename(columns={'level_0': 'pcdate', 'level_1': 'pctime'}, inplace=True)
# #                         if "pcdate" in df.columns:
# #                             df['dtm'] = pd.to_datetime(df['pcdate'] + ' ' + df['pctime'])
# #                         else:
# #                             if "tei49c" in tbl:
# #                                 df['dtm'] = pd.to_datetime(year + df['date'] + ' ' + df['time'])
# #                             else:
# #                                 df['dtm'] = pd.to_datetime(df['date'] + ' ' + df['time'])
# #                         df['source'] = os.path.join(archive, file)
# #                         if 'hio3' in df.columns:
# #                             df.drop(columns='hio3', inplace=True)
# #                         if 'o3lt' in df.columns:
# #                             df.drop(columns='o3lt', inplace=True)
# #                         df.set_index('dtm', inplace=True)
# #                         if 'index' in df.columns:
# #                             df.drop(columns='index', inplace=True)
# #                         res = df2sqlite.df2sqlite(df, db, tbl)
# #     except Exception as err:
# #         print(err)

# # # %% download and process files from pay-data
# # base_url = "https://hub.meteoswiss.ch/filebrowser/pay-data/data/pay/Kenya/MKN/incoming//tei49c/"
# # file_urls = mchfilebrowser.get_urls_from_filebrowser(url=base_url, pattern="tei49c.+zip")
# # target = "C:/Users/localadmin/Documents/git/gawkenya/data/thermo/tei49c"
# # root = "C:/Users/localadmin/Documents/"
# # db = os.path.join(root, "data/mkn.sqlite")
# # tbl = "tei49c"

# # for file_url in file_urls:
# #     print(f"Downloading {file_url}")
# #     obj = mchfilebrowser.download_url(file_url)
# #     df = pd.read_csv(obj, sep="\s+", engine="python")
# #     df.drop('o3lt', axis=1, inplace=True)
# #     df2sqlite.df2sqlite(df=df, db=db, tbl=tbl)

# # # %% process files copied directly from minix
# # root = "C:/Users/localadmin/Documents/"
# # db = os.path.join(root, "data/mkn.sqlite")

# # # %% tei49c
# # tbl = "tei49c"
# # folder = os.path.join(root, "data/minix/thermo/", tbl)
# # # archive = os.path.join(folder, "2021.zip")
# # # zip2sqlite(file=archive, db=db, tbl=tbl, year="2021")

# # # archive = os.path.join(folder, "2022.zip")
# # # zip2sqlite(file=archive, db=db, tbl=tbl, year="2022")

# # archive = os.path.join(folder, "tei49c-20221123.zip")
# # zip2sqlite(file=archive, db=db, tbl=tbl, year="2022")

# # # %% tei49i
# # tbl = "tei49i"
# # folder = os.path.join(root, "data/minix/thermo/", tbl)

# # # archive = os.path.join(folder "tei49i_all_lrec-20220719102005.zip")
# # archive = os.path.join(folder, "tei49i-20221123.zip")
# # zip2sqlite(archive, db, tbl)

# # # %% tei49i_2
# # tbl = "tei49i_2"
# # folder = os.path.join(root, "data/minix/thermo/", tbl)

# # archive = os.path.join(folder, "tei49i_2-20221123.zip")
# # zip2sqlite(archive, db, tbl)


# #   # %% don't run
# # import os
# # import re

# # def remove_echo(file: str, echo=r"lrec\s\n"):
# #     try:
# #         with open(file, "rt") as fh:
# #             content = fh.read()
# #             if re.search(echo, content):
# #                 print(file)
# #                 content = re.sub(echo, "", content)
# #                 fh.close()
# #                 with open(file, "wt") as fh:
# #                     fh.write(content)
# #         fh.close()

# #     except Exception as err:
# #         print(err)

# # path = "C:/Users/localadmin/Documents/data/minix/thermo/tei49c/11/"
# # files = os.listdir(path)
# # for file in files:
# #     remove_echo(f"{path}/{file}")
# # # %%
