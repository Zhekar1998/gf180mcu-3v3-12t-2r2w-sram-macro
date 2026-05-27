# GF180MCU 12T 2R2W SRAM Release Physical Seed Package

| Macro | Shape | Size | Area | Max | DRC | Pins | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `1024x32` | `1003.960um x 1172.280um` | `1.176922mm^2` | `1.200000mm^2` | `0` | `175` | `pass_max` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `1024x8` | `585.560um x 618.040um` | `0.361900mm^2` | `0.350000mm^2` | `0` | `79` | `warn_within_5pct` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `512x32` | `1003.960um x 618.040um` | `0.620487mm^2` | `0.600000mm^2` | `0` | `171` | `warn_within_5pct` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `512x8` | `585.560um x 340.920um` | `0.199629mm^2` | `0.200000mm^2` | `0` | `75` | `pass_max` |

Generated artifacts per macro:

- Magic top layout with repeated verified 4x4 tile array;
- row-edge/control placement corridor geometry;
- physical boundary pins for control/address/data plus VDD/VSS;
- M4/M5 top-level power straps;
- GDS, LEF, blackbox SPICE, blackbox SV, behavioral SV, decode contract.

Final package closure is reported by the downstream stdcell,
row-select, column-periphery, full-GDS extraction, and local-signoff
reports.
