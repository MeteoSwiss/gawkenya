# %%
# Author: joerg.klausen@meteoswiss.ch
import os
import shutil


# %%
def fix_meteo_file_names(root: str, scope=["incoming", "archive"]) -> int:
    """Rename VMSW43.\d{12}.* files to VRXA00.\d{12}.*; also remove .001 extension

    Args:
        root (str): path to root folder containing meteo bulletins
        scope (list, optional): Sub-folders of root to process. Defaults to ["incoming", "archive"].

    Returns:
        int: number of files moved.
    """
    try:
        paths = [os.path.join(root, sc, "meteo") for sc in scope]
        n = 0
        for path in paths:
            for dirpath, dirnames, filenames in os.walk(path, topdown=True):
                for file in filenames:
                    dst = file.replace("VMSW43", "VRXA00").replace(".001", "")
                    if dst != file:
                        shutil.move(src=os.path.join(dirpath, file),
                                    dst=os.path.join(dirpath, dst))
                        n += 1
        return n
    except Exception as err:
        print(err)

# %%
if __name__ == "__main__":
    pass

