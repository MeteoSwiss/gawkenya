# Analyses level 2

This folder contains scripts to analyse the processed Mt. Kenya measurement data (level 2), including comparison to model (CAMS) data. 

The analyses is focussing on data since 2020. However, some additional data (e.g. flask data) is available for earlier years. 


### Scripts
To obtain the CAMS data and read in the measurement data from the WDC (World data center), use the file `analyses_stepbystep.ipynb`

## Data
### Greehouse gases 
* **Variables**: CO2, CH4, N2O
  * data obtained from WDCGG: https://gaw.kishou.go.jp/
* Flask (event) and continuous daily aggregated data

### Other gases
* **Variables**: O3, CO
  * O3, COdata obtained from EBAS: https://ebas-data.nilu.no/Default.aspx
  * newest O3 data obtained from MCH (?)
* Flask (event) and continuous daily aggregated data, hourly averages for O3 data
  
### Aerosol particles
* **Variables**: Aerosol light backscattering coefficient & Aerosol light scattering coefficient (at 450nm, 525nm & 635nm), Equivalent black carbon at 880nm
  * _Aerosol light backscattering coefficient & Aerosol light scattering coefficient (at 450nm, 525nm & 635nm) in 2015 from EBAS: https://ebas-data.nilu.no/Default.aspx_
  * _All other data from MCH: M:\pay-data\data\pay\Kenya\MKN\incoming\ (\ae33 & \aerosol)_
* hourly averages

### Meteorology
* **Variables**: Pressure, Relative Humidity, Temperature, Wind direction, Wind speed, Global radiation, Precipitation
  * Older Pressure, Relative Humidity, Temperature, Wind direction & Wind speed data from EBAS: https://ebas-data.nilu.no/Default.aspx
  * Newer data from MCH: through jretrieve from dwh (see Jörg's git: \gaw-kenya\jretrieve.ipynb) (**not working yet!?**)
* hourly data
* [Script to create Plot](SD_Meteorology.ipynb)

## How To add new data to Plots
1. Download data from Data centre and add to data/wdc/ebas or data/wdc/wdcgg
2. If the species was not used so far, add it to the dictionary `AvailableData` (defined in `read_wdc_data.py`)
3. Run the plotting scripts

