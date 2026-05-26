# Full GDS LVS/PEX

Magic extraction/PEX run directly from the packaged macro GDS wrappers.

- `blackbox`: `off`
- `cthresh`: `0.0`
- `rthresh`: `0.0`
- `extresist`: `on`
- `resistor_tee`: `on`
- `pex_nets`: `['VDD', 'VSS']`

| Macro | Status | Shorts | LVS bytes | RC bytes | MOS | R | C | Log |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `PASS` | 0 | 609289 | 609289 | 0 | 0 | 0 | `reports/full_gds_lvs_pex_power_rc/gf180mcu_3v3_12t_2r2w_sram_512x8/gf180mcu_3v3_12t_2r2w_sram_512x8.magic_full_gds_pex.log` |
