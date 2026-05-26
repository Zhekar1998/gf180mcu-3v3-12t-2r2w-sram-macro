# gf180mcu_3v3_12t_2r2w_sram_512x32 Release Physical Seed

| Check | Result |
| --- | --- |
| Source shell | `gf180mcu_3v3_12t_2r2w_sram_512x32_source_full_control` |
| Logical shape | `512 x 32` |
| Physical rows / groups | `128` / `4` |
| Size | `1003.960um x 618.040um` |
| Area | `0.620487mm^2` |
| Area/bit | `37.872um^2/bit` |
| Row-edge width | `167.360um` |
| Port strip width | `37.840um` |
| Boundary pins | `171` |
| Magic DRC | `0` |
| Footprint status | `warn_within_5pct` |

This is the release hard-macro physical seed for top-level integration:
GDS, LEF, Magic, blackbox CDL/SV, behavioral model, decode contract,
row-edge corridors, boundary pins, and M4/M5 power are emitted.

Downstream package gates integrate Avalon control/row-select standard
cells, column periphery leaves, and routed control/periphery shapes into
the published macro GDS before local signoff.
