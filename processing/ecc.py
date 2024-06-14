import os
import io
import re
import time
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
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
                            new_columns=["Time[s]", "Iecc[mA]", "Tp[K]", "Um[V]", "Im[mA]", "ref[nbar]", "ecc[nbar]"])

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
        
    def plot_ecc_asap(self, data_dict: dict):
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
