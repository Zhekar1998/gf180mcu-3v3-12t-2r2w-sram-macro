# GF180MCU 3.3V 12T 2R2W SRAM Macro

<p align="center">
  <img src="assets/work-in-progress.svg" alt="WORK IN PROGRESS - NOT TAPEOUT SIGNOFF" width="100%">
</p>

This package contains the current Detronyx custom SRAM review collateral for a GF180MCU 3.3V-oriented 12T two-read/two-write hard macro. It is prepared for external engineering review, not presented as foundry tapeout signoff.

## Macro Variants

| Macro | Rows | Data width | Bits | Size um | Area mm2 | Area per bit um2 | Pins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | 1024 | 32 | 32768 | 1019.545 x 1306.950 | 1.332494 | 40.665 | 175 |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | 1024 | 8 | 8192 | 594.640 x 666.920 | 0.396577 | 48.410 | 79 |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | 512 | 32 | 16384 | 1019.545 x 752.710 | 0.767422 | 46.840 | 171 |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | 512 | 8 | 4096 | 594.640 x 389.800 | 0.231791 | 56.590 | 75 |

## Verification Snapshot

| Area | Status | Notes |
| --- | --- | --- |
| 12T leaf storage checks | `PASS` locally | See `verification/README.md` and `verification/results/README.md`. |
| Packaged local open-source signoff | `{'PASS': 36, 'WARN': 4}` | Magic PEX, pin LVS, full-GDS extraction/short audit, 512x8 VDD/VSS RC smoke, KLayout density/antenna, packaged SNM proxy logs, Avalon control placement/GDS/routing, row-select/WL-buffer placement/GDS merge, and column periphery integration run from this repo. See `reports/local_signoff_full/README.md`. |
| Release Netgen LVS gate | `PASS` | Tile device LVS plus macro-top tile blackbox LVS. Counts: `{'PASS': 8}`. The prior VSS PDN column / `c3_r1_rbl` short is fixed and covered as a regression target. See `reports/lvs_gate/README.md` and `verification/`. |
| Periphery leaf DRC/LVS gate | `PASS` | Compact Tim-derived row decode/WL-driver, write-driver, precharge/sense, and write-conflict leaves are Magic DRC clean and Netgen LVS `match_unique`; periphery gate counts: 22 pass / 0 fail. The folded `write_driver` is x32 tile-pitch-compatible at `25.950um x 68.880um`; `precharge_sense` is compacted to `18.710um x 24.455um`. See `reports/periphery_block_leaves/summary.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_periphery_lvs.py`. |
| Column periphery GDS integration | `PASS` | Published macro GDS tops are compact hybrid wrappers containing the array/control core, per-bit `detronyx_12t_precharge_sense_rc1` and `detronyx_12t_write_driver_rc1` column leaves, M5 data routes, M4 control/bitline landing trunks, and top/bottom M5 wrapper rails. The placement consumes existing `control_bottom/control_top` bands before growing the wrapper, clears only local old fill keepouts under new column leaves, and regenerates wrapper density fill. Gate counts: `{'PASS': 31}` including mandatory M5 VDD/VSS short audits on all four variants; 512x8 GF180 `main.drc` smoke has `0` violations. See `reports/column_periphery_gds_merge/README.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py`. |
| Avalon stdcell control integration | `PASS` | Avalon GF180MCU 3.3V stdcell GDS/LEF/CDL/Liberty/Verilog collateral is vendored, and each macro has generated stdcell-backed control-matrix CDL collateral. Gate counts: `{'PASS': 37}`. See `reports/stdcell_control_integration/README.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_gate.py`. |
| Avalon stdcell placement | `PASS` | Ordinary Avalon `INV`/`NAND`/`NOR` control gates are placed into existing top/bottom control bands without changing macro width or height; row-select placement is closed by the dedicated row-select expansion. Gate counts: `{'PASS': 33}`. See `reports/stdcell_control_placement/README.md`. |
| Avalon stdcell GDS merge | `PASS` | Published macro GDS files physically instantiate the placed Avalon control stdcells; total placed GDS instances: `1228`, footprint unchanged. Gate counts: `{'PASS': 17}`. See `reports/stdcell_control_gds_merge/README.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_gds_gate.py`. |
| Avalon row-select/WL-buffer GDS merge | `PASS` | Custom row-select/WL-buffer functions are expanded into row-pitch-compatible Avalon `NAND4 + 3*INV` rows and physically merged into all four macro GDS files; total added row-select stdcells: `9216`, footprint unchanged. Gate counts: `{'PASS': 23}` and 512x8 GF180 `main.drc` smoke has `0` violations. See `reports/stdcell_row_select_gds_merge/README.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_row_select_gds_gate.py`. |
| Avalon control/predecode signal routing | `PASS` | Top-level M2/M3 route cells connect expanded Avalon control/predecode nets, macro address/enable pins, and row-select NAND input sinks in all four macro GDS files; routed nets/endpoints: `1296` / `12520`, footprint unchanged. Gate counts: `{'PASS': 18}` and 512x8 GF180 `main.drc` smoke has `0` violations. See `reports/stdcell_control_signal_routing/README.md` and `verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_routing_gate.py`. |
| Full-GDS Magic extraction / PEX | `PASS` locally | Device-expanded no-RC Magic extraction from the published GDS wrappers passes all four variants with no electrical shorts (`reports/full_gds_lvs_pex_no_rc_all/MANIFEST.json`). Parameterized 512x8 VDD/VSS RC PEX also passes (`reports/full_gds_lvs_pex_power_rc/MANIFEST.json`). Full-net all-signal RC PEX is still beyond the local timeout budget and is treated as future characterization scope, not a packaged local blocker. |
| Published GDS top-cell aliases | `PASS` | Internal top cells are rewritten to the public macro aliases; see `reports/final_physical/gds_topcell_rewrite.json`. |
| C-aware timing proxy | `WARN` | Source: `openrcx_geometry_fallback`. See `reports/cap_pex_timing/README.md`. |
| Native Magic C extraction | `WARN` | Local GF180MCU Magic techfile emits R/devices but no capacitance coefficients; OpenRCX fallback is used for C timing proxy. |
| Local density/fill and antenna | `PASS` | KLayout GF180 density and antenna decks pass on all four published GDS variants. |
| Foundry signoff | `NOT INCLUDED` | Needs independent PDK/foundry-grade LVS/PEX/DRC/EM/IR review before tapeout intent. |

## Contents

- `macros/`: GDS, LEF, SPICE blackbox, SystemVerilog blackbox/behavioral/decode contracts, pin JSON, and per-macro summaries.
- `reports/`: generated physical, signoff, C/OpenRCX timing, and staged open-source evidence.
- `verification/`: release-facing LVS and connectivity scripts for the packaged extracted reports.
- `scripts/`: release-facing generator entrypoints and helper modules used to build the array and final physical macro collateral.
- `third_party/`: vendored Apache-2.0 Avalon GF180MCU 3.3V standard-cell collateral used by the release control-matrix package.
- `MANIFEST.json`: package file inventory, public macro aliases, and GDS top-cell rewrite status.

## Implementation Basis

- Timothy Edwards / Open Circuit Design GF180MCU 3.3V SRAM macros: https://github.com/RTimothyEdwards/gf180mcu_ocd_ip_sram
- Timothy Edwards 512x8 3.3V SRAM macro used as the main GF180 transistor/layout reference: https://github.com/RTimothyEdwards/gf180mcu_ocd_ip_sram/tree/main/cells/gf180mcu_ocd_ip_sram__sram512x8m8wm1
- Original Google/GF open GF180MCU SRAM macro repository: https://github.com/google/globalfoundries-pdk-ip-gf180mcu_fd_ip_sram
- Avalon GF180MCU 3.3V standard-cell library for SRAM control logic: https://github.com/AvalonSemiconductors/gf180mcu_as_sc_mcu7t3v3

## Regeneration Notes

This publication bundle is generated from the Detronyx GF180 SRAM experiment workspace. The public package intentionally uses neutral macro aliases and includes release-facing verification and generator scripts, not the full local experiment workspace. For local regeneration, use the matching Detronyx workspace flow that produced `reports/final_physical`, `reports/lvs_gate`, `reports/full_gds_lvs_pex_no_rc_all`, `reports/full_gds_lvs_pex_power_rc`, and `reports/cap_pex_timing`. Run `klayout -b -r scripts/rewrite_gf180mcu_3v3_12t_2r2w_sram_gds_topcells.rb`, then `python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_stdcell_control.py`, then `klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_stdcell_gds.rb`, then `python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_row_select_stdcells.py`, then `klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_row_select_gds.rb`, then `klayout -b -r scripts/route_gf180mcu_3v3_12t_2r2w_sram_control_signals.rb`, then `python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_column_periphery.py`, then `klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_column_periphery_gds.rb`, then `python3 verification/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py`, and finally `python3 scripts/run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py --timeout-sec 900 --no-rc --out-dir reports/full_gds_lvs_pex_no_rc_all` after copying generated GDS files into the public package.

## Review Questions

- Are the 12T 2W2R bitcell and shared M4/M5 escape assumptions physically defensible for GF180MCU?
- Is the current footprint strategy acceptable before investing in full macro periphery tiling and extraction?
- What minimum extra characterization is required before this can become tapeout-intent memory collateral?
- Should the next step be full OpenRCX/DEF-based extraction, foundry-rule PEX, or abutted full-macro periphery integration?

## Remaining Tapeout-Intent Work

- Golden reference schematic-vs-layout reconciliation for the expanded routed top. The macro GDS now contains routed Avalon control/predecode, row-select/WL-buffer stdcells, and the column `precharge_sense`/`write_driver` leaves; the packaged local gate covers full-GDS extraction and short audit, but a separately maintained full intended SRAM transistor CDL is still needed for a foundry-style Netgen reference LVS.
- Remaining non-column periphery integration: the standalone row decode/WL-driver and write-conflict leaves remain separate collateral; row-select/WL behavior is currently closed through Avalon stdcell expansion instead of those standalone leaves.
- Full-net extracted-RC SPICE characterization on the expanded macro GDS, including bitline landing parasitics, write-driver loading, precharge/sense loading, and routed control/data capacitance. Current local Magic full-net `extresist all` exceeds the local timeout budget; no-RC extraction and VDD/VSS RC smoke are available.
- SNM/read-disturb/half-select/dual-write characterization on final extracted parasitics. Packaged local proxy logs pass for VDD sweep plus disturb/conflict cases.
- Liberty characterization: setup/hold, clk-to-q, pin caps, power, and invalid arcs.
- EM/IR with real current profiles, foundry density/fill review, latch-up/package review, and final tapeout signoff.
