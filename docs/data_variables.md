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
