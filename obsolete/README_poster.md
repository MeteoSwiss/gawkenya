# About
From Sarina.

Plotting time series of the available data at Mount Kenya (MKN). Example 2023:
![Poster 2023.](https://github.com/sdanioth/MKN_AvailableData_Plots/blob/main/Poster/Poster_MKN_dataseries.jpg)

* Poster can be found in /main/Poster/
* Data is available in /main/data/
* Plots are available in /main/Plots/

## Data and Scripts
### Greehouse gases 
* **Variables**: CO2, CH4, N2O, SF6, 13CO2, C18O2
  * data obtained from WDCGG: https://gaw.kishou.go.jp/
* Flask (event) and continuous daily aggregated data
* [Script to create Plot](SD_Greenhouse_gases.ipynb)

### Other gases
* **Variables**: O3, CO, H2, Ethane, Other VOCs (2-Methylbutane, 2-Methylpropane, n-Butane, n-Pentane, Propane)
  * H2  (& CO) data obtained from WDCGG: https://gaw.kishou.go.jp/
  * O3, CO, VOCs data obtained from EBAS: https://ebas-data.nilu.no/Default.aspx
  * newest O3 data obtained from MCH
* Flask (event) and continuous daily aggregated data, hourly averages for O3 data
* [Script to create Plot](SD_Other_gases.ipynb)
* [Script to arrange O3 MCH data](SD_Read_MCH_Files.ipynb)
  
### Aerosol particles
* **Variables**: Aerosol light backscattering coefficient & Aerosol light scattering coefficient (at 450nm, 525nm & 635nm), Equivalent black carbon at 880nm
  * Aerosol light backscattering coefficient & Aerosol light scattering coefficient (at 450nm, 525nm & 635nm) in 2015 from EBAS: https://ebas-data.nilu.no/Default.aspx
  * All other data from MCH: M:\pay-data\data\pay\Kenya\MKN\incoming\ (\ae33 & \aerosol)
* hourly averages
* [Script to create Plot](SD_Aerosol_particles.ipynb) 
* [Script to arrange AE31 and AE33 MCH data](SD_Read_MCH_Files.ipynb)

### Meteorology
* **Variables**: Pressure, Relative Humidity, Temperature, Wind direction, Wind speed, Global radiation, Precipitation
  * Older Pressure, Relative Humidity, Temperature, Wind direction & Wind speed data from EBAS: https://ebas-data.nilu.no/Default.aspx
  * Newer data from MCH: through jretrieve from dwh (see Jörg's git: \gaw-kenya\jretrieve.ipynb)
* hourly data
* [Script to create Plot](SD_Meteorology.ipynb)

## Python
* For Plots: used python version 3.10.6 
* For arranging MCH Files: used python version 3.8.10

## How To add new data to Plots
1. Download data from Data centre or arrange MCH data as in [Script](SD_Read_MCH_Files.ipynb)
2. Save them into the [Data Folder](data) 
3. Run the plotting scripts

