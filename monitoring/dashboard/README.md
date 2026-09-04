# GAW Kenya static data dashboard

This directory contains the static dashboard generator used to publish summary
information from the **current Level-1 parquet files** in the private
`gawkenyadata` repository.

The dashboard is deliberately static. The private data repository runs the
build after relevant commits, checks out this public repository for the
builder/front-end source, and pushes only the generated public site to the
`gh-pages` branch of `gawkenya`.

## What is published

For each configured station, the builder scans only the current UTC
`level1/<station>/YYYY/MM/` directory. Every parquet file is treated as a data
source. Numeric observation columns become variables unless excluded in
`config.yml`.

The summary table contains one row per published variable with:

- variable
- source name (the parquet path relative to the `gawkenyadata` root)
- latest entry
- number of physical rows
- duplicate timestamps
- expected number of rows
- availability (%)

Repeated timestamps are reported explicitly. Availability is based on the
number of **unique non-null timestamps**, not on the physical parquet row count,
so repeated records do not inflate availability. It is intentionally not capped
at 100%; a value above 100% after de-duplication indicates that the configured
or inferred cadence deserves inspection.

Expected rows are calculated from the beginning of the current UTC month to the
build time. Cadence comes from an explicit source override when configured;
otherwise it is inferred as the median positive timestamp interval from the
newest sample of timestamps.

Statistics use the entire parquet file. Plot data are downsampled for browser
display (`max_plot_points`, default 3000 per source), and the newest record is
always included. If a timestamp is repeated, the last record is retained in the
plot. Raw parquet files are never copied into the generated site.

## Quality-flag colours

The dashboard follows the same saved per-variable flag convention and colour
mapping as `ez_flag_data.py`. For a variable named `x`, the builder looks for a
flag column named `f_x` by default. Flag columns themselves are not offered as
plottable variables.

The plot uses coloured scatter points:

| Flag | Meaning | Colour |
|---:|---|---|
| null / absent / other | unflagged | magenta |
| 0 | valid | blue |
| 1 | invalid | red |
| 2 | uncertain | gray |
| 3 | zero check | cyan |
| 4 | span check | brown |

If a source has no matching flag column, its plotted points are shown as
unflagged (magenta). The flag-column prefix defaults to `f_` and can be changed
globally with `dashboard.flag_prefix` or for a source with `flag_prefix`.
Individual variables can also be mapped explicitly:

```yaml
source_overrides:
  some-source:
    flag_columns:
      temperature: qc_temperature
```

## Configuration

Edit `config.yml` to add stations or source-specific rules. Override keys can be
one of:

- a parquet file stem, e.g. `ae33`
- a source id relative to the monthly directory
- `<station>/<source-id>`, e.g. `mkn/ae33`

Supported source overrides include:

```yaml
source_overrides:
  mkn/ae33:
    cadence: 1m
    time_column: dtm
    variables: [BC1, BC2, BC3, BC4, BC5, BC6]
  nrb/diagnostics:
    publish: false
```

Use `publish: false` for any source whose derived values must not appear on the
public site.

## Local build

From the `gawkenya` checkout:

```bash
python -m pip install -r monitoring/dashboard/requirements.txt
python monitoring/dashboard/build_dashboard.py \
  --data-root /path/to/gawkenyadata \
  --output /tmp/gawkenya-dashboard
python -m http.server 8000 --directory /tmp/gawkenya-dashboard
```

Then open `http://localhost:8000/`.

`dashboard.py` at repository root is retained as a small compatibility entry
point and accepts the same arguments.

## Deployment

The workflow belongs in the private `gawkenyadata` repository as
`.github/workflows/publish-dashboard.yml`. It runs when `level1/**` changes on
`main`, or on manual `workflow_dispatch`. To keep Actions I/O small as the data
archive grows, it uses a blobless sparse checkout and materializes only the
current UTC `level1/{mkn,nrb,buc}/YYYY/MM` partitions.

Create one repository Actions secret in `gawkenyadata`:

`GAWKENYA_PUBLISH_TOKEN`

Use a fine-grained GitHub personal access token restricted to the public
`MeteoSwiss/gawkenya` repository with **Contents: Read and write**. The workflow
uses it only to check out and push the generated `gh-pages` branch.

In `gawkenya`, configure **Settings → Pages → Build and deployment → Deploy from
a branch**, selecting `gh-pages` and `/ (root)`.

When dashboard source/configuration changes in `gawkenya`, run the private
`Publish GAW Kenya dashboard` workflow manually to regenerate the public site
from the current private data snapshot.
