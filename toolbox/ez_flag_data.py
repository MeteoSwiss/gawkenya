import os

import matplotlib
import matplotlib.dates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import polars as pl
from ipyfilechooser import FileChooser  # type: ignore
from IPython.display import display
from ipywidgets import widgets, Button, HBox, Layout, Output, Text, VBox
from ipywidgets.widgets import Dropdown

from toolbox.utils import pl_simplify_dtypes

# file related configurations
root_dir = '/product_data/data/pay/Kenya/git/gawkenyadata'
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
excl_vars_meteo = ('iii', 'zzzztttt', 'termin')
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


def propagate_zero_span_flags_from_ne300_5002(
    df: pl.DataFrame,
    *,
    dtm: str = "dtm",
    source_flag_col: str | None = None,
    overwrite: bool = False,
) -> pl.DataFrame:
    """
    Propagate SPAN/ZERO flags (3/4) from the 5002 flag series to all other
    channels with numeric column names > 1_000_000.

    Behavior
    --------
    - Creates `f_<nnn>` columns if missing.
    - Copies only codes {2, 3, 4} from 5002 at matching timestamps.
    - Preserves existing manual flags by default:
        * overwrite=False (default): fill only where `f_<nnn>` is NULL.
        * overwrite=True : set 3/4 wherever 5002 has 3/4 (even if not NULL).

    Parameters
    ----------
    df : pl.DataFrame
    dtm : str
        Timestamp column name (default "dtm").
    source_flag_col : str | None
        Column to read 5002 flags from. If None, prefer "f_5002" if present,
        otherwise fall back to "flags" (useful when 5002 is currently selected).
    overwrite : bool
        If True, overwrite non-NULL values; else only fill NULLs.

    Returns
    -------
    pl.DataFrame
        Updated frame with propagated flags.
    """
    if dtm not in df.columns:
        return df

    # Choose the source flag column
    src = source_flag_col
    if src is None:
        if "f_5002" in df.columns:
            src = "f_5002"
        elif "flags" in df.columns:
            src = "flags"
        else:
            return df  # nothing to propagate from

    if src not in df.columns:
        return df

    # mask where 5002 indicates zero/span
    m_34 = pl.col(src).is_in([2, 3, 4])

    updates = []
    for c in df.columns:
        # select only numeric channel columns > 1_000_000 (and not '5002')
        if c.isdigit() and int(c) > 1_000_000:
            fcol = f"f_{c}"
            # current flag column (or NULL literal if it doesn't exist yet)
            cur = pl.col(fcol) if fcol in df.columns else pl.lit(None, dtype=pl.Int8)

            if overwrite:
                # force-copy 3/4 wherever source has 3/4
                new = (
                    pl.when(m_34).then(pl.col(src).cast(pl.Int8)).otherwise(cur)
                    .alias(fcol)
                )
            else:
                # additive: fill only where the target is still NULL
                new = (
                    pl.when(cur.is_null() & m_34)
                      .then(pl.col(src).cast(pl.Int8))
                      .otherwise(cur)
                      .alias(fcol)
                )
            updates.append(new)

    if not updates:
        return df
    return df.with_columns(updates)


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

    if "termin" in df.columns:
        df = df.with_columns(pl.col("termin").cast(pl.Utf8))

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
        # Ensure `keys` dict has an entry for 0 if you want a specific color for "valid".
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
    If the current variable is '5002', propagate SPAN/ZERO flags (3/4)
    from 5002 to all >1_000_000 channels additively before saving.
    """
    # import os
    from datetime import datetime
    import polars as pl

    global df, dropdown_variable_select

    # If the user is on 5002, propagate 3/4 to the other channels (additively).
    try:
        if dropdown_variable_select.value == "5002":
            # When 5002 is open, the plotting alias column is typically `flags`;
            # tell the propagator to read from it so we don’t rely on f_5002 being present.
            df = propagate_zero_span_flags_from_ne300_5002(
                df,
                dtm="dtm",
                source_flag_col=flags,   # use the plotting alias as the source
                overwrite=True,           # additive: fill only NULLs
            )
    except Exception as e:
        try:
            infobox.value = f"Propagation failed: {e}"
        except Exception:
            pass

    if dropdown_variable_select.value is not None:
        # rename flag column only if it exists
        if flags in df.columns:
            f_col_name = f"{flag_col_prefix}{variable}"
            if f_col_name in df.columns:
                df = df.drop(f_col_name)
            df = df.rename({flags: f_col_name})
        # drop color column only if it exists
        if colors in df.columns:
            df = df.drop(colors)

    # set file name and save to the SOURCE file (no target, no .bak)
    source_file = os.path.join(file_chooser.selected_path, file_chooser.selected_filename)
    if new_file_on_save:
        base, ext = os.path.splitext(source_file)
        if os.path.exists(source_file):
            infobox.value = f"'{os.path.basename(source_file)}' exists already. A unique name will be created."
            source_file = f"{base}-{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"

    os.makedirs(os.path.dirname(source_file), exist_ok=True)
    infobox.value = f"Saving to '{source_file}'."

    try:
        df = pl_simplify_dtypes(df)  # if you have this helper
    except NameError:
        pass

    df.write_parquet(source_file)

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
