import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def plot_scatter_with_regression(x: np.ndarray, y: np.ndarray, pm: str,
                                 xlabel: str, ylabel: str,
                                 output_path: Path,
                                 width: float = 6, height: float = 5) -> None:
    """
    Generate and save scatter plot with regression line and equation.

    Args:
        x (np.ndarray): X-axis data.
        y (np.ndarray): Y-axis data.
        pm (str): Pollutant name, used in plot title and filename.
        xlabel (str): X-axis label.
        ylabel (str): Y-axis label.
        output_path (Path): Full path to save the PNG file.
        width (float): Plot width (inches).
        height (float): Plot height (inches).
    """
    if len(x) < 2 or len(y) < 2:
        print(f"⚠️ Not enough data to plot {pm}")
        return

    slope, intercept = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]

    plt.figure(figsize=(width, height))
    plt.scatter(x, y, alpha=0.5, label="Data")
    x_fit = np.linspace(x.min(), x.max(), 100)
    y_fit = slope * x_fit + intercept
    plt.plot(x_fit, y_fit, color="red", lw=2, label="Fit")

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(f"{pm} comparison")
    plt.text(0.05, 0.95,
             f"$r$ = {r:.3f}\n$y = {slope:.2f}x + {intercept:.2f}$",
             transform=plt.gca().transAxes,
             fontsize=10, va='top', ha='left',
             bbox=dict(facecolor='white', alpha=0.7))
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
