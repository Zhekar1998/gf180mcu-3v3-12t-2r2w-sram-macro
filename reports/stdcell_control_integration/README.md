# Avalon Stdcell Control Integration

This report binds the SRAM control matrix to real GF180MCU 3.3V
Avalon standard-cell collateral for ordinary digital logic.
SRAM-specific row-select/WL-buffer cells remain custom leaves.

| Macro | Physical WL Rows | Control Gates | Avalon Gates | Custom Row-Select |
| --- | ---: | ---: | ---: | ---: |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `64` | `532` | `276` | `256` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `128` | `788` | `276` | `512` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `128` | `834` | `322` | `512` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `256` | `1378` | `354` | `1024` |

Included Avalon collateral:

- merged GDS
- LEF and min/nom/max tech LEF
- CDL
- Verilog
- TT/SS/FF Liberty corners

The published top macro GDS files physically contain the placed
Avalon `INV`/`NAND`/`NOR` control stdcells after the GDS merge step.
Custom row-select/WL-buffer and periphery leaves remain separate
until a row-pitch-compatible row-edge integration is generated.
