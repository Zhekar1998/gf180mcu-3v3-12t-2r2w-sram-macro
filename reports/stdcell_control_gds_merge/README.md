# Stdcell Control GDS Merge

Avalon stdcell control gates are physically instantiated in the published macro GDS files.
This merge does not change macro width or height.

| Macro | Status | Inserted | Expected | Footprint |
| --- | --- | ---: | ---: | --- |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `PASS` | 276 | 276 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `PASS` | 276 | 276 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `PASS` | 322 | 322 | `true` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `PASS` | 354 | 354 | `true` |
