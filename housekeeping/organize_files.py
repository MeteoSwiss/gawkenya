# %%
# Author: joerg.klausen@meteoswiss.ch
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime


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

# %%
if __name__ == "__main__":
    pass

