from io import StringIO
import json
import polars as pl
import requests
import time

class DWH:
    locationID = ""
    api_token = ""

    def __init__(self, access_token: str, locationID: str, parameterShortNames: str, delimiter: str=",", placeholder: str="None", measCatNr: str="1"):
        """Constructor for DWH jretrieve instance with verification of successful connection.

        Args:
            access_token (str): access token, inquire with MeteoSwiss ITAE or MDI
            locationID (str): DWH internal short identifier of station, e.g. "KEMKN" or "KENAI"
            parameterShortNames (str): concatenated string, separated with commata, of all DWH variables to be retrieved. Examples:
                                    tre200h0: Lufttemperatur 2 m über Boden; Stundenmittel (°C, 261)
                                    ure200h0: Relative Luftfeuchtigkeit 2 m über Boden; Stundenmittel (%, 266)
                                    dkl010h0: Windrichtung; Stundenmittel (°, 282)
                                    fkl010h0: Windgeschwindigkeit skalar; Stundenmittel (m/s, 283)
                                    gre000h0: Globalstrahlung; Stundenmittel (W/m², 269)
                                    prestah0: Luftdruck auf Barometerhöhe (QFE); Stundenmittel (hPa, 306)
                                    rre150h0: Niederschlag; Stundensumme (mm, 267)
            delimiter (str, optional): Delimiter of response items. Defaults to ",".
            placeholder (str, optional): Null value indicator. Defaults to "None".
            measCatNr (str, optional): DWH internal measurement category identifier. Defaults to "1".

        Raises:
            ValueError: Response obtained if connection fails.
        """
        self.location_id = locationID
        self.parameter_short_names = parameterShortNames
        self.delimiter = delimiter
        self.placeholder = placeholder
        self.meas_cat_nr = measCatNr

        # log into DWH and verify connection
        auth_url='https://service.meteoswiss.ch/auth/realms/meteoswiss.ch/protocol/openid-connect/token'
        auth_data = (('grant_type', 'refresh_token'), ('client_id', 'api-token'), ('refresh_token', access_token))
        self.base_url = 'https://service.meteoswiss.ch/jretrieve/api/v1/surface/nat_abbr'
        try:
            res = requests.post(url=auth_url, data=auth_data)
            if res.status_code==200:    
                self.auth_header = 'Bearer ' + json.loads(res.text)['access_token']
                print("DWH initialized.")
            else:
                raise ValueError(f"Connection to DWH failed with status code: {res.status_code}")
        except Exception as err:
            print(err)

    def jretrieve(self, start: str, end: str=None) -> pl.DataFrame:
        df = pl.DataFrame()
        if end is None:
            end = time.strftime("%Y%m%d%H%S%S")
        try:
            url = f"{self.base_url}?delimiter={self.delimiter}&placeholder={self.placeholder}&locationIds={self.location_id}"
            url = f"{url}&date={start}-{end}&parameterShortNames={self.parameter_short_names}&measCatNr={self.meas_cat_nr}"
            res = requests.get(url=url, headers={'Authorization': self.auth_header})

            df = pl.read_csv(StringIO(res.text), separator=self.delimiter, null_values='None')
            return df
        except Exception as err:
            print(err)
            return df