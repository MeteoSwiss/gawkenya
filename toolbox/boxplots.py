import matplotlib.pyplot as plt
import polars as pl

def box_plot(df: pl.DataFrame, var: str, by: str=['Hour [UTC]', 'Month'], dtm: str='dtm', 
             max_box_width: float=0.6, figsize: float=[7, 5],
             suptitle: str='suptitle', title: str='title', ylabel: str='ylabel') -> pl.DataFrame:
    # select columns to work with
    df = df.select([dtm, var])

    # create an grouping column
    if by=='Hour [UTC]':
        df = df.with_columns(pl.col(dtm).dt.hour().alias(by))
    elif by=='Month':
        df = df.with_columns(pl.col(dtm).dt.month().alias(by))
    else:
        raise ValueError("'by' not recognized.")

    df_pd = df.to_pandas()

    # Group by 'by' and count non-null values in the 'var' column
    widths = (
        df.group_by(by)
        .agg(pl.col(var).drop_nulls().count().alias('counts'))
        .sort(by)
        ).with_columns(
            (pl.col('counts') / pl.col('counts').max() * max_box_width).alias('widths'),
            )
    
    plt.figure(figsize=figsize)
    df_pd.boxplot(column=var, by=by, grid=False, figsize=figsize, widths=widths['widths'])
    plt.xlabel(by)
    plt.ylabel(ylabel)
    plt.title(title, size=8)
    plt.suptitle(suptitle)
    plt.show()
    return df


def daily_cumsum_monthly_box_plot(df: pl.DataFrame, var: str, dtm: str='dtm', 
             max_box_width: float=0.6, figsize: float=[7, 5],
             suptitle: str='suptitle', title: str='title', ylabel: str='ylabel', ylim: float=[None, None]) -> pl.DataFrame:
    """Compute daily cumulative sums, then plot data as boxplots

    Args:
        df (pl.DataFrame): polars DataFrame
        var (str): Name of variable
        dtm (str, optional): Column name of datetime stamp column of pl.Datetime type. Defaults to 'dtm'.
        max_box_width (float, optional): width of largest box. Defaults to 0.6.
        figsize (float, optional): Figure size. Defaults to [7, 5].
        suptitle (str, optional): Main title of figure. Defaults to 'suptitle'.
        title (str, optional): Subtitle. Defaults to 'title'.
        ylabel (str, optional): Y-label describing var. Defaults to 'ylabel'.
        ylim (float, optional): Y-axis limits. Defalts to [None, None].

    Returns:
        pl.Dataframe: Aggregated data from which the boxplot was produced.
    """
    # select columns to work with
    df = df.select([dtm, var])

    # Compute daily cumulative sums of 'var'
    df = df.with_columns(pl.col(dtm).cast(pl.Date).alias('date'))
    df = df.with_columns(pl.col(var).cum_sum().over(pl.col('date')).alias('daily_cumsums'),
                        #  pl.col(dtm).dt.year().alias('year'),
                         pl.col(dtm).dt.month().alias('month'),
                        #  pl.col(dtm).dt.day().alias('day'),
                         )
    df = df.group_by(by='date').max()

    # Group by 'by' and count non-null values in the 'var' column
    widths = (
        df.group_by('month')
        .agg(pl.col(var).drop_nulls().count().alias('counts'))
        .sort('month')
        ).with_columns(
            (pl.col('counts') / pl.col('counts').max() * max_box_width).alias('widths'),
            )
    
    df_pd = df.to_pandas()

    plt.figure(figsize=figsize)
    df_pd.boxplot(column='daily_cumsums', by='month', grid=False, figsize=figsize, widths=widths['widths'])
    plt.xlabel('Month')
    plt.ylim(ylim)
    plt.ylabel(ylabel)
    plt.title(title, size=8)
    plt.suptitle(suptitle)
    plt.show()

    df = df.drop(['dtm', var])
    return df.rename({'daily_cumsums': var})


def daily_mean_monthly_box_plot(df: pl.DataFrame, var: str, dtm: str='dtm', 
             max_box_width: float=0.6, figsize: float=[7, 5],
             suptitle: str='suptitle', title: str='title', ylabel: str='ylabel', ylim: float=[None, None]) -> pl.DataFrame:
    """Compute daily mean values, then plot data as boxplots

    Args:
        df (pl.DataFrame): polars DataFrame
        var (str): Name of variable
        dtm (str, optional): Column name of datetime stamp column of pl.Datetime type. Defaults to 'dtm'.
        max_box_width (float, optional): width of largest box. Defaults to 0.6.
        figsize (float, optional): Figure size. Defaults to [7, 5].
        suptitle (str, optional): Main title of figure. Defaults to 'suptitle'.
        title (str, optional): Subtitle. Defaults to 'title'.
        ylabel (str, optional): Y-label describing var. Defaults to 'ylabel'.
        ylim (float, optional): Y-axis limits. Defalts to [None, None].

    Returns:
        pl.Dataframe: Aggregated data from which the boxplot was produced.
    """
    # select columns to work with
    df = df.select([dtm, var])

    # Compute daily means of 'var'
    df = df.with_columns(pl.col(dtm).cast(pl.Date).alias('date'))
    df = df.group_by(by='date').mean()
    df = df.with_columns(#pl.col(var).mean().over(pl.col('date')).alias('daily_means'),
                         pl.col(dtm).dt.month().alias('month'),
                         )

    # Group by 'by' and count non-null values in the 'var' column
    widths = (
        df.group_by('month')
        .agg(pl.col(var).drop_nulls().count().alias('counts'))
        .sort('month')
        ).with_columns(
            (pl.col('counts') / pl.col('counts').max() * max_box_width).alias('widths'),
            )
    
    df_pd = df.to_pandas()

    plt.figure(figsize=figsize)
    df_pd.boxplot(column=var, by='month', grid=False, figsize=figsize, widths=widths['widths'])
    plt.xlabel('Month')
    plt.ylim(ylim)
    plt.ylabel(ylabel)
    plt.title(title, size=8)
    plt.suptitle(suptitle)
    plt.show()

    df = df.drop(['dtm', var])
    return df
