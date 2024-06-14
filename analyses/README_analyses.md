# Analyses level 2

This folder contains scripts to analyse the processed Mt. Kenya measurement data (level 2), including comparison to model (CAMS) data. 

The analyses is focussing on data since 2020. However, some additional data (e.g. flask data) is available for earlier years. 


# Files and folder structure of the analyses-folder
### Folders
`input/`: scripts to read the data (CAMS model data and measurement data from WDC and ) \
`output/`: Save analyses figures (saved locally only, excluded from git) \
`plotting/`: scripts for plotting:
  * `plot_curve_fits.ipynb`: Use the NOAA curve-fitting approach (saved in `utils/ccg_filter`) to run curve fits and remove trends from the data. Make plots with the fitted lines.

`utils`:  utilities required for the analyses 

### Files
Jupyter-notebooks for data-analysis and plotting: 
* `analyses_stepbystep.ipynb`: step-by-step procedure to obtain measurement and CAMS data
* `check_camsp.ipynb`: Notebook to check and analyse cams data
* `check_data.ipynb`: General notebook to check measurement data
* `check_fires.ipynb`: Notebook to check CAMS GFAS fire data, also compare it with e.g. CO measurement data. 


# How to
To obtain the CAMS data and read in the measurement data from the WDC (World data center), use the file `analyses_stepbystep.ipynb`

To plot different datasets and do some analyses, use the `check_[...].ipynb` notebooks



