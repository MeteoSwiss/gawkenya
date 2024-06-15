# gawkenya
Support an end-to-end data chain from instrument to raw data to clean data to products for GAW Kenya.

# setup
## Install pyenv
1. Follow directions under https://realpython.com/intro-to-pyenv/, basically
   $ curl https://pyenv.run | bash
   $ pyenv install -v 3.11
2. Verify with 
   $ pyenv versions, which should show something like
    * system (set by /home/zue/users/jkl/.pyenv/version)
      3.11.7
3. Test installation (NB: this will take some time) with
   $ pyenv global 3.11.7
   $ python -m test
4. Create virtual environment with
   $ pyenv virtualenv 3.11.7 gawkenya
5. Activate the environment
   $ pyenv local gawkenya
6. Install requirements (NB: path depends on your local git)
   $ pyenv exec pip install -r "/home/zue/users/jkl/Public/git/gawkenya/requirements.txt"

## Install nappy (needed for AMES files only)
- pip install nappy  
If that does not work, try: 
- pip install git+https://github.com/joergklausen/nappy.git
<!-- There is a bug in the original distribution that prevents a normal pip install. Workaround: Forked the original repo, commented out line 17 in /utils/common_utils.py. Then, the following worked without errors pip install git+https://github.com/joergklausen/nappy.git -->

# Repo structure

- `analyses`: Analyses of level 2 data (from WDC), comparison with e.g. CAMS data. See [separate README](analyses\README_analyses.md). 
  - `input/`: scripts to read the data (CAMS model data and measurement data from WDC and ) \
  - `output/`: Save analyses figures (saved locally only, excluded from git) \
  - `plotting/`: scripts for plotting:
  * `plot_curve_fits.ipynb`: Use the NOAA curve-fitting approach (saved in `utils/ccg_filter`) to run curve fits and remove trends from the data. Make plots with the fitted lines.
  - `utils`:  utilities required for the analyses 
- `data`
  - `level1`
    - monthly folders for monthly .parquet files (g2401)
    - yearly .parquet data (ae33, aerosol: A11a, S11a, S11c, S11k, S11m, S11s)
- `ez_flag_data`
  - TODO: explainations
- `housekeeping`
  - TODO: explainations
- `monitoring`
  - TODO: explainations
- `obsolete`: contains the scripts by Sarina to make data plots for a poster. 
- `processing`: contains one python script to process data from each instrument (e.g. `ae33.py`) or database (e.g. `ebas.py`)
- `results`: some outputs
- `sandbox`
- `tests`
- `toolbox`
- `.`
  - `[...]_compile_[...].ipynb`: jupyter notebooks to compile .... TODO 
  - `[...]_process_[...].ipynb`: jupyter notebooks to process .... TODO 

