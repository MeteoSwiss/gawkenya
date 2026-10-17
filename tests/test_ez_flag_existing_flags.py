"""Regression: pre-existing source quality flags must survive variable changes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import matplotlib.pyplot as plt
import polars as pl

import toolbox.ez_flag_data as ez


def test_switch_between_preflagged_variables(monkeypatch):
    start = datetime(2026, 10, 15, tzinfo=UTC)
    source = pl.DataFrame(
        {
            "dtm": [start, start + timedelta(minutes=5)],
            "air_temperature": [20.0, 20.5],
            "battery_percent": [90.0, 89.0],
            "battery_voltage": [3600.0, 3590.0],
            "f_air_temperature": [0, 1],
            "f_battery_percent": [0, 0],
            "f_battery_voltage": [1, 0],
        },
        schema_overrides={"dtm": pl.Datetime("us", "UTC")},
    )
    fig, ax = plt.subplots()
    try:
        monkeypatch.setattr(ez, "df", source, raising=False)
        monkeypatch.setattr(ez, "fig", fig, raising=False)
        monkeypatch.setattr(ez, "ax", ax, raising=False)
        monkeypatch.setattr(ez, "infobox", SimpleNamespace(value=""), raising=False)
        monkeypatch.setattr(ez, "selected_file", "tahmo.parquet", raising=False)
        ez.on_dropdown_value_selected(
            SimpleNamespace(old=None, new="air_temperature")
        )
        assert ez.df[ez.flags].to_list() == [0, 1]

        # Simulate an interactive edit on the currently selected variable.
        ez.df = ez.df.with_columns(pl.lit(2).alias(ez.flags))
        ez.on_dropdown_value_selected(
            SimpleNamespace(old="air_temperature", new="battery_percent")
        )
        assert ez.df["f_air_temperature"].to_list() == [2, 2]
        assert ez.df[ez.flags].to_list() == [0, 0]

        ez.on_dropdown_value_selected(
            SimpleNamespace(old="battery_percent", new="battery_voltage")
        )
        assert ez.df["f_battery_percent"].to_list() == [0, 0]
        assert ez.df[ez.flags].to_list() == [1, 0]
        assert ez.df["f_battery_voltage"].to_list() == [1, 0]
        assert ez.df["battery_percent"].to_list() == [90.0, 89.0]
    finally:
        plt.close(fig)
