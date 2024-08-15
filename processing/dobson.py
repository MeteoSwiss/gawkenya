import os
import datetime
import logging
import time
import re
# import pandas as pd
import polars as pl

# define constants
num = r"[-]?[0-9]+[\.]?[0-9]*"

class DData:
    def __init__(self, config, ver='v0.1'):
        self.root = config['root']
        
        # configure logging
        _logger = config['logging'].split('.')[0]
        self.logger = logging.getLogger(f"{_logger}.{__name__}")
        self.logger.info("Initialize DData")
        self._file_name = str()
        self._file_content = str()
        self._header = tuple()

    def _read_file(self, file: str):
        try:
            self._file_name = os.path.basename(file)
            with open(file, 'r') as f:
                self._file_content = f.read()
            return
        except Exception as err:
            self.logger.error(err)


    def _extract_file_header(self) -> list:
        try:
            if self._file_content:
                # construct parser for header information
                # header information is contained in elements of object header
                # basic and dN: 0-19
                # NTable: 20-21            
                # Zpoly: 22-34
                # EmpCor: 35-40
                regex_header = r"(Dobson\d+)\s" + (r"[ ]*(" + num + r")\s?") * 3 
                regex_header += r"(\w+)\s+" + (r"[ ]*(" + num + r")\s?") * 12
                regex_header += r"dN\s+" + (r"[ ]*(" + num + r")\s?") * 3
                regex_header += r"NTable\s?" + (r"((?:[ ]*" + num + r"\s?){31})\s+") * 3
    #            regex_header += r"((" + num + r"){31})\s+((" + num + r"){31})\s+"
                regex_header += r"Zpoly\s?" + (r"((?:[ ]*" + num + r"\s?){10})\s+") * 2
                regex_header += (r"((?:[ ]*" + num + r"\s+){4})") * 10
                regex_header += r"EmpCor\s+" + (r"((?:[ ]*" + num + r"\s?){3})\s+") * 2
                regex_header += r"((?:[ ]*" + num + r"\s?){2})\s+"
                regex_header += (r"((?:[ ]*" + num + r"\s?){5})\s+") * 2
                header = re.findall(regex_header, self._file_content)
                if header == []:
                    self.logger.error(f"Error reading {self._file_name}: Header section not recognized, giving up.")
                    return list()
                self._header = header[0]
                return self._header
            else:
                self.logger.error(f"File {self._file_name} is empty.")
        except Exception as err:
            self.logger.error(err)


    def _extract_file_data(self, scope: str="basic") -> pl.DataFrame:
        try:
            if self._file_content and self._header:              
                # construct parser for data information         
                # data information is contained in data (type: list)
                # If observations were repeated, data is a list of tuples.
                regex_data = r"([BCDFMSZ]+)\s([ ]*" + num + r")\s?([ACD]+)\s+"
                data = re.findall(regex_data, self._file_content)
                if data == []:
                    self.logger.error(f"Error reading {self._file_name}: Data section empty or not recognized, giving up.")
                    return pl.DataFrame()
                data = data[0]
                sequence = data[2]
                n = len(sequence)
                m = len(set(sequence)) - 1

                if scope == 'basic':
                    # Tuple structure:
                    # basic and sequence: 0-2
                    # single wavelengths block: 2+(1..n), 
                    #       where n: length of sequence
                    # wavelength pair blocks: 2+n+(1..m-1), 
                    #       where m: number of unique letters in sequence
                    # comment: 2+n+(m-1)+1
                    single = r"(?:X[ACD]\s+\d{2}:\d{2}:\d{2}\s+" + (r"(?:[ ]*" + num + r")\s+") * 3 + r")[ ]*(" + num + r")\s+"
                    pair = r"(?:(X[ACD]{2})\s+(\d{2}:\d{2}:\d{2})\s+" + (r"[ ]*(" + num + r")\s+") * 3 + r")\s?"
                    for i in sequence:
                        regex_data += single

                    # count possible pairs based on sequence, extend regex           
                    for i in range(m):
                        regex_data += pair 

                    regex_data += r"(?:comment\s?)?(.+)?"
                    data = re.findall(regex_data, self._file_content)
                    if data == []:
                        self.logger.error(f"Error reading {self._file_name}: Data section incomplete.")
                        return pl.DataFrame()

                    cols = ['source','type','sequence','comments','dtm','sza','mu']
                    cols += ['XAD','XCD','X1','X2','X3','X4','X5','X6','X7']
                            
                    res = []                
                    for i in range(len(data)):
                        # for each set of observations                    
                        # for each single observation according to sequence                        
                        dtm = "%s-%02d-%02d %s" % (self._header[3], int(self._header[2]), int(self._header[1]), data[i][n + 4])                    
                        row = [self._file_name] + [data[i][0]] + [data[i][2]]
                        row += [data[i][3+n+5*m]] + [dtm]
                        row += [data[i][3+n+3]] + [data[i][3+n+2]]
                        row += [data[i][3+n+4]]
                        if m>1:
                            row += [data[i][3+n+5*m-1]]
                        else:
                            row += ['']
                        row += data[i][3:(3+n)]
                        row += [''] * (7-n)
                        res.append(tuple(row))

                    df = pl.DataFrame(data=res, orient='row')
                    df.columns = cols

                if scope == 'full':
                    # Tuple structure:
                    # basic and sequence: 0-2
                    # single wavelengths block: 2+(1..n), 
                    #       where n: length of sequence
                    # wavelength pair blocks: 2+n+(1..m-1), 
                    #       where m: number of unique letters in sequence
                    # comment: 2+n+(m-1)+1
                    raise ValueError("Not implemented.")
                
                    # single = r"(X[ACD]\s+\d{2}:\d{2}:\d{2}\s+" + (r"(?:[ ]*" + num + r"\s+)") * 4 + r")"
                    # pair = r"(X[ACD]{2}\s+\d{2}:\d{2}:\d{2}\s+" + (r"(?:[ ]*" + num + r"\s+)") * 3 + r")"
                    # # count single wavelength observations based on sequence
                    # for i in sequence:
                    #     regex_data += single
                    # # count possible pairs based on sequence, extend regex           
                    # for i in range(m - 1):
                    #     regex_data += pair 
                    # regex_data += r"\s+comment\s?(.+)"
                    # data = re.findall(regex_data, txt)

                return df           
            else:
                self.logger.error(f"File {self._file_name} _file_content is empty.")
                return pl.DataFrame()

        except Exception as err:
            self.logger.error(err)


    def read_file(self, file: str) -> tuple[tuple[str], pl.DataFrame]:
        try:
            self.logger.info(f"Reading file {file}")
            self._read_file(file)
            header = self._extract_file_header()
            df_data = self._extract_file_data()

            return header, df_data

        except Exception as err:
            self.logger.error(err)


    def process_directory(self, path: str) -> tuple[list, pl.DataFrame]:
        try:
            header = []
            df_data = pl.DataFrame()
            for root, dirs, files in os.walk(path):
                cnt = 0
                self.logger.info(f"Processing {root} ...")
                for file in files:
                    self.logger.info(f"Processing {file} ...")
                    hdr, df = self.read_file(os.path.join(root, file)) 
                    if hdr:
                        header.append(hdr)
                    if not df.is_empty():               
                        df_data = pl.concat([df_data, df], how='diagonal')
                    cnt += 1
                self.logger.info(f"{cnt} of {len(files)} files processed.")

            return header, df_data       
        except Exception as err:
            print(err)


    def plot_tco(file: str) -> None:
        df = pl.read_parquet(file)