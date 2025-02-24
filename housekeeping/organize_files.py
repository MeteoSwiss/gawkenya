# %%
# Author: joerg.klausen@meteoswiss.ch
import datetime
import os
import platform
import re
import shutil
import subprocess
import time
import zipfile
from collections import defaultdict
# from datetime import datetime

import matplotlib.pyplot as plt
import polars as pl


# %%
def organize_files(cfg: dict, branch="incoming", verbosity=0) -> int:
    """Move files found in <root>/<branch>/<folders to subfolders organized by year, month(, day)

    Args:
        cfg (dict): must contain elements 
            "root" (str): path to parent of folders; 
            "branches" (str): folders between root and folders
            "folders" (list): list of folders where files are expected; 
            for each element in "folders", an entry 
                "name of folder" (dict): 
                    "pattern" (str): a regular expression matching the files to be moved:
                    "buckets" ("daily"|"monthly"): determines if subfolders are generated for days or only for months.
        branch (str, optional): specifies the branch below root to be processed. Defaults to "incoming".  
    Raises:
        ValueError: raised if value for buckets is not recognized.

    Returns:
        int: total number of files moved.
    """
    total = 0
    for folder in cfg["folders"]:
        pattern = cfg[folder]["pattern"]
        n = 0
        src = os.path.join(cfg["root"], branch, folder)
        # os.makedirs(src, exist_ok=True)
        files = os.listdir(src)
        for file in files:
            name = re.search(pattern, file)
            if name: 
                if re.search(r"d\{7\}\.", pattern):
                    dtm = time.strptime(re.search(r"\d{7}", name.group()).group(), "%j%Y")
                else:
                    dtm = time.strptime(re.search(r"\d{8}", name.group()).group(), "%Y%m%d")
                if cfg[folder]["buckets"] in "daily":
                    dst = os.path.join(src, 
                                       str(dtm.tm_year), "{:02d}".format(dtm.tm_mon), "{:02d}".format(dtm.tm_mday))
                elif cfg[folder]["buckets"] in "monthly":
                    dst = os.path.join(src, 
                                       str(dtm.tm_year), "{:02d}".format(dtm.tm_mon))
                elif cfg[folder]["buckets"] in "yearly":
                    dst = os.path.join(src, str(dtm.tm_year))
                else:
                    raise ValueError("'buckets' unknown.")
                os.makedirs(dst, exist_ok=True)
                if verbosity > 1:
                    print(f"{os.path.join(src, file)} > {os.path.join(dst, file)}")
                shutil.move(src=os.path.join(src, file),
                            dst=os.path.join(dst, file))
                n += 1
        if verbosity > 0:
            print(f"Finished organizing files under '{cfg['root']}{branch}/{folder}'. {n} files moved.")
        total += n
        # files = os.listdir(src)
        # if files==list():
        #     os.removedirs(src)
    return total


def move_files(source: str, target: str, pattern: str=None, verbose: bool=True) -> int:
    """Move files from source and sub-folders to target.

    Args:
        source (str): Absolute path to source directory
        target (str): Absolute path to target directory
        verbose (bool, optional): Print current activity to stdout. Defaults to True.
    """
    try:
        n = 0
        os.makedirs(target, exist_ok=True)
        for root, dirs, files in os.walk(source):
            for file in files:
                src=os.path.join(root, file)
                dst=os.path.join(target, file)
                if pattern:
                    if bool(re.search(pattern, file)):
                        # print(f"{pattern}: {src} > {dst}")
                        shutil.move(src=src, dst=dst)
                        n += 1
                else:
                    # print(f"{src} > {dst}")
                    # shutil.move(src=src, dst=dst)
                    n += 1
                if verbose:
                    print(f"{n}: {src} > {dst}")

            # remove empty directories
            try:
                os.rmdir(root)
            except:
                pass

        if verbose:
            print(f"Done, {n} files moved from {source} to {target}.")
        return n
    except Exception as err:
        print(err)
        if verbose:
            print(f"{n} files moved from {source} to {target} before encountering above error.")
        return n


def organize_files_by_year_month_day(source: str, verbose: bool=True) -> int:
    """Move files from source and sub-folders to target.

    Args:
        source (str): Absolute path to source directory
        verbose (bool, optional): Print current activity to stdout. Defaults to True.
    """
    if verbose:
        print(f"### organize_files_by_year_month_day under '{source}' ...")
    if not os.path.exists(source):
        print(f"Source folder '{source}' does not exist.")
        return

    duplicates_folder = os.path.join(source, 'duplicates')
    if not os.path.exists(duplicates_folder):
        os.makedirs(duplicates_folder)

    for root, dirs, files in os.walk(source):
        for file in files:
            try:
                # Split file name and extension
                name, ext = os.path.splitext(file)
                parts = name.split('-')
                
                # if len(parts) != 2:
                #     continue
                
                prefix, datetime_part = parts
                # if len(datetime_part) != 12:
                #     continue

                # Parse the date and time part
                try:
                    dt = datetime.strptime(datetime_part, '%Y%m%d%H%M')
                except ValueError:
                    print(f"{file} name does not contain a proper datetime.")
                    continue
                
                year = dt.strftime('%Y')
                month = dt.strftime('%m')
                day = dt.strftime('%d')

                # Create target directory structure
                target_dir = os.path.join(source, year, month, day)
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)

                source_path = os.path.join(root, file)
                target_path = os.path.join(target_dir, file)

                # Check if the file is already in the right place
                if os.path.abspath(source_path) == os.path.abspath(target_path):
                    continue

                if os.path.exists(target_path):
                    # Move to duplicates if file already exists
                    duplicate_target = os.path.join(duplicates_folder, file)
                    count = 1
                    while os.path.exists(duplicate_target):
                        duplicate_target = os.path.join(duplicates_folder, f"{os.path.splitext(file)[0]}_{count}{ext}")
                        count += 1
                    if verbose:
                        print(f"Moving duplicate file to {duplicate_target}.")
                    shutil.move(source_path, duplicate_target)
                else:
                    # Move file to the target directory
                    if verbose:
                        print(f"Moving {source_path} to {target_path}.")
                    shutil.move(source_path, target_path)
            except Exception as err:
                print(f"Error processing file '{file}': {err}")


def find_empty_folders(source: str, verbose: bool=True, delete: bool=True) -> int:
    """Remove empty folders under source. Uses the system function 'find', which is only available under linux.

    Args:
        source (str): full path to source folder
        verbose (bool, optional): Should the path of empty folders be printed to stdout?. Defaults to True.

    Returns:
        int: Number of empty folders found
    """
    if verbose:
        print(f"### find_empty_folders under '{source}' with option delete={delete} ...")
    delete = '-delete' if delete else ''
    if platform.system() in ['Linux', 'Darwin']:  # 'Darwin' is macOS
        try:
            # Ensure the folder exists
            if not os.path.isdir(source):
                print(f"The specified folder '{source}' does not exist.")
                return

            # Run the `find` command with the specified parameters (use the -print option and subprocess.PIPE to redirect output)
            result = subprocess.run(['find', source, '-empty', '-type', 'd', '-print', delete], 
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            folders = result.stdout.strip().split('\n')
            # Print the output
            if verbose:
                if result:
                    if delete:
                        caveat = " and deleted."
                    print(f"Empty folders found{caveat}: {folders}")
                else:
                    print("No empty folders found.")
            return len(folders)
        except subprocess.CalledProcessError as err:
            # Handle any errors that occur during the execution of the command
            print(f"Error executing find command: {err}")
    else:
        raise ValueError("OS currently not supported.")


def remove_empty_files_and_folders(source: str=str()):
    try:
        if os.path.exists(source):
            for root, dirs, files in os.walk(source):
                if len(files)==0 and len(dirs)==0:
                    os.removedirs(root)
                    print(f"{root} removed.")
                
                for file in files:
                    src = os.path.join(root, file)
                    print(f"processing {src}")
                    # If the file is a ZIP file, read it from the archive
                    if zipfile.is_zipfile(src):
                        with zipfile.ZipFile(src, 'r') as zip_file:
                            # Get the first CSV file in the archive
                            csv_files = [f for f in zip_file.namelist() if f.endswith(('.dat', '.csv'))]
                            if not csv_files:
                                raise ValueError("No CSV files found in the zip archive.")
                            with zip_file.open(csv_files[0]) as fh:
                                tmp = fh.readline()
                                if len(tmp)==0  or tmp==b'\r\n' or tmp==b'':
                                    os.remove(src)
                                    print(f"{src} removed.")

                    # If it's not a ZIP file, process it directly
                    else:
                        with open(src, 'r') as fh:
                            tmp = fh.readline()
                            if len(tmp)==0:
                                os.remove(src)
                                print(f"{src} removed.")
    except Exception as err:
        print(err)


def get_file_counts(base_path: str, base_name: str, base_folders: dict={'incoming':'incoming', 'archive':'archive', 'issues':'issues'}, n_days: int=7) -> pl.DataFrame:
    """
    Scan directories ('incoming', 'archive', 'issues'), count files for each <name> per day.
    """
    file_name_pattern = re.compile(rf'({base_name})-(\d{{8}})(\d{{4}})?(\d{{2}})?\.(\w+)$')
    
    # Get the last N days as datetime objects
    today = datetime.datetime.now()#.strftime('%Y%m%d')
    valid_dates = { (today - datetime.timedelta(days=i)).strftime('%Y%m%d'): (today - datetime.timedelta(days=i)).date() for i in range(n_days) }
    
    file_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # {date: {name: {folder: count}}}
    
    for folder_key, folder in base_folders.items():
        folder_path = os.path.join(base_path, folder, base_name)
        if not os.path.exists(folder_path):
            continue
        
        for root, _, files in os.walk(folder_path):
            for file in files:
                match = re.match(file_name_pattern, file)
                if match:
                    name, date_str = match.group(1), match.group(2)
                    if date_str in valid_dates:
                        file_counts[date_str][name][folder_key] += 1
    
    # Convert to polars DataFrame
    data = []
    for date_str, names in file_counts.items():
        for name, folders in names.items():
            incoming_count = folders.get('incoming', 0)
            archive_count = folders.get('archive', 0)
            issues_count = folders.get('issues', 0)
            total_count = incoming_count + archive_count + issues_count
            data.append([
                valid_dates[date_str], name,
                incoming_count,
                archive_count,
                issues_count,
                total_count
            ])
    
    df = pl.DataFrame(data, schema=["date", "name", "incoming", "archive", "issues", "total"])
    return df

# def plot_file_counts(df: pl.DataFrame):
#     """
#     Create a stacked bar plot showing the number of files per day, categorized by folder type.
#     """
#     df = df.melt(id_vars=['date', 'name'], value_vars=['incoming', 'archive', 'issues'], variable_name='folder', value_name='count')
    
#     plt.figure(figsize=(12, 6))
#     plt.bar(data=df.to_pandas(), x='date', y='count', hue='folder', estimator=sum)
#     plt.xticks(rotation=45)
#     plt.xlabel("Date")
#     plt.ylabel("File Count")
#     plt.title("File Counts Over the Last N Days")
#     plt.legend(title="Folder")
#     plt.show()
def plot_file_counts(df: pl.DataFrame):
    """
    Create a stacked bar plot showing the number of files per day, categorized by folder type.
    """
    df = df.melt(id_vars=['date', 'name'], value_vars=['incoming', 'archive', 'issues'], variable_name='folder', value_name='count')
    
    plt.figure(figsize=(12, 6))
    unique_dates = df['date'].unique().to_list()
    bottom_values = {folder: [0] * len(unique_dates) for folder in ['incoming', 'archive', 'issues']}
    
    for folder in ['incoming', 'archive', 'issues']:
        counts = [df.filter((df['date'] == date) & (df['folder'] == folder))['count'].sum() for date in unique_dates]
        plt.bar(unique_dates, counts, label=folder, bottom=bottom_values[folder])
        bottom_values[folder] = [b + c for b, c in zip(bottom_values[folder], counts)]
    
    plt.xticks(rotation=45)
    plt.xlabel("Date")
    plt.ylabel("File Count")
    plt.title("File Counts Over the Last N Days")
    plt.legend(title="Folder")
    plt.show()
    return

# Example usage:
# base_directory = "/path/to/root"  # Change this to the actual path
# n_days = 30  # Adjust as needed
# df = get_file_counts(base_directory, n_days)
# plot_file_counts(df)

# %%
if __name__ == "__main__":
    pass

