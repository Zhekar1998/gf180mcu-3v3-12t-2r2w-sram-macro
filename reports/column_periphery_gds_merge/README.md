# Column Periphery GDS Merge

The published macro GDS tops are compact hybrid wrappers containing the original array/control core, per-bit read/write column leaves, route geometry, and top/bottom M5 wrapper rails. The placement consumes existing top/bottom control bands before growing the wrapper, and clears only local old density/fill keepouts under the new column leaves. The route wrapper intentionally emits no manual dummy fill/poly; density closure belongs in a separate signoff fill step after routed connectivity is closed. Long per-leaf M5 power taps are intentionally disabled until a dedicated PDN router is added.

| Macro | Status | Instances | Routes | Route shapes | New bbox |
| --- | --- | ---: | ---: | ---: | --- |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `PASS` | 32 | 128 | 729 | `594.64um x 389.8um` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `PASS` | 128 | 512 | 2930 | `1019.545um x 752.71um` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `PASS` | 32 | 128 | 729 | `594.64um x 666.92um` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `PASS` | 128 | 512 | 2930 | `1019.545um x 1306.95um` |

Smoke DRC:

- `gf180mcu_3v3_12t_2r2w_sram_512x8`: GF180 KLayout `main.drc` PASS, `0` violations, report `reports/column_periphery_gds_merge/gf180mcu_3v3_12t_2r2w_sram_512x8/main_drc.lyrdb`.
