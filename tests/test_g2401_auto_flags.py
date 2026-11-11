"""G2401 automatic QC flags from Picarro solenoid valve states."""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import polars as pl

from processing.g2401 import G2401


def _frame() -> pl.DataFrame:
    return pl.DataFrame({
        "dtm": [1, 2, 3, 4, 5, 6],
        "DATE": ["2026-11-11"] * 6,
        "FRAC_DAYS_SINCE_JAN1": [315.0] * 6,
        "solenoid_valves": [0, 1, 2, 7, None, -1],
        "CO2_dry_sync": [415.0] * 6,
        "CH4_dry_sync": [1.9] * 6,
        "CO_sync": [0.1] * 6,
        "CavityPressure": [140.0] * 6,
        "source": ["test"] * 6,
    })


def test_valve_state_maps_to_measurement_flags() -> None:
    result = G2401().auto_flag_g2401_data(_frame())
    expected = [0, 4, 2, 2, None, None]
    for name in ("CO2_dry_sync", "CH4_dry_sync", "CO_sync", "CavityPressure"):
        assert result[f"f_{name}"].to_list() == expected

    for name in ("dtm", "DATE", "FRAC_DAYS_SINCE_JAN1",
                 "solenoid_valves", "source"):
        assert f"f_{name}" not in result.columns


def test_existing_manual_flags_are_not_overwritten() -> None:
    frame = _frame().with_columns(
        pl.Series("f_CO2_dry_sync", [1, None, 0, 3, None, None], dtype=pl.Int8)
    )
    importer = G2401()
    result = importer.auto_flag_g2401_data(frame)
    assert result["f_CO2_dry_sync"].to_list() == [1, 4, 0, 3, None, None]
    assert result["f_CH4_dry_sync"].to_list() == [0, 4, 2, 2, None, None]
    forced = importer.auto_flag_g2401_data(frame, overwrite=True)
    assert forced["f_CO2_dry_sync"].to_list() == [0, 4, 2, 2, None, None]


def test_missing_valve_column_leaves_dataframe_unchanged() -> None:
    frame = _frame().drop("solenoid_valves")
    assert G2401().auto_flag_g2401_data(frame).equals(frame)


def test_zip_import_auto_flags_and_preserves_utc(tmp_path: Path) -> None:
    # 22 columns: the existing DataLog_User_Sync schema expects two strings,
    # four floats, two integers and fourteen floats.
    columns = [
        "DATE", "TIME", "FRAC_DAYS_SINCE_JAN1",
        "FRAC_HRS_SINCE_JAN1", "CO2_dry_sync", "CH4_dry_sync",
        "EPOCH_TIME", "JULIAN_DAYS", "CO_sync", "CavityPressure",
        "CavityTemp", "DasTemp", "EtalonTemp", "WarmBoxTemp",
        "MPVPosition", "solenoid_valves", "H2O_sync",
        "extra1", "extra2", "extra3", "extra4", "extra5",
    ]
    rows = []
    for minute, state in enumerate((0, 1, 3)):
        values = [
            "2026-11-11", f"13:{minute:02d}:00", "315", "1",
            "415.0", "1.9", "100000", "315",
            "0.1", "140", "40", "40", "40", "40", "0",
            str(state), "0.2", "0", "0", "0", "0", "0",
        ]
        rows.append(" ".join(values))
    source = "\n".join([" ".join(columns), *rows]) + "\n"
    path = tmp_path / "CFKADS2320-20261111-130000Z-DataLog_User_Sync.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("DataLog_User_Sync.dat", source)

    result, error = G2401().extract_to_dataframe(path)
    assert error is None
    assert result.height == 3
    assert result["dtm"].dtype == pl.Datetime("us", "UTC")
    assert result["f_CO2_dry_sync"].to_list() == [0, 4, 2]
    assert result["f_CO_sync"].to_list() == [0, 4, 2]
    assert "f_solenoid_valves" not in result.columns
