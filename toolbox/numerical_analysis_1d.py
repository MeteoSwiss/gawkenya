import polars as pl
import numpy as np
from scipy.interpolate import CubicSpline
from typing import Union

def interpolate_logarithmic(x_col: pl.Series, y_col: pl.Series, N: int, x0: Union[int, float], method: str='cubic_spline') -> pl.DataFrame:
    """
    Expand the number of logarithmically distributed x values by a factor of N using cubic spline interpolation,
    and compute the corresponding y values. Ensure that x0 is one of the interpolated x values.
    
    Parameters:
    x_col (pl.Series): A Polars Series containing the x values (logarithmically spaced).
    y_col (pl.Series): A Polars Series containing the y values.
    N (int): Factor by which to expand the number of x values.
    x0 (Union[int, float]): A specific x value to be included in the interpolated results.
    method (str, optional): Defines which method is used for interpolation. Defaults to 'cubic_spline'.
    
    Returns:
    pl.DataFrame: A new Polars DataFrame containing the interpolated 'x' and 'y' values.
    """
    
    # Convert Polars Series to NumPy arrays
    x_values = x_col.to_numpy()
    y_values = y_col.to_numpy()
    
    # Create an  interpolation function
    if method=='linear':
        interpolation_function = np.interp(np.log(x_values), x_values, y_values)
    elif method=='cubic_spline':
        interpolation_function = CubicSpline(np.log(x_values), y_values)
    
    # Generate new x values in log-space
    log_x_min = np.log(x_values.min())
    log_x_max = np.log(x_values.max())
    num_new_points = len(x_values) * N
    new_log_x_values = np.linspace(log_x_min, log_x_max, num=num_new_points)
    
    # Include x0 in the new x values if it's within the range
    if np.log(x_values.min()) <= np.log(x0) <= np.log(x_values.max()):
        new_log_x_values = np.append(new_log_x_values, np.log(x0))
        new_log_x_values = np.unique(new_log_x_values)
        new_log_x_values.sort()
    
    # Convert back to linear space
    new_x_values = np.exp(new_log_x_values)
    
    # Compute the corresponding y values
    new_y_values = interpolation_function(np.log(new_x_values))
    
    # Create a new DataFrame with the interpolated x and y values
    interpolated_df = pl.DataFrame({
        'x': new_x_values,
        'y': new_y_values
    })
    
    return interpolated_df


def integrate_1d(x_col: pl.Series, y_col: pl.Series) -> float:
    """
    Integrate the area under the curve defined by x_col and y_col using the trapezoidal rule.
    
    Parameters:
    x_col (pl.Series): A Polars Series containing the x values.
    y_col (pl.Series): A Polars Series containing the y values.
    
    Returns:
    float: The area under the curve.
    """   
    # Convert Polars Series to NumPy arrays
    x_values = x_col.to_numpy()
    y_values = y_col.to_numpy()
    
    # Compute the area under the curve using the trapezoidal rule
    area = np.trapz(y_values, x_values)
    
    return area