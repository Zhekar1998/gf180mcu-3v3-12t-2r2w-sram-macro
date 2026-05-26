# gf180mcu_3v3_12t_2r2w_sram_512x8 Release Physical Seed

| Check | Result |
| --- | --- |
| Source shell | `gf180mcu_3v3_12t_2r2w_sram_512x8_source_full_control` |
| Logical shape | `512 x 8` |
| Physical rows / groups | `64` / `8` |
| Size | `585.560um x 340.920um` |
| Area | `0.199629mm^2` |
| Area/bit | `48.738um^2/bit` |
| Row-edge width | `167.360um` |
| Port strip width | `37.840um` |
| Boundary pins | `75` |
| Magic DRC | `0` |
| Footprint status | `pass_max` |

This is the release hard-macro physical seed for top-level integration:
GDS, LEF, Magic, blackbox CDL/SV, behavioral model, decode contract,
row-edge corridors, boundary pins, and M4/M5 power are emitted.

Downstream package gates integrate Avalon control/row-select standard
cells, column periphery leaves, and routed control/periphery shapes into
the published macro GDS before local signoff.
