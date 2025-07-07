# %%
# Author: joerg.klausen@meteoswiss.ch
# import datetime
# import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl


# %%
def count_files(path: str, pattern: str, dte: datetime=None) -> int:
    """Count the number of files matching <pattern> in <path>

    Args:
        path (str): Path to search.
        pattern (str): regex describing the files to count.

    Returns:
        int: Number of files matching criteria
    """
    count = 0

    if re.search(r"d\{7\}\.", pattern) and dte:
        regex_pattern = re.compile(f'(?=.*{pattern})(?=.*{dte.strftime("%j%Y")})')
    elif dte:
        regex_pattern = re.compile(f'(?=.*{pattern})(?=.*{dte.strftime("%Y%m%d")})')
    else:
        regex_pattern = re.compile(pattern)

    for root, dirs, files in os.walk(path):
        for file in files:
            if regex_pattern.match(file):
                count += 1

    return count

#%%
def sum_pairwise(list_of_lists):
    """Given a list of lists of numbers, return a list of pairwise sums"""
    totals = list_of_lists[0]
    foo = lambda l1, l2: [a + b for a, b in zip(l1, l2)]
    for lst in list_of_lists[1:]:
        totals = foo(totals, lst)
    return totals


# %%
def get_file_coverage(cfg: dict, days: int) -> dict:
    """
    Count instrument files per day over the past N days based on date in filename.

    Searches:
      - <root>/<branch>/<instrument>
      - <root>/<branch>/<instrument>/<year>/<month>/<day>

    Args:
        cfg (dict): Configuration with keys:
            - root: base path (str)
            - branches: list[str]
            - folders: list[str] (instrument names)
            - For each folder: cfg[folder]['pattern'] (regex with date in filename)
        days (int): Number of days to consider

    Returns:
        dict: {date_str: {instrument: file_count}}
    """
    root = Path(cfg["root"])
    today = datetime.today().date()
    date_range = [today - timedelta(days=i) for i in range(days)]
    date_set = set(date_range)

    stats = {str(date): {instr: 0 for instr in cfg["folders"]} for date in date_range}
    patterns = {instr: re.compile(cfg[instr]["pattern"]) for instr in cfg["folders"]}

    for branch in cfg["branches"]:
        for instr in cfg["folders"]:
            pattern = patterns[instr]
            base = root / branch / instr

            if not base.exists():
                continue

            # --- First: scan directly in <instrument> directory ---
            print(f"Counting files under {base} ...")
            for file_path in base.iterdir():
                if file_path.is_file():
                    _count_file_by_date(file_path, pattern, date_set, stats, instr)

            # --- Then: scan <year>/<month>/<day> substructure ---
            for date in date_range:
                day_path = base / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
                if not day_path.exists():
                    continue
                for file_path in day_path.iterdir():
                    if file_path.is_file():
                        _count_file_by_date(file_path, pattern, date_set, stats, instr)

    return stats


def _count_file_by_date(file_path: Path, pattern: re.Pattern, date_set: set, stats: dict, instr: str) -> None:
    """Helper: Try to extract a date from the file name and increment stats."""
    try:
        match = pattern.search(file_path.name)
        if not match:
            return
        date_str = re.search(r"\d{8}|\d{7}", match.group()).group()
        file_date = datetime.strptime(date_str, "%Y%m%d" if len(date_str) == 8 else "%j%Y").date()
        if file_date in date_set:
            stats[str(file_date)][instr] += 1
    except Exception:
        pass


# def get_file_coverage(cfg: dict, days: int) -> dict:
#     """
#     Counts files in a specified folder structure, matching each instrument's file pattern, over a defined period.

#     Parameters:
#         cfg['root'] (str): The root directory path.
#         cfg['branches'] (list): List of branch folder names within the root folder.
#         cfg['folders'] (list): List of instrument names (sub-folders) in the branches.
#         days (int): Number of days in the past to analyze.

#     Returns:
#         dict: A dictionary of file counts per instrument per day.
#     """
#     # Get the current date
#     today = datetime.today()
    
#     # Generate the list of dates to analyze
#     date_range = [(today - timedelta(days=i)).date() for i in range(days)]
    
#     # generate a dictionary of file name patterns per folder
#     file_patterns = {instrument: cfg[instrument]['pattern'] for instrument in cfg['folders']}
#     # file_patterns = {instrument: {cfg[instrument]['pattern'] for instrument in folders}}

#     # Initialize a dictionary to store the file counts
#     stats = {str(date): {instrument: 0 for instrument in cfg["folders"]} for date in date_range}
    
#     # Traverse the directory structure and count files
#     for branch in cfg["branches"]:
#         for instrument in cfg["folders"]:
#             # Compile the regex pattern for the current instrument
#             pattern = re.compile(file_patterns[instrument])
            
#             # Loop through each date in the range, organized by year/month/day
#             for date in date_range:
#                 year, month, day = date.strftime('%Y'), date.strftime('%m'), date.strftime('%d')
                
#                 # Construct the folder path for the given branch, instrument, and date structure (year/month/day)
#                 folder_path = os.path.join(cfg['root'], branch, instrument, year, month, day)
                
#                 if os.path.exists(folder_path):
#                     # Count the number of files matching the pattern in the folder
#                     file_count = len([f for f in os.listdir(folder_path)
#                                       if os.path.isfile(os.path.join(folder_path, f)) and pattern.match(f)])
#                     stats[str(date)][instrument] += file_count

#     return stats


def plot_file_coverage(stats: dict):
    try:
        stats = pd.DataFrame(stats).T.sort_index()
        stats = stats.fillna(0)  # Fill NaN values with 0 if there are any

        # Plot each instrument's data as a line plot
        stats.plot(kind='line', marker='o', figsize=(10, 6))

        # Add labels and legend
        plt.xlabel('Date')
        plt.ylabel('File Count')
        plt.title('File Count per instrument')
        plt.xticks(rotation=45)
        plt.grid(False)
        plt.legend(title='Instruments', bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.tight_layout(rect=[0, 0, 0.85, 1])
        plt.show()
    except Exception as err:
        print(err)


# %%
# def __barplot_file_coverage(stats: dict) -> None:
#     """Bar plot of file coverage statistics generated by get_file_coverage()

#     Args:
#         stats (dict): JSON object with expected number of files per day and actual number of files for each day.
#     """
#     x = np.arange(len(stats["dates"]))
#     w = 0.15 # bar width

#     fig, ax = plt.subplots()

#     m = 0
#     for key, values in stats.items():
#         if key not in ["root", "dates"]:
#             expected = [stats[key]["expected"] for i in x]
#             missing = [i - j for i, j in zip(expected, stats[key]["found"]["totals"])]
#             x_values = x + w*m
#             y_values = values["found"]["totals"]
#             #  [TODO] specify yerr as vertical bars between found and expected
#             # yerr = np.array([missing, expected])
#             found = ax.bar(x_values, y_values, w)
#             ax.bar_label(found, rotation=90, label_type='center', fontsize=8)
#             m += 1

#     fig.suptitle(f"Files found under {stats['root']}")
#     ax.set_title(f"including: /incoming, /archive, /issues")
#     ax.set_ylabel("Files per day")
#     ax.set_xlabel("Date")
#     ax.set_xticks(x, stats["dates"], rotation=30)
#     ax.legend(labels=[i for i in stats.keys()][2:], loc='best', fontsize=8)

#     fig.show()

#     return None

# %%
# def __lineplot_file_coverage(stats) -> None:
#     """Line plot of file coverage statistics generated by get_file_coverage()

#     Args:
#         stats (dict): JSON object with expected number of files per day and actual number of files for each day.
#     """
#     x = np.arange(len(stats["dates"]))

#     fig, ax = plt.subplots()

#     for key, values in stats.items():
#         if key not in ["root", "dates"]:
#             ax.plot(stats["dates"], stats[key]["found"]["totals"])
#             ax.set_label(key)

#     ax.set_title(f"Files found under {stats['root']}")
#     ax.set_ylabel("Files per day")
#     ax.set_xlabel("Date")
#     ax.set_xticks(x, stats["dates"], rotation=30)
#     ax.legend(labels=[i for i in stats.keys()][2:], loc='best', fontsize=8)

#     return None


# def plot_coverage(stats: dict=None, cfg: dict=None, days: int=7) -> None:
#     """Plot file coverage statistics generated by get_file_coverage()

#     Args:
#         stats (dict): JSON object with expected number of files per day and actual number of files for each day.
#         cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
#         days (int): Number of days to consider. Defaults to 7.
#     """
#     if stats is None:
#         if cfg:
#             stats = get_file_coverage(cfg=cfg, days=days, simple=True)
#         else:
#             raise ValueError("Either 'stats', or 'cfg' and 'days' must be specified.")

#     if days > 3:
#         __lineplot_file_coverage(stats=stats)
#     else:
#         __barplot_file_coverage(stats=stats)

#     return None

# %%
# def print_coverage(stats: dict=None, cfg: dict=None, days: int=7) -> pd.DataFrame:
#     """Print file coverage statistics generated by get_file_coverage() as a simple table

#     Args:
#         stats (dict): JSON object with expected number of files per day and actual number of files for each day.
#         cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
#         days (int): Number of days to consider. Defaults to 7.
#     """
#     if stats is None:
#         if cfg:
#             stats = get_file_coverage(cfg=cfg, days=days)
#         else:
#             raise ValueError("Either 'stats', or 'cfg' and 'days' must be specified.")

#     # dates = stats['dates']
#     dates = stats.keys()
#     # columns = [i for i in stats.keys()][2:]
#     columns = stats[dates[0]].keys()
#     expected_values = [stats[column]['expected'] for column in columns]
#     totals_values = {column: stats[column]['found']['totals'] for column in columns}

#     # create a DataFrame
#     df = pd.DataFrame(totals_values, index=dates)

#     # add the 'expected' row as the first row
#     df = pd.concat([pd.DataFrame([expected_values], columns=columns), df])
    
#     df.reset_index(inplace=True)
#     df.loc[0, "index"] = "expected"

#     return df 


# %%
if __name__ == "__main__":
    pass


