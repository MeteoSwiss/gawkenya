from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import polars as pl
import pandas as pd
import dash
from dash import dcc, html, Input, Output
import plotly.express as px
import uvicorn
import threading

# Create sample Polars DataFrame
df = pl.DataFrame({
    "timestamp": pd.date_range("2025-03-01", periods=1000, freq="H"),
    "value": pl.Series(range(1000)).shuffle()
})
df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))

# Start FastAPI server
app = FastAPI()

# Allow Dash frontend to access FastAPI
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/data")
async def get_data():
    """Serve data as JSON."""
    return df.to_pandas().to_dict(orient="records")

# Start Dash app
dash_app = dash.Dash(__name__, server=app, routes_pathname_prefix="/dashboard/")

dash_app.layout = html.Div([
    dcc.Graph(id="time-series"),
    dcc.Graph(id="histogram"),
    dcc.Graph(id="diurnal-variability"),
    dcc.Interval(id="update-interval", interval=5000, n_intervals=0)  # Auto-refresh every 5s
])

@dash_app.callback(
    [Output("time-series", "figure"),
     Output("histogram", "figure"),
     Output("diurnal-variability", "figure")],
    [Input("update-interval", "n_intervals")]
)
def update_graphs(_):
    import requests
    response = requests.get("http://127.0.0.1:8000/data").json()
    df_plot = pd.DataFrame(response)
    df_plot["timestamp"] = pd.to_datetime(df_plot["timestamp"])

    # Time Series Plot
    fig_time_series = px.line(df_plot, x="timestamp", y="value", title="Time Series")

    # Histogram (Distribution)
    fig_histogram = px.histogram(df_plot, x="value", nbins=30, title="Data Distribution")

    # Diurnal Variability
    df_plot["hour"] = df_plot["timestamp"].dt.hour
    fig_diurnal = px.box(df_plot, x="hour", y="value", title="Diurnal Variability")

    return fig_time_series, fig_histogram, fig_diurnal

# Run FastAPI and Dash in a separate thread
def run():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    threading.Thread(target=run).start()
    dash_app.run_server(debug=True, use_reloader=False)
