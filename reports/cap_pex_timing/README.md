# current C-Aware PEX And Critical-Path Timing Proxy

- Status: `WARN`
- Cap source: `openrcx_geometry_fallback`
- Mini-array: `gf180mcu_3v3_12t_2r2w_sram_capmini_16x16` / `256` bits / `104.400 x 69.080 um` active tile area
- Magic thresholds: `cthresh=0.05 fF`, `rthresh=0.1 ohm`
- Native Magic C-PEX artifact status: omitted from release package after invalid mini-array extraction diagnostics. The timing numbers below use only the OpenRCX geometry fallback capacitance model.

## Extracted Capacitance

| Net class | Nets | Min fF | Mean fF | Max fF | Per-cell fF |
| --- | ---: | ---: | ---: | ---: | ---: |
| `rbl` | 32 | 34.7014 | 39.6235 | 40.9804 | 2.47647 |
| `rwl` | 32 | 67.0433 | 98.9292 | 119.706 | 6.18307 |
| `wbl` | 64 | 31.7389 | 37.1031 | 38.0179 | 2.31894 |
| `wwl` | 32 | 67.0433 | 98.9292 | 119.706 | 6.18307 |

## Scaled Critical Path Proxy

The ngspice testbench uses extracted/scaled wire capacitance plus idealized drivers/current sinks.  It is useful for order-of-magnitude WL/BL timing and not a replacement for final sense-amp/write-driver characterization.

| Macro | C_WL fF | C_BL fF | R_WL ohm | R_BL ohm | WL 50% ns | BL -150mV ns | Write 10% ns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | 197.858 | 633.976 | 80.3168 | 93.7824 | 0.239576 | 10.5346 | 1.16364 |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | 49.4646 | 316.988 | 46.8448 | 49.4432 | 0.227317 | 5.77982 | 1.06724 |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | 197.858 | 316.988 | 80.3168 | 49.4432 | 0.239576 | 5.77982 | 1.06724 |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | 49.4646 | 158.494 | 46.8448 | 27.2736 | 0.227317 | 3.40241 | 1.04932 |

## Caveats

- Native Magic GF180MCU extraction currently emits resistance and devices, but no C elements because the local Magic techfile has no capacitance coefficients in its extract section.
- When Magic C is absent, capacitance is derived from GF180MCU OpenRCX nominal rules and the generated 16x16 mini-array track geometry, then scaled to final macro dimensions.
- The earlier Magic C-PEX mini-array artifact is intentionally not shipped, because it was not used by the timing proxy and carried invalid extraction diagnostics from pre-fix collateral.
- The timing proxy does not model real decoder output resistance, sense amplifier offset, write-driver contention, or cell current corners.
- Full macro C-PEX remains intentionally avoided because it is not practical for local ngspice transient runs at the 1024x32 size.
