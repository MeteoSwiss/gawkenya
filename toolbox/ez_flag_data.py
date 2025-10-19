import os
from datetime import datetime

import matplotlib
import matplotlib.dates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import polars as pl
from ipyfilechooser import FileChooser  # type: ignore
from IPython.display import display
from ipywidgets import widgets, Button, HBox, Layout, Output, Text, VBox, GridBox, ToggleButtons
from ipywidgets.widgets import Dropdown

from toolbox.utils import pl_simplify_dtypes

# file related configurations
root_dir = os.path.join(os.getcwd(), 'data')
source_dir = ''
target_dir = ''   # folder for compiled and/or flagged data. 

# dataframe column label configurations
dtm = 'dtm'
flags = '_flag_'
colors = '_color_'

# other configurations
keys = {'escape': {'flag': None, 'color': 'magenta', 'meaning': 'unflagged'},
        '0': {'flag': 0, 'color': 'blue', 'meaning': 'valid'},
        '1': {'flag': 1, 'color': 'red', 'meaning': 'invalid'},
        '2': {'flag': 2, 'color': 'gray', 'meaning': 'uncertain'},
        '3': {'flag': 3, 'color': 'cyan', 'meaning': 'zero'},
        '4': {'flag': 4, 'color': 'brown', 'meaning': 'span'},}
flag_col_prefix = 'f_'
new_file_on_save = False

# variables to be excluded from variable select dropdown
excl_vars_general = (dtm, 'source', '_color_', '_flag_', 'f_None',)
excl_vars_ae33 = ('Inst_SN', 'DateTime_1', 'unclear', 'DateTime_2', )
excl_vars_g2401 = ('DATE', 'TIME', 'FRAC_DAYS_SINCE_JAN1', 'FRAC_HRS_SINCE_JAN1', 'JULIAN_DAYS', 'EPOCH_TIME',)
excl_vars_meteo = ('iii', 'zzzztttt',)
exclude_variables = excl_vars_general + excl_vars_ae33 + excl_vars_g2401 + excl_vars_meteo 

def _order_key_items(keys: dict) -> list[tuple[str, dict]]:
    """Put 'escape' first, then numeric keys ascending, then others."""
    items = []
    if "escape" in keys:
        items.append(("escape", keys["escape"]))
    items += [(k, keys[k]) for _, k in sorted((int(k), k) for k in keys if k.isdigit())]
    items += [(k, v) for k, v in keys.items() if k not in {"escape"} and not k.isdigit()]
    return items

def add_legend_below_axes(ax, keys: dict, ncol: int | None = None, bottom_pad: float = 0.22):
    """
    Place a figure-level legend centered below the x-axis (outside plot area).
    - ax: your Matplotlib Axes
    - keys: your flag/color mapping (as in ez_flag_data.py)
    - ncol: number of legend columns (auto if None)
    - bottom_pad: extra bottom margin (fraction of figure height)
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
            Line2D([0], [0], marker='o', linestyle='',
                   markerfacecolor=color, markeredgecolor='#333',
                   markersize=6, label=f"{flag}: {meaning}")
        )

    if ncol is None:
        ncol = min(6, len(handles)) if handles else 1

    # Make room below and place the legend just under the axes
    fig.subplots_adjust(bottom=bottom_pad)
    fig.legend(handles=handles,
               loc="lower center",
               ncol=ncol,
               bbox_to_anchor=(0.5, 0.02),  # (x, y) in figure coords; small positive y keeps it inside canvas
               frameon=True)


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
        # Be tolerant across environment differences
        pass


# def _flagging_is_auto() -> bool:
#     # Checkbox -> boolean
#     try:
#         return bool(flag_mode.value)
#     except Exception:
#         return False

# def _apply_flags_for_column_preserving_manual(
#     df: pl.DataFrame,
#     col: str,
#     dtm: str = "dtm",
# ) -> pl.DataFrame:
#     """
#     Compute SPAN/ZERO flags for one column using processing.neph.Neph.apply_zero_span_flags,
#     then merge them into df by filling only rows where existing f_<col> is NULL.
#     Existing (manual/previous) non-NULL flags are preserved.
#     """
#     fcol = f"f_{col}"
#     if dtm not in df.columns or col not in df.columns:
#         return df

#     # Compute fresh flags on a minimal copy to keep it focused and avoid column clashes
#     from processing.neph import Neph
#     inst = Neph.__new__(Neph)  # avoid __init__
#     tmp = df.select([dtm, col])
#     tmp_flagged = Neph.apply_zero_span_flags(inst, tmp, dtm=dtm, primary=col)

#     # Stage new flags under a unique temp name to avoid join collisions
#     new_name = f"__newflag__{col}"
#     if new_name in df.columns:
#         df = df.drop(new_name)  # extremely defensive; shouldn’t exist

#     tmp_flagged = tmp_flagged.select(
#         dtm,
#         pl.col(f"f_{col}").cast(pl.Int8).alias(new_name)  # keep 0/3/4 as-is
#     )

#     # Left-join new flags by time, then coalesce to preserve existing non-NULL flags
#     joined = df.join(tmp_flagged, on=dtm, how="left")

#     if fcol in joined.columns:
#         joined = joined.with_columns(
#             pl.coalesce([pl.col(fcol), pl.col(new_name)]).alias(fcol)
#         ).drop(new_name)
#     else:
#         joined = joined.rename({new_name: fcol})

#     return joined


def on_file_chooser_read_file():
    """
    Load the selected .parquet file as the *source*.
    If automatic flagging is enabled, compute additive flags for 5002
    (fill only NULL rows). Then select 5002 to color points immediately.
    """
    import polars as pl

    global file_chooser, df, dropdown_variable_select, infobox, selected_file

    selected_file = getattr(file_chooser, "selected", None) or getattr(file_chooser, "value", None)
    if not selected_file:
        infobox.value = "Please select a file."
        return
    if not str(selected_file).lower().endswith(".parquet"):
        raise ValueError("Please select a .parquet file.")

    # Load source
    df = pl.read_parquet(selected_file)
    if "dtm" in df.columns:
        df = df.sort("dtm")

    # Optional dtype clean-up
    try:
        df = pl_simplify_dtypes(df)  # noqa: F821
    except NameError:
        pass

    # Automatic, *additive* flagging for 5002 (if present)
    # try:
    #     if _flagging_is_auto() and "5002" in df.columns:
    #         df = _apply_flags_for_column_preserving_manual(df, "5002", dtm="dtm")
    # except Exception as e:
    #     infobox.value = f"Automatic flagging failed: {e}"

    # Populate variable dropdown (exclude dtm, helper columns, and any f_* columns)
    try:
        cols = [c for c in df.columns if c not in ("dtm", "_flag_", "_color_") and not c.startswith("f_")]
        dropdown_variable_select.options = cols

        # # Select 5002 if available to trigger coloring immediately
        # if "5002" in cols:
        #     dropdown_variable_select.value = "5002"
    except Exception:
        pass

    infobox.value = f"Opened: {selected_file} | shape={df.shape}"


def on_dropdown_value_selected(change):
    """
    When a different variable is chosen, compute flags for that variable and
    fill them only where f_<var> is still NULL. Existing manual/previous flags stay.
    Then expose '_flag_' / '_color_' for plotting and draw.
    """
    import polars as pl

    global df, sc, variable, infobox, selected_file

    old = change.old
    variable = change.new

    # Reset axes & title
    ax.cla()
    ax.set_title(f"ezFlag - Interactive data flagging\n{selected_file}")

    if not variable or variable not in df.columns or df.select(pl.col(variable).count()).item() == 0:
        infobox.value = f"No data available for {variable}"
        return

    infobox.value = ""
    f_variable = f"{flag_col_prefix}{variable}"

    # # --- COMPLETE FLAGS ADDITIVELY FOR SELECTED VARIABLE ---
    # try:
    #     df = _apply_flags_for_column_preserving_manual(df, variable, dtm="dtm")
    # except Exception as e:
    #     infobox.value = f"Flagging for '{variable}' failed: {e}"

    # Base color
    df = df.with_columns(pl.lit(keys["escape"]["color"], dtype=pl.Utf8).alias(colors))

    # Swap previously selected variable's plotting flag back into its f_<old>
    if flags in df.columns and old is not None:
        df = df.rename({flags: f"{flag_col_prefix}{old}"})

    # Bring selected variable's flags into the plotting alias
    if f_variable in df.columns:
        df = df.rename({f_variable: flags})

        # Color points based on flags mapping in `keys` (0/3/4 etc.)
        # Ensure your `keys` dict has an entry for 0 if you want a specific color for "valid".
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
        # No flag column yet (unlikely here) -> init plotting flag to None
        df = df.with_columns(pl.lit(keys["escape"]["flag"], dtype=pl.Int8).alias(flags))

    # Draw
    sc = ax.scatter(df[dtm], df[variable], c=df[colors], alpha=0.7, s=10, picker=5)

    # legend below x-axis
    add_legend_below_axes(ax, keys, bottom_pad=0.15)

    ax.set_ylabel(ylabel=variable)
    ax.autoscale_view()    
    fig.canvas.draw_idle()
    _reseed_builtin_toolbar(fig)


def on_picked_flag_point(event):
    """
    event.mouseevent.key : None, Any character, shift, control, win (cf. https://matplotlib.org/stable/users/explain/figure/event_handling.html#event-attributes)
    event.mouseevent.button : 1: left, 2: middle, 3: right
    event.ind : index of point picked. NB: the index is set when the figure is created for the first time, so is unaffected by zooming.
    """
    global df, infobox

    infobox.value = f"Zoom OFF & key = '{event.mouseevent.key}'. Point with index = {event.ind} selected."
    if ax.get_navigate_mode() is None:
        if keys.get(event.mouseevent.key):
            flag = keys[event.mouseevent.key]["flag"]
            color = keys[event.mouseevent.key]["color"]
            df[event.ind, flags] = flag
            df[event.ind, colors] = color
            sc.set_color(df[colors])
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
            condition = ((pl.col(dtm).dt.replace_time_zone(None) > zoom_xlim[0]) & (pl.col(dtm).dt.replace_time_zone(None) < zoom_xlim[1])
                        & (pl.col(variable) > zoom_ylim[0]) & (pl.col(variable) < zoom_ylim[1]))
            df = df.with_columns([pl.when(condition)
                                .then(pl.lit(color))
                                .otherwise(pl.col(colors)).alias(colors),
                                pl.when(condition)
                                .then(pl.lit(flag))
                                .otherwise(pl.col(flags)).alias(flags),])
            sc.set_color(df[colors])
            fig.canvas.draw_idle()
        else:
            infobox.value = f"Zoom ON, but key '{event.key}' not assigned."


def on_clicked_save_data(event):
    """
    Save the current dataframe back to the *source* file (no target dir).
    If `new_file_on_save` is True, create a timestamped filename in the same folder.
    """
    import os
    from datetime import datetime
    import polars as pl

    global df, dropdown_variable_select

    # 1) optional: rename flag column and drop color column if they exist
    if dropdown_variable_select.value is not None:
        # rename flag column only if it exists
        try:
            if 'flags' in globals() and flags in df.columns:
                df = df.rename({flags: f"{flag_col_prefix}{variable}"})
        except Exception:
            pass

        # drop color column only if it exists
        try:
            if 'colors' in globals() and colors in df.columns:
                df = df.drop(colors)
        except Exception:
            pass

    # 2) compute source path (selected file) and output path
    source_file = os.path.join(file_chooser.selected_path, file_chooser.selected_filename)
    target_file = source_file  # <- save to source

    # If you still want the optional "new file on save" behavior, keep this:
    try:
        if 'new_file_on_save' in globals() and new_file_on_save:
            base, ext = os.path.splitext(source_file)
            if os.path.exists(target_file):
                target_file = f"{base}-{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    except Exception:
        # If the toggle isn't defined, ignore and just overwrite the source file
        pass

    # 3) write dataframe (no .bak)
    try:
        df = pl_simplify_dtypes(df)  # if you have this helper; otherwise it's a no-op
    except NameError:
        pass

    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    infobox.value = f"Saving to '{target_file}'."
    df.write_parquet(target_file)

    # 4) refresh UI figure if present
    try:
        fig.canvas.draw_idle()
    except Exception:
        pass
    return


def ez_flag_data(design: int=2, width: int=10, height: int=5):
    global file_chooser, dropdown_variable_select, button_save_data, infobox, layout, fig, ax
    # global flag_mode
    
    # prepare figure and create widget for display
    fig = plt.figure(figsize=(width, height))
    ax = fig.subplots()

    # create input widgets
    # flag_mode = widgets.Checkbox(
    #     value=True,
    #     description="Apply automatic flagging of SPAN and ZERO upon loading file.",
    #     indent=False,
    #     tooltip="Apply ZERO/SPAN flags for 5002 on load",
    # )
    file_chooser = FileChooser(
        select_desc="Select file", 
        change_desc="Select file",
        path=os.path.join(root_dir, source_dir), 
        filter_pattern="*.parquet",
        layout=Layout(width='700px'))
    dropdown_variable_select = Dropdown(
        value=None, 
        options=[], 
        description="Variable")
    button_save_data = Button(description="Save data", layout=Layout(width='80px'))

    # create layout
    if design==1:
        infobox = Text(description="NB", layout=Layout(width='700px'))
        layout = VBox([file_chooser, dropdown_variable_select, infobox, button_save_data, Output()]) 
        # layout = VBox([flag_mode, file_chooser, dropdown_variable_select, infobox, button_save_data, Output()])
    else:
        infobox = Text(layout=Layout(width='800px'))
        layout = VBox([file_chooser, dropdown_variable_select, HBox([button_save_data, infobox]), Output()]) 
        # layout = VBox([flag_mode, file_chooser, dropdown_variable_select, HBox([button_save_data, infobox]), Output()])

    # connect events
    button_save_data.on_click(on_clicked_save_data)
    dropdown_variable_select.observe(on_dropdown_value_selected, names='value')
    cid_pick = fig.canvas.mpl_connect('pick_event', on_picked_flag_point)
    cid_key_press = fig.canvas.mpl_connect('key_press_event', on_key_pressed_flag_points)

    # Register callback function
    file_chooser.register_callback(on_file_chooser_read_file)

    # Display widgets
    display(layout)

    # display the plot
    plt.show()
