"use strict";

const state = {
  index: null,
  station: null,
  stationCache: new Map(),
  sourceId: null,
  variable: null,
};

const el = (id) => document.getElementById(id);

function formatTimestamp(value) {
  if (!value) return "—";
  return value.replace("T", " ").replace("Z", " UTC");
}

function formatInteger(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en").format(value);
}

function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(1);
}

function shortCommit(value) {
  return value ? value.slice(0, 12) : "—";
}

async function getJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json();
}

function setOptions(select, entries, selectedValue = null) {
  select.replaceChildren();
  for (const entry of entries) {
    const option = document.createElement("option");
    option.value = entry.value;
    option.textContent = entry.label;
    select.append(option);
  }
  if (selectedValue && entries.some((entry) => entry.value === selectedValue)) {
    select.value = selectedValue;
  }
  select.disabled = entries.length === 0;
}

async function loadStation(stationId) {
  const meta = state.index.stations.find((station) => station.id === stationId);
  if (!meta) return null;
  if (!state.stationCache.has(stationId)) {
    state.stationCache.set(stationId, await getJson(meta.data_file));
  }
  return state.stationCache.get(stationId);
}

function renderTable() {
  const tbody = el("summary-table").querySelector("tbody");
  tbody.replaceChildren();
  const rows = state.station?.summary ?? [];
  el("empty-table").hidden = rows.length !== 0;

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.sourceId = row.source_id;
    tr.dataset.variable = row.variable;
    tr.tabIndex = 0;
    if (row.source_id === state.sourceId && row.variable === state.variable) tr.classList.add("selected");

    const values = [
      { value: row.variable },
      { value: row.source_name, className: "source", title: row.source_name },
      { value: formatTimestamp(row.latest_entry) },
      { value: formatInteger(row.number_rows), className: "numeric" },
      { value: formatInteger(row.expected_rows), className: "numeric" },
      { value: formatPercent(row.availability_pct), className: "numeric" },
    ];
    for (const cell of values) {
      const td = document.createElement("td");
      td.textContent = cell.value;
      if (cell.className) td.className = cell.className;
      if (cell.title) td.title = cell.title;
      tr.append(td);
    }

    const activate = () => selectSeries(row.source_id, row.variable);
    tr.addEventListener("click", activate);
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
    tbody.append(tr);
  }
}

function renderErrors() {
  const errors = state.station?.errors ?? [];
  const card = el("errors-card");
  const list = el("errors-list");
  list.replaceChildren();
  card.hidden = errors.length === 0;
  for (const item of errors) {
    const li = document.createElement("li");
    li.textContent = `${item.source_name}: ${item.error}`;
    list.append(li);
  }
}

function sourceEntries() {
  const sources = state.station?.sources ?? {};
  return Object.values(sources)
    .sort((a, b) => a.source_name.localeCompare(b.source_name))
    .map((source) => ({ value: source.source_id, label: source.source_name }));
}

function variableEntries(sourceId) {
  const source = state.station?.sources?.[sourceId];
  if (!source) return [];
  return Object.keys(source.variables)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .map((variable) => ({ value: variable, label: variable }));
}

function chooseInitialSeries() {
  const sources = sourceEntries();
  if (sources.length === 0) {
    state.sourceId = null;
    state.variable = null;
    setOptions(el("source-select"), []);
    setOptions(el("variable-select"), []);
    renderPlot();
    return;
  }

  if (!sources.some((source) => source.value === state.sourceId)) state.sourceId = sources[0].value;
  setOptions(el("source-select"), sources, state.sourceId);

  const variables = variableEntries(state.sourceId);
  if (!variables.some((variable) => variable.value === state.variable)) {
    state.variable = variables[0]?.value ?? null;
  }
  setOptions(el("variable-select"), variables, state.variable);
  renderPlot();
}

function selectSeries(sourceId, variable) {
  state.sourceId = sourceId;
  state.variable = variable;
  const sources = sourceEntries();
  setOptions(el("source-select"), sources, sourceId);
  setOptions(el("variable-select"), variableEntries(sourceId), variable);
  renderTable();
  renderPlot();
}

function renderPlot() {
  const container = el("time-series");
  const empty = el("empty-plot");
  const source = state.station?.sources?.[state.sourceId];
  const values = source?.variables?.[state.variable];

  if (!source || !state.variable || !values) {
    container.hidden = true;
    empty.hidden = false;
    if (window.Plotly) Plotly.purge(container);
    return;
  }

  container.hidden = false;
  empty.hidden = true;
  el("plot-heading").textContent = state.variable;
  const cadenceText = source.cadence_seconds
    ? `; cadence ${Number(source.cadence_seconds).toLocaleString(undefined, { maximumFractionDigits: 3 })} s (${source.cadence_source})`
    : "";
  el("plot-source").textContent = `${source.source_name}${cadenceText}`;

  if (!window.Plotly) {
    empty.hidden = false;
    empty.textContent = "Plotly could not be loaded.";
    container.hidden = true;
    return;
  }

  const trace = {
    type: "scattergl",
    mode: "lines",
    x: source.timestamps,
    y: values,
    name: state.variable,
    connectgaps: false,
    hovertemplate: "%{x}<br>%{y}<extra></extra>",
  };
  const darkMode = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  const layout = {
    template: darkMode ? "plotly_dark" : "plotly_white",
    margin: { l: 72, r: 28, t: 24, b: 68 },
    xaxis: { title: "Time (UTC)", type: "date", rangeslider: { visible: false } },
    yaxis: { title: state.variable, automargin: true },
    hovermode: "x",
    showlegend: false,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
  };
  const config = { responsive: true, displaylogo: false, scrollZoom: true };
  Plotly.react(container, [trace], layout, config);
}

function renderStationSummary() {
  if (!state.station) return;
  const count = state.station.published_source_count;
  const variables = state.station.summary.length;
  el("station-summary").textContent = `${count} current parquet source(s), ${variables} plottable variable row(s); partition ${state.station.partition}.`;
}

async function changeStation(stationId) {
  state.station = await loadStation(stationId);
  state.sourceId = null;
  state.variable = null;
  renderStationSummary();
  renderErrors();
  chooseInitialSeries();
  renderTable();
}

function bindControls() {
  el("station-select").addEventListener("change", async (event) => {
    await changeStation(event.target.value);
  });
  el("source-select").addEventListener("change", (event) => {
    state.sourceId = event.target.value;
    const variables = variableEntries(state.sourceId);
    state.variable = variables[0]?.value ?? null;
    setOptions(el("variable-select"), variables, state.variable);
    renderTable();
    renderPlot();
  });
  el("variable-select").addEventListener("change", (event) => {
    state.variable = event.target.value;
    renderTable();
    renderPlot();
  });
}

async function init() {
  try {
    state.index = await getJson("data/index.json");
    document.title = state.index.title;
    el("page-title").textContent = state.index.title;
    el("page-subtitle").textContent = `${state.index.subtitle} · ${state.index.level}`;
    el("snapshot-period").textContent = state.index.period;
    el("snapshot-generated").textContent = formatTimestamp(state.index.generated_at);
    el("snapshot-commit").textContent = shortCommit(state.index.data_commit);
    el("footer-source").textContent = `Source: ${state.index.source_repository}`;

    const stations = state.index.stations.map((station) => ({ value: station.id, label: station.label }));
    setOptions(el("station-select"), stations);
    bindControls();
    if (stations.length) await changeStation(stations[0].value);
  } catch (error) {
    console.error(error);
    el("station-summary").textContent = `Dashboard data could not be loaded: ${error.message}`;
    el("empty-table").hidden = false;
    el("empty-plot").hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", init);
