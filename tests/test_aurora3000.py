import zipfile
from pathlib import Path

import polars as pl

from processing.neph import Neph


AURORA3000_HEADER = [
    "dtm",
    "ssp1",
    "ssp2",
    "ssp3",
    "sbsp1",
    "sbsp2",
    "sbsp3",
    "sample_temp",
    "enclosure_temp",
    "RH",
    "pressure",
    "major_state",
    "DIO_state",
]


def _make_zip(tmp_path: Path, zip_name: str, inner_name: str, content: str) -> Path:
    zpath = tmp_path / zip_name
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner_name, content)
    return zpath


def test_aurora3000_no_header_is_parsed_with_fixed_schema(tmp_path: Path) -> None:
    # No header: first row is data
    content = "\n".join(
        [
            "2025-12-08T23:55:00,23.204,28.962,32.417,2.966,3.735,3.640,31.005,31.049,40.266,813.725,0.000,7.000",
            "2025-12-08T23:56:00,22.506,27.924,32.311,3.168,3.546,3.700,30.999,31.048,40.189,813.725,0.000,7.000",
        ]
    )

    zpath = _make_zip(
        tmp_path,
        zip_name="aurora3000-2025120901.zip",          # filename key is important
        inner_name="aurora3000-2025120901.csv",
        content=content,
    )

    inst = Neph(name="neph-test")
    df, err = inst.extract_to_dataframe(zpath)

    assert err is None
    assert df.columns == AURORA3000_HEADER
    assert df.height == 2
    assert df.schema["dtm"] == pl.Datetime("us", "UTC")


def test_aurora3000_with_header_is_parsed(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "dtm,ssp1,ssp2,ssp3,sbsp1,sbsp2,sbsp3,sample_temp,enclosure_temp,RH,pressure,major_state,DIO_state",
            "2026-01-04T00:00:00,44.264,54.789,63.915,4.392,6.354,6.246,31.265,31.617,40.481,812.802,0.000,7.000",
            "2026-01-04T00:01:00,32.112,37.613,46.413,4.245,5.093,5.218,31.293,31.622,40.092,814.174,3.333,116.333",
        ]
    )

    zpath = _make_zip(
        tmp_path,
        zip_name="aurora3000-2026010401.zip",
        inner_name="aurora3000-2026010401.csv",
        content=content,
    )

    inst = Neph(name="neph-test")
    df, err = inst.extract_to_dataframe(zpath)

    assert err is None
    assert df.columns == AURORA3000_HEADER
    assert df.height == 2
    assert df.schema["dtm"] == pl.Datetime("us", "UTC")
