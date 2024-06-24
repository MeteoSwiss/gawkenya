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
from ipywidgets import interact, widgets
from IPython.display import display
import zipfile
from datetime import datetime

class ECCSONDE:
    def __init__(self):
        pass

    def extract_ecc_asap(self, file: str) -> 'dict[str:str, str:str, str:pl.DataFrame]':
        """
        Reads an ozone sonde measurement text file and extracts its content into a dictionary.

        The dictionary contains:
        - 'file': the path of the file.
        - 'metadata': a dictionary of metadata extracted from the file.
        - 'data': a Polars DataFrame containing the measurement data.
        - 'footer': a list of footer lines from the file.

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
        # metadata_list = []
        # data_list = []

        # # Regular expression to match files with the format YYYYMMDD*.TXT
        # pattern = re.compile(r'^\d{8}.*\.TXT$', re.IGNORECASE)

        # # Iterate over all files in the specified folder
        # for filename in os.listdir(folder_path):
        #     if pattern.match(filename):
        #         file_path = os.path.join(folder_path, filename)
                
        #         if os.path.isfile(file_path):
        #             # Extract data and metadata from the file
        #             result = self.extract_ecc_asap(file_path)
                    
        #             if result['metadata'] and not result['data'].is_empty():
        #                 # Add a 'file' column to identify the source file
        #                 metadata = result['metadata']
        #                 metadata['file'] = filename
        #                 metadata_list.append(metadata)

        #                 # Add 'file' and 'dte' columns to the data
        #                 try:
        #                     data = result['data'].with_columns(
        #                         pl.lit(filename).alias('file'),
        #                         pl.lit(time.strftime("%Y-%m-%d", 
        #                             time.strptime(os.path.basename(filename)[:8], "%Y%m%d"))).alias('dte')
        #                     )
        #                     data_list.append(data)
        #                 except Exception as err:
        #                     print(f"Error processing data from file {filename}: {err}")
        
        # # Compile metadata into a Polars DataFrame
        # try:
        #     metadata_df = pl.DataFrame(metadata_list)
        # except Exception as err:
        #     print(f"Error creating metadata DataFrame: {err}")
        #     metadata_df = pl.DataFrame()

        # # Compile data into a single Polars DataFrame
        # try:
        #     data_df = pl.concat(data_list)
        # except Exception as err:
        #     print(f"Error creating data DataFrame: {err}")
        #     data_df = pl.DataFrame()

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


def download_and_extract_shadoz_zip(year: int, url: str='https://acd-ext.gsfc.nasa.gov/anonftp/acd/shadoz/V06', 
                                    station: str='nairobi', target: str='data/level1/shadoz') -> tuple[pl.DataFrame, pl.DataFrame]:
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
        dtm = datetime.strptime(re.search(r'\d{8}T\d{2}', filename).group(), '%Y%m%dT%H')
        df = df.with_columns([
            pl.lit(metadata['filename']).alias('filename'),
            pl.lit(dtm).alias('dtm')
        ])
        
        return df, metadata

    # Construct the full URL to the zip file
    zip_url = f"{url}/{station}/shadoz_{station}_{year}_V06.zip"
    print(f"Downloading {zip_url} ...")
    response = requests.get(zip_url)
    response.raise_for_status()  # Check if the request was successful
    
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


# def compute_total_column_ozone_from_insitu_profile(pressure: pl.Series, ozone_partial_pressure: pl.Series) -> float:
#     """
#     Compute the total column ozone in Dobson Units (DU) from (in-situ) ozone profile data.
    
#     Parameters:
#     pressure (pl.Series): A Polars Series containing atmospheric pressure in hPa.
#     ozone_partial_pressure (pl.Series): A Polars Series containing ozone partial pressure in mPa.
    
#     Returns:
#     float: The total column ozone in Dobson Units (DU).
#     """
#     # Remove rows with Null or NaN values
#     df = pl.DataFrame({
#         'ozone_partial_pressure': ozone_partial_pressure,
#         'pressure': pressure
#     }).drop_nulls()
    
#     # Convert Polars Series to NumPy arrays
#     pressure_values = df['pressure'].to_numpy()
#     ozone_partial_pressure_values = df['ozone_partial_pressure'].to_numpy()
    
#     # Sort the values by pressure in descending order (from surface to top of atmosphere)
#     sorted_indices = np.argsort(pressure_values)[::-1]
#     ozone_partial_pressure_values = ozone_partial_pressure_values[sorted_indices]
#     pressure_values = pressure_values[sorted_indices]
    
#     # Compute the total column ozone in DU using the trapezoidal rule for integration
#     column_ozone = np.trapz(ozone_partial_pressure_values / pressure_values, pressure_values) / 10
    
#     return column_ozone


def calculate_total_column_ozone(df: pl.DataFrame, ozone_col: str='O3_mPa', temp_col: str='Temp', pressure_col: str='Press') -> float:
    """
    Calculate the total column ozone in Dobson Units (DU) from vertical ozone profile data.

    Parameters:
    df (pl.DataFrame): Polars DataFrame containing the ozone profile data.
    ozone_col (str): Column name for ozone partial pressures (mPa).
    temp_col (str): Column name for temperatures (°C).
    pressure_col (str): Column name for atmospheric pressures (hPa).

    Returns:
    float: Total column ozone in Dobson Units (DU).
    """
    # Constants
    k_B = 1.380649e-23  # Boltzmann constant in J/K
    conversion_factor = 2.687e16  # Conversion factor from molecules/cm^2 to DU

    # Eliminate rows with Null values and sort by pressure
    df = df.select([ozone_col, temp_col, pressure_col]).drop_nulls()
    df = df.sort(by=pressure_col, descending=True)
    
    # Extract columns as numpy arrays
    ozone_partial_pressures = df[ozone_col].to_numpy() * 1e-3  # Convert from mPa to Pa
    temperatures_celsius = df[temp_col].to_numpy()
    pressures = df[pressure_col].to_numpy() * 100  # Convert from hPa to Pa

    # Convert temperatures from °C to K
    temperatures_kelvin = temperatures_celsius + 273.15

    # Calculate ozone number density (molecules/m^3) at each pressure level
    ozone_number_densities = ozone_partial_pressures / (k_B * temperatures_kelvin)

    # Integrate ozone number densities over pressure
    total_column_ozone_number_density = np.trapz(ozone_number_densities, pressures)

    # Convert total column ozone number density to Dobson Units
    total_column_ozone_du = total_column_ozone_number_density / (conversion_factor * 1e4)

    return total_column_ozone_du
