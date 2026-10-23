# GAW Kenya data variables

This page documents processed variables whose interpretation is not obvious
from the instrument's raw field name.

## AE33 aethalometer

The AE33 reports equivalent black carbon mass concentration (`BC1` ... `BC7`)
at seven optical wavelengths. In the GAW Kenya Level-1 files these raw AE33
black-carbon values remain available unchanged and are accompanied by derived
aerosol absorption coefficients (`b1_abs` ... `b7_abs`).

The absorption coefficient is calculated from the configured mass-specific
absorption coefficient `SG` and filter-matrix correction factor `H*`:

```text
b_abs [Mm-1] = BC [ng/m3] * SG [m2/g] / H* / 1000
```

The factor `1/1000` converts `ng/m3` to `ug/m3`. Numerically,
`(ug/m3) * (m2/g)` is `Mm-1` (inverse megametres).

For the M8060 filter, the current processing configuration uses `H* = 1.76`.

| AE33 channel | Wavelength (nm) | BC variable | BC unit | SG (m2/g) | Absorption variable | Absorption unit |
| --- | ---: | --- | --- | ---: | --- | --- |
| 1 | 370 | `BC1` | ng/m3 | 18.47 | `b1_abs` | Mm-1 |
| 2 | 470 | `BC2` | ng/m3 | 14.54 | `b2_abs` | Mm-1 |
| 3 | 525 | `BC3` | ng/m3 | 13.14 | `b3_abs` | Mm-1 |
| 4 | 590 | `BC4` | ng/m3 | 11.58 | `b4_abs` | Mm-1 |
| 5 | 660 | `BC5` | ng/m3 | 10.35 | `b5_abs` | Mm-1 |
| 6 | 880 | `BC6` | ng/m3 | 7.77 | `b6_abs` | Mm-1 |
| 7 | 950 | `BC7` | ng/m3 | 7.19 | `b7_abs` | Mm-1 |

The numerical constants are maintained in
`config/instruments/ae33.yml`, rather than in the processor source.

### Quality flags

Quality flags use the `f_` prefix. For AE33, each BC mass-concentration
variable and its derived absorption variable form a linked flag group:

`BC1` <-> `b1_abs`, ..., `BC7` <-> `b7_abs`.

Flagging either representation in `ez_flag_data` therefore writes the same
flag at the same timestamp to both corresponding `f_` columns. The linkage is
configured generically in `config/tools/ez_flag_data.yml`.

## TAHMO ZENTRA weather station (MKN, device z6-02149)

The Level-1 file is `level1/mkn/YYYY/MM/tahmo.parquet`. No unit conversion is applied to the TAHMO source values.

| TAHMO measurement | Level-1 column | Unit as provided by TAHMO |
| --- | --- | --- |
| Air Temperature | `air_temperature` | °C |
| Atmospheric Pressure | `atmospheric_pressure` | kPa |
| Battery Percent | `battery_percent` | % |
| Battery Voltage | `battery_voltage` | mV |
| Gust Speed | `gust_speed` | m/s |
| Lightning Activity | `lightning_activity` | dimensionless / unspecified |
| Lightning Distance | `lightning_distance` | km |
| Logger Temperature | `logger_temperature` | °C |
| Max Precip Rate | `max_precip_rate` | mm/h |
| Precipitation | `precipitation_amount` | mm |
| RH Sensor Temp | `rh_sensor_temp` | °C |
| Reference Pressure | `reference_pressure` | kPa |
| Solar Radiation | `solar_radiation` | W/m² |
| VPD | `vpd` | kPa |
| Vapor Pressure | `vapor_pressure` | kPa |
| Wind Direction | `wind_direction` | ° |
| Wind Speed | `wind_speed` | m/s |
| X-axis Level | `x_axis_level` | ° |
| Y-axis Level | `y_axis_level` | ° |

`dtm` is a timezone-aware UTC datetime from `timestamp_utc` (Unix seconds).
`device_sn` is the source device serial number and `mrid` the largest TAHMO
measurement-record ID for the timestamp. Each measurement has **two distinct
flag columns**:

- `<variable>_err`: source TAHMO `error_flag` as `0` (false), `1` (true), or
  null when that measurement was absent. This column is evidence of source
  instrument status and is **never changed by interactive QC**.
- `f_<variable>`: editable GAW Kenya quality flag, initially `0` for a
  present reading with source error false and `1` for a true source error or
  missing numerical value. `ez_flag_data` may subsequently change this flag
  without changing `<variable>_err`.

Numerical readings with a source error are retained. Files compiled by the
**previous TAHMO processor** do not contain `<variable>_err`: when new incoming
files are merged, existing records receive null in that column because manual
edits to `f_` mean the original source error cannot be recovered reliably.
Reprocess original ZIPs separately if historical source errors are required;
merely rerunning overlapping ZIPs with identical MRIDs does not replace
already QC-ed Level-1 records.

Warnings in `metadata_errors` (e.g. `DEGRADED_OUTPUT`) are not silently
translated into quality flags. `lightning_activity` has an empty `units`
field in the supplied exports; its physical interpretation should be checked
against TAHMO documentation before deriving products from it.

Precipitation is named `precipitation_amount`, measured in millimetres per
source observation interval; `max_precip_rate` is a rate in mm/h. The source
examples are sampled every five minutes; they are not hourly totals.

## NE-300 nephelometer (MKN)

Parameter `4035` is an enumeration of instrument operating states, **not** a
bit mask or a sum of states. Its calibration states `1` and `2` are treated as
**uncertain / transient** (quality flag `2`) regardless of the subsequent
completion record. Completion states `3`–`6` are individual logged records.

| 4035 | Instrument operation (manufacturer's manual) | GAW Kenya QC flag |
| ---: | --- | --- |
| 0 | Normal monitoring | 0 — valid |
| 1 | Zero calibration data | 2 — uncertain / transient |
| 2 | Span calibration data | 2 — uncertain / transient |
| 3 | Zero adjustment completed | 3 — zero |
| 4 | Zero check completed | 5 — zero check |
| 5 | Span calibration completed | 4 — span |
| 6 | Span check completed | 6 — span check |

There is **no look-ahead**: a sequence of `4035` states `0,1,1,4,0` is flagged
`0,2,2,5,2` using the existing 10-minute post-calibration uncertainty window.
The records with state `1` remain flag `2`, even when the subsequent completion
record describes a zero check. Explicit completion records are *never*
replaced by the transition uncertainty window. Unrecognized states such as
`7` remain unclassified (flag `null` on fresh data).

On return to normal state `0` from a non-zero state, the current automatic
10-minute transition uncertainty is retained. The live auto-flagger changes
only missing QC flags by default. It targets numeric scattering channel IDs
1,000,000 through 8,000,000, not the `4035` status or `5002` pressure column.

The flag legend in `ez_flag_data.py` remains a single row. Flags `5` (zero
check, orange) and `6` (span check, purple) remain available. The existing
legend wording `uncertain` for flag `2` includes **transient** records; it is
intentionally not lengthened in order to preserve the compact one-line legend.

The renamed `housekeeping/backfill_ne300_flags.py` corrects historical
measurement flags for instrument states **1 through 6**. It never modifies
normal state `0` or unknown-state flags. By default it replaces missing, valid
(`0`), uncertain (`2`), and specifically recognized *previously generated
incorrect automatic flags*: 

- state 1: old flags 3 or 5 become 2;
- state 2: old flags 4 or 6 become 2;
- state 3: old flag 5 becomes 3;
- state 4: old flag 3 becomes 5;
- state 5: old flag 5 becomes 4;
- state 6: old flag 4 becomes 6.

Other non-null flags, including invalid (`1`), are preserved unless
`--overwrite-all` is explicitly supplied. Historical data do not distinguish
manual flags from previous automatic flags; **review dry-run changes** before
writing if any historical calibration periods were manually edited.
