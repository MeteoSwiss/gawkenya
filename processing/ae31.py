import polars as pl
from pathlib import Path
from io import BytesIO
import zipfile
import logging
import re
from charset_normalizer import from_path
from processing.instrument import Instrument, pl_simplify_dtypes
from datetime import datetime

AE31_HEADER = [
    'B470', 'B470_1', 'B470_2', 'B470_3', 'B470_4', 'B470_5', 'B470_6',
    'G520', 'G520_1', 'G520_2', 'G520_3', 'G520_4', 'G520_5', 'G520_6',
    'IR880', 'IR880_1', 'IR880_2', 'IR880_3', 'IR880_4', 'IR880_5', 'IR880_6',
    'IR950', 'IR950_1', 'IR950_2', 'IR950_3', 'IR950_4', 'IR950_5', 'IR950_6',
    'R660', 'R660_1', 'R660_2', 'R660_3', 'R660_4', 'R660_5', 'R660_6',
    'UV370', 'UV370_1', 'UV370_2', 'UV370_3', 'UV370_4', 'UV370_5', 'UV370_6',
    'Y590', 'Y590_1', 'Y590_2', 'Y590_3', 'Y590_4', 'Y590_5', 'Y590_6',
    'date', 'dtm', 'flow', 'id', 'time'
]

def is_datetime(string: str) -> bool:
    try:
        datetime.strptime(string.strip(), "%Y-%m-%dT%H:%M:%S")
        return True
    except ValueError:
        return False

class AE31(Instrument):
    def __init__(self, name: str = "ae31") -> None:
        super().__init__(name=name)

    def extract_to_dataframe(self, path: Path, dtm: str = "dtm") -> tuple[pl.DataFrame, str | None, str]:
        """
        Extract data from a AE31 file (.dat, .csv, .txt, or .zip) to a Polars DataFrame.

        Args:
            path (Path): Full path to data file.
            dtm (str): Name of datetime column.

        Returns:
            tuple: (DataFrame, error string if any, file type string)
        """
        df = pl.DataFrame()
        file_type = "unknown"

        try:
            # Extract raw content
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as z:
                    data_files = [f for f in z.namelist() if f.endswith(('.dat', '.csv', '.txt'))]
                    if not data_files:
                        raise ValueError("No data files found in the zip archive.")
                    if len(data_files) > 1:
                        raise ValueError("More than 1 file found in the zip archive.")
                    name = data_files[0]
                    raw = z.read(name)
            else:
                raw = path.read_bytes()

            # Detect encoding and decode
            result = from_path(path).best()
            encoding = result.encoding if result else "utf-8"
            text = raw.decode(encoding)
            lines = text.splitlines()

            if not lines or all(not line.strip() for line in lines):
                raise ValueError("File is empty or only contains whitespace")

            first_row = lines[0].strip().split(",")
            
            if is_datetime(first_row[0]):
                skip_rows = 0
                new_columns = AE31_HEADER
            else:
                skip_rows = 1
                new_columns = [h.strip() for h in first_row if h.strip()]

            df = pl.read_csv(
                BytesIO(text.encode("utf-8")),
                separator=",",
                has_header=False,
                skip_rows=skip_rows,
                new_columns=new_columns,
                try_parse_dates=True
            )

            if "Date" in df.columns and "Time" in df.columns:
                df = df.with_columns(
                    (pl.col("Date") + " " + pl.col("Time")).str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S").alias(dtm)
                )

            elif dtm not in df.columns:
                raise ValueError("No datetime column found")

            df = pl_simplify_dtypes(df)
            return df, None, "ae31"

        except Exception as e:
            self.logger.error(f"Failed to extract {path.name}: {e}")
            return df, str(e), file_type


# from pathlib import Path
# import polars as pl

# from toolbox.utils import pl_simplify_dtypes
# from processing.instrument import Instrument


# class AE31(Instrument):
#     """
#     Processor for Magee Scientific AE31 aethalometer data files.
#     Expects data in fixed-width columns with a timestamp field.
#     """

#     def __init__(self):
#         super().__init__(name="ae31")

#     def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None, str]:
#         """
#         Extracts AE31 .txt file into a Polars DataFrame.

#         Args:
#             path (Path): Path to the input text file.

#         Returns:
#             tuple: (DataFrame, error string or None, file type)
#         """
#         df = pl.DataFrame()
#         dtm = self.dtm

#         try:
#             df = pl.read_csv(
#                 source=path,
#                 separator="\t",
#                 skip_rows=0,
#                 comment_prefix="#",
#                 infer_schema_length=100,
#                 ignore_errors=True
#             )

#             # Look for a datetime column
#             datetime_col = next((c for c in df.columns if "datetime" in c.lower() or "date/time" in c.lower()), None)
#             if not datetime_col:
#                 raise ValueError("No datetime column found in AE31 file.")

#             df = df.rename({datetime_col: dtm})
#             df = df.with_columns(pl.col(dtm).str.to_datetime(format=None, time_unit="us", time_zone="UTC"))
#             df = pl_simplify_dtypes(df)
#             return df, None, "ae31"

#         except Exception as e:
#             self.logger.error(f"Failed to extract {path.name}: {e}")
#             return df, str(e), "ae31"

# import logging
# import os
# import re
# import shutil
# import tempfile
# import zipfile
# from datetime import datetime, timedelta
# from pathlib import Path

# import chardet
# import polars as pl


# class AE31:
#     config: dict
#     name: str

#     def __init__(self, config: dict, name='ae31'):
#         """Magee Scientific AE33 aethalometer data as produced by nrbdaq

#         Args:
#             config (dict): general configuration
#         """
#         self.logger: logging.Logger      # config['logging']
#         self.name: str
#         self.root: str                   # config['root']
#         self.incoming: str               # config['branches']['incoming']
#         self.archive: str                # config['branches']['archive']
#         self.issues: str                 # config['branches']['issues']

#         try:
#             # configure logging
#             _logger = f"{os.path.basename(config['logging'])}".split('.')[0]
#             self.logger = logging.getLogger(f"{_logger}.{__name__}")
#             self.logger.info("Initialize AE31")
            
#             self.name = name
#             self.root = config['root']
#             self.incoming = config['branches']['incoming']
#             self.archive = config['branches']['archive']
#             self.issues = config['branches']['issues']
            
#             # root = os.path.expanduser(config['root'])

#             # self.data_path = os.path.join(root, config['AE31']['data'])
#             # os.makedirs(self.data_path, exist_ok=True)
#         except Exception as err:
#             self.logger.error(err)
#             pass

    
#     def move_file(self, src: str, dst: str, split: str = "1mo") -> Path:
#         """create destination path and move file.

#         Args:
#             src (str): Full path to source file.
#             dst (str): Destination root path.
#             split (str, optional): File organization in dst. One of 'year|month|day'. Defaults to 'month'.

#         Returns:
#             Path: Full path to destination.
#         """
#         try:
#             src = Path(src)
#             match = re.search(r"-(\d{4})(\d{2})(\d{2})\d{2}\d{2}\.(zip|dat|csv|txt)$", src.name)

#             if not match:
#                 # print(f"shutil.move({src}, {Path(dst) / src.name}")
#                 shutil.move(src, Path(dst) / src.name)
#                 return Path(dst) / src.name  # Default case if no timestamp match

#             year, month, day = match.group(1, 2, 3)
#             dst = Path(dst) / year / month / day
#             split_map = {
#                 "1y": dst.parents[2],
#                 "1mo": dst.parent,
#                 "1d": dst,
#             }
#             dst = split_map.get(split, dst)
#             dst.mkdir(parents=True, exist_ok=True)

#             # print(f"shutil.move({src}, {Path(dst) / src.name}")
#             shutil.move(src, dst / src.name)            
#             self.logger.info(f"file moved: {src} > {dst / src.name}")
            
#             return dst / src.name
        
#         except Exception as err:
#             self.logger.error("move_file: %s produced exception: %s", src, err)
            

#     def read_csv_no_header(self, file_path: str, dtm: str='dtm') -> pl.DataFrame:
#         """Read an AE31 .csv file and return a pl.DataFrame

#             14.9.3  Data File Format - Seven wavelength Instruments 
#             The AE-3 series seven wavelength Aethalometers measure optical absorbance at seven optical wavelengths 
#             from 370 to 950 nm.  The data are reported on a single line written to disk as follows: 
#             Expanded Data Format:  “date”, “time”, UV [370 nm] result, Blue [470 nm] result, Green [520 nm] result, 
#             Yellow [590 nm] result, Red [660 nm] result, IR1 [880 nm, “standard BC”] result, IR2 [950 nm] result,  
#             #air flow (LPM), bypass fraction#, and then the following columns of data repeated for the seven 
#             measurement wavelengths: 
#             sensing zero signal, sensing beam signal, reference zero signal, reference beam signal, optical attenuation, 
#             air flow (LPM), bypass fraction.    
#             The 'air flow'and 'bypass fraction' columns are repeated to allow for easy visual identification of the 
#             separation between the seven sets of data columns. 
#             A typical line in the data file might look like: 
#             "24-jul-00","16:40", 610 , 604 , 605 , 612 , 617 , 611 , 641 , 
#             3.131, -.9812 , -.9814 , 1.1881 , 1.8384 , 1 , 6.4 , 
#             2.704 , -.9812 , -.9814 , 4.2483 , 2.7373 , 1 , 6.4 , 
#             2.45  , -.9812 , -.9814 , 2.1716 , 1.9438 , 1 , 6.4 , 
#             2.232 , -.9812 , -.9814 , 2.854 , 3.5259 , 1 , 6.4 , 
#             1.957 , -.9812 , -.9814 , 3.3428 , 2.596 , 1 , 6.4 , 
#             1.452  , -.9812 , -.9814 , 4.6719 , 3.3935 , 1 , 6.4 , 
#             1.396 , -.9812 , -.9814 , 2.705 , 2.438 , 1 , 6.4  
        
#         Args:
#             file (str): full path to file

#         Returns:
#             pl.DataFrame: dataframe with header
#         """
#         cols = [f"{dtm}","id","date","time","UV370","B470","G520","Y590","R660","IR880","IR950","flow",]# "bypass",]
#         # cols += ["?370", "sens_zero_370","sens_beam_370","ref_zero_370","ref_beam_370","att_370", ]#"flow_370", "bypass_370",] 
#         # cols += ["?470", "sens_zero_470","sens_beam_470","ref_zero_470","ref_beam_470","att_470", ]#"flow_470", "bypass_470",] 
#         # cols += ["?520", "sens_zero_520","sens_beam_520","ref_zero_520","ref_beam_520","att_520", ]#"flow_520", "bypass_520",] 
#         # cols += ["?590", "sens_zero_590","sens_beam_590","ref_zero_590","ref_beam_590","att_590", ]#"flow_590", "bypass_590",] 
#         # cols += ["?660", "sens_zero_660","sens_beam_660","ref_zero_660","ref_beam_660","att_660", ]#"flow_660", "bypass_660",] 
#         # cols += ["?880", "sens_zero_880","sens_beam_880","ref_zero_880","ref_beam_880","att_880", ]#"flow_880", "bypass_880",] 
#         # cols += ["?950", "sens_zero_950","sens_beam_950","ref_zero_950","ref_beam_950","att_950", ]#"flow_950", "bypass_950",] 
#         cols += ['UV370_1','UV370_2','UV370_3','UV370_4','UV370_5','UV370_6',]
#         cols += ['B470_1','B470_2','B470_3','B470_4','B470_5','B470_6',]
#         cols += ['G520_1','G520_2','G520_3','G520_4','G520_5','G520_6',]
#         cols += ['Y590_1','Y590_2','Y590_3','Y590_4','Y590_5','Y590_6',]
#         cols += ['R660_1','R660_2','R660_3','R660_4','R660_5','R660_6',]
#         cols += ['IR880_1','IR880_2','IR880_3','IR880_4','IR880_5','IR880_6',]
#         cols += ['IR950_1','IR950_2','IR950_3','IR950_4','IR950_5','IR950_6',]
#         df = pl.DataFrame()

#         try:
#             # with open(file, "r") as fh:
#             #     content = fh.read().replace(" ", "").encode()

#             df = pl.read_csv(file_path, has_header=False)
#             df = df.cast({pl.Int64: pl.Int32, pl.Float64: pl.Float32})
#             df.columns = cols
#             df = df.with_columns(pl.col(dtm).str.to_datetime(time_unit='us', time_zone='UTC'), 
#                                  pl.col("date").str.to_date("%d-%b-%y").dt.combine(pl.col("time").str.to_time("%H:%M")).alias("date_time"))

#             self.logger.info(f"{file_path} successfully read.")
            
#             return df
#         except Exception as err:
#             self.logger.error(err)
#             return pl.DataFrame()
            

#     def extract_to_dataframe(self, file_path: str, dtm: str='dtm') -> pl.DataFrame:
#         """
#         Read file and extract to pl.DataFrame.
        
#         Args:
#             file_path (str): Full path to the file.
#             dtm (str, optional): Name of the datetime column. Defaults to 'dtm'.

#         Returns:
#             pl.DataFrame: Processed DataFrame.
#         """
#         try:
#             # If the file is a ZIP file, extract it to a temporary file and process it
#             if zipfile.is_zipfile(file_path):
#                 with zipfile.ZipFile(file_path, 'r') as zip_file:
#                     data_files = [f for f in zip_file.namelist() if f.endswith(('.dat', '.csv', '.txt'))]
#                     if not data_files:
#                         raise ValueError("No data files found in the zip archive.")
#                     if len(data_files) > 1:
#                         raise ValueError("More than 1 file found in the zip archive.")

#                     # # Extract the single file to a temporary file
#                     # temp_file = tempfile.NamedTemporaryFile(delete=False)
#                     # with open(temp_file.name, 'wb') as fh:
#                     #     fh.write(zip_file.read(data_files[0]))

#                     # df = self.read_csv(temp_file.name, dtm)

#                     # os.remove(temp_file.name)

#                     with zip_file.open(name=data_files[0]) as fh:
#                         source = fh.read().decode('utf-8').replace(" ", "").encode()

#                     df = pl.read_csv(source)
#                     df = df.cast({pl.Int64: pl.Int32, pl.Float64: pl.Float32})
#                     df = df.with_columns(pl.col(dtm).str.to_datetime(time_unit='us', time_zone='UTC'), 
#                                         pl.col("date").str.to_date("%d-%b-%y").dt.combine(pl.col("time").str.to_time("%H:%M")).alias("date_time"))
#                 self.logger.info(f"{file_path} successfully read.")    

#                 return df

#             else:
#                 # If it's not a ZIP file, process it directly
#                 return self.read_csv_no_header(file_path=file_path)
        
#         except Exception as err:
#             self.logger.error("%s: %s", file_path, err)
#             return pl.DataFrame()


#     # def append_parquet(self, df: pl.DataFrame, target: Path, dtm: str="dtm",
#     #                    split: str="month", file_name: str="ae31.parquet") -> pl.DataFrame:
#     #     try:
#     #         assert split in {"year", "month", "day"}, "split must be 'year', 'month', or 'day'"

#     #         df = df.with_columns(pl.col(dtm).cast(pl.Datetime))
#     #         start_date, end_date = df[dtm].min().date(), df[dtm].max().date()
#     #         date_ranges = pl.date_range(start_date, end_date, interval="1d", eager=True)

#     #         for date in date_ranges:
#     #             year, month, day = str(date.year), f"{date.month:02d}", f"{date.day:02d}"
#     #             dst = target / year / month / day
#     #             split_map = {
#     #                 "year": dst.parents[2],
#     #                 "month": dst.parent,
#     #                 "day": dst,
#     #             }
#     #             dst = split_map.get(split, dst)
#     #             dst.mkdir(parents=True, exist_ok=True)

#     #             # if split == "year":
#     #             #     folder_path = folder_path.parents[2]
#     #             # elif split == "month":
#     #             #     folder_path = folder_path.parent

#     #             df_filtered = df.filter(
#     #                 (pl.col(dtm).dt.year() == date.year)
#     #                 & (split != "year" or (pl.col(dtm).dt.month() == date.month))
#     #                 & (split != "month" or (pl.col(dtm).dt.date() == date))
#     #             )   # [TODO] handle case where df extends across split?

#     #             file_path = dst / file_name
#     #             if file_path.exists():
#     #                 df_existing = pl.read_parquet(file_path)
#     #                 rows_existing = len(df_existing)
#     #                 df_combined = pl.concat([df_existing, df_filtered], how="diagonal").unique().sort(dtm)
#     #             else:
#     #                 rows_existing = 0
#     #                 df_combined = df_filtered.unique().sort(dtm)
#     #             rows_combined = len(df_combined)

#     #             df_combined.write_parquet(file_path)
            
#     #         self.logger.info(f"{file_path}: rows added: {rows_combined - rows_existing}")
#     #         return df_combined
#     #     except Exception as err:
#     #         self.logger.error("append_parquet: %s produced exception: %s", target / file_name, err)
#     #         return pl.DataFrame()


#     def split_and_save_parquet(self, df: pl.DataFrame, target: Path, file_name: str="ae31.parquet", split: str="1mo", dtm: str="dtm"):
#         try:
#             assert split in {"1y", "1mo", "1d"}, "split must be '1y', '1mo', or '1d'"

#             if dtm not in df.columns:
#                 raise ValueError("DataFrame must contain a 'dtm' column.")
            
#             df = df.sort(dtm)
#             df = df.with_columns(pl.col(dtm).dt.replace_time_zone(time_zone='UTC'))
            
#             if split == "1y":
#                 df = df.with_columns(df[dtm].dt.strftime("%Y").alias("folder"))
#             elif split == "1mo":
#                 df = df.with_columns(df[dtm].dt.strftime("%Y/%m").alias("folder"))
#             elif split == "1d":
#                 df = df.with_columns(df[dtm].dt.strftime("%Y/%m/%d").alias("folder"))
#             # else:
#             #     raise ValueError("Invalid split value. Choose from '1y', '1mo', or '1d'.")
            
#             # target_path = Path(target)
#             partitions = df.partition_by("folder", maintain_order=True)
#             for i, sub_df in enumerate(partitions):
#                 folder = sub_df["folder"].unique()[0]
#                 folder_path = target / folder
#                 folder_path.mkdir(parents=True, exist_ok=True)
#                 parquet_path = folder_path / file_name
                
#                 sub_df = sub_df.drop("folder")  # Drop 'folder' before merging
                
#                 if parquet_path.exists():
#                     existing_df = pl.read_parquet(parquet_path)
#                     existing_df = existing_df.with_columns(pl.col(dtm).dt.replace_time_zone(time_zone='UTC'))
#                     existing_df = pl.concat([existing_df, sub_df], how='diagonal')
#                     existing_df = existing_df.unique().sort(by=dtm)
#                     existing_df.write_parquet(parquet_path)
#                 else:
#                     sub_df.sort(by=dtm).write_parquet(parquet_path)

#         except Exception as err:
#             self.logger.error("split_and_save_parquet: %s produced exception: %s", target / file_name, err)
#             return pl.DataFrame()


#     def compile_data(self, source: str=str(), target: str=str(), file_name: str=str(),
#                                  move_processed_files: bool=True, archive: str=str(), issues: str=str(), 
#                                  split: str="1mo", dtm: str="dtm") -> Path:
#         """
#         Harvest a folder and its sub-folders, compile data into .parquet files, and organize them.
        
#         Args:
#             source (str, optional): Folder to harvest. Defaults to self.root / self.incoming / self.name.
#             target (str, optional): Folder for .parquet files. Defaults to 'data/level1'.
#             dtm (str, optional): Timestamp column name. Defaults to 'dtm'.
#             move_processed_files (bool, optional): Move processed files? Defaults to True.
#         """
#         try:
#             source = Path(source or (Path(self.root) / self.incoming / self.name))
#             archive = Path(archive or (Path(self.root) / self.archive / self.name))
#             issues = Path(issues or (Path(self.root) / self.issues / self.name))
#             target = Path(target or (Path(self.root) / target))
#             os.makedirs(archive, exist_ok=True)
#             os.makedirs(target, exist_ok=True)
#             os.makedirs(issues, exist_ok=True)

#             file_name = file_name or f"{self.name}.parquet"
#             if not source.exists():
#                 return

#             src = Path()
#             df = pl.DataFrame()
#             for root, dirs, files in os.walk(source):
#                 for file in files:
#                     _dst = issues  # Default destination
#                     src = Path(root) / file
#                     _df = self.extract_to_dataframe(file_path=src, dtm=dtm)

#                     if not _df.is_empty():
#                         # df = self.append_parquet(df=_df, target=target, dtm=dtm, split=split, file_name=file_name)
#                         try:
#                             df = pl.concat([df, _df], how='diagonal')
#                             if not df.is_empty():
#                                 _dst = archive  # Success
#                             else:
#                                 continue
#                         except:
#                             self.logger.error(f"compile_files_to_parquet: {file} could not be added to parquet.")
#                             pass
#                     if move_processed_files:
#                         dst = self.move_file(src=src, dst=_dst, split=split)
                
#             if not df.is_empty():
#                 # remove rows with all null entries and remove duplicates
#                 df = df.filter(~pl.all_horizontal(pl.all().is_null())).unique()
#                 df.sort(by=['date_time'])
#                 self.split_and_save_parquet(df=df, target=target, split=split, file_name=file_name)
#                 # df.write_parquet(os.path.join(target, f"{self.name}.parquet"))

#             if Path(root) != source:
#                 try:
#                     Path(root).rmdir()
#                 except OSError:
#                     pass

#             return df

#         except Exception as err:
#             self.logger.error("compile_files_to_parquet: file: %s produced error: %s", src, err)


#     def plot_data(self, filepath: str, save: bool=True):
#         self.logger.warning("Not implemented.")


#         # def read_csv(file_path: str, dtm: str='dtm', mappings: dict=self.mappings) -> pl.DataFrame:
#         #     """Helper function to read a CSV and handle headers."""
#         #     try:
#         #         with open(file_path, 'rb') as f:
#         #             raw_data = f.read()
#         #             encoding = chardet.detect(raw_data)['encoding']

#         #         # Read first row to check for header and ACOEM variable indicators
#         #         with open(file_path, 'r', encoding=encoding) as file:
#         #             first_row = file.readline().strip().split(',')

#         #         # Check if the first column contains a valid datetime or '37' header
#         #         if is_datetime(first_row[0]):
#         #             df = pl.read_csv(file_path, encoding=encoding, has_header=False, try_parse_dates=True)
#         #             df = df.rename({df.columns[0]: dtm})
#         #         elif first_row[0] == '37':
#         #             first_row[0] = dtm
#         #             first_row += ['operation', 'period']
#         #             df = pl.read_csv(file_path, encoding=encoding, has_header=False, skip_rows=1, try_parse_dates=True)
#         #             # df = df.with_columns(
#         #             #     pl.col(df.columns[0]).str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S").alias(dtm)
#         #             # )
#         #             mappings = dict(zip(df.columns, first_row))
#         #             df = df.rename(mappings)
#         #         elif first_row[0] == 'Date & Time':
#         #             # Aurora native format file
#         #             df = pl.read_csv(file_path, encoding=encoding, has_header=True, try_parse_dates=True)
#         #             mappings = dict(zip(mappings["aurora_name"].to_list(), mappings["aurora_id"].to_list()))
#         #             df = df.rename({col: str(mappings[col]) for col in df.columns if col in mappings})
#         #             df = df.rename({'1': 'dtm'})
                    
#         #         else:
#         #             return pl.DataFrame()

#         #         return pl_simplify_dtypes(df)

#         #     except Exception as err:
#         #         print(f"Error reading CSV: {err}")
#         #         return pl.DataFrame()

#         # def is_datetime(value: str) -> bool:
#         #     """Check if a string value can be parsed as a datetime."""
#         #     try:
#         #         datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
#         #         return True
#         #     except ValueError:
#         #         return False




# if __name__ == "__main__":
#     pass

