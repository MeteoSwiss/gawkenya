import os
import polars as pl
import matplotlib.pyplot as plt
from io import BytesIO
import json
import tarfile

class CPD2:
    """NOAA CPD2 tarball
    """
    def __init__(self):
        print("CPD2 initialized.")


    def extract_tarball_to_dataframe(self, path: str, dtm: str="dtm") -> dict:
        """Extract CPD2 tarballs from 'source' and process files.

        Aurora 3000 nephelometer
        a -	High frequency. Scattering, backscattering, temperature, RH and pressure.
        m - Low frequency. Status: Reference.
        s - Statewise. Flags.
        c -	Zero results. Background
        k -	Spancheck results. 
        
        The F2 field is the bitwise OR of the neph status.
        Bits 	Description 	                Origin
        0x0001 	Cell heater off 	            Instrument
        0x0002 	Inlet heater off 	            Instrument
        0x0004 	Sample pump on 	                Instrument
        0x0008 	Zero pump on 	                Instrument
        0x0010 	Span gas valve open 	        Instrument
        0x0080 	Digital aux port on 	        Instrument
        0x0200 	STP correction applied 	        data.edit.standard_corr, data.edit.corr.neph_stp
        0x0400 	Truncation correction applied 	data.edit.standard_corr, data.edit.corr.neph_trunc
        0x0800 	Wavelength adjusted to PSAP 	Never set
        0x2000 	Zero mode 	                    CPD2 (from 00 register and zero issue)
        0x4000 	Blank mode 	                    CPD2 (from explicit blanking time)
        0x8000 	Other calibration 	            CPD2 (from 00 register) 

        Magee AE31 aethalometer
        [TODO]

        Args:
            path (str): Path to CPD2 tarball
        Returns:
            dict: 
                'errors' : list of files that threw an error and were excluded from processing
                'S11a' : polars DataFrame of nephelometer data
                ...
                'A11a' : polars df of aethalometer data
        """
        cpd2 = {'errors': dict(),
                'S11a': pl.DataFrame(), 
                'S11c': pl.DataFrame(), 
                'S11k': pl.DataFrame(), 
                'S11m': pl.DataFrame(), 
                'S11s': pl.DataFrame(), 
                'A11a': pl.DataFrame()
                }

        # configuration of headers
        hdrs_S11 = {'S11a':('S11a','STN','EPOCH',f"{dtm}",'F1_S11','F2_S11','BsB_S11','BsG_S11','BsR_S11','BbsB_S11','BbsG_S11','BbsR_S11','T1_S11','T2_S11','U_S11','P_S11'),
                'S11c':('S11c','STN','EPOCH',f"{dtm}",'BswB_S11','BswG_S11','BswR_S11','BbswB_S11','BbswG_S11','BbswR_S11'),
                'S11k':('S11k','STN','EPOCH',f"{dtm}",'P1_S11','P2_S11','T3_S11','T4_S11','U1_S11','U2_S11','DEN1_S11','DEN2_S11','Csr1B_S11','Csr1G_S11','Csr1R_S11','Cbsr1B_S11','Cbsr1G_S11','Cbsr1R_S11','Csd1B_S11','Csd1G_S11','Csd1R_S11','Cbsd1B_S11','Cbsd1G_S11','Cbsd1R_S11','Csp1B_S11','Csp1G_S11','Csp1R_S11','Cbsp1B_S11','Cbsp1G_S11','Cbsp1R_S11','Csr2B_S11','Csr2G_S11','Csr2R_S11','Cbsr2B_S11','Cbsr2G_S11','Cbsr2R_S11','Csd2B_S11','Csd2G_S11','Csd2R_S11','Cbsd2B_S11','Cbsd2G_S11','Cbsd2R_S11','Csp2B_S11','Csp2G_S11','Csp2R_S11','Cbsp2B_S11','Cbsp2G_S11','Cbsp2R_S11','CsnB_S11','CsnG_S11','CsnR_S11','CbsnB_S11','CbsnG_S11','CbsnR_S11','Bs1B_S11','Bs1G_S11','Bs1R_S11','Bbs1B_S11','Bbs1G_S11','Bbs1R_S11','Bs2B_S11','Bs2G_S11','Bs2R_S11','Bbs2B_S11','Bbs2G_S11','Bbs2R_S11','Bs2gB_S11','Bs2gG_S11','Bs2gR_S11','Bbs2gB_S11','Bbs2gG_S11','Bbs2gR_S11','PCTsB_S11','PCTsG_S11','PCTsR_S11','PCTbsB_S11','PCTbsG_S11','PCTbsR_S11'),
                'S11m':('S11m','STN','EPOCH',f"{dtm}",'CrG_S11','BswB_S11','BswG_S11','BswR_S11','BbswB_S11','BbswG_S11','BbswR_S11','Calparams60_1_S11','Calparams60_2_S11','Calparams60_3_S11','Calparams60_4_S11','Calparams60_5_S11','Calparams60_6_S11','Calparams60_7_S11','Calparams60_8_S11','Calparams60_9_S11','Calparams60_10_S11','Calparams60_11_S11','Calparams60_12_S11','Calparams60_13_S11','Calparams61_1_S11','Calparams61_2_S11','Calparams61_3_S11','Calparams61_4_S11','Calparams61_5_S11','Calparams61_6_S11','Calparams61_7_S11','Calparams61_8_S11','Calparams61_9_S11','Calparams61_10_S11','Calparams61_11_S11','Calparams61_12_S11','Calparams61_13_S11','Calparams62_1_S11','Calparams62_2_S11','Calparams62_3_S11','Calparams62_4_S11','Calparams62_5_S11','Calparams62_6_S11','Calparams62_7_S11','Calparams62_8_S11','Calparams62_9_S11','Calparams62_10_S11','Calparams62_11_S11','Calparams62_12_S11','Calparams62_13_S11','Calparams63_1_S11','Calparams63_2_S11','Calparams63_3_S11','Calparams63_4_S11','Calparams63_5_S11','Calparams63_6_S11','Calparams63_7_S11','Calparams63_8_S11','Calparams63_9_S11','Calparams63_10_S11','Calparams63_11_S11','Calparams63_12_S11','Calparams63_13_S11','Calparams64_1_S11','Calparams64_2_S11','Calparams64_3_S11','Calparams64_4_S11','Calparams64_5_S11','Calparams64_6_S11','Calparams64_7_S11','Calparams64_8_S11','Calparams64_9_S11','Calparams64_10_S11','Calparams64_11_S11','Calparams64_12_S11','Calparams64_13_S11','Calparams65_1_S11','Calparams65_2_S11','Calparams65_3_S11','Calparams65_4_S11','Calparams65_5_S11','Calparams65_6_S11','Calparams65_7_S11','Calparams65_8_S11','Calparams65_9_S11','Calparams65_10_S11','Calparams65_11_S11','Calparams65_12_S11','Calparams65_13_S11'),
                'S11s':('S11s','STN','EPOCH',f"{dtm}",'F2_S11'),
                }
        hdrs_A11 = {'A11a':('A11a','STN','EPOCH',f"{dtm}",'Q_A11','PCT_A11','X1c_A11','X2c_A11','X3c_A11','X4c_A11','X5c_A11','X6c_A11','X7c_A11','ZIr1_A11','ZIr2_A11','ZIr3_A11','ZIr4_A11','ZIr5_A11','ZIr6_A11','ZIr7_A11','Ipz1_A11','Ipz2_A11','Ipz3_A11','Ipz4_A11','Ipz5_A11','Ipz6_A11','Ipz7_A11','Ip1_A11','Ip2_A11','Ip3_A11','Ip4_A11','Ip5_A11','Ip6_A11','Ip7_A11','Ifz1_A11','Ifz2_A11','Ifz3_A11','Ifz4_A11','Ifz5_A11','Ifz6_A11','Ifz7_A11','If1_A11','If2_A11','If3_A11','If4_A11','If5_A11','If6_A11','If7_A11'),
                }

        try:
            # Open the tarball file
            with tarfile.open(path, 'r:gz') as tar:
                # Iterate over each file in the tarball
                for member in tar.getmembers():
                    if 'S11' in member.name or 'A11' in member.name:
                        print(f"Processing {member.name} ...")

                        # read the contents of the file
                        file_content = tar.extractfile(member).read()

                        # convert the file content to a polars DataFrame
                        # read in file w/o separator to allow for lines of different lengths, then split.
                        # using this approach, try_parse_dates cannot work, thus convert after parsing.
                        try:
                            df = pl.read_csv(BytesIO(file_content), 
                                        has_header=False, 
                                        separator=chr(0),
                                        comment_char="!",
                                        ).select(tmp=pl.col('column_1')
                                        .str.split(',')
                                        .list.to_struct(
                                            n_field_strategy='max_width',
                                            fields=lambda x:f"column_{x+1}"
                                        )).unnest('tmp').with_columns(
                                            pl.col('column_4')
                                            .str.to_datetime(format='%Y-%m-%dT%H:%M:%SZ', time_zone='UTC'))

                            if 'S11' in member.name:
                                hdrs = hdrs_S11
                                exclude = "^(F|S).*$"
                            elif 'A11' in member.name:
                                hdrs = hdrs_A11
                                exclude = "^(S|A).*$"
    
                            for k, v in hdrs.items():
                                cpd2[k] = df.filter(pl.col('column_1')==k)[:, :len(v)]
                                cpd2[k].columns = v

                                # cast some of the Utf8 to Float32
                                try:
                                    # if 'S11' in member.name:
                                    #     exclude = "^(F|S).*$"
                                    # elif 'A11' in member.name:
                                    #     exclude = "^(A|S).*$"
                                    cpd2[k] = cpd2[k].with_columns(pl.col(pl.Utf8).exclude(exclude).cast(pl.Float32))
                                except Exception as err:
                                    print(err)
                                    pass

                                # sort data by DateTime and store
                                cpd2[k] = cpd2[k].sort(f"{dtm}")

                        except Exception as err:
                            cpd2['errors'][member.name] = str(err)
                            print(f"Error processing {member.name}: {cpd2['errors'][member.name]} ... file ignored!")
                            pass

            return cpd2

        except Exception as err:
            print(err)         


    def tarballs_to_parquet(self, source: str, target: str, dtm="dtm", archive: str=None, issues: str=None, append_parquet: bool=True, plot: bool=True, verbose: bool=True) -> dict:
        """Process CPD2 tarballs found in source and its sub-folders, compile data found in tarball members in polars DataFrames, save as parquet files in target. Optionally plot the data.

        Args:
            source (str): Path to directory to process. Sub-directories will also be considered.
            target (str): Path to directory where .parquet files will be stored.
            dtm (str, optional): Name of dateTime column. Defaults to 'dtm'.
            archive (str, optional): Root path to directory where files will be archived. Sub-folders will be created corresponding to source. Defaults to None.
            issues (str, optional): Root path to directory where file that could not be processed are moved to. Defaults to None.
            append_parquet (bool, optional): If True, append new data to an existing .parquet file. Defaults to True.
            plot (bool, optional): Should the resulting DataFrames be visualized? Defaults to True.
            verbose (bool, optional): Should information on process be written to console? Defaults to True.
        Returns:
            dict: name of files that could not be processed as well as errors encountered.
        """
        result = {'S11a': pl.DataFrame(), 
                'S11c': pl.DataFrame(), 
                'S11k': pl.DataFrame(), 
                'S11m': pl.DataFrame(), 
                'S11s': pl.DataFrame(), 
                'A11a': pl.DataFrame()}
        errors = dict()
        try:
            # process files
            if verbose:
                print(f"Processing source {source} ...")
            for root, dirs, files in os.walk(source):
                for file in files:
                    if verbose:
                        print(f"Processing {file} ...")
                    tmp = self.extract_tarball_to_dataframe(os.path.join(root, file))
                    if tmp['errors']:
                        errors.update(tmp['errors'])
                        del tmp['errors']
                        if issues:
                            print("Moving to issues")
                    elif archive:
                        print("Moving to archive") # verify path, add year, month??
                    for k, v in tmp.items():
                        result[k] = pl.concat([result[k], v], how='diagonal')

            # create target directory if it doesn't yet exist
            os.makedirs(target, exist_ok=True)

            # split result according to data type and store as separate parquet files
            for k, v in result.items():
                if not result[k].is_empty():
                    result[k] = result[k].sort(dtm)
                    file = os.path.join(target, f"{k}.parquet")
                    if os.path.exists(file):
                        df = pl.read_parquet(source=file)
                        result[k] = pl.concat([df, result[k]])
                    result[k] = result[k].unique()
                    result[k] = result[k].sort(dtm)
                    result[k].write_parquet(file)

                    # plot data
                    if plot:
                        self.plot_dataframe(result, dtm=dtm, type=k)

            # write errors to json file
            with open(os.path.join(target, f"{k}.errors.json"), "a") as fh:
                json.dump(errors, fh)

            return errors

        except Exception as err:
            print(err)         
            

    def plot_dataframe(self, cpd2: dict, type: str=["A11a", "S11a", "S11c", "S11m"], dtm="dtm", start:str=None, end:str=None, title:str="MKN", use_flags=True) -> None:
        try:
            if type=="A11a":
                self.plot_aethalometer_data(cpd2[type], variable="eBC", dtm=dtm, start=start, end=end, title=title)
            elif type in ["S11a", "S11c", "S11k", "S11m"]:
                self.plot_nephelometer_data(cpd2[type], type=type, dtm=dtm, start=start, end=end, title=title, use_flags=use_flags)
            else:
                raise ValueError(f"Type not recognized (source: plot_dataframe)")
        except Exception as err:
            print(err)


    def plot_nephelometer_data(self, df: pl.DataFrame, type: str=["S11a", "S11c", "S11m"], dtm="dtm", start:str=None, end:str=None, title:str="MKN Aurora 3000", use_flags: bool=True, upper_limit: int=2000) -> None:
        """Plot a polars DataFrame containing nephelometer data.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            type (str): Type of dataframe, one of ["S11a", "S11c", "S11m"]
            start (str): Start date of period to plot. Defaults to None.
            end (str): End date of period to plot. Defaults to None.
            title (str): Title of plot. Defaults to "MKN Aurora 3000"
            use_flags (bool): Should data be filtered by flag before plotting? If true, only data with flag "0007" are retained. Defaults to True
            upper_limit (int): Maximum value to be retained. Defaults to 2000.
        """
        try:
            df = df.sort(dtm)

            if start:
                df = df.filter(pl.col(dtm) >= pl.lit(start).str.strptime(pl.Date))
            if end:
                df = df.filter(pl.col(dtm) <= pl.lit(end).str.strptime(pl.Date))

            if type=="S11a":
                sfx = ""
                title1 = "Aerosol total light scattering coefficient"
                title2 = "Aerosol backwards-hemispheric light scattering coefficient"
                if use_flags:
                    __df = df.filter(((pl.col("F2_S11")=="0007") | (pl.col("F2_S11")=="00AB") | (pl.col("F2_S11")=="0093")) & (pl.col(f"Bs{sfx}B_S11") < upper_limit))
                else:
                    __df = df.filter(pl.col(f"Bs{sfx}B_S11") < upper_limit)
            elif type in ["S11c", "S11m"]:
                sfx = "w"
                title1 = "Aerosol total light scattering coefficient background"
                title2 = "Aerosol backwards-hemispheric light scattering coefficient background"
                __df = df
            else:
                raise ValueError(f"Type not recognized (source: plot_nephelometer_data)")
                
            plt.figure(figsize=(12, 6))
            ax1 = plt.subplot(211)
            plt.scatter(__df[dtm], __df[f"Bs{sfx}B_S11"], c="b", marker="o", s=2)
            plt.scatter(__df[dtm], __df[f"Bs{sfx}G_S11"], c="g", marker="o", s=2)
            plt.scatter(__df[dtm], __df[f"Bs{sfx}R_S11"], c="r", marker="o", s=2)
            plt.legend([f"Bs{sfx}B", f"Bs{sfx}G", f"Bs{sfx}R"])
            plt.tick_params('x', labelbottom=False)
            plt.suptitle(f"{title} ({type} data)")
            plt.title(title1)
            plt.ylabel('(1/Mm)')

            ax2 = plt.subplot(212, sharex=ax1)
            plt.scatter(__df[dtm], __df[f"Bbs{sfx}B_S11"], c="b", marker="o", s=2)
            plt.scatter(__df[dtm], __df[f"Bbs{sfx}G_S11"], c="g", marker="o", s=2)
            plt.scatter(__df[dtm], __df[f"Bbs{sfx}R_S11"], c="r", marker="o", s=2)        
            plt.legend([f"Bbs{sfx}B", f"Bbs{sfx}G", f"Bbs{sfx}R"])
            plt.title(title2)
            plt.ylabel('(1/Mm)')

            plt.xlabel(dtm)
            plt.show()
        except Exception as err:
            print(err)


    def plot_aethalometer_data(self, df: pl.DataFrame, variable:str=["eBC"], dtm="dtm", start:str=None, end:str=None, title:str="MKN Magee AE31") -> None:
        """Plot a polars DataFrame containing nephelometer data.

        Args:
            df (pl.DataFrame): Polars DataFrame, with columns depending on <type>
            title (str): Title of plot. Defaults to "MKN Magee AE31"
        """
        try:
            df = df.sort(dtm)

            if start:
                df = df.filter(pl.col(dtm) >= pl.lit(start).str.strptime(pl.Date))
            if end:
                df = df.filter(pl.col(dtm) <= pl.lit(end).str.strptime(pl.Date))

            if variable=="eBC":
                variable = "X"
                sfx = "c"
                subtitle = "Equivalent Black Carbon Concentration"
                ylabel = "(ng/m3)"
                legend = ('370 nm', '470 nm', '521 nm', '590 nm', '660 nm', '880 nm', '950 nm')
                __df = df
            else:
                raise ValueError(f"Type not recognized (source: plot_aethalometer_data)")
            
            c = ('purple', 'darkblue', 'blue', 'green', 'gold', 'orange', 'red')
            plt.figure(figsize=(12, 6))
            for i in range(1, 8):
                plt.scatter(__df[dtm], __df[f"{variable}{i}{sfx}_A11"], c=c[i-1], marker="o", s=2)
            plt.legend(legend)
            plt.suptitle(title)
            plt.title(subtitle)
            plt.xlabel(dtm)
            plt.ylabel(ylabel)
            plt.show()
        except Exception as err:
            print(err)
