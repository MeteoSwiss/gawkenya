import os
import io
import re
import time
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import matplotlib.colors as mcolors
from matplotlib.cm import get_cmap
from ipywidgets import interact, widgets
from IPython.display import display

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
