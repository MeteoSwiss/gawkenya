# Analyses level 2

This folder contains scripts to analyse the processed Mt. Kenya measurement data (level 2), including comparison to model (CAMS) data.  
The analyses is focussing on data since 2020. However, some additional data (e.g. flask data) is available for earlier years. 

## **Content:**
<!-- vscode-markdown-toc -->
* [Files and folder structure](#fiels_folders)
  * [Folder structure](#Folders)
  * [Files](#Files)
* [How to](#Howto)
* [CAMS data](#CAMSdata)
	* [Which CAMS data do we use?](#WhichCAMSdatadoweuse)
	* [Details CAMS best-grid selection](#DetailsCAMSbest-gridselection)

<!-- vscode-markdown-toc-config
	numbering=false
	autoSave=true
	/vscode-markdown-toc-config -->
<!-- /vscode-markdown-toc -->




## <a name='fiels_folders'></a>Files and folder structure
### <a name='Folders'></a>Folders
`input/`: scripts to read the data (CAMS model data and measurement data from WDC and ) \
`output/`: Save analyses figures (saved locally only, excluded from git) \
`plotting/`: scripts for plotting:
  * `plot_curve_fits.ipynb`: Use the NOAA curve-fitting approach (saved in `utils/ccg_filter`) to run curve fits and remove trends from the data. Make plots with the fitted lines.

`utils`:  utilities required for the analyses 

### <a name='Files'></a>Files
Jupyter-notebooks for data-analysis and plotting: 
* `analyses_stepbystep.ipynb`: step-by-step procedure to obtain measurement and CAMS data
* `check_camsp.ipynb`: Notebook to check and analyse cams data
* `check_data.ipynb`: General notebook to check measurement data, for example the seasonal cycles
* `check_fires.ipynb`: Notebook to check CAMS GFAS fire data, also compare it with e.g. CO measurement data. 


## <a name='Howto'></a>How to
To obtain the CAMS data and read in the measurement data from the WDC (World data center), use the file `analyses_stepbystep.ipynb`.  
To plot different datasets and do some analyses, use the `check_[...].ipynb` notebooks (e.g. `check_cams.ipynb`).  
More advanced scripts for figures are found in `plotting/` (e.g. the notebook to create figures with curve fitting, `plotting/plot_curve_fits.ipynb`). 

## <a name='CAMSdata'></a>CAMS data
The CAMS data is very large and is thus not saved in this git repository. 
You can download all the CAMS data as done step-by-step in `analyses_stepbystep.ipynb`. However, it requires to have a login at the [Atmosphere data store](https://ads.atmosphere.copernicus.eu/cdsapp#!/home) and an installation of [cdsapi](https://cds.climate.copernicus.eu/api-how-to). Also, the download may take several hours to days.  


Instead of downloading all the CAMS data, you can also just use the CAMS data that was already selected for the Mt. Kenya station, and that is saved in that repository at `data/level3/cams/cams_best_grid_merged_MKN.nc`
Some of the analyses will not work when only this selected CAMS-data is loaded (some cells in `check_cams.ipynb` or `check_fires.ipynb` will not work), but most figures and analyses work with this selection of CAMS data. 

> Remark: CAMS data selected for the Mt. Kenya station is saved in `cams_best_grid_merged_MKN.nc`. Why `_merged`? In the CAMS-INVGG data, the horizontal resolution changed in 2023. The original file `cams_best_grid_MKN.nc` (not saved in the git repository) contained both datasets (before and after the change) seperately (e.g. as co2_invgg and co2_invgg2). After selecting the best grid, they were merged into one single dataset (e.g. `CO2_invgg`) in the mentioned file `cams_best_grid_merged_MKN.nc`.  
For details, check how that was done in the section "Process cams_best_grid" in `analyses_stepbystep.ipynb`. 

### <a name='WhichCAMSdatadoweuse'></a>Which CAMS data do we use?
* **EAC4: Global reanalysis**
  * **Resolution**: 0.75° horizontal resolution, 3hours
  * **Time period**: 2003-2023
  * **Species**: CO, CH4 (chemistry), Ethane, Ozone, PM1, PM10, PM2.5, aerosol optical depths (865-1240, 5ch.), Aerosol mixing ratios
  * **Meteo**: 10m-wind, wind, 2m-T, T, RfH, p_surf
  * **Area**: Area: Mt. Kenya +/- 5*0.75 (->[ 0.7, -0.8, 39 , 36.5]))

* **CAMS global inversion-optimised greenhouse gas fluxes and concentrations**
  * **Resolution**: 3hourly (CO2), 6hourly (CH4)
    * CO2: before 07-2023: 2.5°lon x 1.27°lat, after 07-2023: 1.4° lon, 0.7°lat
    * CH4: 2020-2021: 2° lat, 3°lon, After 2022: 1°lat, 1°lon
  * **Time period**: 2020-2023 (CO2), 2020-2022 (CH4)
  * **Species**: 
    * CO2, with satellites as  input-observations
      * Assimilated satellite data: OCO-2
    * CH4  with surface air-sample AND satellites as input
      * Assimilated satellite data: OCO-2
      * Assimilated surface data: NOAA [surface air sampling network](https://gml.noaa.gov/outreach/behind_the_scenes/network.html) 

* **EGG4**: Global GHG reanalysis: Finaly not used
  * **Resolution**: 0.75° horizontal resolution, 3h
  * **Time period**: 2003-2020
  * **Species**:  CO2, CH4 (and similar meteo data as in EAC4)

* **CAMS Global Fire Assimilation System (GFAS)**
  * **Resolution**:  0.1°
  * spatially gridded fire data
  * assimilates Fire radiative power (FRP) satellite data (NASA Terra MODIS and Aqua MODIS active fire products)


### <a name='DetailsCAMSbest-gridselection'></a>Details CAMS best-grid selection
The selection of the best CAMS-grid is done by checking the best average correlation between the measured variables and the corresponding CAMS data. This is done in `input.read_cams.get_best_cams()`
