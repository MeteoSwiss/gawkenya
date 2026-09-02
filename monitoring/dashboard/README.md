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
- number of rows
- expected number of rows
- availability (%)

Expected rows are calculated from the beginning of the current UTC month to the
build time. Cadence comes from an explicit source override when configured;
otherwise it is inferred as the median positive timestamp interval from the
newest sample of timestamps. Availability is `number_rows / expected_rows *
100` and is intentionally not capped at 100%, so an incorrect cadence or
unexpected duplicate/faster observations remain visible.

Statistics use the entire parquet file. Plot data are downsampled for browser
display (`max_plot_points`, default 3000 per source), and the newest record is
always included. Raw parquet files are never copied into the generated site.

## Configuration

Edit `config.yml` to add stations or source-specific rules. Override keys can be
one of:

- a parquet file stem, e.g. `ae33`
- a source id relative to the monthly directory
- `<station>/<source-id>`, e.g. `mkn/ae33`

Supported source overrides are:

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
