"""
Definition of useufl figure functions (L. Bernet)
"""

import numpy as np
from enum import Enum
from cycler import cycler
import matplotlib as mpl
import matplotlib.pyplot as plt
import pylab
import colorsys
import matplotlib.colors as mc
from typing import Tuple
import matplotlib.dates as mdates


# Formatter: show major ticks with year in Jan in addition, abd month names otherwise
def custom_month_tick_formatter(x, pos):
    date = mdates.num2date(x)
    if date.month == 1:
        return date.strftime("%b\n%Y")
    else:
        return date.strftime("%b")

class FigureAspects(Enum):
    """Possible figure aspect ratios"""

    GOLDENRATIO = 1.6118
    ASP16_9 = 16 / 9
    ASP4_3 = 4 / 3
    ASP3_2 = 3 / 2


def cm2inch(cm_values: tuple):  # cm2inch(*tupl):
    """function to transform cm in inches (inches needed for figures).
    It has to be a pair of values (width,height)"""
    inch = 2.54
    return tuple(cm / inch for cm in cm_values)


def save_fig_extact_size(
    fig: plt.Figure,
    file_name_fig: str,
    figsize_cm: Tuple[float, float],
    margins_cm: Tuple[float, float, float, float] = (0.1, 0.1, 0.1, 0.1),
    fig_dpi: int = 300,
    fig_format: str = "png",
    set_fig_size: bool = True,
    **kwargs #add kwargs
) -> None:
    """Save a figure with an exact size and margins.

    Args:
        fig (plt.Figure): Matplotlib figure object.
        file_name_fig (str): File name to save the figure.
        figsize_cm (Tuple[float, float]): Desired figure size (width, height) in fraction of figure coordinates(0 to 1)  from border .
        margins_cm (Tuple[float, float, float, float], optional): 
            Margins (left, bottom, right, top) in cm. Defaults to (0.1, 0.1, 0.1, 0.1).
        fig_dpi (int, optional): DPI of the saved figure. Defaults to 300.
        fig_format (str, optional): File format for saving. Defaults to "png".
    """
    # fig.set_size_inches(
    #     cm2inch((figW_temp, figH_temp))
    # )  # have the desired output figure size

    figsize_in = cm2inch(figsize_cm)  # Convert figure size to inches
    fig.set_size_inches(figsize_in)

    # Convert margins to inches and then to fractions of figure widths and heights
    left, bottom, right, top = cm2inch(margins_cm)
    fig.subplots_adjust(
        left=left / figsize_in[0],
        bottom=bottom / figsize_in[1],
        right=1 - right / figsize_in[0],
        top=1 - top / figsize_in[1],
    )
    plt.savefig(file_name_fig, dpi=fig_dpi, format=fig_format, **kwargs)
    return fig

# adjust the lightness of a color
def adjust_lightness(color, amount=0.5):
    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, amount * c[1])), c[2])


def update_all_rcParams(
    fs: int = 8,
    pl_lw: float = 1.2,
    ax_lw: float = 0.8,
    lw_thin: float = 0.4,
    lw_thick: float = 2.0,
    marker_size: float = 3.0,
    my_cols="k",
    axes_col="k",
    tit_col="k",
):
    """
    Update all rcParams for matplotlib plots
    Inputs:
        fs: font size
        pl_lw: plot line width
        ax_lw: axis line width
        lw_thin: thin line width
        my_cols: list of colours
        axes_col: color of axes
        tit_col: color of title
    """
    ############# RC parameters update ###############

    # fm._rebuild() # to use local conda environment fonts
    mpl.rcParams.update(
        {
            # fontsizes
            "font.size": fs,
            "axes.titlesize": fs,  # fontsize of the axes title
            "figure.titlesize": fs,
            "axes.labelsize": "small",  # fontsize of the axes labels
            "xtick.labelsize": "small",  #'small' is calculated relative to the general fontsize
            "ytick.labelsize": "small",
            "legend.fontsize": "x-small",  #'x-small',
            # # copernicus acp font: Nimbus Roman No9 L
            # #'font.family':'monospace',
            # 'font.family': 'serif',
            # 'font.serif': 'Nimbus Roman No9 L',
            # 'font.weight': 'regular',#'normal',
            "mathtext.fontset": "cm",  #'cm', #to use serif font in equations, but not working??
            # I now prefer using a sans-serif font for figures:
            #"font.family": "sans-serif",
            #'font.sans-serif': 'Segoe UI', #'Lato', # not working yet
            #'font.style': 'italic',
            #'font.weight': 'regular',#'normal',
            # linewidth and color
            "lines.linewidth": pl_lw,
            "figure.facecolor": "white",
            "axes.linewidth": ax_lw,
            "axes.facecolor": "white",
            "lines.markersize": marker_size,  # 3 #5,
            "lines.markeredgewidth": lw_thin,
            # axex, ticks, and label colors:
            "axes.edgecolor": axes_col,
            # ax.xaxis.label.set_color('red')
            # ax.tick_params(axis='x', colors='red')
            "xtick.color": axes_col,
            "ytick.color": axes_col,
            "axes.labelcolor": axes_col,
            "text.color": axes_col,  # sets all text to axes_col, can be problematic
            "axes.titlecolor": tit_col,
            # legend
            "legend.edgecolor": "black",  #'None',
            "legend.frameon": True,  # need to adapt framealpha
            "legend.framealpha": 0.5,
            "patch.linewidth": lw_thin,  # legend frame line width
            "legend.handlelength": 1.2,
            # axes and ticks
            "axes.grid": False,
            "grid.linewidth": ax_lw,
            "xtick.bottom": True,
            "ytick.left": True,
            "xtick.top": False,# no ticks at top and right
            "ytick.right": False,
            "xtick.major.width": ax_lw,
            "ytick.major.width": ax_lw,
            "axes.spines.top": False,  # no line at top and right
            "axes.spines.right": False,
            # colors
            "axes.prop_cycle": cycler("color", my_cols),
            ## For mdpi journal: use hyphen for minus signs:
            "axes.unicode_minus": True,  # use unicode minus instead of hyphen (should be default)
            ## Latex text
            #'text.usetex': True,
            #'text.latex.preamble': [r"\usepackage{amsmath}",], # for the align enivironment
        }
    )

    # #use sans-serif for latex math:
    params = {
        "text.usetex": False,
        "mathtext.fontset": "stixsans",
        "mathtext.default": "regular",
    }  # to avoid italic in math environment
    pylab.rcParams.update(params)

    ## For mdpi journal: use hyphen for minus signs:
    # mpl.rcParams.update({'axes.unicode_minus' : True})
    ###################################################
