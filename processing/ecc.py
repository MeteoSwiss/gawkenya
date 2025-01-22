import os
import io
import re
import time
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import requests
import matplotlib.colors as mcolors
from matplotlib.cm import get_cmap
from toolbox.numerical_analysis_1d import interpolate_logarithmic
import datetime
import zipfile
from ipywidgets import interact, widgets
# from IPython.display import display

# [TODO] always compare the ...T... (7 days prior to launch) file with the ...S... file (day of launch).


class ECC:
    def __init__(self):
        pass

    def extract_ecc_asap(self, file: str) -> 'dict[str:str, str:str, str:str, str:pl.DataFrame]':
        """
        Reads an ozone sonde measurement text file and extracts its content into a dictionary.

        The dictionary contains:
        - 'date': the date of the test.
        - 'file': the (relative) path of the file.
        - 'metadata': a dictionary of metadata extracted from the file.
        - 'data': a Polars DataFrame containing the measurement data.

        Parameters:
        file (str): The path to the ozone sonde measurement text file.

        Returns:
        Dict[str, Any]: A dictionary containing the file path, metadata, and data.
        """
        with open(file, 'r', encoding='latin1') as fh:
            lines = fh.readlines()

        metadata = {}
        data = []
        footer = []

        try:
            # Extract metadata from the header (lines 1-7)
            metadata["Date"] = re.search(r"Date:\s+(.*)", lines[0]).group(1).strip()
            metadata["Sonde"] = re.search(r"Sonde:\s+(.*)", lines[1]).group(1).strip()
            metadata["P_pump[inHg]"] = re.search(r"Ppompe\[inHg\]:\s+(.*)", lines[3]).group(1).strip()
            metadata["V_pump[inHG]"] = re.search(r"Vpompe\[inHG\]:\s+(.*)", lines[4]).group(1).strip()
            metadata["Flow_usine[s/100ml]"] = re.search(r"Flow_usine\[s/100ml\]:\s+(.*)", lines[5]).group(1).strip()
            metadata["P_atm[hPa]"] = re.search(r"PressionATM\[hPa\]\s+:\s+(.*)", lines[6]).group(1).strip()
            metadata["Fl[s/100ml] VFl[SCCM]P[hPa] T[K]"] = lines[7].strip()

            # Extract data from lines starting at row 10 until footer, then collect footer lines into a list
            collecting_footer = False
            for line in lines[10:]:
                if '999999.000' in line and all(x == '999999.000' for x in line.split()):
                    collecting_footer = True
                elif collecting_footer:
                    footer.append(line.strip())
                else:
                    data.append(re.sub(' +', ' ', line).strip())

            # Create a Polars DataFrame from the data section
            df = pl.read_csv(io.StringIO("\n".join(data)), separator=' ', null_values='999999.000', has_header=False,
                            new_columns=["Time[s]", "Iecc[mA]", "Tp[K]", "Um[V]", "Im[mA]", "ref[nbar]", "ecc[nbar]"],
                            dtypes=[pl.Float64]*7)

            metadata['footer'] = footer

            # Build the final dictionary
            result = {
                "date": time.strftime("%Y-%m-%d", time.strptime(os.path.basename(file)[:8], "%Y%m%d")),
                "file": file,
                "metadata": metadata,
                "data": df,
            }
            return result
        except Exception as err:
            print(f"Error extracting file '{file}: {err}.")
            return {'file': file, 'metadata': '', 'data': ''}


    def plot_ecc_asap(self, data_dict: dict, suptitle: str=''):
        """
        Plots the 'data' part of the dictionary returned by 'extract_ecc_asap' as an interactive scatter plot with a dropdown to select the column to plot against 'Time[s]'.

        Parameters:
        data_dict (dict): The dictionary returned by 'extract_ecc_asap' containing 'data' as a Polars DataFrame with columns including 'Time[s]'.

        Returns:
        None
        """
        try:
            data_df = data_dict['data']

            # Extract relevant columns for plotting
            time_column = data_df['Time[s]'].to_numpy().astype(float)
            columns_to_plot = [col for col in data_df.columns if col != 'Time[s]']

            # Function to update plot based on dropdown selection
            def update_plot(column):
                plt.figure(figsize=(10, 6))
                plt.scatter(time_column, data_df[column].to_numpy().astype(float), marker='o', s=10)
                plt.xlabel('Time [s]')
                plt.ylabel(column)
                plt.suptitle(suptitle)
                plt.title(f'{column} vs Time')
                plt.grid(True)
                plt.show()

            # Create dropdown widget
            dropdown = widgets.Dropdown(options=columns_to_plot, description='Select Column')

            # Display dropdown and interact to update plot
            interact(update_plot, column=dropdown)

        except KeyError:
            print("Error: 'data' not found in the dictionary.")
        except Exception as e:
            print(f"An error occurred during plotting: {e}")


    def compile_ecc_asap(self, folder_path: str) -> dict:
        """
        Compiles data and metadata from all valid files in a specified folder.

        Parameters:
        folder_path (str): The path to the folder containing ozone sonde measurement text files.

        Returns:
        dict: A dictionary with two Polars DataFrames: 'metadata' and 'data'.
        """
        metadata_df = pl.DataFrame()
        data_df = pl.DataFrame()

        # Regular expression to match files with the format YYYYMMDD*.TXT
        pattern = re.compile(r'^\d{8}.*\.TXT$', re.IGNORECASE)

        # Iterate over all files in the specified folder
        for filename in os.listdir(folder_path):
            if pattern.match(filename):
                file_path = os.path.join(folder_path, filename)
                
                if os.path.isfile(file_path):
                    # Extract data and metadata from the file
                    result = self.extract_ecc_asap(file_path)
                    
                    if len(result['metadata'])>0 and not result['data'].is_empty():
                        # Add a 'file' column to identify the source file
                        metadata = result['metadata']
                        metadata['file'] = filename

                        try:
                            metadata_df = pl.concat([metadata_df, pl.DataFrame(metadata)], how='diagonal')
                        except Exception as err:
                            print(f"Error concatenating metadata from file {filename}: {err}")
                            pass

                        # Add a 'file' column to each row of data
                        data = result['data'].with_columns(
                            pl.lit(filename).alias('file'),
                            pl.lit(time.strftime("%Y-%m-%d", 
                                time.strptime(os.path.basename(filename)[:8], "%Y%m%d"))).alias('dte'),
                        )
                        try:
                            data_df = pl.concat([data_df, data], how='diagonal')
                        except Exception as err:
                            print(f"Error concatenating data from file {filename}: {err}")
                            pass
        return {'metadata': metadata_df, 'data': data_df}
    

    def plot_compiled_ecc_asap(self, data_df: pl.DataFrame, suptitle: str=None, interactive: bool=True, save: bool=True, path: str=None):
        """
        Plots the compiled 'data_df' as an interactive scatter plot with multiple series defined by the 'dte' column.

        Parameters:
        data_df (pl.DataFrame): The compiled data DataFrame.
        suptitle (str, optional): The supertitle for the plot, e.g. 'ecc asap {year}'. Defaults to None.
        interactive (bool, optional): If True, interactive plots are generated, otherwise one plot per column in data_df. Defaults to True.
        save (bool, optional): If interactive=False, whether plots should be saved. Defaults to True.
        path (str, optional): If save=True, the directory path for the plot. Defaults to None.

        Returns:
        None
        """
        # Use the %matplotlib widgets magic for interactive plotting
        # get_ipython().run_line_magic('matplotlib', 'widget')
        try:
            # Convert Polars DataFrame to Pandas DataFrame for compatibility with Matplotlib and ipywidgets
            data_df = data_df.to_pandas()

            # Sort data by 'dte'
            data_df['dte'] = pd.to_datetime(data_df['dte'])
            data_df = data_df.sort_values('dte')

            # Extract unique dates for coloring
            unique_dates = data_df['dte'].unique()
            num_dates = len(unique_dates)

            # Create a color map
            cmap = get_cmap('rainbow')
            colors = [cmap(i / num_dates) for i in range(num_dates)]

            # Function to update plot based on dropdown selection
            def update_plot(column, suptitle):
                fig = plt.figure(figsize=(10, 8))
                try:
                    for i, date in enumerate(unique_dates):
                        date_data = data_df[data_df['dte'] == date]
                        date_data = date_data.dropna(subset=[column])  # Remove rows with NaN values in the selected column
                        plt.scatter(date_data['Time[s]'], date_data[column], color=colors[i], label=str(date.date()), s=10)
                except Exception as err:
                    print(i, date, err)
                    pass
                plt.xlabel('Time [s]')
                plt.ylabel(column)
                if suptitle:
                    plt.suptitle(suptitle)
                plt.title(f'{column} vs Time', size=10)

                # Create a legend outside the plot
                plt.legend(title='Date', bbox_to_anchor=(1.05, 1), loc='upper left', ncol=2, fontsize=8)
                plt.grid(True)
                plt.tight_layout()
                plt.grid(True)
                plt.show()
                return fig

            def save_plot(fig, path):
                if path:
                    fig.savefig(fname=os.path.join(path, f"ecc_asap_{column}.png"), bbox_inches='tight')

            columns_to_plot = [col for col in data_df.columns if col not in ['Time[s]', 'dte', 'file']]
            
            if interactive:
                # Create dropdown widget
                dropdown = widgets.Dropdown(options=columns_to_plot, description='Variable to plot')

                # Display dropdown and interact to update plot
                interact(update_plot, column=dropdown)
            else:
                # generate a plot for each column and optionally save to file
                for column in columns_to_plot:
                    suptitle = suptitle
                    fig = update_plot(column=column, suptitle=suptitle)
                    if save:
                        save_plot(fig=fig, path=path)

        except KeyError as e:
            print(f"Error: {e} not found in the data DataFrame.")
        except Exception as e:
            print(f"An error occurred during plotting: {e}")


    def total_column_ozone_from_pressure_profile(self, df: pl.DataFrame, pressure_col: str, ozone_col: str, other_cols: 'list[str]'=[]) -> pl.DataFrame:
        """
        Calculate total column ozone from ozone partial pressure data in a Polars DataFrame.
        The calculation is based on the ideal gas law (1), the density of air (2) and the hydrostatic formula (3).
            (1) p V = N k_B T -> nu_O3 = N_O3 / V = P_O3 / k_B / T -> dN_O3 / A = P_O3 dz / k_B / T
            (2) rho = m / V = M P / R T
            (3) dP = - rho g dz = - M P g dz / R / T -> dz = R T g / M  dP / P
            (3) into (1) dN_O3 / A = P_O3 (R T g / M) (dP / P) / k_B / T = (R g / k_B / M) P_O3 (dP / P) | integrate from P_0 to P_z
            (4) total ozone column density (P_0 to P_z) = (R g / k_B / M) sum ((P_O3_i + P_O3_i+1) / 2) ln(P_i / P_i+1)
        
        Parameters:
            df (pl.DataFrame): Polars DataFrame containing the data.
            pressure_col (str): Column name for pressure levels in hectopascals (hPa).
            ozone_col (str): Column name for ozone partial pressures in millipascals (mPa).

        Returns:
            pl.DataFrame: Polars DataFrame with cumulative ozone column 'O3_DU_calc' in Dobson Units (DU). Additionally, columns pressure_col, ozone_col and other_col are returned.
        """
        # Constants
        N_A = 6.02214076E+23  # Avogadro's number, 1/mol
        M = 0.0289652  # Molar mass of dry air in kg/mol
        g = 9.80665  # Acceleration due to gravity in m/s^2
        DU = 2.69e20  # Conversion factor for Dobson Units, molecules/m^2

        f_DU = N_A / M / g / DU  # Conversion factor for Dobson Units, Pa/molecule

        # Sort the dataframe by pressure in descending order
        df_sorted = df.sort(by=pressure_col, descending=True)

        # Extract relevant columns, eliminate Null values
        df_sorted = df_sorted.select([pressure_col, ozone_col] + other_cols)#.drop_nulls()

        # Interpolate missing values
        df_sorted = df_sorted.with_columns(
            df_sorted[ozone_col].interpolate(method='linear')
        )

        # Convert columns to numpy arrays for processing
        p_atm = df_sorted[pressure_col].to_numpy() * 100  # convert hPa to Pa
        p_o3 = df_sorted[ozone_col].to_numpy() * 1e-3  # convert mPa to Pa

        # Calculate the cumulative integrated number density of ozone using the trapezoidal rule
        o3_du_calc = np.array([
            np.trapz(p_o3[:i+1] / p_atm[:i+1], p_atm[:i+1]) * (-1) * f_DU
            for i in range(len(p_atm))
        ])

        # Create a new DataFrame with the cumulative ozone column added
        df_result = df_sorted.with_columns(
            pl.Series("O3_DU_calc", o3_du_calc),
        )
        
        return df_result


    def plot_ecc_profile(self, df_ecc: pl.DataFrame, df_model: pl.DataFrame=pl.DataFrame(), model: str=str(), title: str='', save: bool=True, path: str=str()):
        """
        Plot an ozone sonde profile, together with the residual profile obtained from some other source, e.g., CAMS.

        Parameters:
        df_ecc (pl.DataFrame): Polars DataFrame with columns including 'Press', 'O3_mPa'[, 'filename'].
        df_model (pl.DataFrame): Polars DataFrame with columns including 'Press', 'O3_mPa'[, 'filename'].

        Returns:
        None
        """
        try:
            if 'filename' in df_ecc.columns:
                label_ecc = df_ecc['filename'][0].split('.')[0]
            else:
                label_ecc = 'ECC'

            if not df_model.is_empty():
                if 'filename' in df_model.columns:
                    label_model = df_model['filename']
                elif model:
                    label_model = model
                else:
                    label_model = 'model'
                burst_pressure = min(df_ecc['Press'])
                df_residual_interpolated = interpolate_logarithmic(df_model['Press'], df_model['O3_mPa'], N=5, x0=burst_pressure)
                df_above_burst = df_residual_interpolated.filter(pl.col('x') <= burst_pressure)
            fig = plt.figure(figsize=(8, 6))
            plt.scatter(df_ecc['O3_mPa'], df_ecc['Press'], marker='o', s=12, label=label_ecc)
            plt.plot(df_residual_interpolated['y'], df_residual_interpolated['x'], c='red', label=label_model)
            plt.scatter(df_above_burst['y'], df_above_burst['x'], marker='x', c='red', s=12, label=f'{label_model} above burst')
            plt.xlabel('O3 partial pressure [mPa]')
            plt.ylabel('Pressure [hPa]')
            plt.gca().invert_yaxis()
            plt.yscale('log')
            plt.title(title)
            plt.legend()
            # plt.grid(True)
            plt.show()

            if save:
                if path==str():
                    path = 'results/ecc/shadoz'
                    os.makedirs(path, exist_ok=True)
                file = os.path.join(path, f"{label_ecc}.png")
                fig.savefig(file)
        except Exception as err:
            print(err)


class SHADOZ:
    def __init__(self):
        pass

    def download_and_extract_shadoz_zip_to_parquet(self, year: int, url: str='https://acd-ext.gsfc.nasa.gov/anonftp/acd/shadoz/V06', 
                                        station: str='nairobi', target: str='data/level1/ecc/shadoz') -> 'tuple[pl.DataFrame, pl.DataFrame]':
        """
        Downloads a .zip file containing SHADOZ data for a specific station and year, extracts the .dat files,
        and combines them into a single polars DataFrame. The resulting DataFrame is saved as a parquet file.
        
        Parameters:
        url (str): The base URL where the .zip files are hosted.
        station (str): The station name (e.g., 'nairobi').
        year (int): The year of the data to download (e.g., 1998).
        target (str): The directory to save the resulting parquet file.
        
        Returns:
        tuple: A tuple containing polars DataFrames of the data and the metadata for the entire year.
        """
        
        # Function to parse each .dat file
        def parse_dat_file(file_content, filename):
            lines = file_content.decode('utf-8').splitlines()
            metadata = {}
            
            # Number of metadata lines
            num_metadata_lines = int(lines[0].strip())
            
            # Extract metadata
            comment_id = 1
            for i in range(1, num_metadata_lines):
                line = lines[i].strip()
                if 'Comment :' in line:
                    key, value = line.split(':', 1)
                    if value.strip():
                        metadata[f"{key.strip()}_{comment_id}"] = value.strip()
                    comment_id += 1
                elif ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()

            metadata['filename'] = filename            
            variables = lines[num_metadata_lines - 2].strip().split()
            metadata['variables'] = variables
            metadata['units'] = lines[num_metadata_lines - 1].strip().split()

            # Extract data
            data = [line.split() for line in lines[num_metadata_lines:]]

            # Convert to polars DataFrame
            df = pl.DataFrame(data, schema=dict(zip(variables, [pl.Float32]*len(variables))))

            # Encode missing or invalid as Null
            invalid = int(metadata['Missing or bad values'])
            df = df.select([
                pl.when(pl.col(column) == invalid).then(None).otherwise(pl.col(column)).alias(column)
                for column in df.columns
            ])

            # Add filename and datetime
            dtm = datetime.datetime.strptime(re.search(r'\d{8}T\d{2}', filename).group(), '%Y%m%dT%H')
            df = df.with_columns([
                pl.lit(metadata['filename']).alias('filename'),
                pl.lit(dtm).alias('dtm')
            ])
            
            return df, metadata

        # Construct the full URL to the zip file
        zip_url = f"{url}/{station}/shadoz_{station}_{year}_V06.zip"
        print(f"Downloading {zip_url} ...")
        response = requests.get(zip_url)
        if response.ok:
            # Extract the zip file contents into memory
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                file_list = z.namelist()
                dat_files = [file for file in file_list if file.endswith('.dat')]

                # Combine all .dat files into one DataFrame
                all_dataframes = []
                all_metadata = {}
                for dat_file in dat_files:
                    print(f"> Extracting {dat_file}")
                    with z.open(dat_file) as file:
                        file_content = file.read()
                        df, metadata = parse_dat_file(file_content, dat_file)
                        if df is not None:
                            all_dataframes.append(df)
                            all_metadata[dat_file] = metadata

                df_data = pl.concat(all_dataframes)
                df_metadata = pl.DataFrame([{**{"source": k}, **v} for k, v in all_metadata.items()])

            # Store the resulting DataFrame as a parquet file
            os.makedirs(target, exist_ok=True)
            df_data_path = os.path.join(target, f'ecc_sonde_data_{year}.parquet')
            print(f"Saving data to {df_data_path}")
            df_data.write_parquet(df_data_path)
            df_metadata.write_parquet(os.path.join(target, f'ecc_sonde_metadata_{year}.parquet'))

            return df_data, df_metadata
        elif response.status_code==404:
            print(f"Response status '404' received: {zip_url} doesn't seem to exist.")
            pass
            return pl.DataFrame(), pl.DataFrame()


    def compile_time_series_at_given_pressure(self, source: str, pressure_level: int=660, dp: int=5, pattern: str="ecc_sonde_data_", dtm: str="dtm") -> pl.DataFrame:
        """For a pressure range of pressure_level +/- dp, create a pl.Dataframe with the time series of ozone measured at this level.

        Args:
            source (str): path to root directory containing .parquet files of compiled ozone sonde profiles.
            pressure_level (int, optional): desired pressure level in mbar. Defaults to 660 mbar, the actual pressure level of Mount Kenya GAW station.
            dp (int, optional): wiggle room around given pressure level in mbar. Defaults to 5 mbar, corresponding to ca +/- 56 m at 700 mbar.
            pattern (str, optional): file name pattern used to select files to be processed. Defaults to "ecc_sonde_data_".
            dtm (str, optional): name of dateTime column. Defaults to 'dtm'.

        Returns:
            pl.DataFrame: time series of ozone values at given pressure level. Includes elements
                - dtm (datetime[μs]): dateTime stamp of observation
                - Press (Float32): pressure level [mbar]
                - GeopAlt (Float32): geopotential height [km]
                - O3_mPa (Float32): ozone partial pessure [mPa]
                - O3_ppmv (Float32): ozone volume mixing ratio ppmv]
                - O3_ppbv (Float32): ozone volume mixing ratio ppbv]
                - O3_DU (Float32): ozone level [DU]
                - ...: more columns
        """
        try:
            df = pl.DataFrame()
            pres = [pressure_level - dp, pressure_level + dp]
            for root, dirs, files in os.walk(source):
                for file in files:
                    if re.search(pattern=pattern, string=file):
                        df_tmp = pl.read_parquet(os.path.join(root, file))
                        df_tmp = df_tmp.filter((pl.col("Press") > pres[0]) & (pl.col("Press") < pres[1]))
                        if not df_tmp.is_empty():
                            df = pl.concat([df, df_tmp], how='diagonal')
            df = df.sort(by=pl.col('dtm'))
            df = df.with_columns((pl.col('O3_ppmv') * 1000).alias('O3_ppbv'))
            return df
        except Exception as err:
            print(err)

