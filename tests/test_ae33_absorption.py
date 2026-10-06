from __future__ import annotations

import math

import polars as pl

from processing.ae33 import AE33, add_absorption_coefficients


def _config(
    *,
    h_star: float = 1.76,
    bc1_sg: float = 18.47,
) -> dict:
    return {
        "absorption_correction": {
            "filter_type": "M8060",
            "h_star": h_star,
            "bc_unit": "ng/m3",
            "output_unit": "Mm-1",
            "sg_m2_g": {
                "BC1": bc1_sg,
                "BC2": 14.54,
                "BC3": 13.14,
                "BC4": 11.58,
                "BC5": 10.35,
                "BC6": 7.77,
                "BC7": 7.19,
            },
        }
    }


def test_default_config_is_loaded_automatically() -> None:
    processor = AE33()

    correction = processor.config["absorption_correction"]
    assert correction["filter_type"] == "M8060"
    assert correction["h_star"] == 1.76
    assert correction["sg_m2_g"]["BC1"] == 18.47
    assert correction["sg_m2_g"]["BC7"] == 7.19


def test_absorption_uses_configured_coefficients() -> None:
    df = pl.DataFrame({"BC1": [1000.0]})

    default_result = add_absorption_coefficients(df, _config())
    changed_result = add_absorption_coefficients(
        df,
        _config(h_star=2.0, bc1_sg=20.0),
    )

    assert math.isclose(default_result["b1_abs"][0], 18.47 / 1.76)
    assert math.isclose(changed_result["b1_abs"][0], 10.0)


def test_absorption_adds_all_seven_channels() -> None:
    df = pl.DataFrame({f"BC{i}": [1000.0 * i] for i in range(1, 8)})

    actual = add_absorption_coefficients(df, _config())

    for channel in range(1, 8):
        assert f"b{channel}_abs" in actual.columns


def test_absorption_copies_only_existing_bc_flags() -> None:
    df = pl.DataFrame(
        {
            **{f"BC{i}": [float(i)] for i in range(1, 8)},
            "f_BC2": [1],
            "f_BC6": [3],
        }
    )

    actual = add_absorption_coefficients(df, _config())

    for channel in (2, 6):
        assert actual[f"f_b{channel}_abs"].to_list() == actual[f"f_BC{channel}"].to_list()
        assert actual.schema[f"f_b{channel}_abs"] == actual.schema[f"f_BC{channel}"]

    for channel in (1, 3, 4, 5, 7):
        assert f"f_b{channel}_abs" not in actual.columns


def test_invalid_h_star_is_rejected() -> None:
    df = pl.DataFrame({"BC1": [1000.0]})

    try:
        add_absorption_coefficients(df, _config(h_star=0.0))
    except ValueError as exc:
        assert "h_star" in str(exc)
    else:
        raise AssertionError("Expected invalid h_star to fail.")
