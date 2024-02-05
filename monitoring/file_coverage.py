# %%
# Author: joerg.klausen@meteoswiss.ch
import os
import re
import datetime
import json
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl
import numpy as np

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

    if dte:
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
    """Count number of files conforming to <pattern> in a directory structure organized by yyyy/mm/dd, covering a given number of days.

    Args:
        cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
        days (int): Number of days in the past.
        save (bool): Should output be persistent in a file written to <root>?. Defaults to True.
    Returns:
        dict: JSON object and (optionally) JSON file with expected number of files per day and actual number of files for each day.
    """
    dates = [(datetime.datetime.now() - datetime.timedelta(days=d)) for d in range(days, 0, -1)] + [datetime.datetime.now()]
    stats = {"root": cfg["root"]}
    stats["dates"] = [dte.strftime("%Y-%m-%d") for dte in dates]
    

    # df = pl.DataFrame({"Dates": [dte.strftime("%Y-%m-%d") for dte in dates]})

    for folder in cfg["folders"]:
        stats[folder] = {}
        stats[folder]["expected"] = cfg[folder]["expected"]
        stats[folder]["found"] = {}
        found_in_branches = []
        for branch in cfg["branches"]:
            base_path = os.path.join(cfg["root"], branch, folder)
            pattern = cfg[folder]["pattern"]
            found = []
            for date in dates:
                if os.path.exists(path:=os.path.join(base_path, str(date.year), '{:02}'.format(date.month), '{:02}'.format(date.day))):
                    n = count_files(path=path, pattern=pattern)
                elif os.path.exists(path:=os.path.join(base_path, str(date.year), '{:02}'.format(date.month))):
                    n = count_files(path=path, pattern=pattern, dte=date)
                elif os.path.exists(path:=os.path.join(base_path, str(date.year))):
                    n = count_files(path=path, pattern=pattern, dte=date)              
                else:
                    n = 0
                found.append(n)
                # totals.append(n)
            stats[folder]["found"][branch] = found
            found_in_branches = found_in_branches + [found]
        stats[folder]["found"]["totals"] = sum_pairwise(found_in_branches)

    return stats


# def get_file_coverage(cfg: dict, days: int, save: bool=True, simple=True) -> dict:
#     """Count number of files conforming to <pattern> in a directory structure organized by yyyy/mm/dd, covering a given number of days.

#     Args:
#         cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
#         days (int): Number of days in the past.
#         save (bool): Should output be persistent in a file written to <root>?. Defaults to True.
#     Returns:
#         dict: JSON object and (optionally) JSON file with expected number of files per day and actual number of files for each day.
#     """   
#     stats = {"root": cfg["root"]}
#     sep = os.path.sep
#     if simple:
#         dates = [(datetime.datetime.now() - datetime.timedelta(days=d)) for d in range(days, 0, -1)] + [datetime.datetime.now()]
#         stats["dates"] = [dte.strftime("%Y-%m-%d") for dte in dates]
#         stats["expected"] = {}
#         stats["found"] = {}
#         for folder in cfg["folders"]:
#             stats["expected"][folder] = cfg[folder]["expected"]
#             stats["found"][folder] = [] 
#             for dte in dates:
#                 dte = datetime.datetime.date(dte)
#                 if cfg[folder]["buckets"] in "daily":
#                     path = os.path.join(cfg["root"], str(folder), dte.strftime(f"%Y{sep}%m{sep}%d"))
#                     try:
#                         files = list(filter(lambda file: re.search(cfg[folder]["pattern"], file) is not None, os.listdir(path)))
#                         matches = len(files)
#                     except:
#                         matches = 0
#                     stats["found"][folder].append(matches)
#                 elif cfg[folder]["buckets"] in "monthly":
#                     path = os.path.join(cfg["root"], str(folder), dte.strftime(f"%Y{sep}%m"))
#                     try:
#                         files = list(filter(lambda file: re.search(cfg[folder]["pattern"], file) is not None, os.listdir(path)))
#                         matches = len(files)
#                     except:
#                         matches = 0
#                     stats["found"][folder].append(matches)
#                 else:
#                     path = os.path.join(cfg["root"], str(folder))
#                     try:
#                         files = list(filter(lambda file: re.search(cfg[folder]["pattern"], file) is not None, os.listdir(path)))
#                         matches = len(list(filter(lambda file: datetime.datetime.date(datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(path, file)))) == dte, files)))
#                     except:
#                         matches = 0
#                     stats["found"][folder].append(matches)
#     else:
#         stats["expected"] = {}
#         for folder in cfg["folders"]:
#             stats["expected"][folder] = cfg[folder]["expected"]
#             stats[folder] = {}                
#             for d in range(days, 0, -1):
#                 dte = datetime.datetime.now() - datetime.timedelta(days=d)
#                 stats[folder][dte.strftime("%Y-%m-%d")] = {}
#                 path = os.path.join(cfg["root"], folder, dte.strftime(f"%Y{sep}%m{sep}%d"))
#                 try:
#                     files = os.listdir(path)
#                     matches = len([re.search(cfg[folder]["pattern"], file) for file in files])
#                 except:
#                     matches = 0
#                 stats[folder][dte.strftime("%Y-%m-%d")] = matches

#     stats['rel_file_coverage_mean'] = {}
#     stats['rel_file_coverage_sd'] = {}

#     for k, v in stats['expected'].items():
#         stats['rel_file_coverage_mean'][k] = np.mean(stats['found'][k][:-1]) / stats['expected'][k]
#         stats['rel_file_coverage_sd'][k] = np.std(stats['found'][k][:-1]) / stats['expected'][k]

#     if save:
#         if cfg["file_name"]:
#             file=os.path.join(cfg["root"], cfg["file_name"])
#         else:
#             file=os.path.join(cfg["root"], "file_coverage.json")

#         with open(file, "w") as fh:
#             json.dump(stats, fh)

#     return stats

# %%
def __barplot_file_coverage(stats: dict) -> None:
    """Bar plot of file coverage statistics generated by get_file_coverage()

    Args:
        stats (dict): JSON object with expected number of files per day and actual number of files for each day.
    """
    x = np.arange(len(stats["dates"]))
    w = 0.15 # bar width

    fig, ax = plt.subplots()

    m = 0
    for key, values in stats.items():
        if key not in ["root", "dates"]:
            expected = [stats[key]["expected"] for i in x]
            missing = [i - j for i, j in zip(expected, stats[key]["found"]["totals"])]
            x_values = x + w*m
            y_values = values["found"]["totals"]
            #  [TODO] specify yerr as vertical bars between found and expected
            # yerr = np.array([missing, expected])
            found = ax.bar(x_values, y_values, w)
            ax.bar_label(found, rotation=90, label_type='center', fontsize=8)
            m += 1

    fig.suptitle(f"Files found under {stats['root']}")
    ax.set_title(f"including: /incoming, /archive, /issues")
    ax.set_ylabel("Files per day")
    ax.set_xlabel("Date")
    ax.set_xticks(x, stats["dates"], rotation=30)
    ax.legend(labels=[i for i in stats.keys()][2:], loc='best', fontsize=8)

    fig.show()

    return None

# %%
def __lineplot_file_coverage(stats) -> None:
    """Line plot of file coverage statistics generated by get_file_coverage()

    Args:
        stats (dict): JSON object with expected number of files per day and actual number of files for each day.
    """
    x = np.arange(len(stats["dates"]))

    fig, ax = plt.subplots()

    for key, values in stats.items():
        if key not in ["root", "dates"]:
            ax.plot(stats["dates"], stats[key]["found"]["totals"])
            ax.set_label(key)

    ax.set_title(f"Files found under {stats['root']}")
    ax.set_ylabel("Files per day")
    ax.set_xlabel("Date")
    ax.set_xticks(x, stats["dates"], rotation=30)
    ax.legend(labels=[i for i in stats.keys()][2:], loc='best', fontsize=8)

    return None


def plot_coverage(stats: dict=None, cfg: dict=None, days: int=7) -> None:
    """Plot file coverage statistics generated by get_file_coverage()

    Args:
        stats (dict): JSON object with expected number of files per day and actual number of files for each day.
        cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
        days (int): Number of days to consider. Defaults to 7.
    """
    if stats is None:
        if cfg:
            stats = get_file_coverage(cfg=cfg, days=days, simple=True)
        else:
            raise ValueError("Either 'stats', or 'cfg' and 'days' must be specified.")

    if days > 3:
        __lineplot_file_coverage(stats=stats)
    else:
        __barplot_file_coverage(stats=stats)

    return None

# %%
def print_coverage(stats: dict=None, cfg: dict=None, days: int=7) -> None:
    """Print file coverage statistics generated by get_file_coverage() as a simple table

    Args:
        stats (dict): JSON object with expected number of files per day and actual number of files for each day.
        cfg (dict): Configuration, for each instrument or data type. Described in mch-config.yml.
        days (int): Number of days to consider. Defaults to 7.
    """
    if stats is None:
        if cfg:
            stats = get_file_coverage(cfg=cfg, days=days, simple=True)
        else:
            raise ValueError("Either 'stats', or 'cfg' and 'days' must be specified.")

    expected = pd.DataFrame.from_dict(data=stats["expected"], orient="index").transpose()
    found = pd.DataFrame.from_dict(stats["found"])
    dates = pd.DataFrame.from_dict(data=stats["dates"])
    df = pd.concat([dates, found], axis=1)
    df = pd.concat([expected, df], axis=0)
    col = df.pop(0)
    df.insert(0, "Files", col)
    df.iloc[0, 0] = "expected"
    print(df)

    file_cvg_mean = pd.DataFrame.from_dict(data=stats["rel_file_coverage_mean"], orient="index").transpose()
    file_cvg_sd = pd.DataFrame.from_dict(data=stats["rel_file_coverage_sd"], orient="index").transpose()
    df = pd.concat([file_cvg_mean, file_cvg_sd], axis=0)
    df.insert(0, "Coverage", ["mean_rel", "sd_rel"])
    print(df)

    return None 


# %%
if __name__ == "__main__":
    pass


