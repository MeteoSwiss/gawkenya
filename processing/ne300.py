import logging
import os
import shutil
import zipfile
from datetime import datetime

import numpy as np
import polars as pl

from toolbox.utils import pl_simplify_dtypes

MAPPINGS = pl.read_csv('cdp2_aurora_mappings.csv', has_header=True, dtypes=[pl.String]*4)

class NE300:
    config: dict
    name: str
    
    @classmethod
    def __init__(cls, config: dict, name: str='ne300'):
        """Initialize

        Args:
            config (dict): Configuration from config file
            name (str, optional): Instrument name, used in log files. Defaults to 'ne300'.
        """
        cls.logger: logging.Logger      # config['logging']
        cls.name: str
        cls.root: str                   # config['root']
        cls.incoming: str               # config['branches']['incoming']
        cls.archive: str                # config['branches']['archive']
        cls.issues: str                 # config['branches']['issues']
        cls.mappings: pl.DataFrame

        try:
            # configure logging
            _logger = f"{config['logging']}".split('.')[0]
            cls.logger = logging.getLogger(f"{_logger}.{__name__}")
            cls.logger.info("Initialize NE300 class.")
            
            cls.name = name
            cls.root = config['root']
            cls.incoming = config['branches']['incoming']
            cls.archive = config['branches']['archive']
            cls.issues = config['branches']['issues']

            cls.mappings = MAPPINGS
        except Exception as err:
            cls.logger.error(err)
            pass


    def extract_to_dataframe(self, file_path: str, dtm: str='dtm', log: bool=True) -> pl.DataFrame:
        """
        Read file and extract to pl.DataFrame.
        Files in native format, retrieved directly from the instrument (micrSD card or USB stick) have names that start with the serial number of the instrument, e.g., 00...
        Files generated with mkndaq have names that begin with ne300-... This is considered to be the default.
        If the files starts with '37', the first row is assumed to be a header row. In this case, the numbers indicate the ACOEM variable. 
        Otherwise, columns will be labeled 'col_1', 'col_2', etc. The first column will be labeled 'dtm' and an attempt will be made to convert it to a pl.Datetime.
        Headers from native files will also be converted to ACOEM numbers.
        All dtypes will be simplified as much as possible.
        
        Args:
            file_path (str): full path to file.
            dtm (str, optional): name of dateTime column. Defaults to 'dtm'.
            log (bool, optional): Should progress be logged? Defaults to True.

        Returns:
            pl.DataFrame: _description_
        """
        # Check and convert to bytes if necessary
        def ensure_bytes(column):
            if isinstance(column[0], str):
                return [x.encode() for x in column]  # Convert strings to bytes
            return column

        # Function to convert byte string to float
        def bytes_to_float(byte_array):
            byte_array = ensure_bytes(byte_array)  # Ensure all values are bytes
            bytes_np = np.frombuffer(b"".join(byte_array), dtype=np.uint32)
            return bytes_np.astype(np.float32)

        # Function to read CSV and handle header detection
        def read_csv(file, dtm: str='dtm'):
            """parse a csv object

            Args:
                file (IO[Byte]): _description_

            Returns:
                _type_: _description_
            """
            try:
                if 'ne300' in os.path.basename(file.name):
                    first_row = file.readline()
                    try:
                        first_row = first_row.decode('utf-8')
                    except:
                        pass
                    first_row = first_row.strip().split(',')
                    first_row += ['operation', 'period']
                    
                    # Check if the first element is a date or an integer 37
                    try:
                        # Try to parse the first element as a datetime
                        datetime.strptime(first_row[0], "%Y-%m-%d %H:%M:%S")
                        has_header = False  # No header, first column is a datetime
                        try:
                            df = pl.read_csv(file.name, has_header=has_header, try_parse_dates=True)
                        except:
                            df = pl.read_csv(file, has_header=has_header, try_parse_dates=True)
                        df = df.rename({df.columns[0]:dtm})
                    except ValueError:
                        # If it fails, check if the first element is '37'
                        if first_row[0] == '37':
                            first_row[0] = dtm
                            has_header = False #True  # The first row is a header
                            try:
                                df = pl.read_csv(file.name, has_header=has_header, try_parse_dates=True)
                            except:
                                # following throws a warning "Polars found a filename. Ensure you pass a path to the file instead of a python file object when possible for best performance."
                                df = pl.read_csv(file, has_header=has_header, try_parse_dates=True)
                            mappings = dict(zip(df.columns, first_row))
                            df = df.rename(mappings)
                        else:
                            # raise ValueError("Invalid file format: The first element is neither a datetime nor '37'.")
                            return pl.DataFrame()
                else:
                    # file is expected to originate from the instrument directly (microSD card or USB stick)
                    df = pl.read_csv(source=file.name, has_header=True, try_parse_dates=True)
                    _mappings = self.mappings.filter(pl.col('aurora_name').is_in(df.columns))
                    mapping = dict(zip(_mappings['aurora_name'], _mappings['aurora_id']))
                    df = df.rename(mapping=mapping)
                    df = df.rename({'1': dtm})
                    
                    # drop the empty column at the end
                    df.drop_in_place("")

                # Convert the 'operation' column byte string
                # df = df.with_columns(
                #     pl.Series("operation", bytes_to_float(df["operation"].to_list()))
                # )

                df = pl_simplify_dtypes(df)
                return df
            except Exception as err:
                print(err)
                return pl.DataFrame()

        try:
            # If the file is a ZIP file, read it from the archive
            if zipfile.is_zipfile(file_path):
                with zipfile.ZipFile(file_path, 'r') as zip_file:
                    # Get the first CSV file in the archive
                    csv_files = [f for f in zip_file.namelist() if f.endswith(('.dat', '.csv'))]
                    # del zip_file.namelist
                    if not csv_files:
                        raise ValueError("No CSV files found in the zip archive.")
                    with zip_file.open(csv_files[0]) as fh:
                        return read_csv(fh, dtm)
            
            # If it's not a ZIP file, process it directly
            else:
                with open(file_path, 'r') as fh:
                    return read_csv(fh, dtm)

                # # file expected to have been produced by mkndaq.py
                # if zipfile.is_zipfile(file):
                #     file = zipfile.ZipFile(file).read(os.path.basename(file.replace('.zip', '.dat')))
                #     first_row = file.decode().strip().split()[0]
                #     first_row = first_row.strip().split(',')
                # else:   
                #     with open(file, 'r') as fh:
                #         first_row = fh.readline().strip().split(',')

                # # check if the first element is a date or an integer 37
                # try:
                #     # try to parse the first element as a datetime
                #     datetime.strptime(first_row[0], "%Y-%m-%d %H:%M:%S")
                #     has_header = False
                # except ValueError:
                #     # check if the first element is '37'
                #     if first_row[0] == '37':
                #         has_header = True
                #     else:
                #         # raise ValueError("Invalid file format: The first element is neither a datetime nor '37'.")
                #         return pl.DataFrame()
                    
                # # read the CSV file using Polars
                # if has_header:
                #     # If it has a header, use the first row as the header and replace '37' with 'dtm'
                #     df = pl.read_csv(file, has_header=True, try_parse_dates=True)
                #     df = df.rename({"37": "dtm"})
                # else:
                #     # treat the first row as data and generate a default header
                #     df = pl.read_csv(file, has_header=False, try_parse_dates=True)
                #     # Assign column names
                #     column_names = ['dtm'] + [f'col_{i}' for i in range(1, len(first_row))]
                #     df = df.rename({df.columns[i]: column_names[i] for i in range(len(column_names))})
                
                # # convert the 'dtm' column to pl.Datetime
                # # df = df.with_columns(pl.col('dtm').str.strptime(pl.Datetime, fmt="%Y-%m-%d %H:%M:%S"))

                # # Apply the function to cast the columns
                # df = pl_simplify_dtype(df)

                # dtypes = [pl.Datetime(time_unit='us', time_zone=None)] + [pl.Float64]*45 + [pl.String] + [pl.Int64]

                # if df.dtypes==dtypes:
                #     _mappings = self.mappings.filter(pl.col('mkndaq_id').is_in(df.columns))
                #     mapping = dict(zip(_mappings['mkndaq_id'], _mappings['aurora_id']))
                #     df = df.rename(mapping=mapping)                    
                #     return df
                # else:
                #     raise ValueError(f"unexpected dtypes found: {df.dtypes}")

        except Exception as err:
            self.logger.error(f"{file_path}: {err}")
            return pl.DataFrame()



    def compile_files_to_parquet(self, source: str=str(), target: str='data/level1', dtm: str='dtm', archive: str=None, issues: str=None, by_year: bool=True, move_files_on_success: bool=True):
        """
        Harvest a folder and its sub-folders and compile the data found into .parquet files. 
        At this point, 2 file formats are supported, namely the Aurora file format and the mkndaq file format.
        The Aurora file format concerns files stored by the instrument, the mkndaq file format (v1) is the format generated by mkndaq.

        Args:
            source (str, optional): Folder to harvest. Defaults to str().
            target (str, optional): Folder for the resulting .parquet files. Defaults to 'data/level1'.
            dtm (str, optional): key of the timestamp column. Defaults to 'dtm'.
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            by_year (bool, optional): Should .parquet files be organized by year. Defaults to True. NB: Currently not implemented.
        """          
        try:
            if not source:
                source = os.path.join(self.root, self.incoming, self.name)

            df_native = pl.DataFrame()
            df_mkndaq = pl.DataFrame()
            if os.path.exists(source):
                for root, dirs, files in os.walk(source):
                    n = (len(source) - len(root) + 1)
                    relative_path = root[n:] if n < 0 else ""
                    if len(files)==0 and len(dirs)==0:
                        # remove empty folders
                        os.removedirs(root)
                    for file in files:
                        src = os.path.join(root, file)
                        if 'ne300-' in file:
                            # expect file to originate from MKNDAQ
                            _mkndaq = self.extract_to_dataframe(src)
                            if not _mkndaq.is_empty():
                                try:
                                    df_mkndaq = pl.concat([df_mkndaq, _mkndaq], how='diagonal')
                                    if archive and move_files_on_success:
                                        dst = os.path.join(archive, relative_path)
                                        os.makedirs(dst, exist_ok=True)
                                        dst = os.path.join(dst, file)
                                    else:
                                        dst = str()
                                except:
                                    self.logger.error(f"Issue concatenating data frames: {file} produced exception: {err}")
                                    dst = os.path.join(root, file).replace(self.incoming, self.issues)
                            else:
                                dst = os.path.join(root, file).replace(self.incoming, self.issues)
                        else:
                            # expect file to originate from instrument natively
                            _native = self.extract_to_dataframe(src)
                            if not _native.is_empty():
                                try:
                                    df_native = pl.concat([df_native, _native], how='diagonal')
                                    if archive and move_files_on_success:
                                        dst = os.path.join(archive, relative_path)
                                        os.makedirs(dst, exist_ok=True)
                                        dst = os.path.join(dst, file)
                                    else:
                                        dst = str()
                                except:
                                    self.logger.error(f"Issue concatenating data frames: {file} produced exception: {err}")
                                    dst = os.path.join(root, file).replace(self.incoming, self.issues)
                            else:
                                dst = os.path.join(root, file).replace(self.incoming, self.issues)

                        if dst:
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            shutil.move(src=src, dst=dst)
            
                # verify if .parquet already exist, amend and retain unique values
                for file, df in {'ne300_native.parquet': df_native, 'ne300_mkndaq.parquet': df_mkndaq}.items():
                    target_file = os.path.join(target, file)
                    try:
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)
                        if os.path.exists(target_file):
                            df = pl.concat([pl.read_parquet(target_file), 
                                            df], how='diagonal')
                        df = df.unique().sort(by=dtm)
                        df.write_parquet(target_file)
                    except Exception as err:
                        self.logger.error(f"update parquet file: {file} produced error: {err}")
                        df_native.write_parquet(os.path.join(target, '_native.parquet'))
                        df_mkndaq.write_parquet(os.path.join(target, '_mkndaq.parquet'))
                        pass

        except Exception as err:
            self.logger.error(f"file: {file} produced error: {err}")                
            pass
