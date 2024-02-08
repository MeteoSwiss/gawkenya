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
<!-- There is a bug in the original distribution that prevents a normal pip install. Workaround: Forked the original repo, commented out line 17 in /utils/common_utils.py. Then, the following worked without errors
1. $ pip install git+https://github.com/joergklausen/nappy.git -->
1. pip install nappy

## Repo structure
- data
  - level1
    - monthly folders for monthly .parquet files (g2401)
    - yearly .parquet data (ae33, aerosol: A11a, S11a, S11c, S11k, S11m, S11s)



from Sarina:
# About
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

