# %%
# Author: joerg.klausen@meteoswiss.ch
import os
import re
import shutil
import time


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


# %%
if __name__ == "__main__":
    pass

