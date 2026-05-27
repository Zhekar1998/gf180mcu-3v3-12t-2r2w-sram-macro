# Row-Select Stdcell GDS Merge

Row-select/WL-buffer functions are physically implemented with Avalon NAND/INV stdcells inside the existing row-edge strips.
This closes physical row-select stdcell presence and routes WL-buffer outputs directly to the real 4x4 tile WL/RWL metal5 landing pins. Upstream control/predecode routing is handled by `route_gf180mcu_3v3_12t_2r2w_sram_control_signals.rb`.

| Macro | Status | Row-select stdcells | Newly inserted this run | Route shapes | Footprint |
| --- | --- | ---: | ---: | ---: | --- |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `PASS` | 1024 | 1024 | 7984 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `PASS` | 2048 | 2048 | 15920 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `PASS` | 2048 | 2048 | 15920 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `PASS` | 4096 | 4096 | 31792 | `true` |

Smoke DRC:

- `gf180mcu_3v3_12t_2r2w_sram_512x8`: GF180 KLayout `main.drc` PASS, `0` violations, report `reports/stdcell_row_select_gds_merge/gf180mcu_3v3_12t_2r2w_sram_512x8/main_drc.lyrdb`.
