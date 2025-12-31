from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.dates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import polars as pl
try:
    from processing.neph import Neph
except Exception:
    Neph = None  # type: ignore

from ipyfilechooser import FileChooser  # type: ignore
from IPython.display import display
from ipywidgets import Button, HBox, Layout, Output, Text, VBox
from ipywidgets.widgets import Dropdown

from toolbox.utils import pl_simplify_dtypes

# ---------------------------------------------------------------------
# File related configurations
# ---------------------------------------------------------------------
root_dir = Path("/product_data/data/pay/Kenya/git/gawkenyadata")
source_dir = Path("")
target_dir = Path("")  # folder for compiled and/or flagged data.

# ---------------------------------------------------------------------
# Dataframe column label configurations
# ---------------------------------------------------------------------
dtm = "dtm"
flags = "_flag_"
colors = "_color_"

# ---------------------------------------------------------------------
# Flagging scheme
# ---------------------------------------------------------------------
keys: dict[str, dict[str, Any]] = {
    "escape": {"flag": None, "color": "magenta", "meaning": "unflagged"},
    "0": {"flag": 0, "color": "blue", "meaning": "valid"},
    "1": {"flag": 1, "color": "red", "meaning": "invalid"},
    "2": {"flag": 2, "color": "gray", "meaning": "uncertain"},
    "3": {"flag": 3, "color": "cyan", "meaning": "zero"},
    "4": {"flag": 4, "color": "brown", "meaning": "span"},
}
flag_col_prefix = "f_"
new_file_on_save = False

# variables to be excluded from variable select dropdown
excl_vars_general = (dtm, "source", "_color_", "_flag_", "f_None")
excl_vars_ae33 = ("Inst_SN", "DateTime_1", "unclear", "DateTime_2")
excl_vars_g2401 = (
    "DATE",
    "TIME",
    "FRAC_DAYS_SINCE_JAN1",
    "FRAC_HRS_SINCE_JAN1",
    "JULIAN_DAYS",
    "EPOCH_TIME",
)
excl_vars_meteo = ("iii", "zzzztttt", "termin")
exclude_variables = excl_vars_general + excl_vars_ae33 + excl_vars_g2401 + excl_vars_meteo


def _order_key_items(keys: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Put 'escape' first, then numeric keys ascending, then others."""
    items: list[tuple[str, dict[str, Any]]] = []
    if "escape" in keys:
        items.append(("escape", keys["escape"]))
    items += [(k, keys[k]) for _, k in sorted((int(k), k) for k in keys if k.isdigit())]
    items += [(k, v) for k, v in keys.items() if k not in {"escape"} and not k.isdigit()]
    return items


def add_legend_below_axes(ax, keys: dict[str, dict[str, Any]], ncol: int | None = None, bottom_pad: float = 0.22):
    """
    Place a figure-level legend centered below the x-axis (outside plot area).
    """
    fig = ax.figure

    # Remove any previous figure-level legends so we don't stack them
    for lg in list(fig.legends):
        try:
            lg.remove()
        except Exception:
            pass

    handles = []
    for _, info in _order_key_items(keys):
        flag = info.get("flag", "")
        color = info.get("color", "#888")
        meaning = info.get("meaning", "")
        handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="",
                markerfacecolor=color,
                markeredgecolor="#333",
                markersize=6,
                label=f"{flag}: {meaning}",
            )
        )

    if ncol is None:
        ncol = min(6, len(handles)) if handles else 1

    # Make room below and place the legend just under the axes
    fig.subplots_adjust(bottom=bottom_pad)
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=ncol,
        bbox_to_anchor=(0.5, 0.02),  # (x, y) in figure coords
        frameon=True,
    )


def _reseed_builtin_toolbar(fig):
    """
    Make ipympl/matplotlib's native toolbar (Home/Back/Forward) consistent
    after ax.cla() + replot by resetting the nav stack to the current view.
    Best-effort across mpl/ipympl versions.
    """
    tb = getattr(fig.canvas, "toolbar", None)
    if not tb:
        return
    try:
        # mpl>=3.6
        if hasattr(tb, "_nav_stack") and hasattr(tb._nav_stack, "clear"):
            tb._nav_stack.clear()
        # older mpl
        if hasattr(tb, "_views") and hasattr(tb._views, "clear"):
            tb._views.clear()
        if hasattr(tb, "_positions") and hasattr(tb._positions, "clear"):
            tb._positions.clear()
        # push current view as 'home'
        if hasattr(tb, "push_current"):
            tb.push_current()
        if hasattr(tb, "set_history_buttons"):
            tb.set_history_buttons()
        if hasattr(tb, "update"):
            tb.update()
    except Exception:
        pass


def _selected_path_from_filechooser(fc: FileChooser) -> Path | None:
    """
    Return the currently selected file as a Path.
    Supports ipyfilechooser's common attributes across versions.
    """
    try:
        sel_path = getattr(fc, "selected_path", None)
        sel_file = getattr(fc, "selected_filename", None)
        if sel_path and sel_file:
            return Path(sel_path) / sel_file
    except Exception:
        pass

    raw = getattr(fc, "selected", None) or getattr(fc, "value", None)
    if raw:
        return Path(str(raw))
    return None


def on_file_chooser_read_file():
    """
    Load the selected .parquet file as the *source*.

    If the opened file is named 'ne300.parquet' (basename), apply automatic
    NE300 flags additively (fill only NULL rows in f_<nnn> columns).
    """
    global file_chooser, df, dropdown_variable_select, infobox, selected_file

    selected = _selected_path_from_filechooser(file_chooser)
    if not selected:
        infobox.value = "Please select a file."
        return

    if selected.suffix.lower() != ".parquet":
        raise ValueError("Please select a .parquet file.")

    selected_file = selected

    df = pl.read_parquet(selected_file)
    if dtm in df.columns:
        df = df.sort(dtm)

    if "termin" in df.columns:
        df = df.with_columns(pl.col("termin").cast(pl.Utf8))

    # Optional dtype clean-up
    try:
        df = pl_simplify_dtypes(df)
    except Exception:
        pass

    # Auto NE300 flagging only for file name convention "ne300.parquet"
    try:
        if selected_file.name.lower() == "ne300.parquet":
            if Neph is not None:
                df = Neph(name="neph").auto_flag_ne300_data(df)

    except Exception as e:
        infobox.value = f"Automatic NE300 flagging failed: {e}"

    # Populate variable dropdown (exclude dtm, helper columns, and any f_* columns)
    try:
        cols = [c for c in df.columns if c not in ("dtm", "_flag_", "_color_") and not c.startswith("f_")]
        dropdown_variable_select.options = cols
    except Exception:
        pass

    infobox.value = f"Opened: {selected_file} | shape={df.shape}"


def on_dropdown_value_selected(change):
    """
    When a different variable is chosen:
    - swap flag series to plotting alias _flag_
    - compute colors from _flag_ for plotting
    """
    global df, sc, variable, infobox, selected_file

    old = change.old
    variable = change.new

    ax.cla()
    ax.set_title(f"ezFlag - Interactive data flagging\n{selected_file}")

    if not variable or variable not in df.columns or df.select(pl.col(variable).count()).item() == 0:
        infobox.value = f"No data available for {variable}"
        return

    infobox.value = ""
    f_variable = f"{flag_col_prefix}{variable}"

    # Base color
    df = df.with_columns(pl.lit(keys["escape"]["color"], dtype=pl.Utf8).alias(colors))

    # Swap previously selected variable's plotting flag back into its f_<old>
    if flags in df.columns and old is not None:
        df = df.rename({flags: f"{flag_col_prefix}{old}"})

    # Bring selected variable's flags into the plotting alias
    if f_variable in df.columns:
        df = df.rename({f_variable: flags})

        if colors in df.columns:
            for k in keys.keys():
                if keys[k]["flag"] is not None:
                    df = df.with_columns(
                        pl.when(pl.col(flags) == keys[k]["flag"])
                        .then(pl.lit(keys[k]["color"]))
                        .otherwise(pl.col(colors))
                        .alias(colors)
                    )
    else:
        df = df.with_columns(pl.lit(keys["escape"]["flag"], dtype=pl.Int8).alias(flags))

    sc = ax.scatter(df[dtm], df[variable], c=df[colors].to_list(), alpha=0.7, s=10, picker=5)

    add_legend_below_axes(ax, keys, bottom_pad=0.15)

    ax.set_ylabel(ylabel=variable)
    ax.autoscale_view()
    fig.canvas.draw_idle()
    _reseed_builtin_toolbar(fig)


def on_picked_flag_point(event):
    """
    event.mouseevent.key : None, Any character, shift, control, win
    event.mouseevent.button : 1: left, 2: middle, 3: right
    event.ind : index of point picked.
    """
    global df, infobox

    infobox.value = f"Zoom OFF & key = '{event.mouseevent.key}'. Point with index = {event.ind} selected."
    if ax.get_navigate_mode() is None:
        if keys.get(event.mouseevent.key):
            flag = keys[event.mouseevent.key]["flag"]
            color = keys[event.mouseevent.key]["color"]
            df[event.ind, flags] = flag
            df[event.ind, colors] = color
            sc.set_color(df[colors].to_list())
            fig.canvas.draw_idle()
        else:
            infobox.value = f"Zoom OFF & point picked, but key '{event.mouseevent.key}' not assigned."


def on_key_pressed_flag_points(event):
    global df, variable, infobox

    infobox.value = f"Zoom ON & key = '{event.key}' pressed."
    if ax.get_navigate_mode() == "ZOOM":
        if keys.get(event.key):
            flag = keys[event.key]["flag"]
            color = keys[event.key]["color"]
            meaning = keys[event.key]["meaning"]
            infobox.value = f"flag = {flag} ({meaning})"
            zoom_xlim = ax.get_xlim()
            zoom_xlim = [matplotlib.dates.num2date(x, tz=None).replace(tzinfo=None) for x in zoom_xlim]
            zoom_ylim = ax.get_ylim()
            condition = (
                (pl.col(dtm).dt.replace_time_zone(None) > zoom_xlim[0])
                & (pl.col(dtm).dt.replace_time_zone(None) < zoom_xlim[1])
                & (pl.col(variable) > zoom_ylim[0])
                & (pl.col(variable) < zoom_ylim[1])
            )
            df = df.with_columns(
                [
                    pl.when(condition).then(pl.lit(color)).otherwise(pl.col(colors)).alias(colors),
                    pl.when(condition).then(pl.lit(flag)).otherwise(pl.col(flags)).alias(flags),
                ]
            )
            sc.set_color(df[colors].to_list())
            fig.canvas.draw_idle()
        else:
            infobox.value = f"Zoom ON, but key '{event.key}' not assigned."


def on_clicked_save_data(event):
    """
    Save the current dataframe back to the *source* file (no target dir).

    If the current variable is '5002', propagate SPAN/ZERO flags (3/4)
    from 5002 to all >1_000_000 channels before saving.
    """
    global df, dropdown_variable_select, file_chooser, variable, infobox

    # # If the user is on 5002, propagate 2/3/4 to the other channels.
    # try:
    #     if dropdown_variable_select.value == "5002":
    #         if Neph is not None:
    #             df = Neph(name="neph").propagate_zero_span_flags_from_5002(
    #                 df,
    #                 dtm="dtm",
    #                 source_flag_col=flags,  # use the plotting alias as the source
    #                 overwrite=True,  # set wherever 5002 has 2/3/4
    #             )
    # except Exception as e:
    #     try:
    #         infobox.value = f"Propagation failed: {e}"
    #     except Exception:
    #         pass

    if dropdown_variable_select.value is not None:
        if flags in df.columns:
            f_col_name = f"{flag_col_prefix}{variable}"
            if f_col_name in df.columns:
                df = df.drop(f_col_name)
            df = df.rename({flags: f_col_name})
        if colors in df.columns:
            df = df.drop(colors)

    source_file = _selected_path_from_filechooser(file_chooser)
    if not source_file:
        infobox.value = "No selected file to save."
        return

    if new_file_on_save:
        if source_file.exists():
            infobox.value = f"'{source_file.name}' exists already. A unique name will be created."
            source_file = source_file.with_name(f"{source_file.stem}-{datetime.now().strftime('%Y%m%d%H%M%S')}{source_file.suffix}")

    source_file.parent.mkdir(parents=True, exist_ok=True)
    infobox.value = f"Saving to '{source_file}'."

    try:
        df = pl_simplify_dtypes(df)
    except Exception:
        pass

    df.write_parquet(source_file)

    try:
        fig.canvas.draw_idle()
    except Exception:
        pass
    return


def ez_flag_data(design: int = 2, width: int = 10, height: int = 5):
    global file_chooser, dropdown_variable_select, button_save_data, infobox, layout, fig, ax

    fig = plt.figure(figsize=(width, height))
    ax = fig.subplots()

    file_chooser = FileChooser(
        select_desc="Select file",
        change_desc="Select file",
        path=str(root_dir / source_dir),
        filter_pattern="*.parquet",
        layout=Layout(width="700px"),
    )
    dropdown_variable_select = Dropdown(value=None, options=[], description="Variable")
    button_save_data = Button(description="Save data", layout=Layout(width="80px"))

    if design == 1:
        infobox = Text(description="NB", layout=Layout(width="700px"))
        layout = VBox([file_chooser, dropdown_variable_select, infobox, button_save_data, Output()])
    else:
        infobox = Text(layout=Layout(width="800px"))
        layout = VBox([file_chooser, dropdown_variable_select, HBox([button_save_data, infobox]), Output()])

    button_save_data.on_click(on_clicked_save_data)
    dropdown_variable_select.observe(on_dropdown_value_selected, names="value")
    fig.canvas.mpl_connect("pick_event", on_picked_flag_point)
    fig.canvas.mpl_connect("key_press_event", on_key_pressed_flag_points)

    file_chooser.register_callback(on_file_chooser_read_file)

    display(layout)
    plt.show()
