"""Regression for saving twice in an active ez_flag_data plot."""

from datetime import datetime
from types import SimpleNamespace

import polars as pl

import toolbox.ez_flag_data as ez


def test_save_twice_does_not_remove_interactive_plot_columns(tmp_path, monkeypatch):
    timestamps = [datetime(2026, 11, 11, 12, 0), datetime(2026, 11, 11, 12, 1)]
    frame = pl.DataFrame(
        {
            "dtm": timestamps,
            "o3": [40.0, 41.0],
            "_flag_": pl.Series([None, 1], dtype=pl.Int8),
            "_color_": ["magenta", "red"],
        }
    )
    target = tmp_path / "o3.parquet"
    info = SimpleNamespace(value="")

    monkeypatch.setattr(ez, "df", frame, raising=False)
    monkeypatch.setattr(ez, "variable", "o3", raising=False)
    monkeypatch.setattr(ez, "dropdown_variable_select", SimpleNamespace(value="o3"), raising=False)
    monkeypatch.setattr(ez, "file_chooser", object(), raising=False)
    monkeypatch.setattr(ez, "_selected_path_from_filechooser", lambda _: target)
    monkeypatch.setattr(ez, "infobox", info, raising=False)
    monkeypatch.setattr(
        ez, "fig", SimpleNamespace(canvas=SimpleNamespace(draw_idle=lambda: None)),
        raising=False,
    )

    ez.on_clicked_save_data(None)
    first = pl.read_parquet(target)
    assert first.get_column("f_o3").to_list() == [None, 1]
    assert "_flag_" not in first.columns
    assert "_color_" not in first.columns
    assert ez.df is frame
    assert frame.get_column("_color_").to_list() == ["magenta", "red"]

    # Simulate further keyboard/mouse flagging on the still-active plot.
    frame[0, "_flag_"] = 2
    frame[0, "_color_"] = "gray"
    ez.on_clicked_save_data(None)
    second = pl.read_parquet(target)
    assert second.get_column("f_o3").to_list() == [2, 1]
    assert "_flag_" not in second.columns
    assert "_color_" not in second.columns
    assert ez.df is frame
    assert frame.get_column("_color_").to_list() == ["gray", "red"]
    assert info.value.startswith("Saved to")
